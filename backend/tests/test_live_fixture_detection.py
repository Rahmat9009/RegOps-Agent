from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from regops_api.analyst_settings import AnalystSettings
from regops_api.live_fixture import (
    KNOWN_SOURCE_SHA256,
    MINIMUM_LIVE_FIXTURE_KEYS,
    MinimumLiveFixture,
    load_minimum_live_fixture,
    resolve_minimum_live_detections,
)
from regops_api.pdf_reader import parse_pdf
from regops_api.verification import verify_obligations
from regops_api.worker_models import EvidenceAnchor, MinimumLiveDetection, SourceDocument

SAMPLE = Path(__file__).parents[2] / "samples" / "regops-synthetic-regulation-2026.pdf"


def source_and_fixture() -> tuple[SourceDocument, MinimumLiveFixture]:
    content = SAMPLE.read_bytes()
    fixture = load_minimum_live_fixture(sha256(content).hexdigest())
    source = parse_pdf(
        content=content,
        doc_id=fixture.source_doc_id,
        source_sha256=fixture.source_sha256,
        limits=AnalystSettings().pdf,
    )
    return source, fixture


def all_detected() -> MinimumLiveDetection:
    return MinimumLiveDetection(
        placement_fee_prohibition=True,
        fee_schedule_reissue=True,
        employer_paid_medical_exception=True,
    )


def test_all_true_fixture_detections_resolve_to_exact_immutable_candidates() -> None:
    source, fixture = source_and_fixture()

    candidates = resolve_minimum_live_detections(
        fixture=fixture,
        source=source,
        detections=all_detected(),
    )

    assert fixture.obligation_keys == MINIMUM_LIVE_FIXTURE_KEYS
    assert len(candidates.obligations) == 3
    assert [item.model_dump() for item in candidates.obligations] == [
        item.model_dump() for item in fixture.accepted_obligations
    ]
    checked = verify_obligations(
        run_id="fixture-detection-test",
        source=source,
        accepted=fixture.accepted_catalog(source),
        candidates=candidates,
    )
    assert checked.output is not None and checked.result.obligation_count == 3


def test_detection_model_is_strict_frozen_and_has_no_authoritative_fields() -> None:
    assert set(MinimumLiveDetection.model_fields) == set(MINIMUM_LIVE_FIXTURE_KEYS)
    for malformed in (
        {"placement_fee_prohibition": True, "fee_schedule_reissue": True},
        {
            "placement_fee_prohibition": 1,
            "fee_schedule_reissue": True,
            "employer_paid_medical_exception": True,
        },
        all_detected().model_dump() | {"statement": "model-owned"},
    ):
        with pytest.raises(ValidationError):
            MinimumLiveDetection.model_validate(malformed)
    with pytest.raises(ValidationError):
        all_detected().placement_fee_prohibition = False


@pytest.mark.parametrize("key", MINIMUM_LIVE_FIXTURE_KEYS)
def test_any_false_detection_fails_closed_before_resolution(key: str) -> None:
    source, fixture = source_and_fixture()
    detections = MinimumLiveDetection.model_validate(all_detected().model_dump() | {key: False})

    with pytest.raises(ValueError, match="FIXTURE_DETECTION_REJECTED"):
        resolve_minimum_live_detections(
            fixture=fixture,
            source=source,
            detections=detections,
        )


@pytest.mark.parametrize("change", ["quote", "page"])
def test_resolved_fixture_candidates_still_require_exact_pdf_evidence(change: str) -> None:
    source, fixture = source_and_fixture()
    anchor = fixture.accepted_obligations[0].evidence[0]
    update: dict[str, object] = (
        {"quote": "Synthetic quotation absent from the document."}
        if change == "quote"
        else {"page": 2}
    )
    changed_anchor = EvidenceAnchor.model_validate(
        anchor.model_dump() | update
    )
    changed_obligation = fixture.accepted_obligations[0].model_copy(
        update={"evidence": (changed_anchor, *fixture.accepted_obligations[0].evidence[1:])}
    )
    changed_fixture = fixture.model_copy(
        update={"accepted_obligations": (changed_obligation, *fixture.accepted_obligations[1:])}
    )
    candidates = resolve_minimum_live_detections(
        fixture=changed_fixture,
        source=source,
        detections=all_detected(),
    )

    checked = verify_obligations(
        run_id="fixture-detection-test",
        source=source,
        accepted=changed_fixture.accepted_catalog(source),
        candidates=candidates,
    )

    assert checked.output is None


def test_unknown_hash_and_wrong_document_never_resolve_fixture_detections() -> None:
    source, fixture = source_and_fixture()
    wrong_identity = source.identity.model_copy(update={"doc_id": "wrong-synthetic-doc"})
    wrong_pages = tuple(
        page.model_copy(update={"doc_id": wrong_identity.doc_id}) for page in source.pages
    )
    wrong_source = source.model_copy(update={"identity": wrong_identity, "pages": wrong_pages})

    with pytest.raises(ValueError, match="FIXTURE_DETECTION_BOUNDARY_REJECTED"):
        resolve_minimum_live_detections(
            fixture=fixture,
            source=wrong_source,
            detections=all_detected(),
        )
    with pytest.raises(ValueError, match="UNKNOWN_LIVE_SOURCE"):
        load_minimum_live_fixture("f" * 64)
    assert fixture.source_sha256 == KNOWN_SOURCE_SHA256
