from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, ValidationError

from regops_api.schemas import (
    Approval,
    ApprovalDecision,
    CounterfactualPreview,
    EvidenceReference,
    FindingScores,
    RunProgress,
    RunState,
)


def test_run_state_contract_is_unchanged() -> None:
    assert [state.value for state in RunState] == [
        "INGESTED",
        "EXTRACTING",
        "EXTRACTED",
        "MAPPING",
        "MAPPED",
        "VERIFYING",
        "VERIFIED",
        "AWAITING_APPROVAL",
        "EXECUTING",
        "REVALIDATING",
        "COMPLETED",
        "FAILED_RECOVERABLE",
        "FAILED",
    ]


def test_counterfactual_preview_has_deterministic_shadow_output() -> None:
    preview = CounterfactualPreview(
        action_id="action-1",
        shadow_run_id="shadow-1",
        baseline_finding_count=3,
        resolved_finding_ids=["finding-1"],
        unchanged_finding_ids=["finding-2"],
        new_conflict_ids=[],
        remaining_high_risk_ids=["finding-2"],
        detected_finding_picture_improves=True,
    )

    assert preview.narrative is None
    assert preview.baseline_finding_count == 3


def test_approval_decision_accepts_decision_and_optional_note() -> None:
    without_note = ApprovalDecision.model_validate({"decision": "approve"})
    with_note = ApprovalDecision.model_validate(
        {"decision": "reject", "note": "Evidence needs another review."}
    )

    assert without_note.note is None
    assert with_note.note == "Evidence needs another review."


def test_approval_decision_rejects_client_supplied_reviewer_identity() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ApprovalDecision.model_validate(
            {"decision": "approve", "decided_by": "client-selected-reviewer"}
        )


def test_approval_response_may_include_backend_assigned_reviewer_identity() -> None:
    approval = Approval.model_validate(
        {
            "approval_id": "approval-1",
            "action_id": "action-1",
            "run_id": "run-1",
            "status": "APPROVED",
            "decided_by": "demo-reviewer",
        }
    )

    assert approval.decided_by == "demo-reviewer"


@pytest.mark.parametrize(
    ("model", "data"),
    [
        (
            EvidenceReference,
            {"doc_id": "reg-1", "doc_kind": "regulation", "page": 0, "quote": "x"},
        ),
        (
            FindingScores,
            {
                "evidence_strength": 1.01,
                "source_authority": "primary_government",
                "interpretation_confidence": 0.5,
                "operational_severity": "high",
                "human_review_required": True,
            },
        ),
        (
            RunProgress,
            {
                "documents_total": 1,
                "documents_processed": 2,
                "percent": 50,
            },
        ),
    ],
)
def test_core_schema_constraints_reject_invalid_input(
    model: type[BaseModel], data: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(data)


def test_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        CounterfactualPreview.model_validate(
            {
                "action_id": "action-1",
                "shadow_run_id": "shadow-1",
                "baseline_finding_count": 0,
                "resolved_finding_ids": [],
                "unchanged_finding_ids": [],
                "new_conflict_ids": [],
                "remaining_high_risk_ids": [],
                "detected_finding_picture_improves": False,
                "gemini_authoritative_count": 1,
            }
        )


def test_datetime_fixture_is_timezone_aware() -> None:
    assert datetime.now(UTC).tzinfo is UTC
