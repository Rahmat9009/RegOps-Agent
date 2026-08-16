"""Single-process one-document orchestration foundation for Phase 1A."""

from __future__ import annotations

from pydantic import BaseModel, ValidationError

from regops_api.domain_models import AnalystOutput, InvestigatorOutput
from regops_api.integrations import IntegrationUnavailableError
from regops_api.repositories import FindingRepository, ObligationRepository, RunRepository
from regops_api.roles import ImpactInvestigator, RegulationAnalyst
from regops_api.schemas import Finding, Run, RunState
from regops_api.state_machine import RunStateCoordinator


class AgentOutputValidationError(RuntimeError):
    """Agent output failed the strict Pydantic boundary and was not persisted."""


class OneDocumentOrchestrator:
    """Orchestrates extraction/mapping with injected real roles or explicit test doubles."""

    def __init__(
        self,
        *,
        runs: RunRepository,
        obligations: ObligationRepository,
        findings: FindingRepository,
        states: RunStateCoordinator,
        analyst: RegulationAnalyst,
        investigator: ImpactInvestigator,
    ) -> None:
        self._runs = runs
        self._obligations = obligations
        self._findings = findings
        self._states = states
        self._analyst = analyst
        self._investigator = investigator

    def extract(self, run_id: str, content: bytes) -> AnalystOutput:
        run = self._states.transition(run_id, RunState.EXTRACTING)
        try:
            raw = self._analyst.analyze(regulation=run.regulation, content=content)
            payload = raw.model_dump() if isinstance(raw, BaseModel) else raw
            output = AnalystOutput.model_validate(payload)
        except (ValidationError, TypeError, ValueError) as exc:
            self._states.transition(
                run_id,
                RunState.FAILED_RECOVERABLE,
                failure_code="INVALID_ANALYST_OUTPUT",
            )
            raise AgentOutputValidationError("analyst output failed validation") from exc
        except IntegrationUnavailableError:
            self._states.transition(
                run_id,
                RunState.FAILED_RECOVERABLE,
                failure_code="ANALYST_INTEGRATION_UNAVAILABLE",
            )
            raise
        self._obligations.add_obligations(run_id, output.obligations)
        self._states.transition(run_id, RunState.EXTRACTED)
        return output

    def map_impacts(self, run_id: str) -> InvestigatorOutput:
        self._states.transition(run_id, RunState.MAPPING)
        try:
            raw = self._investigator.investigate(
                run_id=run_id,
                obligations=self._obligations.list_obligations(run_id),
            )
            payload = raw.model_dump() if isinstance(raw, BaseModel) else raw
            output = InvestigatorOutput.model_validate(payload)
            findings = [
                Finding.model_validate(
                    investigated.model_dump() | {"proposed_action": None}
                )
                for investigated in output.findings
            ]
        except (ValidationError, TypeError, ValueError) as exc:
            self._states.transition(
                run_id,
                RunState.FAILED_RECOVERABLE,
                failure_code="INVALID_INVESTIGATOR_OUTPUT",
            )
            raise AgentOutputValidationError("investigator output failed validation") from exc
        except IntegrationUnavailableError:
            self._states.transition(
                run_id,
                RunState.FAILED_RECOVERABLE,
                failure_code="INVESTIGATOR_INTEGRATION_UNAVAILABLE",
            )
            raise
        self._findings.add_findings(findings)
        self._states.transition(run_id, RunState.MAPPED)
        return output

    def verify(self, run_id: str) -> Run:
        self._states.transition(run_id, RunState.VERIFYING)
        return self._states.transition(run_id, RunState.VERIFIED)
