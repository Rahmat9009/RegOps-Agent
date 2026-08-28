"""Persistence interfaces for Phase 1A domain records."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from regops_api.domain_models import (
    ActionAttemptResult,
    ActionRecord,
    ApprovalDecisionCommit,
    ApprovalRequiredActionCommit,
    AuditEvent,
    CaseTag,
    InternalReviewTask,
    RegulationRecord,
    RunCheckpoint,
    RunIntakeCommit,
    ShadowContractSnapshot,
    SourceDocumentRecord,
    SyntheticContract,
    VerifiedWorkerHandoffCommit,
    WorkerHandoffRecord,
)
from regops_api.schemas import (
    ActionAutonomy,
    ActionStatus,
    ActionType,
    AffectedCase,
    Approval,
    ApprovalStatus,
    AuditReport,
    Finding,
    Obligation,
    Run,
    RunState,
)


class RecordNotFoundError(LookupError):
    """Raised when a requested repository record does not exist."""


class DuplicateRecordError(RuntimeError):
    """Raised when a unique record or idempotency key already exists."""


class StaleRecordError(RuntimeError):
    """Raised when an atomic update observes a different current record."""


def validate_approval_decision_outputs(commit: ApprovalDecisionCommit) -> None:
    expected = commit.expected_action.action
    updated = commit.action.action
    approved = commit.approval.status is ApprovalStatus.APPROVED
    if (
        commit.expected_approval.approval_id != commit.approval.approval_id
        or commit.expected_approval.action_id != expected.action_id
        or commit.expected_approval.finding_id != commit.expected_finding.finding_id
        or commit.expected_approval.run_id != commit.expected_action.run_id
        or expected.type is not ActionType.DRAFT_AMENDMENT
        or expected.autonomy is not ActionAutonomy.APPROVAL_REQUIRED
        or expected.status is not ActionStatus.AWAITING_APPROVAL
        or commit.approval.status
        not in {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}
        or commit.approval.action_id != expected.action_id
        or commit.approval.finding_id != expected.finding_id
        or commit.approval.run_id != commit.expected_action.run_id
        or commit.action.run_id != commit.expected_action.run_id
        or updated.action_id != expected.action_id
        or updated.finding_id != expected.finding_id
        or updated.idempotency_key != expected.idempotency_key
        or updated.type is not expected.type
        or updated.autonomy is not expected.autonomy
        or updated.status
        is not (
            ActionStatus.APPROVED_DRAFT if approved else ActionStatus.REJECTED
        )
        or commit.finding.finding_id != commit.expected_finding.finding_id
        or commit.finding.run_id != commit.expected_finding.run_id
        or commit.finding.proposed_action != updated
        or commit.run.run_id != commit.expected_action.run_id
        or any(
            checkpoint.run_id != commit.run.run_id
            for checkpoint in commit.checkpoints
        )
        or any(event.run_id != commit.run.run_id for event in commit.audit_events)
        or (approved and commit.snapshot is None)
        or (not approved and commit.snapshot is not None)
    ):
        raise StaleRecordError("approval decision output binding is invalid")


class RunRepository(Protocol):
    def add_run(self, run: Run) -> None: ...

    def get_run(self, run_id: str) -> Run: ...

    def update_run(self, run: Run) -> None: ...


class RegulationRepository(Protocol):
    def add_regulation(self, record: RegulationRecord) -> None: ...

    def get_regulation(self, regulation_id: str) -> RegulationRecord: ...

    def find_regulation_by_hash(self, content_sha256: str) -> RegulationRecord | None: ...

    def list_regulations_by_source(self, source_filename: str) -> list[RegulationRecord]: ...


class SourceDocumentRepository(Protocol):
    def add_source_document(self, record: SourceDocumentRecord) -> None: ...

    def get_source_document(self, run_id: str) -> SourceDocumentRecord: ...


class ObligationRepository(Protocol):
    def add_obligations(self, run_id: str, obligations: list[Obligation]) -> None: ...

    def list_obligations(self, run_id: str) -> list[Obligation]: ...


class SyntheticContractRepository(Protocol):
    def add_synthetic_contract(self, contract: SyntheticContract) -> None: ...

    def get_synthetic_contract(self, contract_id: str) -> SyntheticContract: ...

    def list_synthetic_contracts(self) -> list[SyntheticContract]: ...

    def save_shadow_snapshot(self, snapshot: ShadowContractSnapshot) -> None: ...

    def get_shadow_snapshot(self, snapshot_id: str) -> ShadowContractSnapshot: ...


class SyntheticCaseRepository(Protocol):
    def add_synthetic_case(self, case: AffectedCase) -> None: ...

    def get_synthetic_case(self, case_id: str) -> AffectedCase: ...

    def list_synthetic_cases(self) -> list[AffectedCase]: ...


class FindingRepository(Protocol):
    def add_findings(self, findings: list[Finding]) -> None: ...

    def get_finding(self, finding_id: str) -> Finding: ...

    def list_findings(self, run_id: str) -> list[Finding]: ...

    def update_finding(self, finding: Finding) -> None: ...


class ReviewTaskRepository(Protocol):
    def add_review_task(self, task: InternalReviewTask) -> None: ...

    def get_review_task(self, task_id: str) -> InternalReviewTask: ...

    def list_review_tasks(self, run_id: str) -> list[InternalReviewTask]: ...


class ApprovalRepository(Protocol):
    def add_approval(self, approval: Approval) -> None: ...

    def get_approval(self, approval_id: str) -> Approval: ...

    def update_approval(self, approval: Approval) -> None: ...

    def list_approvals(self, run_id: str) -> list[Approval]: ...


class AuditRepository(Protocol):
    def append_audit_event(self, event: AuditEvent) -> None: ...

    def list_audit_events(self, run_id: str) -> list[AuditEvent]: ...

    def save_audit_report(self, report: AuditReport) -> None: ...

    def get_audit_report(self, run_id: str) -> AuditReport: ...


class ActionRepository(Protocol):
    def add_action(self, record: ActionRecord) -> None: ...

    def get_action(self, action_id: str) -> ActionRecord: ...

    def find_action_by_idempotency_key(self, idempotency_key: str) -> ActionRecord | None: ...

    def update_action(self, record: ActionRecord) -> None: ...

    def list_actions(self, run_id: str) -> list[ActionRecord]: ...


class CheckpointRepository(Protocol):
    def append_checkpoint(self, checkpoint: RunCheckpoint) -> None: ...

    def latest_checkpoint(self, run_id: str) -> RunCheckpoint | None: ...

    def list_checkpoints(self, run_id: str) -> list[RunCheckpoint]: ...


class CaseTagRepository(Protocol):
    def add_case_tag(self, tag: CaseTag) -> None: ...

    def list_case_tags(self, run_id: str) -> list[CaseTag]: ...


@runtime_checkable
class RunStateAtomicRepository(Protocol):
    def initialize_run_state(self, run: Run, checkpoint: RunCheckpoint) -> None: ...

    def commit_run_transition(
        self,
        *,
        expected_state: RunState,
        run: Run,
        checkpoint: RunCheckpoint,
        audit_event: AuditEvent,
    ) -> None: ...


@runtime_checkable
class ApprovalDecisionAtomicRepository(Protocol):
    def commit_approval_decision(self, commit: ApprovalDecisionCommit) -> None: ...


@runtime_checkable
class ApprovalRequiredActionAtomicRepository(Protocol):
    def create_approval_required_action(
        self, commit: ApprovalRequiredActionCommit
    ) -> ActionAttemptResult: ...


@runtime_checkable
class RunIntakeAtomicRepository(Protocol):
    def commit_run_intake(self, commit: RunIntakeCommit) -> None: ...


@runtime_checkable
class VerifiedWorkerHandoffAtomicRepository(Protocol):
    def get_worker_handoff(self, run_id: str) -> WorkerHandoffRecord: ...

    def commit_verified_worker_handoff(self, commit: VerifiedWorkerHandoffCommit) -> bool: ...


class RepositoryBundle(
    RunRepository,
    RegulationRepository,
    SourceDocumentRepository,
    ObligationRepository,
    SyntheticContractRepository,
    SyntheticCaseRepository,
    FindingRepository,
    ReviewTaskRepository,
    ApprovalRepository,
    AuditRepository,
    ActionRepository,
    CheckpointRepository,
    CaseTagRepository,
    RunStateAtomicRepository,
    ApprovalDecisionAtomicRepository,
    ApprovalRequiredActionAtomicRepository,
    RunIntakeAtomicRepository,
    VerifiedWorkerHandoffAtomicRepository,
    Protocol,
):
    """Complete persistence surface required by the Phase 1B runtime."""
