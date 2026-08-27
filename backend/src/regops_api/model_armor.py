"""Explicit text inspection, separate from Gemini and from PDF extraction.

Only fixed outcomes cross this boundary. No vendor message, match, replacement
text or diagnostic is retained. Both templates must execute the required filters.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Protocol

from google.api_core import exceptions as cloud_errors
from google.cloud import modelarmor_v1

from regops_api.adapter_logging import sensitive_io
from regops_api.worker_models import WorkerModel

Direction = Literal["input", "output"]


class ArmorOutcome(StrEnum):
    ALLOWED = "allowed"
    PROMPT_INJECTION_BLOCKED = "prompt_injection_blocked"
    SENSITIVE_DATA_BLOCKED = "sensitive_data_blocked"
    UNSAFE_CONTENT_BLOCKED = "unsafe_content_blocked"
    INSPECTION_UNAVAILABLE = "inspection_unavailable"
    MALFORMED_RESPONSE = "malformed_inspection_response"
    INSPECTION_REJECTED = "inspection_rejected"


class ArmorResult(WorkerModel):
    outcome: ArmorOutcome


class TextInspection(Protocol):
    def inspect(self, *, text: str, direction: Direction, timeout: float) -> ArmorResult: ...


_FILTERS = {
    "pi_and_jailbreak": ("pi_and_jailbreak_filter_result", ArmorOutcome.PROMPT_INJECTION_BLOCKED),
    "sdp": ("sdp_filter_result", ArmorOutcome.SENSITIVE_DATA_BLOCKED),
    "rai": ("rai_filter_result", ArmorOutcome.UNSAFE_CONTENT_BLOCKED),
    "malicious_uris": ("malicious_uri_filter_result", ArmorOutcome.UNSAFE_CONTENT_BLOCKED),
    "csam": ("csam_filter_filter_result", ArmorOutcome.UNSAFE_CONTENT_BLOCKED),
    "virus_scan": ("virus_scan_filter_result", ArmorOutcome.UNSAFE_CONTENT_BLOCKED),
}


def sanitized_armor_result(payload: object) -> ArmorResult:
    """Decode the official protobuf's snake_case dict, with enum names.

    SUCCESS alone is insufficient: missing, skipped, unknown and contradictory
    filter results cannot authorize a call. SDP must inspect, not rewrite the input.
    """
    malformed = ArmorResult(outcome=ArmorOutcome.MALFORMED_RESPONSE)
    unavailable = ArmorResult(outcome=ArmorOutcome.INSPECTION_UNAVAILABLE)
    if not isinstance(payload, dict):
        return malformed
    invocation = payload.get("invocation_result")
    if invocation in ("PARTIAL", "FAILURE"):
        return unavailable
    if invocation != "SUCCESS":
        return malformed
    results = payload.get("filter_results")
    if not isinstance(results, dict) or not {"pi_and_jailbreak", "sdp", "rai"} <= results.keys():
        return malformed
    blocked: list[ArmorOutcome] = []
    for name, wrapper in results.items():
        if name not in _FILTERS or not isinstance(wrapper, dict):
            return malformed
        field, category = _FILTERS[name]
        # Proto dictionaries may include default empty fields; ignore only those.
        populated = {k: v for k, v in wrapper.items() if v}
        if set(populated) != {field} or not isinstance(populated[field], dict):
            return malformed
        result = populated[field]
        if name == "sdp":
            if {k for k, v in result.items() if v} != {"inspect_result"}:
                return malformed
            result = result["inspect_result"]
        if not isinstance(result, dict):
            return malformed
        execution = result.get("execution_state")
        if execution in ("EXECUTION_SKIPPED", "EXECUTION_FAILED"):
            return unavailable
        if execution != "EXECUTION_SUCCESS":
            return malformed
        match = result.get("match_state")
        if match == "MATCH_FOUND":
            blocked.append(category)
        elif match != "NO_MATCH_FOUND":
            return malformed
    expected = "MATCH_FOUND" if blocked else "NO_MATCH_FOUND"
    if payload.get("filter_match_state") != expected:
        return malformed
    return ArmorResult(outcome=sorted(blocked)[0] if blocked else ArmorOutcome.ALLOWED)


class GoogleModelArmor:
    def __init__(
        self, *, client: modelarmor_v1.ModelArmorClient, input_template: str, output_template: str
    ) -> None:
        self._client = client
        self._input_template = input_template
        self._output_template = output_template

    def inspect(self, *, text: str, direction: Direction, timeout: float) -> ArmorResult:
        with sensitive_io():
            try:
                data = modelarmor_v1.DataItem(text=text)
                if direction == "input":
                    response = self._client.sanitize_user_prompt(
                        request=modelarmor_v1.SanitizeUserPromptRequest(
                            name=self._input_template,
                            user_prompt_data=data,
                        ),
                        retry=None,
                        timeout=timeout,
                    )
                elif direction == "output":
                    response = self._client.sanitize_model_response(
                        request=modelarmor_v1.SanitizeModelResponseRequest(
                            name=self._output_template,
                            model_response_data=data,
                        ),
                        retry=None,
                        timeout=timeout,
                    )
                else:
                    return ArmorResult(outcome=ArmorOutcome.MALFORMED_RESPONSE)
            except (
                cloud_errors.DeadlineExceeded,
                cloud_errors.TooManyRequests,
                cloud_errors.ServiceUnavailable,
                cloud_errors.InternalServerError,
                TimeoutError,
            ):
                return ArmorResult(outcome=ArmorOutcome.INSPECTION_UNAVAILABLE)
            except Exception:
                return ArmorResult(outcome=ArmorOutcome.INSPECTION_REJECTED)
            try:
                payload = modelarmor_v1.SanitizationResult.to_dict(
                    response.sanitization_result,
                    preserving_proto_field_name=True,
                    use_integers_for_enums=False,
                )
                return sanitized_armor_result(payload)
            except Exception:
                return ArmorResult(outcome=ArmorOutcome.MALFORMED_RESPONSE)
