from __future__ import annotations

from datetime import UTC, datetime

from regops_api.domain_models import SyntheticContract
from regops_api.schemas import (
    AffectedCase,
    DocumentKind,
    EvidenceReference,
    Finding,
    FindingsBySeverity,
    FindingScores,
    FindingStatus,
    FindingVerdict,
    Obligation,
    ObligationType,
    Regulation,
    Relationship,
    Run,
    RunProgress,
    RunState,
    Severity,
    SourceAuthority,
)

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def make_regulation(reg_id: str = "reg-1", filename: str = "rule.pdf") -> Regulation:
    return Regulation(
        reg_id=reg_id,
        title="Synthetic retention rule",
        source_filename=filename,
        synthetic=True,
    )


def make_run(run_id: str = "run-1") -> Run:
    return Run(
        run_id=run_id,
        state=RunState.INGESTED,
        created_at=NOW,
        updated_at=NOW,
        regulation=make_regulation(),
        progress=RunProgress(
            documents_total=1,
            documents_processed=0,
            percent=0,
        ),
        findings_by_severity=FindingsBySeverity(low=0, medium=0, high=1),
    )


def make_obligation(obligation_id: str = "obl-1") -> Obligation:
    evidence = EvidenceReference(
        doc_id="reg-1",
        doc_kind=DocumentKind.REGULATION,
        page=2,
        quote="Synthetic records must have a bounded retention period.",
    )
    return Obligation(
        obligation_id=obligation_id,
        statement="Use a bounded retention period.",
        type=ObligationType.REQUIREMENT,
        evidence=[evidence],
    )


def make_finding(finding_id: str = "finding-1") -> Finding:
    obligation = make_obligation()
    contract_evidence = EvidenceReference(
        doc_id="contract-1",
        doc_kind=DocumentKind.CONTRACT,
        page=1,
        quote="Records are retained forever.",
    )
    return Finding(
        finding_id=finding_id,
        run_id="run-1",
        target_id="contract-1",
        relationship=Relationship.CONFLICTS_WITH,
        severity=Severity.HIGH,
        verdict=FindingVerdict.SURVIVED,
        status=FindingStatus.OPEN,
        human_review_required=True,
        obligation=obligation,
        affected_case=AffectedCase(
            case_id="case-1",
            summary="Synthetic demo case",
            synthetic=True,
        ),
        evidence_path=[*obligation.evidence, contract_evidence],
        scores=FindingScores(
            evidence_strength=0.9,
            source_authority=SourceAuthority.PRIMARY_GOVERNMENT,
            interpretation_confidence=0.8,
            operational_severity=Severity.HIGH,
            human_review_required=True,
        ),
    )


def make_contract() -> SyntheticContract:
    return SyntheticContract(
        contract_id="contract-1",
        title="Synthetic services contract",
        clauses={
            "retention": "retain forever",
            "audit": "no audit right",
            "notice": "send notice",
        },
        synthetic=True,
    )
