from __future__ import annotations

from datetime import UTC, datetime

import pytest

from regops_api.action_policy import (
    ActionPolicy,
    AllowlistedActionService,
    derive_idempotency_key,
)
from regops_api.approvals import (
    DEMO_REVIEWER,
    ApprovalAlreadyDecidedError,
    ApprovalService,
)
from regops_api.audit import AuditReportService
from regops_api.counterfactual import DeterministicCounterfactual
from regops_api.domain_models import (
    AuditEventType,
    ConflictMatch,
    IdempotencyResult,
    ProposedAmendment,
    SyntheticContract,
)
from regops_api.in_memory import InMemoryRepositories
from regops_api.repositories import RecordNotFoundError
from regops_api.schemas import (
    ActionStatus,
    ActionType,
    ApprovalDecision,
    ApprovalDecisionValue,
    ApprovalStatus,
    FindingStatus,
    Obligation,
    Severity,
)
from regops_api.state_machine import RunStateCoordinator
from tests.factories import NOW, make_contract, make_finding, make_obligation, make_run


def matching_pipeline(
    contract: SyntheticContract, obligations: list[Obligation]
) -> list[ConflictMatch]:
    assert obligations
    if "forever" in contract.clauses["retention"]:
        return [ConflictMatch(conflict_id="finding-1", severity=Severity.HIGH)]
    return []


def seed_repositories() -> InMemoryRepositories:
    repositories = InMemoryRepositories.for_tests()
    RunStateCoordinator(repositories, repositories, repositories).initialize(make_run())
    repositories.add_findings([make_finding()])
    repositories.add_obligations("run-1", [make_obligation()])
    repositories.add_synthetic_contract(make_contract())
    return repositories


def make_action_service(
    repositories: InMemoryRepositories,
) -> AllowlistedActionService:
    return AllowlistedActionService(
        actions=repositories,
        findings=repositories,
        review_tasks=repositories,
        case_tags=repositories,
        approvals=repositories,
        audits=repositories,
        clock=lambda: NOW,
    )


def make_approval_service(repositories: InMemoryRepositories) -> ApprovalService:
    return ApprovalService(
        approvals=repositories,
        actions=repositories,
        contracts=repositories,
        obligations=repositories,
        findings=repositories,
        audits=repositories,
        counterfactual=DeterministicCounterfactual(matching_pipeline),
        clock=lambda: NOW,
    )


def proposed_amendment() -> ProposedAmendment:
    finding = make_finding()
    action = ActionPolicy().propose(finding, ActionType.DRAFT_AMENDMENT)
    return ProposedAmendment(
        action_id=action.action_id,
        finding_id=finding.finding_id,
        contract_id=finding.target_id,
        clause_updates={"retention": "retain for 30 days"},
    )


def test_policy_autonomy_and_idempotency_key_are_backend_determined() -> None:
    finding = make_finding()
    policy = ActionPolicy()

    tag = policy.propose(finding, ActionType.TAG_CASE)
    task = policy.propose(finding, ActionType.CREATE_REVIEW_TASK)
    draft = policy.propose(finding, ActionType.DRAFT_AMENDMENT)

    assert tag.autonomy.value == "auto"
    assert task.autonomy.value == "auto"
    assert draft.autonomy.value == "approval_required"
    assert draft.status is ActionStatus.AWAITING_APPROVAL
    assert tag.idempotency_key == derive_idempotency_key(
        "run-1", "finding-1", ActionType.TAG_CASE
    )
    assert len({tag.idempotency_key, task.idempotency_key, draft.idempotency_key}) == 3


def test_automatic_review_task_is_idempotent_and_audited() -> None:
    repositories = seed_repositories()
    service = make_action_service(repositories)
    finding = make_finding()

    first = service.attempt(
        finding=finding, action_type=ActionType.CREATE_REVIEW_TASK
    )
    duplicate = service.attempt(
        finding=finding, action_type=ActionType.CREATE_REVIEW_TASK
    )

    assert first.action.status is ActionStatus.EXECUTED
    assert duplicate.duplicate_prevented is True
    assert duplicate.action.action_id == first.action.action_id
    assert len(repositories.list_review_tasks("run-1")) == 1
    results = [
        event.idempotency_result
        for event in repositories.list_audit_events("run-1")
        if event.event_type is AuditEventType.IDEMPOTENCY_RESULT
    ]
    assert results == [
        IdempotencyResult.FIRST_EXECUTION,
        IdempotencyResult.DUPLICATE_PREVENTED,
    ]


