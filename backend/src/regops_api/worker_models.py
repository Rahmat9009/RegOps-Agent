"""Bounded worker data, separate from the frozen public API.

Accepted catalogs are backend-owned policy inputs, never model output. Verified
types are handoff records, not proof by themselves: the verifier must construct
them. No worker model carries tools, prompts, provider payloads or action data.
"""

from __future__ import annotations

import unicodedata
from datetime import date
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from regops_api.schemas import DocumentKind, FindingVerdict, ObligationType, Relationship, Severity

MAX_PAGE_TEXT = 20_000
MAX_OBLIGATIONS = 50
MAX_FINDINGS = 500


def safe_text(value: str) -> str:
    """Reject invisible controls; never silently repair untrusted quotations."""
    if not value.strip() or any(
        unicodedata.category(char).startswith("C") and char not in "\n\r\t" for char in value
    ):
        raise ValueError("UNSAFE_TEXT")
    return value


SafeText = Annotated[str, AfterValidator(safe_text)]
Identifier = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ResourceId = Annotated[
    str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
]
Statement = Annotated[SafeText, Field(min_length=1, max_length=1000)]
Quote = Annotated[SafeText, Field(min_length=1, max_length=300)]
ExceptionText = Annotated[SafeText, Field(min_length=1, max_length=500)]
PageNumber = Annotated[int, Field(ge=1, le=100)]
Score = Annotated[
    float,
    Field(ge=0, le=1, allow_inf_nan=False),
    AfterValidator(lambda value: 0.0 if value == 0 else value),
]


class WorkerModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    @field_validator("synthetic", check_fields=False, mode="before")
    @classmethod
    def synthetic_boolean(cls, value: object) -> object:
        if value is not True:
            raise ValueError("SYNTHETIC_REQUIRED")
        return value


class ImmutableSourceIdentity(WorkerModel):
    doc_id: Identifier
    doc_kind: DocumentKind
    source_sha256: Digest
    page_count: PageNumber
    synthetic: Literal[True]


class SourcePage(WorkerModel):
    doc_id: Identifier
    source_sha256: Digest
    page: PageNumber
    # Blank pages are valid, but cannot support evidence.
    text: Annotated[str, Field(max_length=MAX_PAGE_TEXT)]

    @field_validator("text")
    @classmethod
    def safe_page(cls, value: str) -> str:
        if value.strip():
            safe_text(value)
        elif any(char not in " \t\r\n" for char in value):
            raise ValueError("UNSAFE_TEXT")
        return value


