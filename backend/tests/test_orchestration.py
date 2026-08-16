from __future__ import annotations

from typing import cast

import pytest

from regops_api.domain_models import AnalystOutput, InvestigatedFinding, InvestigatorOutput
from regops_api.in_memory import InMemoryRepositories
from regops_api.integrations import (
    IntegrationUnavailableError,
    UnavailableRegulationAnalyst,
)
from regops_api.orchestration import AgentOutputValidationError, OneDocumentOrchestrator
from regops_api.schemas import Obligation, Regulation, RunState
from regops_api.state_machine import RunStateCoordinator
from tests.factories import make_finding, make_obligation, make_run


class MaliciousAnalyst:
    def analyze(self, *, regulation: Regulation, content: bytes) -> AnalystOutput:
        del regulation, content
        return cast(
            AnalystOutput,
            {
                "obligations": [make_obligation().model_dump()],
                "actions": [{"type": "draft_amendment"}],
            },
        )


class ValidAnalyst:
    def analyze(self, *, regulation: Regulation, content: bytes) -> AnalystOutput:
        del regulation, content
        return AnalystOutput(obligations=[make_obligation()])


class ValidInvestigator:
    def investigate(
        self, *, run_id: str, obligations: list[Obligation]
    ) -> InvestigatorOutput:
        assert run_id == "run-1"
        assert obligations
        finding = make_finding()
        investigated = InvestigatedFinding.model_validate(
            finding.model_dump(exclude={"proposed_action"})
        )
        return InvestigatorOutput(findings=[investigated])


def make_orchestrator(
    repositories: InMemoryRepositories,
    analyst: MaliciousAnalyst | ValidAnalyst | UnavailableRegulationAnalyst,
) -> OneDocumentOrchestrator:
    states = RunStateCoordinator(repositories, repositories, repositories)
    states.initialize(make_run())
    return OneDocumentOrchestrator(
        runs=repositories,
        obligations=repositories,
        findings=repositories,
        states=states,
        analyst=analyst,
        investigator=ValidInvestigator(),
    )


def test_invalid_agent_output_is_rejected_before_persistence_and_checkpointed() -> None:
    repositories = InMemoryRepositories.for_tests()
    orchestrator = make_orchestrator(repositories, MaliciousAnalyst())

    with pytest.raises(AgentOutputValidationError):
        orchestrator.extract("run-1", b"%PDF-synthetic")

    assert repositories.list_obligations("run-1") == []
    assert repositories.get_run("run-1").state is RunState.FAILED_RECOVERABLE
    checkpoint = repositories.latest_checkpoint("run-1")
    assert checkpoint is not None
    assert checkpoint.resume_state is RunState.EXTRACTING
    assert checkpoint.failure_code == "INVALID_ANALYST_OUTPUT"


def test_valid_outputs_drive_extraction_mapping_and_verification() -> None:
    repositories = InMemoryRepositories.for_tests()
    orchestrator = make_orchestrator(repositories, ValidAnalyst())

    orchestrator.extract("run-1", b"%PDF-synthetic")
    orchestrator.map_impacts("run-1")
    run = orchestrator.verify("run-1")

    assert run.state is RunState.VERIFIED
    assert repositories.list_obligations("run-1")[0].obligation_id == "obl-1"
    assert repositories.list_findings("run-1")[0].finding_id == "finding-1"


def test_missing_production_analyst_fails_clearly_without_findings() -> None:
    repositories = InMemoryRepositories.for_tests()
    orchestrator = make_orchestrator(repositories, UnavailableRegulationAnalyst())

    with pytest.raises(IntegrationUnavailableError, match="required and unavailable"):
        orchestrator.extract("run-1", b"%PDF-synthetic")

    assert repositories.get_run("run-1").state is RunState.FAILED_RECOVERABLE
    assert repositories.list_obligations("run-1") == []
    assert repositories.list_findings("run-1") == []