def test_tag_case_is_automatic_and_allowlisted() -> None:
    repositories = seed_repositories()
    result = make_action_service(repositories).attempt(
        finding=make_finding(), action_type=ActionType.TAG_CASE
    )

    assert result.action.status is ActionStatus.EXECUTED
    assert repositories.list_case_tags("run-1")[0].tag == "potential-regulatory-conflict"


def test_draft_amendment_cannot_target_a_different_finding_or_contract() -> None:
    repositories = seed_repositories()
    service = make_action_service(repositories)
    amendment = proposed_amendment().model_copy(update={"contract_id": "contract-2"})

    with pytest.raises(ValueError, match="target must match"):
        service.attempt(
            finding=make_finding(),
            action_type=ActionType.DRAFT_AMENDMENT,
            amendment=amendment,
        )

    assert repositories.list_actions("run-1") == []


def test_rejected_amendment_never_executes_and_repeated_decision_conflicts() -> None:
    repositories = seed_repositories()
    attempt = make_action_service(repositories).attempt(
        finding=make_finding(),
        action_type=ActionType.DRAFT_AMENDMENT,
        amendment=proposed_amendment(),
    )
    assert attempt.approval is not None
    approvals = make_approval_service(repositories)

    result = approvals.decide(
        attempt.approval.approval_id,
        ApprovalDecision(
            decision=ApprovalDecisionValue.REJECT,
            note="Needs human revision.",
        ),
    )

    assert result.approval.status is ApprovalStatus.REJECTED
    assert result.approval.decided_by == DEMO_REVIEWER
    assert result.counterfactual is None
    assert repositories.get_action(attempt.action.action_id).action.status is ActionStatus.REJECTED
    with pytest.raises(RecordNotFoundError):
        repositories.get_shadow_snapshot(result.approval.action_id)
    assert not any(
        event.event_type is AuditEventType.ACTION_EXECUTED
        for event in repositories.list_audit_events("run-1")
    )
    with pytest.raises(ApprovalAlreadyDecidedError):
        approvals.decide(
            attempt.approval.approval_id,
            ApprovalDecision(decision=ApprovalDecisionValue.APPROVE),
        )


def test_approved_amendment_updates_only_shadow_and_resolves_detected_finding() -> None:
    repositories = seed_repositories()
    original = repositories.get_synthetic_contract("contract-1")
    attempt = make_action_service(repositories).attempt(
        finding=make_finding(),
        action_type=ActionType.DRAFT_AMENDMENT,
        amendment=proposed_amendment(),
    )
    assert attempt.approval is not None

    result = make_approval_service(repositories).decide(
        attempt.approval.approval_id,
        ApprovalDecision(decision=ApprovalDecisionValue.APPROVE),
    )

    assert result.approval.status is ApprovalStatus.APPROVED
    assert result.approval.decided_by == DEMO_REVIEWER
    assert result.counterfactual is not None
    assert result.counterfactual.preview.resolved_finding_ids == ["finding-1"]
    approved_action = repositories.get_action(attempt.action.action_id).action
    assert approved_action.status is ActionStatus.APPROVED_DRAFT
    assert repositories.get_finding("finding-1").status is FindingStatus.RESOLVED
    assert repositories.get_synthetic_contract("contract-1") == original
    snapshot = repositories.get_shadow_snapshot(
        result.counterfactual.snapshot.snapshot_id
    )
    assert snapshot.shadow.clauses["retention"] == "retain for 30 days"


def test_audit_report_counts_prevented_duplicates_without_fabricated_evaluation() -> None:
    repositories = seed_repositories()
    action_service = make_action_service(repositories)
    action_service.attempt(
        finding=make_finding(), action_type=ActionType.CREATE_REVIEW_TASK
    )
    action_service.attempt(
        finding=make_finding(), action_type=ActionType.CREATE_REVIEW_TASK
    )

    report = AuditReportService(
        runs=repositories,
        actions=repositories,
        findings=repositories,
        audits=repositories,
        clock=lambda: datetime.now(UTC),
    ).generate("run-1")

    assert report.idempotency.duplicate_actions_prevented == 1
    assert report.idempotency.duplicate_action_rate == 0.5
    assert report.evaluation is None
    assert repositories.get_audit_report("run-1") == report
