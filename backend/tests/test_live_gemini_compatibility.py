"""Explicitly opt-in, payload-blind Gemini 3.5 request diagnostics."""

from __future__ import annotations

import os
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

import httpx
import pytest
from google import genai
from google.auth import exceptions as auth_exceptions
from google.genai import errors, types

from regops_api.adapter_logging import sensitive_io
from regops_api.gemini_analyst import _provider_response_schema
from regops_api.worker_models import AnalystDraftOutput

_ENABLED = os.getenv("REGOPS_LIVE_GEMINI_DIAGNOSTIC") == "1"
_MODEL = "gemini-3.5-flash"
_PROMPT = (
    "SYNTHETIC DIAGNOSTIC ONLY. Return one invented obligation with invented evidence "
    "that conforms to the supplied JSON schema."
)
_SYSTEM = "Return only schema-valid JSON. This is a bounded synthetic transport diagnostic."


def _config(**updates: Any) -> types.GenerateContentConfig:
    values: dict[str, Any] = {
        "system_instruction": _SYSTEM,
        "candidate_count": 1,
        "max_output_tokens": 512,
        "should_return_http_response": True,
        "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
        "http_options": types.HttpOptions(
            timeout=30_000,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    }
    values.update(updates)
    return types.GenerateContentConfig(**values)


def _status(
    *,
    client: genai.Client,
    label: str,
    config: types.GenerateContentConfig,
) -> int | str:
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=_PROMPT)])]
    try:
        with sensitive_io():
            # Never access or render the response body. A successful response may
            # contain an opaque thought signature, so discard the response whole.
            client.models.generate_content(model=_MODEL, contents=contents, config=config)
    except errors.APIError as error:
        status: int | str = error.code if isinstance(error.code, int) else "API_ERROR"
    except auth_exceptions.DefaultCredentialsError:
        status = "ADC_UNAVAILABLE"
    except auth_exceptions.RefreshError:
        status = "ADC_REFRESH_REJECTED"
    except auth_exceptions.TransportError:
        status = "ADC_TRANSPORT_ERROR"
    except httpx.TransportError:
        status = "TRANSPORT_ERROR"
    except (AttributeError, TypeError, ValueError):
        status = "CLIENT_CONFIGURATION_ERROR"
    except RuntimeError:
        status = "CLIENT_RUNTIME_ERROR"
    except OSError:
        status = "OS_TRANSPORT_ERROR"
    except Exception:
        status = "CLIENT_ERROR"
    else:
        status = 200
    print(f"LIVE_GEMINI_DIAGNOSTIC {label}=HTTP_{status}")
    return status


def _require_ok(statuses: Mapping[str, int | str]) -> None:
    for label, status in statuses.items():
        if status != 200:
            pytest.fail(f"{label}_FAILED_HTTP_{status}", pytrace=False)


@pytest.mark.live_gemini
@pytest.mark.skipif(not _ENABLED, reason="live Gemini request diagnostic explicitly disabled")
def test_live_gemini_35_generate_content_config_incrementally() -> None:
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("REGOPS_GEMINI_LOCATION") or os.getenv("REGOPS_REGION")
    if not project or not location:
        pytest.skip("explicit Gemini project/location configuration is incomplete")
    if os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"):
        pytest.fail("ADC_REQUIRED", pytrace=False)

    client = genai.Client(
        enterprise=True,
        project=project,
        location=location,
        http_options=types.HttpOptions(
            api_version="v1",
            timeout=30_000,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    try:
        base = _config()
        thinking = _config(
            thinking_config=types.ThinkingConfig(
                include_thoughts=False,
                thinking_level=types.ThinkingLevel.MINIMAL,
            )
        )
        json_mode = thinking.model_copy(update={"response_mime_type": "application/json"})
        _require_ok(
            {
                "MODEL_ACCESS": _status(client=client, label="MODEL_ACCESS", config=base),
                "THINKING_MINIMAL": _status(
                    client=client, label="THINKING_MINIMAL", config=thinking
                ),
                "JSON_MODE": _status(client=client, label="JSON_MODE", config=json_mode),
            }
        )

        authored = json_mode.model_copy(
            update={"response_json_schema": AnalystDraftOutput.model_json_schema()}
        )
        projected = json_mode.model_copy(
            update={"response_json_schema": _provider_response_schema()}
        )
        outer_cardinality = deepcopy(_provider_response_schema())
        outer_cardinality["properties"]["obligations"].update(
            {"minItems": 1, "maxItems": 50}
        )
        authored_status = _status(
            client=client, label="AUTHORED_ANALYST_SCHEMA", config=authored
        )
        projected_status = _status(
            client=client, label="PROJECTED_ANALYST_SCHEMA", config=projected
        )
        cardinality_status = _status(
            client=client,
            label="PROJECTED_SCHEMA_OUTER_CARDINALITY",
            config=json_mode.model_copy(
                update={"response_json_schema": outer_cardinality}
            ),
        )
        if (authored_status, projected_status, cardinality_status) != (400, 200, 400):
            pytest.fail("ANALYST_SCHEMA_DIAGNOSIS_INCONCLUSIVE", pytrace=False)

        legacy_status = _status(
            client=client,
            label="LEGACY_TEMPERATURE_ZERO",
            config=projected.model_copy(update={"temperature": 0}),
        )
        if legacy_status not in {200, 400}:
            pytest.fail("LEGACY_TEMPERATURE_UNEXPECTED_STATUS", pytrace=False)
    finally:
        with sensitive_io():
            client.close()
