"""Capability-minimal interfaces for the four RegOps roles."""

from __future__ import annotations

from typing import Protocol

from regops_api.domain_models import (
    ActionAttemptResult,
    AnalystOutput,
    DetectionResult,
    InvestigatorOutput,
    ProposedAmendment,
)
from regops_api.schemas import ActionType, Finding, Obligation, Regulation


class ChangeDetector(Protocol):
    def detect(self, *, source_filename: str, content: bytes) -> DetectionResult: ...


class RegulationAnalyst(Protocol):
    """Extraction-only role: no action-controller or mutation capability is supplied."""

    def analyze(self, *, regulation: Regulation, content: bytes) -> AnalystOutput: ...


class ImpactInvestigator(Protocol):
    """Investigation-only role: it receives records, never action tools."""

    def investigate(self, *, run_id: str, obligations: list[Obligation]) -> InvestigatorOutput: ...


class ActionController(Protocol):
    """The only role allowed to perform allowlisted actions."""

    def attempt(
        self,
        *,
        finding: Finding,
        action_type: ActionType,
        amendment: ProposedAmendment | None = None,
    ) -> ActionAttemptResult: ...
