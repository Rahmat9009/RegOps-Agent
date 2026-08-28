"""Strict internal models for the Phase 1A domain foundation."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from regops_api.schemas import (
    ActionAutonomy,
    ActionStatus,
    ActionType,
    AffectedCase,
    Approval,
    ApprovalStatus,
    AuditReport,
    EvidenceReference,
    Finding,
    FindingScores,
    FindingStatus,
    FindingVerdict,
    Obligation,
    ProposedAction,
    Regulation,
    Relationship,
    Run,
    RunState,
    Severity,
)
from regops_api.worker_models import VerifiedWorkerOutput


class DomainModel(BaseModel):
    """Strict base for records that never accept undeclared agent or client data."""

    model_config = ConfigDict(extra="forbid")


class ChangeClassification(StrEnum):
    NEW = "new"
    REVISED = "revised"
    DUPLICATE = "duplicate"


class DetectionResult(DomainModel):
    classification: ChangeClassification
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_regulation_id: str | None = None
    next_version: int = Field(ge=1)


class RegulationRecord(DomainModel):
    regulation: Regulation
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    version: int = Field(ge=1)
    supersedes_regulation_id: str | None = None
    created_at: datetime


class SourceDocumentRecord(DomainModel):
    run_id: str = Field(min_length=1)
    regulation_id: str = Field(min_length=1)
    object_name: str = Field(min_length=1)
    gcs_uri: str = Field(pattern=r"^gs://[^/]+/.+$")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1)
    content_type: Literal["application/pdf"]
    sanitized_filename: str = Field(min_length=1)
    synthetic: Literal[True]
    created_at: datetime


class StoredSourceObject(DomainModel):
    object_name: str = Field(min_length=1)
    gcs_uri: str = Field(pattern=r"^gs://[^/]+/.+$")


class WorkflowLaunchRequest(DomainModel):
    run_id: str = Field(min_length=1)
    source_gcs_uri: str = Field(pattern=r"^gs://[^/]+/.+$")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    synthetic: Literal[True]


class SyntheticContract(DomainModel):
    """A labelled synthetic contract record; never a real customer contract."""

    contract_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    clauses: dict[str, str]
    revision: int = Field(default=1, ge=1)
    synthetic: Literal[True]


class ProposedAmendment(DomainModel):
    action_id: str = Field(min_length=1)
    finding_id: str = Field(min_length=1)
    contract_id: str = Field(min_length=1)
    clause_updates: dict[str, str] = Field(min_length=1)


class ShadowContractSnapshot(DomainModel):
    snapshot_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    source_revision: int = Field(ge=1)
    original: SyntheticContract
    shadow: SyntheticContract
    created_at: datetime


class InvestigatedFinding(DomainModel):
    """Investigator output deliberately excludes all proposed-action fields."""

    finding_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    relationship: Relationship
    severity: Severity
    verdict: FindingVerdict
    status: FindingStatus
    human_review_required: bool
    obligation: Obligation
    affected_case: AffectedCase | None = None
    evidence_path: list[EvidenceReference] = Field(min_length=1)
    scores: FindingScores


class AnalystOutput(DomainModel):
    obligations: list[Obligation] = Field(min_length=1)


class InvestigatorOutput(DomainModel):
    findings: list[InvestigatedFinding]


class InternalReviewTask(DomainModel):
    task_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    finding_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    status: Literal["OPEN", "CLOSED"] = "OPEN"
    synthetic: Literal[True]
    created_at: datetime


class CaseTag(DomainModel):
    case_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    finding_id: str = Field(min_length=1)
    tag: Literal["potential-regulatory-conflict"]
    created_at: datetime


class ActionRecord(DomainModel):
    run_id: str = Field(min_length=1)
    action: ProposedAction
    amendment: ProposedAmendment | None = None

    @model_validator(mode="after")
    def amendment_is_only_for_draft_action(self) -> ActionRecord:
        if self.action.type is ActionType.DRAFT_AMENDMENT and self.amendment is None:
            raise ValueError("draft_amendment requires an amendment payload")
        if self.action.type is not ActionType.DRAFT_AMENDMENT and self.amendment is not None:
            raise ValueError("only draft_amendment may carry an amendment payload")
        return self


class ActionAttemptResult(DomainModel):
    action: ProposedAction
    duplicate_prevented: bool
    approval: Approval | None = None


class PendingApprovalSlot(DomainModel):
    run_id: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    finding_id: str = Field(min_length=1)


class ApprovalRequiredActionCommit(DomainModel):
    expected_finding: Finding
    action: ActionRecord
    approval: Approval
    finding: Finding
    pending_slot: PendingApprovalSlot
    action_attempt_event: AuditEvent
    first_execution_event: AuditEvent
    duplicate_event: AuditEvent

    @model_validator(mode="after")
    def records_are_coherently_bound(self) -> ApprovalRequiredActionCommit:
        proposed = self.action.action
        amendment = self.action.amendment
        expected_finding = self.expected_finding.model_copy(
            update={
                "status": FindingStatus.AWAITING_APPROVAL,
                "proposed_action": proposed,
            }
        )
        identifiers = {
            self.expected_finding.run_id,
            self.action.run_id,
            self.approval.run_id,
            self.finding.run_id,
            self.pending_slot.run_id,
            self.action_attempt_event.run_id,
            self.first_execution_event.run_id,
            self.duplicate_event.run_id,
        }
        if len(identifiers) != 1:
            raise ValueError("approval-required action records must share one run")
        if (
            proposed.type is not ActionType.DRAFT_AMENDMENT
            or proposed.autonomy is not ActionAutonomy.APPROVAL_REQUIRED
            or proposed.status is not ActionStatus.AWAITING_APPROVAL
            or self.approval.status is not ApprovalStatus.PENDING
            or self.expected_finding.finding_id != proposed.finding_id
            or self.finding.finding_id != proposed.finding_id
            or self.approval.finding_id != proposed.finding_id
            or self.approval.action_id != proposed.action_id
            or self.pending_slot.approval_id != self.approval.approval_id
            or self.pending_slot.action_id != proposed.action_id
            or self.pending_slot.finding_id != proposed.finding_id
            or self.finding.status is not FindingStatus.AWAITING_APPROVAL
            or self.finding.proposed_action != proposed
            or self.finding != expected_finding
            or amendment is None
            or amendment.action_id != proposed.action_id
            or amendment.finding_id != proposed.finding_id
            or amendment.contract_id != self.expected_finding.target_id
            or self.action_attempt_event.event_type is not AuditEventType.ACTION_ATTEMPTED
            or self.action_attempt_event.action_id != proposed.action_id
            or self.first_execution_event.event_type is not AuditEventType.IDEMPOTENCY_RESULT
            or self.first_execution_event.action_id != proposed.action_id
            or self.first_execution_event.idempotency_result
            is not IdempotencyResult.FIRST_EXECUTION
            or self.duplicate_event.event_type is not AuditEventType.IDEMPOTENCY_RESULT
            or self.duplicate_event.action_id != proposed.action_id
            or self.duplicate_event.idempotency_result is not IdempotencyResult.DUPLICATE_PREVENTED
        ):
            raise ValueError("approval-required action binding is invalid")
        return self


class RunCheckpoint(DomainModel):
    run_id: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    state: RunState
    recorded_at: datetime
    resume_state: RunState | None = None
    failure_code: str | None = None

    @model_validator(mode="after")
    def recoverable_failure_requires_resume_state(self) -> RunCheckpoint:
        if self.state is RunState.FAILED_RECOVERABLE and self.resume_state is None:
            raise ValueError("FAILED_RECOVERABLE checkpoints require resume_state")
        if self.state is not RunState.FAILED_RECOVERABLE and self.resume_state is not None:
            raise ValueError("resume_state is only valid for FAILED_RECOVERABLE checkpoints")
        return self


class RunIntakeCommit(DomainModel):
    run: Run
    checkpoint: RunCheckpoint
    regulation: RegulationRecord
    source_document: SourceDocumentRecord

    @model_validator(mode="after")
    def records_are_coherently_bound(self) -> RunIntakeCommit:
        expected_object_name = f"runs/{self.run.run_id}/source/regulation.pdf"
        gcs_object_name = self.source_document.gcs_uri.removeprefix("gs://").partition("/")[2]
        if (
            self.run.state is not RunState.INGESTED
            or self.checkpoint.run_id != self.run.run_id
            or self.checkpoint.sequence != 0
            or self.checkpoint.state is not self.run.state
            or self.checkpoint.recorded_at != self.run.created_at
            or self.regulation.regulation != self.run.regulation
            or self.source_document.run_id != self.run.run_id
            or self.source_document.regulation_id != self.run.regulation.reg_id
            or self.source_document.source_sha256 != self.regulation.content_sha256
            or self.source_document.sanitized_filename != self.run.regulation.source_filename
            or self.source_document.object_name != expected_object_name
            or gcs_object_name != expected_object_name
            or self.source_document.created_at != self.run.created_at
            or self.regulation.created_at != self.run.created_at
        ):
            raise ValueError("run intake metadata binding is invalid")
        return self


class AuditEventType(StrEnum):
    STATE_TRANSITION = "state_transition"
    ACTION_ATTEMPTED = "action_attempted"
    ACTION_EXECUTED = "action_executed"
    APPROVAL_DECIDED = "approval_decided"
    IDEMPOTENCY_RESULT = "idempotency_result"
    REVALIDATION_RESULT = "revalidation_result"


class IdempotencyResult(StrEnum):
    FIRST_EXECUTION = "first_execution"
    DUPLICATE_PREVENTED = "duplicate_prevented"


class RevalidationResult(DomainModel):
    resolved_finding_ids: list[str]
    unchanged_finding_ids: list[str]
    new_conflict_ids: list[str]


class AuditEvent(DomainModel):
    event_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    event_type: AuditEventType
    occurred_at: datetime
    action_id: str | None = None
    approval_id: str | None = None
    actor: str | None = None
    from_state: RunState | None = None
    to_state: RunState | None = None
    idempotency_result: IdempotencyResult | None = None
    revalidation_result: RevalidationResult | None = None

    @model_validator(mode="after")
    def fields_match_event_type(self) -> AuditEvent:
        if self.event_type is AuditEventType.STATE_TRANSITION and (
            self.from_state is None or self.to_state is None
        ):
            raise ValueError("state_transition requires from_state and to_state")
        if (
            self.event_type
            in {
                AuditEventType.ACTION_ATTEMPTED,
                AuditEventType.ACTION_EXECUTED,
            }
            and self.action_id is None
        ):
            raise ValueError("action audit events require action_id")
        if self.event_type is AuditEventType.APPROVAL_DECIDED and (
            self.approval_id is None or self.actor is None
        ):
            raise ValueError("approval_decided requires approval_id and actor")
        if self.event_type is AuditEventType.IDEMPOTENCY_RESULT and self.idempotency_result is None:
            raise ValueError("idempotency_result event requires its result")
        if (
            self.event_type is AuditEventType.REVALIDATION_RESULT
            and self.revalidation_result is None
        ):
            raise ValueError("revalidation_result event requires its result")
        return self


class ConflictMatch(DomainModel):
    conflict_id: str = Field(min_length=1)
    severity: Severity


class StoredApproval(DomainModel):
    approval: Approval


class StoredAuditReport(DomainModel):
    report: AuditReport


class ApprovalDecisionCommit(DomainModel):
    expected_approval: Approval
    expected_action: ActionRecord
    expected_finding: Finding
    expected_run_state: RunState
    approval: Approval
    action: ActionRecord
    finding: Finding
    run: Run
    snapshot: ShadowContractSnapshot | None = None
    checkpoints: list[RunCheckpoint]
    audit_events: list[AuditEvent]


class WorkerHandoffRecord(DomainModel):
    run_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    obligation_ids: list[str] = Field(min_length=1)
    finding_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)
    synthetic: Literal[True]


class VerifiedWorkerHandoffCommit(DomainModel):
    expected_source: SourceDocumentRecord
    output: VerifiedWorkerOutput
    obligations: list[Obligation] = Field(min_length=1)
    contract: SyntheticContract
    finding: Finding
    action: ActionRecord
    approval: Approval
    pending_slot: PendingApprovalSlot
    run: Run
    checkpoints: list[RunCheckpoint] = Field(min_length=3, max_length=3)
    audit_events: list[AuditEvent] = Field(min_length=5)
    handoff: WorkerHandoffRecord

    @model_validator(mode="after")
    def records_are_coherently_bound(self) -> VerifiedWorkerHandoffCommit:
        proposal = self.action.action
        run_id = self.output.run_id
        if (
            self.expected_source.run_id != run_id
            or self.expected_source.source_sha256 != self.output.source.source_sha256
            or self.run.run_id != run_id
            or self.run.state is not RunState.AWAITING_APPROVAL
            or self.run.pending_approvals != [self.approval]
            or self.finding.run_id != run_id
            or self.finding.status is not FindingStatus.AWAITING_APPROVAL
            or self.finding.proposed_action != proposal
            or self.action.run_id != run_id
            or self.action.amendment is None
            or proposal.type is not ActionType.DRAFT_AMENDMENT
            or proposal.autonomy is not ActionAutonomy.APPROVAL_REQUIRED
            or proposal.status is not ActionStatus.AWAITING_APPROVAL
            or self.approval.status is not ApprovalStatus.PENDING
            or self.approval.run_id != run_id
            or self.approval.action_id != proposal.action_id
            or self.approval.finding_id != self.finding.finding_id
            or self.pending_slot.run_id != run_id
            or self.pending_slot.approval_id != self.approval.approval_id
            or self.pending_slot.action_id != proposal.action_id
            or self.pending_slot.finding_id != self.finding.finding_id
            or self.handoff.run_id != run_id
            or self.handoff.source_sha256 != self.output.source.source_sha256
            or self.handoff.corpus_sha256 != self.output.corpus_sha256
            or self.handoff.obligation_ids
            != sorted(obligation.obligation_id for obligation in self.obligations)
            or self.handoff.obligation_ids
            != sorted(obligation.obligation_id for obligation in self.output.obligations)
            or len(self.output.findings) != 1
            or self.output.findings[0].finding_id != self.finding.finding_id
            or self.finding.obligation.obligation_id
            != self.output.findings[0].obligation.obligation_id
            or self.handoff.finding_id != self.finding.finding_id
            or self.handoff.action_id != proposal.action_id
            or self.handoff.approval_id != self.approval.approval_id
            or [checkpoint.state for checkpoint in self.checkpoints]
            != [RunState.VERIFYING, RunState.VERIFIED, RunState.AWAITING_APPROVAL]
            or any(checkpoint.run_id != run_id for checkpoint in self.checkpoints)
            or any(event.run_id != run_id for event in self.audit_events)
        ):
            raise ValueError("verified worker handoff binding is invalid")
        return self
