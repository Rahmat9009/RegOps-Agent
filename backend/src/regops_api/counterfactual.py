"""Deterministic shadow-state counterfactual validation."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from regops_api.domain_models import (
    ConflictMatch,
    ProposedAmendment,
    ShadowContractSnapshot,
    SyntheticContract,
)
from regops_api.schemas import CounterfactualPreview, Obligation, Severity

MatchAndValidate = Callable[[SyntheticContract, list[Obligation]], list[ConflictMatch]]


class CounterfactualResult:
    def __init__(
        self,
        *,
        preview: CounterfactualPreview,
        snapshot: ShadowContractSnapshot,
    ) -> None:
        self.preview = preview
        self.snapshot = snapshot


class DeterministicCounterfactual:
    """Runs one supplied matching function unchanged on original and shadow state."""

    def __init__(self, matcher: MatchAndValidate) -> None:
        self._matcher = matcher

    def evaluate(
        self,
        *,
        run_id: str,
        contract: SyntheticContract,
        amendment: ProposedAmendment,
        obligations: list[Obligation],
        now: datetime | None = None,
    ) -> CounterfactualResult:
        if amendment.contract_id != contract.contract_id:
            raise ValueError("amendment target does not match synthetic contract")
        original = deepcopy(contract)
        baseline_matches = self._validated_matches(self._matcher(original, obligations))
        shadow = self._apply_to_shadow(original, amendment)
        shadow_matches = self._validated_matches(self._matcher(shadow, obligations))

        baseline_ids = set(baseline_matches)
        shadow_ids = set(shadow_matches)
        resolved = sorted(baseline_ids - shadow_ids)
        unchanged = sorted(baseline_ids & shadow_ids)
        new = sorted(shadow_ids - baseline_ids)
        remaining_high = sorted(
            conflict_id
            for conflict_id, match in shadow_matches.items()
            if match.severity is Severity.HIGH
        )
        baseline_high_count = sum(
            match.severity is Severity.HIGH for match in baseline_matches.values()
        )
        shadow_risk_picture = (len(remaining_high), len(shadow_matches))
        baseline_risk_picture = (baseline_high_count, len(baseline_matches))
        snapshot_id = str(uuid5(NAMESPACE_URL, f"regops:shadow:{amendment.action_id}"))
        recorded_at = now or datetime.now(UTC)
        snapshot = ShadowContractSnapshot(
            snapshot_id=snapshot_id,
            run_id=run_id,
            action_id=amendment.action_id,
            source_revision=original.revision,
            original=original,
            shadow=shadow,
            created_at=recorded_at,
        )
        return CounterfactualResult(
            preview=CounterfactualPreview(
                action_id=amendment.action_id,
                shadow_run_id=snapshot_id,
                baseline_finding_count=len(baseline_matches),
                resolved_finding_ids=resolved,
                unchanged_finding_ids=unchanged,
                new_conflict_ids=new,
                remaining_high_risk_ids=remaining_high,
                detected_finding_picture_improves=shadow_risk_picture
                < baseline_risk_picture,
                narrative=None,
            ),
            snapshot=snapshot,
        )

    @staticmethod
    def _apply_to_shadow(
        original: SyntheticContract, amendment: ProposedAmendment
    ) -> SyntheticContract:
        clauses = deepcopy(original.clauses)
        clauses.update(amendment.clause_updates)
        return original.model_copy(
            deep=True,
            update={"clauses": clauses, "revision": original.revision + 1},
        )

    @staticmethod
    def _validated_matches(matches: list[ConflictMatch]) -> dict[str, ConflictMatch]:
        result = {match.conflict_id: match for match in matches}
        if len(result) != len(matches):
            raise ValueError("matching/validation output contains duplicate conflict ids")
        return result