class SourceDocument(WorkerModel):
    """Already extracted pages, bound by a trusted reader to immutable bytes.

    Digest authenticity is the reader's obligation; this phase neither downloads
    nor parses PDFs and cannot infer a PDF byte digest from its page text.
    """

    identity: ImmutableSourceIdentity
    pages: Annotated[tuple[SourcePage, ...], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def complete_manifest(self) -> Self:
        if (
            len(self.pages) != self.identity.page_count
            or {page.page for page in self.pages} != set(range(1, self.identity.page_count + 1))
            or any(
                page.doc_id != self.identity.doc_id
                or page.source_sha256 != self.identity.source_sha256
                for page in self.pages
            )
        ):
            raise ValueError("SOURCE_BINDING_MISMATCH")
        return self


class EvidenceAnchor(WorkerModel):
    doc_id: Identifier
    doc_kind: DocumentKind
    source_sha256: Digest
    page: PageNumber
    quote: Quote


Evidence = Annotated[tuple[EvidenceAnchor, ...], Field(min_length=1, max_length=5)]
EvidencePath = Annotated[tuple[EvidenceAnchor, ...], Field(min_length=2, max_length=15)]


class ObligationClaim(WorkerModel):
    statement: Statement
    type: ObligationType
    exceptions: Annotated[tuple[ExceptionText, ...], Field(max_length=10)] = ()
    effective_date: date | None = None
    evidence: Evidence


class CandidateObligation(ObligationClaim):
    """No model-owned obligation ID or backend authority."""


class AcceptedObligation(ObligationClaim):
    """Trusted, reviewed claim and its exact required anchors, not an LLM claim."""


class VerifiedObligation(ObligationClaim):
    run_id: Identifier
    source_sha256: Digest
    obligation_id: ResourceId
    synthetic: Literal[True] = True


class AcceptedEvidenceCatalog(WorkerModel):
    source: ImmutableSourceIdentity
    obligations: Annotated[tuple[AcceptedObligation, ...], Field(min_length=1, max_length=50)]


class AnalystDraftOutput(WorkerModel):
    obligations: Annotated[tuple[CandidateObligation, ...], Field(min_length=1, max_length=50)]


class MinimumLiveDetection(WorkerModel):
    """Non-authoritative Gemini detections for the exact synthetic demo fixture."""

    placement_fee_prohibition: bool
    fee_schedule_reissue: bool
    employer_paid_medical_exception: bool


class VerifiedObligationSet(WorkerModel):
    run_id: Identifier
    source: ImmutableSourceIdentity
    obligations: Annotated[tuple[VerifiedObligation, ...], Field(min_length=1, max_length=50)]


class CorpusRecord(WorkerModel):
    document: SourceDocument
    title: Annotated[SafeText, Field(min_length=1, max_length=200, pattern=r"^SYNTHETIC DEMO ")]
    evidence: Annotated[tuple[EvidenceAnchor, ...], Field(min_length=1, max_length=50)]


class AcceptedImpact(WorkerModel):
    """Backend-owned matching rule result for one immutable corpus snapshot.

    Exact obligation/target/case/evidence binding supplies semantic support;
    quotation presence alone is never treated as entailment. Unknown claims fail
    closed. A later deterministic matcher may produce these records, not an agent.
    """

    obligation: AcceptedObligation
    target_id: Identifier
    target_clause: Identifier | None = None
    affected_case_id: Identifier | None = None
    relationship: Relationship
    verdict: FindingVerdict
    evidence: EvidencePath
    evidence_strength: Score
    interpretation_confidence: Score


class CorpusSnapshot(WorkerModel):
    schema_version: Literal["worker-corpus-v1"] = "worker-corpus-v1"
    records: Annotated[tuple[CorpusRecord, ...], Field(min_length=1, max_length=500)]
    impacts: Annotated[tuple[AcceptedImpact, ...], Field(max_length=500)]
    synthetic: Literal[True]


class CandidateFinding(WorkerModel):
    # A reference to a backend-issued ID, not a candidate-owned identifier.
    obligation_id: ResourceId
    target_id: Identifier
    target_clause: Identifier | None = None
    affected_case_id: Identifier | None = None
    relationship: Relationship
    severity: Severity
    verdict: FindingVerdict
    human_review_required: bool
    evidence: EvidencePath
    evidence_strength: Score
    interpretation_confidence: Score


class InvestigatorDraftOutput(WorkerModel):
    findings: Annotated[tuple[CandidateFinding, ...], Field(max_length=500)]


class VerifiedFinding(WorkerModel):
    finding_id: ResourceId
    run_id: Identifier
    obligation: VerifiedObligation
    target_id: Identifier
    target_clause: Identifier | None
    affected_case_id: Identifier | None
    relationship: Relationship
    severity: Severity
    verdict: FindingVerdict
    human_review_required: bool
    evidence: EvidencePath
    evidence_strength: Score
    interpretation_confidence: Score
    # Synthetic authority describes the fictional issuer, not a real government.
    source_authority: Literal["primary_government"] = "primary_government"
    status: Literal["OPEN"] = "OPEN"
    synthetic: Literal[True] = True


class VerifiedWorkerOutput(WorkerModel):
    schema_version: Literal["worker-verified-v1"] = "worker-verified-v1"
    run_id: Identifier
    source: ImmutableSourceIdentity
    corpus_sha256: Digest
    obligations: Annotated[tuple[VerifiedObligation, ...], Field(min_length=1, max_length=50)]
    findings: Annotated[tuple[VerifiedFinding, ...], Field(max_length=500)]


class IssueCode(StrEnum):
    INVALID_SCHEMA = "INVALID_SCHEMA"
    SOURCE_BINDING_MISMATCH = "SOURCE_BINDING_MISMATCH"
    WRONG_DOCUMENT = "WRONG_DOCUMENT"
    WRONG_DOCUMENT_KIND = "WRONG_DOCUMENT_KIND"
    WRONG_PAGE = "WRONG_PAGE"
    QUOTE_MISMATCH = "QUOTE_MISMATCH"
    QUOTE_NOT_ON_PAGE = "QUOTE_NOT_ON_PAGE"
    DUPLICATE_ANCHOR = "DUPLICATE_ANCHOR"
    UNSUPPORTED_OBLIGATION = "UNSUPPORTED_OBLIGATION"
    UNSUPPORTED_FINDING = "UNSUPPORTED_FINDING"
    FOREIGN_TARGET = "FOREIGN_TARGET"
    MISSING_OBLIGATION_BINDING = "MISSING_OBLIGATION_BINDING"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    FOREIGN_EVIDENCE = "FOREIGN_EVIDENCE"
    INVALID_CATALOG = "INVALID_CATALOG"
    IDENTIFIER_COLLISION = "IDENTIFIER_COLLISION"


class VerificationIssue(WorkerModel):
    code: IssueCode
    stage: Literal["evidence", "obligations", "findings", "duplicate"]


class VerificationResult(WorkerModel):
    """Safe to log: only bounded counts, fixed stages and fixed issue codes."""

    accepted: bool
    obligation_count: Annotated[int, Field(ge=0, le=50)] = 0
    finding_count: Annotated[int, Field(ge=0, le=500)] = 0
    issues: Annotated[tuple[VerificationIssue, ...], Field(max_length=64)] = ()

    @model_validator(mode="after")
    def consistent_result(self) -> Self:
        if self.accepted == bool(self.issues) or (
            not self.accepted and (self.obligation_count or self.finding_count)
        ):
            raise ValueError("INVALID_VERIFICATION_RESULT")
        return self


class ObligationVerification(WorkerModel):
    result: VerificationResult
    output: VerifiedObligationSet | None = None

    @model_validator(mode="after")
    def output_requires_acceptance(self) -> Self:
        if self.result.accepted != (self.output is not None):
            raise ValueError("INVALID_VERIFICATION_RESULT")
        return self


class FindingVerification(WorkerModel):
    result: VerificationResult
    output: VerifiedWorkerOutput | None = None

    @model_validator(mode="after")
    def output_requires_acceptance(self) -> Self:
        if self.result.accepted != (self.output is not None):
            raise ValueError("INVALID_VERIFICATION_RESULT")
        return self


class PreviouslyVerifiedSource(WorkerModel):
    """Loaded only from a successful authoritative verification checkpoint."""

    run_id: Identifier
    source: ImmutableSourceIdentity


class DuplicateSourceCompletion(WorkerModel):
    run_id: Identifier
    source_sha256: Digest
    result: Literal["duplicate_source_skipped"] = "duplicate_source_skipped"
    terminal_state: Literal["COMPLETED"] = "COMPLETED"
    # A plan only; no transitions or writes are performed in Phase 1B.2A.
    state_path: tuple[
        Literal["INGESTED"],
        Literal["EXTRACTING"],
        Literal["EXTRACTED"],
        Literal["MAPPING"],
        Literal["MAPPED"],
        Literal["VERIFYING"],
        Literal["VERIFIED"],
        Literal["COMPLETED"],
    ] = (
        "INGESTED",
        "EXTRACTING",
        "EXTRACTED",
        "MAPPING",
        "MAPPED",
        "VERIFYING",
        "VERIFIED",
        "COMPLETED",
    )
    analysis_calls: Literal[0] = 0
    obligations_created: Literal[0] = 0
    findings_created: Literal[0] = 0
    actions_created: Literal[0] = 0
    approvals_created: Literal[0] = 0
