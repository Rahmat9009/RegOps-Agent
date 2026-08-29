"""Opt-in, content-free compatibility check for minimum-live boolean detection."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from hashlib import sha256

import pytest
from google.cloud import modelarmor_v1
from pydantic import ValidationError

from regops_api.adapter_logging import sensitive_io
from regops_api.analyst_errors import AnalystCode, AnalystError
from regops_api.analyst_settings import AnalystSettings
from regops_api.config import RuntimeMode, RuntimeSettings
from regops_api.gemini_analyst import (
    GeminiMinimumLiveDetector,
    _json_object,
    build_demo_detector,
)
from regops_api.live_fixture import (
    KNOWN_SOURCE_SHA256,
    load_minimum_live_fixture,
    resolve_minimum_live_detections,
)
from regops_api.pdf_reader import parse_pdf
from regops_api.verification import verify_obligations
from regops_api.worker_models import MinimumLiveDetection
from tests.test_pdf_reader import SAMPLE

_ENABLED = os.getenv("REGOPS_LIVE_DETECTION_DIAGNOSTIC") == "1"


@dataclass(frozen=True)
class _SafeSummary:
    request_succeeded: bool
    armor: str
    schema_parsed: bool
    placement_fee_prohibition: bool | None
    fee_schedule_reissue: bool | None
    employer_paid_medical_exception: bool | None
    verifier_accepted: bool
    candidate_count: int
    verified_count: int


def _template_location(template: str, project: str, name: str) -> str:
    match = re.fullmatch(
        rf"projects/{re.escape(project)}/locations/([a-z][a-z0-9-]{{1,62}})/"
        rf"templates/{re.escape(name)}",
        template,
    )
    if match is None:
        raise ValueError("INVALID_ARMOR_TEMPLATE_RESOURCE")
    return match.group(1)


def _armor_category(code: AnalystCode) -> str:
    return {
        AnalystCode.MODEL_ARMOR_INPUT_BLOCKED: "input_blocked",
        AnalystCode.MODEL_ARMOR_OUTPUT_PROMPT_INJECTION_BLOCKED: "prompt_injection_blocked",
        AnalystCode.MODEL_ARMOR_OUTPUT_SENSITIVE_DATA_BLOCKED: "sensitive_data_blocked",
        AnalystCode.MODEL_ARMOR_OUTPUT_UNSAFE_CONTENT_BLOCKED: "unsafe_content_blocked",
        AnalystCode.MODEL_ARMOR_OUTPUT_BLOCKED: "blocked",
        AnalystCode.MODEL_ARMOR_UNAVAILABLE: "unavailable",
        AnalystCode.MODEL_ARMOR_MALFORMED_RESPONSE: "malformed",
        AnalystCode.MODEL_ARMOR_REJECTED: "rejected",
    }.get(code, "not_reached")


def _run_live(project: str, gemini_location: str) -> _SafeSummary:
    request_succeeded = False
    armor = "not_reached"
    parsed_detection: MinimumLiveDetection | None = None
    candidate_count = 0
    verified_count = 0
    verifier_accepted = False
    with sensitive_io():
        discovery: modelarmor_v1.ModelArmorClient | None = None
        detector: GeminiMinimumLiveDetector | None = None
        text: str | None = None
        try:
            discovery = modelarmor_v1.ModelArmorClient()
            names: dict[str, list[str]] = {"regops-input": [], "regops-output": []}
            for template in discovery.list_templates(
                parent=f"projects/{project}/locations/-",
                retry=None,
                timeout=20,
            ):
                for name in names:
                    if template.name.endswith(f"/templates/{name}"):
                        names[name].append(template.name)
            if any(len(matches) != 1 for matches in names.values()):
                raise RuntimeError("REGOPS_ARMOR_TEMPLATES_NOT_UNIQUE")
            input_template = names["regops-input"][0]
            output_template = names["regops-output"][0]
            location = _template_location(input_template, project, "regops-input")
            if location != _template_location(output_template, project, "regops-output"):
                raise RuntimeError("REGOPS_ARMOR_TEMPLATE_LOCATIONS_DIFFER")
            content = SAMPLE.read_bytes()
            if sha256(content).hexdigest() != KNOWN_SOURCE_SHA256:
                raise RuntimeError("TRACKED_SYNTHETIC_SOURCE_MISMATCH")
            fixture = load_minimum_live_fixture(KNOWN_SOURCE_SHA256)
            settings = AnalystSettings(
                armor_input_template=input_template,
                armor_output_template=output_template,
            )
            runtime = RuntimeSettings(
                mode=RuntimeMode.DEMO,
                project_id=project,
                armor_location=location,
                gemini_location=gemini_location,
            )
            source = parse_pdf(
                content=content,
                doc_id=fixture.source_doc_id,
                source_sha256=KNOWN_SOURCE_SHA256,
                limits=settings.pdf,
            )
            detector = build_demo_detector(content=content, runtime=runtime, settings=settings)
            try:
                text = detector._analyze_text(source=source)
                request_succeeded = True
                armor = "allowed"
                _json_object(text)
                parsed_detection = MinimumLiveDetection.model_validate_json(text)
            except AnalystError as error:
                request_succeeded = error.code not in {
                    AnalystCode.GEMINI_TIMEOUT,
                    AnalystCode.GEMINI_RATE_LIMITED,
                    AnalystCode.GEMINI_UNAVAILABLE,
                    AnalystCode.GEMINI_REQUEST_REJECTED,
                }
                armor = _armor_category(error.code)
            except (ValueError, ValidationError, RecursionError):
                request_succeeded = True
                armor = "allowed"
            finally:
                if text is not None:
                    del text
                    text = None
            if parsed_detection is not None and all(parsed_detection.model_dump().values()):
                candidates = resolve_minimum_live_detections(
                    fixture=fixture,
                    source=source,
                    detections=parsed_detection,
                )
                candidate_count = len(candidates.obligations)
                checked = verify_obligations(
                    run_id="live-detection-compatibility",
                    source=source,
                    accepted=fixture.accepted_catalog(source),
                    candidates=candidates,
                )
                verifier_accepted = checked.output is not None
                verified_count = (
                    len(checked.output.obligations) if checked.output is not None else 0
                )
                del candidates, checked
        finally:
            if detector is not None:
                detector.close()
            if discovery is not None:
                discovery.transport.close()  # type: ignore[no-untyped-call]
    values = parsed_detection.model_dump() if parsed_detection is not None else {}
    return _SafeSummary(
        request_succeeded=request_succeeded,
        armor=armor,
        schema_parsed=parsed_detection is not None,
        placement_fee_prohibition=values.get("placement_fee_prohibition"),
        fee_schedule_reissue=values.get("fee_schedule_reissue"),
        employer_paid_medical_exception=values.get("employer_paid_medical_exception"),
        verifier_accepted=verifier_accepted,
        candidate_count=candidate_count,
        verified_count=verified_count,
    )


@pytest.mark.live_gemini
@pytest.mark.skipif(not _ENABLED, reason="live detection diagnostic explicitly disabled")
def test_live_minimum_detection_compatibility_reports_only_safe_fields() -> None:
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    gemini_location = os.getenv("REGOPS_GEMINI_LOCATION") or os.getenv("REGOPS_REGION")
    if not project or not gemini_location:
        pytest.skip("explicit Gemini project/location configuration is incomplete")
    if os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"):
        pytest.fail("ADC_REQUIRED", pytrace=False)

    summary = _run_live(project, gemini_location)
    print(f"LIVE_DETECTION REQUEST_SUCCEEDED={summary.request_succeeded}")
    print(f"LIVE_DETECTION ARMOR={summary.armor}")
    print(f"LIVE_DETECTION SCHEMA_PARSED={summary.schema_parsed}")
    print(
        "LIVE_DETECTION VALUES="
        f"{summary.placement_fee_prohibition},"
        f"{summary.fee_schedule_reissue},"
        f"{summary.employer_paid_medical_exception}"
    )
    print(f"LIVE_DETECTION VERIFIER_ACCEPTED={summary.verifier_accepted}")
    print(f"LIVE_DETECTION CANDIDATES={summary.candidate_count}")
    print(f"LIVE_DETECTION VERIFIED={summary.verified_count}")
    assert summary.request_succeeded
    assert summary.armor == "allowed"
    assert summary.schema_parsed
    assert (
        summary.placement_fee_prohibition,
        summary.fee_schedule_reissue,
        summary.employer_paid_medical_exception,
    ) == (True, True, True)
    assert summary.verifier_accepted
    assert summary.candidate_count == summary.verified_count == 3
