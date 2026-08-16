"""Pydantic v2 models for the RegOps API contract."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    """Strict base model shared by all API contract objects."""

    model_config = ConfigDict(extra="forbid")


class RunState(StrEnum):
    INGESTED = "INGESTED"
    EXTRACTING = "EXTRACTING"
    EXTRACTED = "EXTRACTED"
    MAPPING = "MAPPING"
    MAPPED = "MAPPED"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    REVALIDATING = "REVALIDATING"
    COMPLETED = "COMPLETED"
    FAILED_RECOVERABLE = "FAILED_RECOVERABLE"
    FAILED = "FAILED"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SourceAuthority(StrEnum):
    PRIMARY_GOVERNMENT = "primary_government"
    SECONDARY = "secondary"
    INTERNAL = "internal"


class Relationship(StrEnum):
    CONFLICTS_WITH = "conflicts_with"
    REQUIRES_UPDATE = "requires_update"
    NO_IMPACT = "no_impact"


class FindingVerdict(StrEnum):
    SURVIVED = "survived"
    REFUTED = "refuted"
    UNCERTAIN = "uncertain"


class FindingStatus(StrEnum):
    OPEN = "OPEN"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    RESOLVED = "RESOLVED"


class ActionType(StrEnum):
    TAG_CASE = "tag_case"
    CREATE_REVIEW_TASK = "create_review_task"
    DRAFT_AMENDMENT = "draft_amendment"


class ActionAutonomy(StrEnum):
    AUTO = "auto"
    APPROVAL_REQUIRED = "approval_required"


class ActionStatus(StrEnum):
    PENDING = "PENDING"
    EXECUTED = "EXECUTED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED_DRAFT = "APPROVED_DRAFT"
    REJECTED = "REJECTED"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ApprovalDecisionValue(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class ObligationType(StrEnum):
    PROHIBITION = "prohibition"
    REQUIREMENT = "requirement"
    LIMIT = "limit"
    EXCEPTION = "exception"


class DocumentKind(StrEnum):
    REGULATION = "regulation"
    CONTRACT = "contract"
    POLICY = "policy"
    CASE = "case"


class HealthStatus(ContractModel):
    status: Literal["ok"]
    version: str


class ErrorDetail(ContractModel):
    location: list[str | int] = Field(default_factory=list)
    message: str
    type: str


class APIError(ContractModel):
    code: str
    message: str
    details: list[ErrorDetail] | None = None


class RunProgress(ContractModel):
    documents_total: int = Field(ge=0)
    documents_processed: int = Field(ge=0)
    partitions_total: int = Field(default=0, ge=0)
    partitions_complete: int = Field(default=0, ge=0)
    percent: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def completed_work_cannot_exceed_totals(self) -> RunProgress:
        if self.documents_processed > self.documents_total:
            raise ValueError("documents_processed cannot exceed documents_total")
        if self.partitions_complete > self.partitions_total:
            raise ValueError("partitions_complete cannot exceed partitions_total")
        return self


class Regulation(ContractModel):
    reg_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    jurisdiction: str | None = None
    source_filename: str = Field(min_length=1)
    synthetic: Literal[True]


class EvidenceReference(ContractModel):
    doc_id: str = Field(min_length=1)
    doc_kind: DocumentKind
    page: int = Field(ge=1)
    quote: str = Field(min_length=1)


class Obligation(ContractModel):
    obligation_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    type: ObligationType
    exceptions: list[str] = Field(default_factory=list)
    effective_date: date | None = None
    evidence: list[EvidenceReference] = Field(min_length=1)


class FindingScores(ContractModel):
    evidence_strength: float = Field(ge=0, le=1)
    source_authority: SourceAuthority
    interpretation_confidence: float = Field(ge=0, le=1)
    operational_severity: Severity
    human_review_required: bool


class ProposedAction(ContractModel):
    action_id: str = Field(min_length=1)
    finding_id: str = Field(min_length=1)
    type: ActionType
    autonomy: ActionAutonomy
    status: ActionStatus
    idempotency_key: str = Field(min_length=1)


class FindingSummary(ContractModel):
    finding_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    relationship: Relationship
    severity: Severity
    verdict: FindingVerdict
    status: FindingStatus
    human_review_required: bool


class AffectedCase(ContractModel):
    case_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    signed_date: date | None = None
    synthetic: Literal[True]


class Finding(FindingSummary):
    obligation: Obligation
    affected_case: AffectedCase | None = None
    evidence_path: list[EvidenceReference] = Field(min_length=1)
    scores: FindingScores
    proposed_action: ProposedAction | None = None


class FindingList(ContractModel):
    items: list[FindingSummary]
    total: int = Field(ge=0)


class CounterfactualPreview(ContractModel):
    """Authoritative output from rerunning matching against a shadow copy."""

    action_id: str = Field(min_length=1)
    shadow_run_id: str = Field(min_length=1)
    baseline_finding_count: int = Field(ge=0)
    resolved_finding_ids: list[str]
    unchanged_finding_ids: list[str]
    new_conflict_ids: list[str]
    remaining_high_risk_ids: list[str]
    detected_finding_picture_improves: bool
    narrative: str | None = None


class Approval(ContractModel):
    approval_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    status: ApprovalStatus
    decided_at: datetime | None = None
    decided_by: str | None = Field(
        default=None,
        description="Backend-assigned reviewer identity; demo value is demo-reviewer",
    )
    note: str | None = None


class ApprovalDecision(ContractModel):
    decision: ApprovalDecisionValue
    note: str | None = None


class FindingsBySeverity(ContractModel):
    low: int = Field(ge=0)
    medium: int = Field(ge=0)
    high: int = Field(ge=0)


class Run(ContractModel):
    run_id: str = Field(min_length=1)
    state: RunState
    created_at: datetime
    updated_at: datetime
    regulation: Regulation
    progress: RunProgress
    findings_by_severity: FindingsBySeverity = Field(
        default_factory=lambda: FindingsBySeverity(low=0, medium=0, high=0)
    )
    pending_approvals: list[Approval] = Field(default_factory=list)
    completed_actions: list[ProposedAction] = Field(default_factory=list)


class AuditIdempotency(ContractModel):
    duplicate_actions_prevented: int = Field(ge=0)
    duplicate_action_rate: float = Field(ge=0, le=1)


class AuditRevalidation(ContractModel):
    findings_resolved: int = Field(ge=0)
    findings_remaining: int = Field(ge=0)


class AuditProcessing(ContractModel):
    total_seconds: float = Field(ge=0)
    documents_processed: int = Field(ge=0)


class AuditEvaluation(ContractModel):
    obligation_precision: float = Field(ge=0, le=1)
    impact_precision: float = Field(ge=0, le=1)
    impact_recall: float = Field(ge=0, le=1)
    citation_correctness: float = Field(ge=0, le=1)
    false_escalation_rate: float = Field(ge=0, le=1)
    resume_success_rate: float = Field(ge=0, le=1)


class AuditReport(ContractModel):
    run_id: str = Field(min_length=1)
    generated_at: datetime
    executed_actions: list[ProposedAction]
    idempotency: AuditIdempotency
    revalidation: AuditRevalidation
    processing: AuditProcessing
    evaluation: AuditEvaluation | None = None
    audit_package_url: str | None = None
