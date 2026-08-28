"""Exact-hash synthetic fixture for the minimum live submission slice."""

from __future__ import annotations

from datetime import datetime
from hmac import compare_digest
from importlib.resources import files
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from regops_api.counterfactual import CounterfactualResult, DeterministicCounterfactual
from regops_api.domain_models import ConflictMatch, ProposedAmendment, SyntheticContract
from regops_api.schemas import Obligation, Severity
from regops_api.worker_models import (
    AcceptedEvidenceCatalog,
    AcceptedObligation,
    CandidateFinding,
    CorpusSnapshot,
    SourceDocument,
    VerifiedObligationSet,
    WorkerModel,
)

KNOWN_SOURCE_SHA256 = "6571084f3ff2215fcf48d467c7d9e8afd808f5f4b644c00ddca7a9ca66e4c5d9"


class MinimumLiveFixture(WorkerModel):
    fixture_version: Literal["minimum-live-slice-v1"]
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_doc_id: str = Field(min_length=1, max_length=128)
    accepted_obligations: tuple[AcceptedObligation, ...] = Field(min_length=1)
    corpus: CorpusSnapshot
    target_contract: SyntheticContract
    amendment_clause_updates: dict[str, str] = Field(min_length=1)
    synthetic: Literal[True]

    @model_validator(mode="after")
    def exact_demo_boundary(self) -> MinimumLiveFixture:
        if (
            self.source_sha256 != KNOWN_SOURCE_SHA256
            or self.target_contract.contract_id != "syn-contract-worker-001"
            or len(self.corpus.impacts) != 1
            or self.corpus.impacts[0].target_id != self.target_contract.contract_id
            or self.corpus.impacts[0].obligation not in self.accepted_obligations
            or self.corpus.synthetic is not True
        ):
            raise ValueError("LIVE_FIXTURE_INVALID")
        return self

    def accepted_catalog(self, source: SourceDocument) -> AcceptedEvidenceCatalog:
        if source.identity.doc_id != self.source_doc_id or not compare_digest(
            source.identity.source_sha256, self.source_sha256
        ):
            raise ValueError("UNKNOWN_LIVE_SOURCE")
        return AcceptedEvidenceCatalog(
            source=source.identity,
            obligations=self.accepted_obligations,
        )

    def mapped_candidate(self, obligations: VerifiedObligationSet) -> CandidateFinding:
        rule = self.corpus.impacts[0]
        obligation = next(
            (
                item
                for item in obligations.obligations
                if item.statement == rule.obligation.statement
                and item.evidence == rule.obligation.evidence
            ),
            None,
        )
        if obligation is None:
            raise ValueError("LIVE_MAPPING_OBLIGATION_MISSING")
        return CandidateFinding(
            obligation_id=obligation.obligation_id,
            target_id=rule.target_id,
            target_clause=rule.target_clause,
            affected_case_id=rule.affected_case_id,
            relationship=rule.relationship,
            severity=Severity.HIGH,
            verdict=rule.verdict,
            human_review_required=True,
            evidence=rule.evidence,
            evidence_strength=rule.evidence_strength,
            interpretation_confidence=rule.interpretation_confidence,
        )


def load_minimum_live_fixture(source_sha256: str) -> MinimumLiveFixture:
    if not compare_digest(source_sha256, KNOWN_SOURCE_SHA256):
        raise ValueError("UNKNOWN_LIVE_SOURCE")
    try:
        content = (
            files("regops_api")
            .joinpath("runtime_fixtures/minimum_live_slice.json")
            .read_text(encoding="utf-8")
        )
        return MinimumLiveFixture.model_validate_json(content)
    except (OSError, UnicodeError, ValidationError):
        raise ValueError("LIVE_FIXTURE_INVALID") from None


def placement_fee_matcher(
    contract: SyntheticContract,
    obligations: list[Obligation],
    *,
    conflict_id: str,
) -> list[ConflictMatch]:
    if contract.contract_id != "syn-contract-worker-001" or not contract.synthetic:
        return []
    clause = contract.clauses.get("placement-fee")
    if clause != ("The synthetic worker must pay a placement fee of BDT 11,000 before deployment."):
        return []
    prohibition = next(
        (
            item
            for item in obligations
            if item.statement
            == "Licensed recruitment agencies must not charge migrant workers placement fees."
        ),
        None,
    )
    if prohibition is None:
        return []
    return [
        ConflictMatch(
            conflict_id=conflict_id,
            severity=Severity.HIGH,
        )
    ]


class MinimumLiveCounterfactual(DeterministicCounterfactual):
    def __init__(self) -> None:
        super().__init__(lambda _contract, _obligations: [])

    def evaluate(
        self,
        *,
        run_id: str,
        contract: SyntheticContract,
        amendment: ProposedAmendment,
        obligations: list[Obligation],
        now: datetime | None = None,
    ) -> CounterfactualResult:
        engine = DeterministicCounterfactual(
            lambda target, rules: placement_fee_matcher(
                target,
                rules,
                conflict_id=amendment.finding_id,
            )
        )
        return engine.evaluate(
            run_id=run_id,
            contract=contract,
            amendment=amendment,
            obligations=obligations,
            now=now,
        )


def minimum_live_counterfactual() -> DeterministicCounterfactual:
    return MinimumLiveCounterfactual()
