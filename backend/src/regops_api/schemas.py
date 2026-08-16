"""Pydantic v2 models for the RegOps API contract."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    UrlConstraints,
    field_validator,
    model_validator,
)
from pydantic.json_schema import WithJsonSchema

HTTPS_URL_PATTERN = r"^[Hh][Tt][Tt][Pp][Ss]://[^/?#\s]+"
HttpsUrl = Annotated[
    AnyUrl,
    UrlConstraints(allowed_schemes=["https"], host_required=True),
    WithJsonSchema(
        {"type": "string", "format": "uri", "pattern": HTTPS_URL_PATTERN}
    ),
]


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
    scores: FindingScores


class AffectedCase(ContractModel):
    case_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    signed_date: date | None = None
    synthetic: Literal[True]


class Finding(FindingSummary):
    obligation: Obligation
    affected_case: AffectedCase | None = None
    evidence_path: list[EvidenceReference] = Field(min_length=1)
    proposed_action: ProposedAction | None = None


class FindingsBySeverity(ContractModel):
    low: int = Field(ge=0)
    medium: int = Field(ge=0)
    high: int = Field(ge=0)


class FindingList(ContractModel):
    items: list[FindingSummary] = Field(description="Selected page of matching findings.")
    total: int = Field(
        ge=0,
        description="Findings matching the active filters before pagination.",
    )
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    by_severity: FindingsBySeverity = Field(
        description=(
            "Severity counts across the complete filtered result before pagination."
        )
    )


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
    finding_id: str = Field(min_length=1)
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


class RunTransition(ContractModel):
    from_state: RunState | None
    to_state: RunState
    occurred_at: datetime
    reason: Annotated[str, Field(min_length=1)] | None
    actor: str = Field(min_length=1)


class RecoveryInfo(ContractModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "if": {
                "properties": {"recovery_available": {"const": True}},
                "required": ["recovery_available"],
            },
            "then": {"properties": {"checkpoint_state": {"not": {"type": "null"}}}},
        },
    )

    recovery_available: bool
    checkpoint_state: RunState | None
    attempt_count: int = Field(ge=0)
    last_error_code: str | None
    last_error_message: str | None

    @model_validator(mode="after")
    def available_recovery_requires_checkpoint(self) -> RecoveryInfo:
        if self.recovery_available and self.checkpoint_state is None:
            raise ValueError("recovery_available requires checkpoint_state")
        return self


class ChangeDetection(ContractModel):
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_source_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    changed: bool
    detected_at: datetime


class Run(ContractModel):
    run_id: str = Field(min_length=1)
    state: RunState
    created_at: datetime
    updated_at: datetime
    regulation: Regulation
    progress: RunProgress
    transitions: list[RunTransition] = Field(
        min_length=1,
        json_schema_extra={
            "prefixItems": [
                {
                    "allOf": [
                        {"$ref": "#/components/schemas/RunTransition"},
                        {
                            "type": "object",
                            "required": ["from_state"],
                            "properties": {"from_state": {"type": "null"}},
                        },
                    ]
                }
            ]
        },
    )
    recovery: RecoveryInfo | None = None
    change_detection: ChangeDetection | None = None
    findings_by_severity: FindingsBySeverity = Field(
        default_factory=lambda: FindingsBySeverity(low=0, medium=0, high=0)
    )
    pending_approvals: list[Approval] = Field(default_factory=list)
    completed_actions: list[ProposedAction] = Field(default_factory=list)

    @model_validator(mode="after")
    def transitions_form_authoritative_chain(self) -> Run:
        if self.transitions[0].from_state is not None:
            raise ValueError("the first transition must have a null from_state")
        for previous, current in zip(self.transitions, self.transitions[1:], strict=False):
            if current.from_state is not previous.to_state:
                raise ValueError("transitions must form a continuous state chain")
        timestamps = [transition.occurred_at for transition in self.transitions]
        if timestamps != sorted(timestamps):
            raise ValueError("transitions must be ordered oldest to newest")
        if self.transitions[-1].to_state is not self.state:
            raise ValueError("the final transition must agree with run state")
        return self


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
    audit_package_url: HttpsUrl | None = Field(
        default=None,
        description=(
            "Short-lived, absolute HTTPS signed download URL generated by the backend; "
            "clients never submit this response-only value"
        ),
    )

    @field_validator("audit_package_url", mode="before")
    @classmethod
    def audit_package_url_has_raw_https_host(cls, value: object) -> object:
        if value is None:
            return None
        raw_value = str(value)
        if raw_value != raw_value.strip():
            raise ValueError("audit_package_url must not contain surrounding whitespace")
        try:
            parsed = urlsplit(raw_value)
            host = parsed.hostname
        except ValueError as error:
            raise ValueError("audit_package_url must be a valid absolute HTTPS URL") from error
        if parsed.scheme.lower() != "https" or not parsed.netloc or not host:
            raise ValueError("audit_package_url must be a valid absolute HTTPS URL")
        return value
