from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any, cast

import pytest
from google.cloud import modelarmor_v1 as m

from regops_api.model_armor import ArmorOutcome, GoogleModelArmor, sanitized_armor_result


def allowed_payload() -> dict[str, Any]:
    def clean() -> dict[str, str]:
        return {"execution_state": "EXECUTION_SUCCESS", "match_state": "NO_MATCH_FOUND"}

    return {
        "invocation_result": "SUCCESS",
        "filter_match_state": "NO_MATCH_FOUND",
        "filter_results": {
            "pi_and_jailbreak": {"pi_and_jailbreak_filter_result": clean()},
            "rai": {"rai_filter_result": clean()},
            "sdp": {"sdp_filter_result": {"inspect_result": clean()}},
        },
    }


def test_complete_inspection_is_required() -> None:
    assert sanitized_armor_result(allowed_payload()).outcome is ArmorOutcome.ALLOWED
    payload = allowed_payload()
    for bad in (
        None,
        {},
        {"invocation_result": "SUCCESS"},
        payload | {"filter_results": {}},
        payload | {"invocation_result": []},
        payload | {"filter_match_state": "MATCH_FOUND"},
    ):
        assert sanitized_armor_result(bad).outcome is ArmorOutcome.MALFORMED_RESPONSE
    for name in payload["filter_results"]:
        changed = deepcopy(payload)
        del changed["filter_results"][name]
        assert sanitized_armor_result(changed).outcome is ArmorOutcome.MALFORMED_RESPONSE


@pytest.mark.parametrize("invocation", ["PARTIAL", "FAILURE"])
def test_partial_or_failed_inspection_is_unavailable(invocation: str) -> None:
    assert sanitized_armor_result(
        allowed_payload() | {"invocation_result": invocation}
    ).outcome is (ArmorOutcome.INSPECTION_UNAVAILABLE)


@pytest.mark.parametrize(
    ("name", "field", "outcome"),
    [
        (
            "pi_and_jailbreak",
            "pi_and_jailbreak_filter_result",
            ArmorOutcome.PROMPT_INJECTION_BLOCKED,
        ),
        ("rai", "rai_filter_result", ArmorOutcome.UNSAFE_CONTENT_BLOCKED),
        ("sdp", "sdp_filter_result", ArmorOutcome.SENSITIVE_DATA_BLOCKED),
    ],
)
def test_block_categories_and_sanitized_result(
    name: str, field: str, outcome: ArmorOutcome
) -> None:
    payload = allowed_payload()
    result = payload["filter_results"][name][field]
    if name == "sdp":
        result = result["inspect_result"]
    result["match_state"] = "MATCH_FOUND"
    result["message_items"] = ["private source text"]
    payload["filter_match_state"] = "MATCH_FOUND"
    actual = sanitized_armor_result(payload)
    assert actual.outcome is outcome
    assert set(actual.model_dump()) == {"outcome"}
    assert "private" not in actual.model_dump_json()


@pytest.mark.parametrize(
    ("field", "value", "outcome"),
    [
        ("execution_state", "EXECUTION_SKIPPED", ArmorOutcome.INSPECTION_UNAVAILABLE),
        ("execution_state", "EXECUTION_FAILED", ArmorOutcome.INSPECTION_UNAVAILABLE),
        ("execution_state", "UNKNOWN", ArmorOutcome.MALFORMED_RESPONSE),
        ("execution_state", [], ArmorOutcome.MALFORMED_RESPONSE),
        ("match_state", "SUSPICIOUS", ArmorOutcome.MALFORMED_RESPONSE),
    ],
)
def test_uncertain_filter_fails_closed(field: str, value: object, outcome: ArmorOutcome) -> None:
    payload = allowed_payload()
    payload["filter_results"]["rai"]["rai_filter_result"][field] = value
    assert sanitized_armor_result(payload).outcome is outcome


class FakeArmorClient:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, str, float, object]] = []
        self.fail = fail

    def sanitize_user_prompt(
        self, *, request: m.SanitizeUserPromptRequest, timeout: float, retry: object
    ) -> m.SanitizeUserPromptResponse:
        self.calls.append(("input", request.name, timeout, retry))
        logging.getLogger("google.cloud.modelarmor_v1").debug("private source text")
        if self.fail:
            raise RuntimeError("private project credential detail")
        return m.SanitizeUserPromptResponse(sanitization_result=allowed_payload())

    def sanitize_model_response(
        self, *, request: m.SanitizeModelResponseRequest, timeout: float, retry: object
    ) -> m.SanitizeModelResponseResponse:
        self.calls.append(("output", request.name, timeout, retry))
        return m.SanitizeModelResponseResponse(sanitization_result=allowed_payload())


def test_official_client_requests_use_separate_templates_no_sdk_retries(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    fake = FakeArmorClient()
    adapter = GoogleModelArmor(
        client=cast(Any, fake), input_template="input", output_template="output"
    )
    assert (
        adapter.inspect(text="synthetic", direction="input", timeout=4).outcome
        is ArmorOutcome.ALLOWED
    )
    assert (
        adapter.inspect(text="synthetic", direction="output", timeout=3).outcome
        is ArmorOutcome.ALLOWED
    )
    assert fake.calls == [("input", "input", 4, None), ("output", "output", 3, None)]
    assert "private" not in caplog.text


def test_vendor_exception_is_discarded(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    adapter = GoogleModelArmor(
        client=cast(Any, FakeArmorClient(True)), input_template="input", output_template="output"
    )
    result = adapter.inspect(text="private source text", direction="input", timeout=1)
    assert result.outcome is ArmorOutcome.INSPECTION_REJECTED
    assert "private" not in caplog.text + result.model_dump_json()


def test_structured_dependency_diagnostics_are_suppressed_and_context_is_restored(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from regops_api.adapter_logging import sensitive_io

    caplog.set_level(logging.DEBUG)
    with sensitive_io():
        logging.getLogger("new.diagnostic.logger").error(
            "raw source",
            extra={"payload": "private signed URL and prompt"},
        )
    assert not caplog.records
    logging.getLogger("new.diagnostic.logger").info("safe outer event")
    assert caplog.messages == ["safe outer event"]


@pytest.mark.parametrize("status", ["rai", "sdp", "pi_and_jailbreak"])
def test_malformed_vendor_wrapper_cannot_allow_input(status: str) -> None:
    payload = allowed_payload()
    payload["filter_results"][status] = {"unknown_filter": {"match_state": "NO_MATCH_FOUND"}}
    assert sanitized_armor_result(payload).outcome is ArmorOutcome.MALFORMED_RESPONSE
