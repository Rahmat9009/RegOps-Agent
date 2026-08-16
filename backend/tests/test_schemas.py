import json
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, ValidationError

from regops_api.schemas import (
    Approval,
    ApprovalDecision,
    AuditReport,
    ChangeDetection,
    CounterfactualPreview,
    EvidenceReference,
    FindingList,
    FindingsBySeverity,
    FindingScores,
    FindingSummary,
    RecoveryInfo,
    Run,
    RunProgress,
    RunState,
    RunTransition,
)
from tests.factories import NOW, make_run


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
            "finding_id": "finding-1",
            "status": "APPROVED",
            "decided_by": "demo-reviewer",
        }
    )

    assert approval.decided_by == "demo-reviewer"


def test_finding_summary_requires_scores() -> None:
    data = {
        "finding_id": "finding-1",
        "run_id": "run-1",
        "target_id": "contract-1",
        "relationship": "conflicts_with",
        "severity": "high",
        "verdict": "survived",
        "status": "OPEN",
        "human_review_required": True,
    }

    with pytest.raises(ValidationError, match="scores"):
        FindingSummary.model_validate(data)


def test_recovery_metadata_requires_checkpoint_when_available() -> None:
    unavailable = RecoveryInfo(
        recovery_available=False,
        checkpoint_state=None,
        attempt_count=0,
        last_error_code=None,
        last_error_message=None,
    )

    assert unavailable.checkpoint_state is None
    with pytest.raises(ValidationError, match="requires checkpoint_state"):
        RecoveryInfo(
            recovery_available=True,
            checkpoint_state=None,
            attempt_count=1,
            last_error_code="VERTEX_TIMEOUT",
            last_error_message="Provider request timed out",
        )


@pytest.mark.parametrize(
    "invalid_hash",
    [
        "A" * 64,
        "g" * 64,
        "a" * 63,
        "a" * 65,
        "not-a-sha256",
    ],
)
def test_change_detection_rejects_non_lowercase_sha256(invalid_hash: str) -> None:
    with pytest.raises(ValidationError):
        ChangeDetection(
            source_sha256=invalid_hash,
            previous_source_sha256=None,
            changed=True,
            detected_at=NOW,
        )


def test_change_detection_validates_previous_sha256_too() -> None:
    with pytest.raises(ValidationError):
        ChangeDetection(
            source_sha256="a" * 64,
            previous_source_sha256="B" * 64,
            changed=True,
            detected_at=NOW,
        )


def test_run_rejects_first_transition_with_non_null_from_state() -> None:
    run = make_run()
    payload = run.model_dump()
    payload["transitions"][0]["from_state"] = RunState.FAILED

    with pytest.raises(ValidationError, match="first transition"):
        Run.model_validate(payload)


def test_run_rejects_discontinuous_transition_chain() -> None:
    run = make_run()
    discontinuous = RunTransition(
        from_state=RunState.MAPPED,
        to_state=RunState.EXTRACTING,
        occurred_at=datetime(2026, 8, 16, 12, 1, tzinfo=UTC),
        reason=None,
        actor="orchestrator",
    )
    payload = run.model_dump()
    payload["state"] = RunState.EXTRACTING
    payload["transitions"].append(discontinuous.model_dump())

    with pytest.raises(ValidationError, match="continuous state chain"):
        Run.model_validate(payload)


def test_run_rejects_final_transition_that_disagrees_with_state() -> None:
    run = make_run()
    final = RunTransition(
        from_state=RunState.INGESTED,
        to_state=RunState.EXTRACTING,
        occurred_at=datetime(2026, 8, 16, 12, 1, tzinfo=UTC),
        reason=None,
        actor="orchestrator",
    )
    payload = run.model_dump()
    payload["transitions"].append(final.model_dump())

    assert run.transitions[0].from_state is None
    assert run.recovery is None
    assert run.change_detection is None
    with pytest.raises(ValidationError, match="final transition"):
        Run.model_validate(payload)


def test_run_rejects_reverse_chronological_transitions() -> None:
    run = make_run()
    initial = run.transitions[0].model_copy(
        update={"occurred_at": datetime(2026, 8, 16, 12, 2, tzinfo=UTC)}
    )
    second = RunTransition(
        from_state=RunState.INGESTED,
        to_state=RunState.EXTRACTING,
        occurred_at=datetime(2026, 8, 16, 12, 1, tzinfo=UTC),
        reason=None,
        actor="orchestrator",
    )
    payload = run.model_dump()
    payload["state"] = RunState.EXTRACTING
    payload["transitions"] = [initial.model_dump(), second.model_dump()]

    with pytest.raises(ValidationError, match="oldest to newest"):
        Run.model_validate(payload)


@pytest.mark.parametrize(("field", "value"), [("actor", ""), ("reason", "")])
def test_run_transition_rejects_empty_safe_labels(field: str, value: str) -> None:
    payload = {
        "from_state": None,
        "to_state": RunState.INGESTED,
        "occurred_at": NOW,
        "reason": None,
        "actor": "system",
    }
    payload[field] = value

    with pytest.raises(ValidationError, match=field):
        RunTransition.model_validate(payload)


def test_finding_list_enforces_pagination_bounds() -> None:
    with pytest.raises(ValidationError):
        FindingList(
            items=[],
            total=0,
            limit=101,
            offset=0,
            by_severity=FindingsBySeverity(low=0, medium=0, high=0),
        )


@pytest.mark.parametrize(
    "invalid_url",
    [
        "https://?download=1",
        "https://#fragment",
        "https:///audit.zip",
        "http://example.com/audit.zip",
        "//example.com/audit.zip",
        "/audit.zip",
        "javascript:alert(1)",
        "data:text/plain,test",
        " javascript:alert(1)",
        " https://example.com/audit.zip",
    ],
)
def test_audit_package_url_must_be_absolute_https(invalid_url: str) -> None:
    with pytest.raises(ValidationError):
        AuditReport.model_validate(
            {
                "run_id": "run-1",
                "generated_at": NOW,
                "executed_actions": [],
                "idempotency": {
                    "duplicate_actions_prevented": 0,
                    "duplicate_action_rate": 0,
                },
                "revalidation": {"findings_resolved": 0, "findings_remaining": 0},
                "processing": {"total_seconds": 0, "documents_processed": 0},
                "audit_package_url": invalid_url,
            }
        )


def test_signed_audit_package_url_serializes_as_json_string() -> None:
    signed_url = (
        "https://storage.googleapis.com/regops-audit/run-1.zip?"
        "X-Goog-Signature=abc123"
    )
    report = AuditReport.model_validate(
        {
            "run_id": "run-1",
            "generated_at": NOW,
            "executed_actions": [],
            "idempotency": {
                "duplicate_actions_prevented": 0,
                "duplicate_action_rate": 0,
            },
            "revalidation": {"findings_resolved": 0, "findings_remaining": 0},
            "processing": {"total_seconds": 0, "documents_processed": 0},
            "audit_package_url": signed_url,
        }
    )
    serialized_url = json.loads(report.model_dump_json())["audit_package_url"]

    assert serialized_url == signed_url
    assert isinstance(serialized_url, str)


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
