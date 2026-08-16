from __future__ import annotations

from regops_api.counterfactual import DeterministicCounterfactual
from regops_api.domain_models import ConflictMatch, ProposedAmendment, SyntheticContract
from regops_api.schemas import Obligation, Severity
from tests.factories import NOW, make_contract, make_obligation


class RecordingMatcher:
    def __init__(self) -> None:
        self.seen: list[SyntheticContract] = []

    def __call__(
        self, contract: SyntheticContract, obligations: list[Obligation]
    ) -> list[ConflictMatch]:
        assert obligations
        self.seen.append(contract.model_copy(deep=True))
        matches = [ConflictMatch(conflict_id="finding-audit", severity=Severity.MEDIUM)]
        if "forever" in contract.clauses["retention"]:
            matches.append(
                ConflictMatch(conflict_id="finding-retention", severity=Severity.HIGH)
            )
        if contract.clauses["notice"] != "send notice":
            matches.append(
                ConflictMatch(conflict_id="finding-notice", severity=Severity.MEDIUM)
            )
        return matches


def test_counterfactual_reruns_same_matcher_and_computes_authoritative_sets() -> None:
    matcher = RecordingMatcher()
    service = DeterministicCounterfactual(matcher)
    original = make_contract()
    amendment = ProposedAmendment(
        action_id="action-1",
        finding_id="finding-retention",
        contract_id="contract-1",
        clause_updates={
            "retention": "retain for 30 days",
            "notice": "no notice",
        },
    )

    result = service.evaluate(
        run_id="run-1",
        contract=original,
        amendment=amendment,
        obligations=[make_obligation()],
        now=NOW,
    )

    assert len(matcher.seen) == 2
    assert result.preview.baseline_finding_count == 2
    assert result.preview.resolved_finding_ids == ["finding-retention"]
    assert result.preview.unchanged_finding_ids == ["finding-audit"]
    assert result.preview.new_conflict_ids == ["finding-notice"]
    assert result.preview.remaining_high_risk_ids == []
    assert result.preview.detected_finding_picture_improves is True
    assert result.preview.narrative is None


def test_counterfactual_never_mutates_source_contract() -> None:
    original = make_contract()
    before = original.model_dump()
    result = DeterministicCounterfactual(RecordingMatcher()).evaluate(
        run_id="run-1",
        contract=original,
        amendment=ProposedAmendment(
            action_id="action-1",
            finding_id="finding-1",
            contract_id="contract-1",
            clause_updates={"retention": "retain for 30 days"},
        ),
        obligations=[make_obligation()],
        now=NOW,
    )

    assert original.model_dump() == before
    assert result.snapshot.original.model_dump() == before
    assert result.snapshot.shadow.revision == original.revision + 1
    assert result.snapshot.shadow.clauses["retention"] == "retain for 30 days"
