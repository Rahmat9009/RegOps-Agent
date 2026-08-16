"""Strict internal models for the Phase 1A domain foundation."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from regops_api.schemas import (
    ActionType,
    AffectedCase,
    Approval,
    AuditReport,
    EvidenceReference,
    FindingScores,
    FindingStatus,
    FindingVerdict,
    Obligation,
    ProposedAction,
    Regulation,
    Relationship,
    RunState,
    Severity,
)


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
        if self.event_type in {
            AuditEventType.ACTION_ATTEMPTED,
            AuditEventType.ACTION_EXECUTED,
        } and self.action_id is None:
            raise ValueError("action audit events require action_id")
        if self.event_type is AuditEventType.APPROVAL_DECIDED and (
            self.approval_id is None or self.actor is None
        ):
            raise ValueError("approval_decided requires approval_id and actor")
        if (
            self.event_type is AuditEventType.IDEMPOTENCY_RESULT
            and self.idempotency_result is None
        ):
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
