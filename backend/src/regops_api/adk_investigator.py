"""One-shot ADK Impact Investigator with a deterministic ephemeral session."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from enum import StrEnum
from hashlib import sha256
from importlib.resources import files
from typing import Annotated, Any, Literal, Protocol

from google.adk.agents import LlmAgent
from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.function_tool import FunctionTool
from google.genai import types
from pydantic import Field, TypeAdapter, ValidationError

from regops_api.corpus import (
    CORPUS_TOOL_SCHEMA_VERSION,
    TOOL_NAMES,
    ImmutableSyntheticCorpus,
    tool_functions,
)
from regops_api.worker_ids import canonical_bytes
from regops_api.worker_models import (
    Digest,
    Identifier,
    InvestigatorDraftOutput,
    ResourceId,
    VerifiedObligationSet,
    WorkerModel,
)

APP_NAME: Literal["regops-impact-investigator"] = "regops-impact-investigator"
USER_ID: Literal["synthetic-worker"] = "synthetic-worker"
INVESTIGATOR_AGENT_NAME = "impact_investigator"
INSTRUCTION_VERSION: Literal["impact-investigator-v1"] = "impact-investigator-v1"
MAX_OUTPUT_CHARS = 128_000


class InvestigatorCode(StrEnum):
    INVALID_INPUT = "INVESTIGATOR_INVALID_INPUT"
    INVALID_CONFIGURATION = "INVESTIGATOR_CONFIGURATION_INVALID"
    INVOCATION_FAILED = "ADK_INVOCATION_FAILED"
    MALFORMED_OUTPUT = "ADK_MALFORMED_OUTPUT"


class InvestigatorError(RuntimeError):
    """Fixed safe failure; no provider exception, transcript, or payload is retained."""

    def __init__(self, code: InvestigatorCode) -> None:
        self.code = code
        super().__init__(code.value)


ObligationIds = Annotated[tuple[ResourceId, ...], Field(min_length=1, max_length=50)]
ModelName = Annotated[str, Field(pattern=r"^gemini-[a-zA-Z0-9.-]{1,100}$")]
_MODEL_NAME = TypeAdapter(ModelName)


class InvestigatorSessionState(WorkerModel):
    obligation_set_sha256: Digest
    corpus_sha256: Digest
    obligation_ids: ObligationIds
    synthetic: Literal[True] = True


class InvestigatorSessionBoundary(WorkerModel):
    app_name: Literal["regops-impact-investigator"] = APP_NAME
    user_id: Literal["synthetic-worker"] = USER_ID
    session_id: Digest
    run_id: Identifier
    model: ModelName
    instruction_version: Literal["impact-investigator-v1"] = INSTRUCTION_VERSION
    tool_schema_version: Literal["investigator-tools-v1"] = CORPUS_TOOL_SCHEMA_VERSION
    state: InvestigatorSessionState


def impact_investigator_prompt() -> str:
    return (
        files("regops_api")
        .joinpath("prompts/impact_investigator.txt")
        .read_text(encoding="utf-8")
    )


def _validated_model(model: str) -> str:
    try:
        return _MODEL_NAME.validate_python(model, strict=True)
    except ValidationError:
        raise InvestigatorError(InvestigatorCode.INVALID_CONFIGURATION) from None


def _canonical_obligations(obligations: VerifiedObligationSet) -> VerifiedObligationSet:
    return obligations.model_copy(
        update={
            "obligations": tuple(
                sorted(obligations.obligations, key=lambda item: item.obligation_id)
            )
        }
    )


def build_session_boundary(
    *,
    obligations: VerifiedObligationSet,
    corpus: ImmutableSyntheticCorpus,
    model: str,
) -> InvestigatorSessionBoundary:
    model = _validated_model(model)
    try:
        obligations = VerifiedObligationSet.model_validate(obligations)
    except ValidationError:
        raise InvestigatorError(InvestigatorCode.INVALID_INPUT) from None
    ordered = _canonical_obligations(obligations)
    obligation_sha256 = sha256(canonical_bytes(ordered)).hexdigest()
    state = InvestigatorSessionState(
        obligation_set_sha256=obligation_sha256,
        corpus_sha256=corpus.canonical_sha256,
        obligation_ids=tuple(item.obligation_id for item in ordered.obligations),
    )
    session_material = json.dumps(
        {
            "run_id": obligations.run_id,
            "obligation_set_sha256": obligation_sha256,
            "corpus_sha256": corpus.canonical_sha256,
            "model": model,
            "instruction_version": INSTRUCTION_VERSION,
            "tool_schema_version": CORPUS_TOOL_SCHEMA_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    try:
        return InvestigatorSessionBoundary(
            session_id=sha256(session_material).hexdigest(),
            run_id=obligations.run_id,
            model=model,
            state=state,
        )
    except ValidationError:
        raise InvestigatorError(InvestigatorCode.INVALID_INPUT) from None


def build_investigator_request(obligations: VerifiedObligationSet) -> str:
    """Build bounded current-turn data; this is not copied into session state."""
    try:
        ordered = _canonical_obligations(VerifiedObligationSet.model_validate(obligations))
    except ValidationError:
        raise InvestigatorError(InvestigatorCode.INVALID_INPUT) from None
    payload = {
        "synthetic": True,
        "instruction": "Compare these validated obligations using only registered tools.",
        "obligations": [
            {
                "obligation_id": item.obligation_id,
                "statement": item.statement,
                "type": item.type,
                "exceptions": item.exceptions,
                "effective_date": item.effective_date,
                "evidence": item.evidence,
            }
            for item in ordered.obligations
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def build_impact_investigator_agent(
    *, corpus: ImmutableSyntheticCorpus, model: str = "gemini-3.5-flash"
) -> LlmAgent:
    model = _validated_model(model)
    functions = tool_functions(corpus)
    if tuple(function.__name__ for function in functions) != TOOL_NAMES:
        raise InvestigatorError(InvestigatorCode.INVALID_CONFIGURATION)
    return LlmAgent(
        name=INVESTIGATOR_AGENT_NAME,
        description="Evidence-first impact mapping over one immutable synthetic corpus.",
        model=model,
        instruction=impact_investigator_prompt(),
        tools=[FunctionTool(function) for function in functions],
        output_schema=InvestigatorDraftOutput,
        mode="single_turn",
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
        include_contents="none",
        generate_content_config=types.GenerateContentConfig(
            temperature=0,
            candidate_count=1,
            max_output_tokens=8192,
            thinking_config=types.ThinkingConfig(include_thoughts=False),
        ),
    )


class AdkEventStream(Protocol):
    def __call__(
        self,
        *,
        runner: Runner,
        boundary: InvestigatorSessionBoundary,
        request: types.Content,
    ) -> AsyncIterator[Event]: ...


class InvestigatorInvocation(Protocol):
    async def run(
        self,
        *,
        agent: LlmAgent,
        boundary: InvestigatorSessionBoundary,
        request: str,
    ) -> str: ...


def _default_event_stream(
    *, runner: Runner, boundary: InvestigatorSessionBoundary, request: types.Content
) -> AsyncIterator[Event]:
    return runner.run_async(
        user_id=boundary.user_id,
        session_id=boundary.session_id,
        new_message=request,
    )


class InMemoryAdkInvocation:
    """Fresh in-memory service per call; nothing survives the returned result."""

    def __init__(self, *, event_stream: AdkEventStream = _default_event_stream) -> None:
        self._event_stream = event_stream

    async def run(
        self,
        *,
        agent: LlmAgent,
        boundary: InvestigatorSessionBoundary,
        request: str,
    ) -> str:
        service = InMemorySessionService()
        try:
            await service.create_session(
                app_name=boundary.app_name,
                user_id=boundary.user_id,
                session_id=boundary.session_id,
                state=boundary.state.model_dump(mode="json"),
            )
            runner = Runner(
                agent=agent,
                app_name=boundary.app_name,
                session_service=service,
                memory_service=None,
                artifact_service=None,
                credential_service=None,
            )
            content = types.Content(role="user", parts=[types.Part.from_text(text=request)])
            final_text: str | None = None
            async for event in self._event_stream(
                runner=runner,
                boundary=boundary,
                request=content,
            ):
                if event.error_code:
                    raise InvestigatorError(InvestigatorCode.INVOCATION_FAILED)
                if not event.is_final_response():
                    continue
                if final_text is not None or event.error_code or event.content is None:
                    raise InvestigatorError(InvestigatorCode.MALFORMED_OUTPUT)
                parts = event.content.parts or []
                if not parts:
                    raise InvestigatorError(InvestigatorCode.MALFORMED_OUTPUT)
                serialized = [part.model_dump(exclude_none=True) for part in parts]
                if any(
                    set(part) != {"text"} or not isinstance(part["text"], str)
                    for part in serialized
                ):
                    raise InvestigatorError(InvestigatorCode.MALFORMED_OUTPUT)
                final_text = "".join(part["text"] for part in serialized)
            if final_text is None:
                raise InvestigatorError(InvestigatorCode.MALFORMED_OUTPUT)
            return final_text
        except InvestigatorError:
            raise
        except Exception:
            raise InvestigatorError(InvestigatorCode.INVOCATION_FAILED) from None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_FIELD")
        result[key] = value
    return result


def parse_investigator_output(text: str) -> InvestigatorDraftOutput:
    if not text.strip() or len(text) > MAX_OUTPUT_CHARS:
        raise InvestigatorError(InvestigatorCode.MALFORMED_OUTPUT)
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("INVALID_CONSTANT")),
        )
        if not isinstance(value, dict) or set(value) != {"findings"}:
            raise ValueError("INVALID_OBJECT")
        return InvestigatorDraftOutput.model_validate_json(text)
    except (ValueError, ValidationError, RecursionError):
        raise InvestigatorError(InvestigatorCode.MALFORMED_OUTPUT) from None


class AdkImpactInvestigator:
    """Candidate-only role. Deterministic verification remains a separate gate."""

    def __init__(
        self,
        *,
        corpus: ImmutableSyntheticCorpus,
        model: str = "gemini-3.5-flash",
        invocation: InvestigatorInvocation | None = None,
        agent: LlmAgent | None = None,
    ) -> None:
        self._corpus = corpus
        self._model = _validated_model(model)
        self.agent = agent or build_impact_investigator_agent(corpus=corpus, model=model)
        self._invocation = invocation or InMemoryAdkInvocation()

    async def investigate_async(
        self, *, obligations: VerifiedObligationSet, corpus: Any
    ) -> InvestigatorDraftOutput:
        if corpus is not self._corpus:
            raise InvestigatorError(InvestigatorCode.INVALID_INPUT)
        boundary = build_session_boundary(
            obligations=obligations,
            corpus=self._corpus,
            model=self._model,
        )
        request = build_investigator_request(obligations)
        text = await self._invocation.run(agent=self.agent, boundary=boundary, request=request)
        return parse_investigator_output(text)

    def investigate(
        self, *, obligations: VerifiedObligationSet, corpus: Any
    ) -> InvestigatorDraftOutput:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.investigate_async(obligations=obligations, corpus=corpus))
        raise InvestigatorError(InvestigatorCode.INVALID_CONFIGURATION)
