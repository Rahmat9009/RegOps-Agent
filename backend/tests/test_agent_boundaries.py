from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from regops_api.domain_models import AnalystOutput, InvestigatedFinding, InvestigatorOutput
from regops_api.integrations import (
    IntegrationUnavailableError,
    UnavailableImpactInvestigator,
    UnavailableRegulationAnalyst,
)
from regops_api.roles import ImpactInvestigator, RegulationAnalyst
from tests.factories import make_finding, make_obligation, make_regulation


def test_analyst_output_rejects_actions_and_extra_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AnalystOutput.model_validate(
            {
                "obligations": [make_obligation().model_dump()],
                "actions": [{"type": "tag_case"}],
            }
        )


def test_investigator_output_cannot_propose_an_action() -> None:
    finding = make_finding()
    payload = finding.model_dump()
    payload["proposed_action"] = {
        "action_id": "malicious-action",
        "finding_id": finding.finding_id,
        "type": "draft_amendment",
        "autonomy": "auto",
        "status": "EXECUTED",
        "idempotency_key": "attacker-chosen",
    }

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        InvestigatedFinding.model_validate(payload)


def test_read_only_role_interfaces_have_no_action_tool_parameters() -> None:
    analyst_parameters = inspect.signature(RegulationAnalyst.analyze).parameters
    investigator_parameters = inspect.signature(ImpactInvestigator.investigate).parameters

    assert set(analyst_parameters) == {"self", "regulation", "content"}
    assert set(investigator_parameters) == {"self", "run_id", "obligations"}
    assert not ({"tools", "actions", "action_controller"} & set(analyst_parameters))
    assert not ({"tools", "actions", "action_controller"} & set(investigator_parameters))


def test_production_role_placeholders_fail_instead_of_fabricating_output() -> None:
    with pytest.raises(IntegrationUnavailableError, match="Gemini/Vertex"):
        UnavailableRegulationAnalyst().analyze(
            regulation=make_regulation(), content=b"%PDF-synthetic"
        )
    with pytest.raises(IntegrationUnavailableError, match="unavailable"):
        UnavailableImpactInvestigator().investigate(
            run_id="run-1", obligations=[make_obligation()]
        )


def test_investigator_output_accepts_only_strict_investigated_findings() -> None:
    finding = make_finding()
    payload = finding.model_dump(exclude={"proposed_action"})
    output = InvestigatorOutput.model_validate({"findings": [payload]})

    assert output.findings[0].finding_id == "finding-1"
