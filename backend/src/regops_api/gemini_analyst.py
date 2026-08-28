"""Guarded candidate-only adapter; no corpus, actions, writes or orchestration."""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable
from contextlib import ExitStack, suppress
from email.utils import parsedate_to_datetime
from importlib.resources import files
from math import isfinite
from typing import Any, Protocol, TypeVar

import httpx
from google import genai
from google.api_core.client_options import ClientOptions
from google.cloud import modelarmor_v1
from google.genai import errors, types
from pydantic import ValidationError

from regops_api.adapter_logging import sensitive_io
from regops_api.analyst_errors import AnalystCode, AnalystError
from regops_api.analyst_settings import AnalystSettings
from regops_api.config import RuntimeSettings
from regops_api.model_armor import (
    ArmorOutcome,
    ArmorResult,
    Direction,
    GoogleModelArmor,
    TextInspection,
)
from regops_api.pdf_reader import parse_pdf
from regops_api.worker_models import AnalystDraftOutput, SourceDocument

T = TypeVar("T")


class GenerationClient(Protocol):
    def generate_content(
        self, *, model: str, contents: list[types.Content], config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse: ...


def analyst_prompt() -> str:
    return (
        files("regops_api").joinpath("prompts/regulation_analyst.txt").read_text(encoding="utf-8")
    )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_FIELD")
        result[key] = value
    return result


def _json_object(text: str) -> dict[str, Any]:
    def invalid_constant(_value: str) -> None:
        raise ValueError("INVALID_JSON_CONSTANT")

    value = json.loads(text, object_pairs_hook=_unique_object, parse_constant=invalid_constant)
    if not isinstance(value, dict) or not value:
        raise ValueError("INVALID_OBJECT")
    return value


def _retry_after(response: object) -> float:
    """Keep only a bounded delay, never the provider's headers or response."""
    if not isinstance(response, httpx.Response):
        return 0.0
    header = response.headers.get("retry-after", "")
    if not header or len(header) > 128:
        return 0.0
    try:
        seconds = float(header)
    except ValueError:
        try:
            date = parsedate_to_datetime(header)
            if date.tzinfo is None:
                return 0.0
            seconds = date.timestamp() - time.time()
        except (ValueError, TypeError, OverflowError):
            return 0.0
    return min(4.0, max(0.0, seconds)) if isfinite(seconds) else 0.0


class GeminiRegulationAnalyst:
    """Satisfies CandidateAnalyst.analyze(source=...) without changing that port.

    The trusted caller supplies the immutable PDF bytes and its independently
    parsed manifest. Re-extraction compares the complete manifest before use.
    Only inspected page text is sent, never PDF metadata or a mutable GCS reference.
    """

    def __init__(
        self,
        *,
        content: bytes,
        settings: AnalystSettings,
        client: GenerationClient,
        input_inspector: TextInspection,
        output_inspector: TextInspection,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._content = content
        self._settings = AnalystSettings.model_validate(settings)
        self._client = client
        self._input = input_inspector
        self._output = output_inspector
        self._clock, self._sleep, self._jitter = clock, sleep, jitter
        self._close_clients: Callable[[], None] = lambda: None

    def close(self) -> None:
        """Release clients owned by the demo factory; injected clients stay caller-owned."""
        with sensitive_io(), suppress(Exception):
            self._close_clients()

    def _retry(
        self, call: Callable[[float], T], *, deadline: float, timeout: float, expired: AnalystCode
    ) -> T:
        for attempt in range(self._settings.max_attempts):
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise AnalystError(expired)
            try:
                result = call(min(timeout, remaining))
                if self._clock() > deadline:
                    raise AnalystError(expired)
                return result
            except AnalystError as error:
                code, transient = error.code, error.transient
                retry_after = error.retry_after_seconds
            # Raise outside the exception handler so raw exception context cannot
            # survive in a retained sanitized failure.
            if not transient or attempt + 1 >= self._settings.max_attempts:
                raise AnalystError(code)
            delay = max(min(2**attempt * self._jitter(), 4.0), retry_after)
            if self._clock() + delay >= deadline:
                raise AnalystError(code)
            self._sleep(delay)
        raise AnalystError(expired)

    def _inspect(self, text: str, direction: Direction, deadline: float) -> None:
        inspector = self._input if direction == "input" else self._output

        def call(timeout: float) -> None:
            try:
                with sensitive_io():
                    result = inspector.inspect(text=text, direction=direction, timeout=timeout)
            except (TimeoutError, httpx.TimeoutException):
                result = ArmorResult(outcome=ArmorOutcome.INSPECTION_UNAVAILABLE)
            except Exception:
                result = ArmorResult(outcome=ArmorOutcome.INSPECTION_REJECTED)
            try:
                result = ArmorResult.model_validate(result)
            except ValidationError:
                result = ArmorResult(outcome=ArmorOutcome.MALFORMED_RESPONSE)
            if result.outcome is ArmorOutcome.ALLOWED:
                return
            if result.outcome is ArmorOutcome.INSPECTION_UNAVAILABLE:
                code = AnalystCode.MODEL_ARMOR_UNAVAILABLE
            elif result.outcome is ArmorOutcome.MALFORMED_RESPONSE:
                code = AnalystCode.MODEL_ARMOR_MALFORMED_RESPONSE
            elif result.outcome is ArmorOutcome.INSPECTION_REJECTED:
                code = AnalystCode.MODEL_ARMOR_REJECTED
            else:
                code = (
                    AnalystCode.MODEL_ARMOR_INPUT_BLOCKED
                    if direction == "input"
                    else AnalystCode.MODEL_ARMOR_OUTPUT_BLOCKED
                )
            raise AnalystError(code)

        self._retry(
            call,
            deadline=deadline,
            timeout=self._settings.armor_timeout_seconds,
            expired=AnalystCode.MODEL_ARMOR_UNAVAILABLE,
        )

    def _generate(self, source: SourceDocument, timeout: float) -> str:
        retry_after = 0.0
        config = types.GenerateContentConfig(
            system_instruction=analyst_prompt(),
            temperature=0,
            candidate_count=1,
            max_output_tokens=self._settings.max_output_tokens,
            response_mime_type="application/json",
            response_json_schema=AnalystDraftOutput.model_json_schema(),
            # Otherwise google-genai parses candidate JSON before our Armor gate.
            should_return_http_response=True,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            thinking_config=types.ThinkingConfig(include_thoughts=False),
            http_options=types.HttpOptions(
                timeout=max(1, int(timeout * 1000)),
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(
                        text=(
                            "SYNTHETIC DOCUMENT DATA ONLY. Use this source binding: "
                            + source.identity.model_dump_json()
                        )
                    ),
                    *(
                        types.Part.from_text(
                            text=json.dumps(
                                {"page": page.page, "text": page.text},
                                ensure_ascii=False,
                            )
                        )
                        for page in source.pages
                    ),
                ],
            )
        ]
        try:
            with sensitive_io():
                response = self._client.generate_content(
                    model=self._settings.model,
                    contents=contents,
                    config=config,
                )
        except (TimeoutError, httpx.TimeoutException):
            code = AnalystCode.GEMINI_TIMEOUT
        except errors.APIError as error:
            retry_after = _retry_after(error.response)
            status = error.code
            code = (
                AnalystCode.GEMINI_RATE_LIMITED
                if status == 429
                else AnalystCode.GEMINI_TIMEOUT
                if status in {408, 504}
                else AnalystCode.GEMINI_UNAVAILABLE
                if isinstance(status, int) and 500 <= status <= 599
                else AnalystCode.GEMINI_REQUEST_REJECTED
            )
        except httpx.TransportError:
            code = AnalystCode.GEMINI_UNAVAILABLE
        except Exception:
            code = AnalystCode.GEMINI_REQUEST_REJECTED
        else:
            raw = (
                response.sdk_http_response
                if isinstance(response, types.GenerateContentResponse)
                else None
            )
            if raw is not None and isinstance(raw.body, str) and raw.body.strip():
                try:
                    if len(raw.body.encode("utf-8")) <= self._settings.max_response_bytes:
                        return raw.body
                except UnicodeError:
                    pass
            code = AnalystCode.GEMINI_MALFORMED_OUTPUT
        raise AnalystError(code, retry_after_seconds=retry_after)

    def analyze(self, *, source: SourceDocument) -> AnalystDraftOutput:
        deadline = self._clock() + self._settings.stage_timeout_seconds
        try:
            source = SourceDocument.model_validate(source)
        except ValidationError:
            raise AnalystError(AnalystCode.SOURCE_BINDING_MISMATCH) from None
        parsed = parse_pdf(
            content=self._content,
            doc_id=source.identity.doc_id,
            source_sha256=source.identity.source_sha256,
            limits=self._settings.pdf,
        )
        if parsed != source:
            raise AnalystError(AnalystCode.SOURCE_BINDING_MISMATCH)
        for page in parsed.pages:
            self._inspect(page.text, "input", deadline)
        raw = self._retry(
            lambda timeout: self._generate(parsed, timeout),
            deadline=deadline,
            timeout=self._settings.timeout_seconds,
            expired=AnalystCode.GEMINI_TIMEOUT,
        )
        # First inspect the raw HTTP body so the SDK cannot parse model JSON.
        # Inspect decoded text again to prevent JSON escapes hiding malicious text.
        self._inspect(raw, "output", deadline)
        try:
            envelope = _json_object(raw)
            feedback = envelope.get("promptFeedback", {})
            if feedback.get("blockReason"):
                raise AnalystError(AnalystCode.GEMINI_REFUSED)
            candidates = envelope.get("candidates")
            if not isinstance(candidates, list) or len(candidates) != 1:
                raise ValueError("INVALID_CANDIDATES")
            candidate = candidates[0]
            finish = candidate.get("finishReason")
            if finish in {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}:
                raise AnalystError(AnalystCode.GEMINI_REFUSED)
            if finish != "STOP":
                raise ValueError("INCOMPLETE_OUTPUT")
            if any(r.get("blocked") is True for r in candidate.get("safetyRatings", [])):
                raise AnalystError(AnalystCode.GEMINI_REFUSED)
            content = candidate["content"]
            if content.get("role") != "model":
                raise ValueError("INVALID_ROLE")
            parts = content["parts"]
            if not isinstance(parts, list) or not parts:
                raise ValueError("EMPTY_PARTS")
            if any(
                not isinstance(p, dict) or set(p) != {"text"} or not isinstance(p["text"], str)
                for p in parts
            ):
                raise ValueError("NON_TEXT_OUTPUT")
            text = "".join(p["text"] for p in parts)
            if not text.strip() or len(text) > self._settings.max_output_chars:
                raise ValueError("INVALID_OUTPUT_SIZE")
        except AnalystError:
            raise
        except Exception:
            raise AnalystError(AnalystCode.GEMINI_MALFORMED_OUTPUT) from None
        self._inspect(text, "output", deadline)
        try:
            _json_object(text)  # Also reject duplicate keys and NaN, not just schema violations.
            return AnalystDraftOutput.model_validate_json(text)
        except (ValueError, ValidationError, RecursionError):
            pass
        raise AnalystError(AnalystCode.GEMINI_MALFORMED_OUTPUT)


def build_demo_analyst(
    *, content: bytes, runtime: RuntimeSettings, settings: AnalystSettings
) -> GeminiRegulationAnalyst:
    """Explicit cloud construction only; no test/production/Developer API fallback."""
    settings.validate_demo(runtime)
    with sensitive_io():
        try:
            with ExitStack() as clients:
                gemini = genai.Client(
                    enterprise=True,
                    project=runtime.project_id,
                    location=runtime.region,
                    http_options=types.HttpOptions(
                        api_version="v1",
                        timeout=90_000,
                        retry_options=types.HttpRetryOptions(attempts=1),
                    ),
                )
                clients.callback(gemini.close)
                armor_client = modelarmor_v1.ModelArmorClient(
                    client_options=ClientOptions(
                        api_endpoint=f"modelarmor.{runtime.region}.rep.googleapis.com",
                    )
                )
                clients.callback(armor_client.transport.close)
                assert settings.armor_input_template and settings.armor_output_template
                armor = GoogleModelArmor(
                    client=armor_client,
                    input_template=settings.armor_input_template,
                    output_template=settings.armor_output_template,
                )
                analyst = GeminiRegulationAnalyst(
                    content=content,
                    settings=settings,
                    client=gemini.models,
                    input_inspector=armor,
                    output_inspector=armor,
                )
                analyst._close_clients = clients.pop_all().close
                return analyst
        except Exception:
            pass
    raise AnalystError(AnalystCode.ANALYST_CONFIGURATION_INVALID)
