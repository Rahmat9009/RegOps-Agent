from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any, get_type_hints

import pytest
from pydantic import BaseModel, ValidationError

from regops_api import worker_models, worker_ports
from regops_api.worker_models import (
    AcceptedEvidenceCatalog,
    AnalystDraftOutput,
    CandidateFinding,
    CandidateObligation,
    CorpusSnapshot,
    EvidenceAnchor,
    ImmutableSourceIdentity,
    InvestigatorDraftOutput,
    SourceDocument,
    SourcePage,
    VerificationResult,
    VerifiedWorkerOutput,
)

FIXTURES = Path(__file__).resolve().parents[1] / "evals" / "fixtures"


def fixture_data(name: str) -> dict[str, Any]:
    value: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return value


def source_fixture() -> SourceDocument:
    return SourceDocument.model_validate_json((FIXTURES / "source.json").read_bytes())


def catalog_fixture() -> AcceptedEvidenceCatalog:
    return AcceptedEvidenceCatalog.model_validate_json(
        (FIXTURES / "accepted-obligations.json").read_bytes(),
    )


def analyst_fixture() -> AnalystDraftOutput:
    return AnalystDraftOutput.model_validate_json(
        (FIXTURES / "analyst-candidates.json").read_bytes()
    )


def corpus_fixture() -> CorpusSnapshot:
    return CorpusSnapshot.model_validate_json((FIXTURES / "corpus.json").read_bytes())


def finding_payload() -> dict[str, Any]:
    finding = fixture_data("benchmark.json")["findings"][0]
    return {
        key: value
        for key, value in finding.items()
        if key not in {"evaluation_id", "obligation_evaluation_id", "expected_action"}
    } | {"obligation_id": "7fd187e1-e22a-5a91-978a-b49a9db29824"}


def test_all_worker_models_forbid_extras_and_revalidate_frozen_instances() -> None:
    models = [
        cls
        for cls in vars(worker_models).values()
        if inspect.isclass(cls) and issubclass(cls, worker_models.WorkerModel)
    ]
    assert len(models) >= 20
    for model in models:
        assert model.model_config["extra"] == "forbid"
        assert model.model_config["strict"] is True
        assert model.model_config["frozen"] is True
        assert model.model_config["revalidate_instances"] == "always"
        assert model.model_config["hide_input_in_errors"] is True


@pytest.mark.parametrize(
    "field",
    [
        "obligation_id",
        "run_id",
        "prompt",
        "chain_of_thought",
        "source_gcs_uri",
        "signed_url",
        "actions",
        "approvals",
        "decided_by",
        "raw_output",
    ],
)
def test_candidate_obligation_rejects_authority_and_hidden_fields(field: str) -> None:
    payload = fixture_data("analyst-candidates.json")["obligations"][0] | {field: "untrusted"}
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CandidateObligation.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    "field",
    [
        "finding_id",
        "run_id",
        "status",
        "proposed_action",
        "decided_by",
        "action_id",
        "reasoning",
    ],
)
def test_candidate_finding_rejects_model_owned_ids_and_actions(field: str) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CandidateFinding.model_validate_json(json.dumps(finding_payload() | {field: "untrusted"}))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("relationship", "approve"),
        ("severity", "critical"),
        ("verdict", "legally_compliant"),
        ("human_review_required", "false"),
        ("human_review_required", 0),
        ("evidence_strength", -0.01),
        ("evidence_strength", 1.01),
        ("evidence_strength", "0.9"),
        ("evidence_strength", True),
        ("interpretation_confidence", float("nan")),
        ("interpretation_confidence", float("inf")),
        ("target_id", "https://foreign.example"),
        ("obligation_id", "OBL-model-generated"),
        ("evidence", []),
    ],
)
def test_candidate_fields_fail_closed(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        CandidateFinding.model_validate_json(json.dumps(finding_payload() | {field: value}))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("statement", "x" * 1001),
        ("statement", " \n\t"),
        ("statement", "hidden\x00text"),
        ("statement", "hidden\u202etext"),
        ("exceptions", ["x" * 501]),
        ("exceptions", ["x"] * 11),
        ("evidence", []),
        ("type", "action"),
        ("effective_date", "2026-02-30"),
    ],
)
def test_obligation_text_and_collection_bounds(field: str, value: object) -> None:
    payload = fixture_data("analyst-candidates.json")["obligations"][0] | {field: value}
    with pytest.raises(ValidationError):
        CandidateObligation.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    ("model", "field", "count"),
    [
        (AnalystDraftOutput, "obligations", 51),
        (AnalystDraftOutput, "obligations", 0),
        (InvestigatorDraftOutput, "findings", 501),
    ],
)
def test_output_collection_bounds(model: type[BaseModel], field: str, count: int) -> None:
    item = (
        fixture_data("analyst-candidates.json")["obligations"][0]
        if field == "obligations"
        else finding_payload()
    )
    with pytest.raises(ValidationError):
        model.model_validate_json(json.dumps({field: [item] * count}))


def test_evidence_collection_and_string_upper_bounds() -> None:
    claim = fixture_data("analyst-candidates.json")["obligations"][0]
    with pytest.raises(ValidationError):
        CandidateObligation.model_validate_json(
            json.dumps(claim | {"evidence": claim["evidence"] * 3})
        )
    with pytest.raises(ValidationError):
        CandidateFinding.model_validate_json(
            json.dumps(
                finding_payload() | {"evidence": finding_payload()["evidence"] * 4},
            )
        )
    with pytest.raises(ValidationError):
        EvidenceAnchor.model_validate_json(json.dumps(claim["evidence"][0] | {"quote": "x" * 301}))
    with pytest.raises(ValidationError):
        SourcePage.model_validate(source_fixture().pages[0].model_dump() | {"text": "x" * 20001})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_sha256", "A" * 64),
        ("source_sha256", "0" * 63),
        ("doc_id", "x" * 129),
        ("page_count", 101),
        ("page_count", True),
        ("page_count", "4"),
        ("synthetic", False),
        ("synthetic", 1),
        ("synthetic", "true"),
    ],
)
def test_immutable_identity_is_strict(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        ImmutableSourceIdentity.model_validate(
            source_fixture().identity.model_dump() | {field: value}
        )


def test_source_pages_must_be_complete_unique_and_bound() -> None:
    source = source_fixture()
    variants = [
        source.pages[:-1],
        (source.pages[0],) * 4,
        (
            source.pages[0].model_copy(update={"source_sha256": "b" * 64}),
            *source.pages[1:],
        ),
    ]
    for pages in variants:
        with pytest.raises(ValidationError):
            SourceDocument.model_validate(source.model_dump() | {"pages": pages})


def test_immutable_records_cannot_be_modified_and_candidates_cannot_be_handed_off() -> None:
    source = source_fixture()
    with pytest.raises(ValidationError, match="frozen"):
        source.pages[0].text = "changed"
    with pytest.raises(ValidationError):
        VerifiedWorkerOutput.model_validate(analyst_fixture().model_dump())
    with pytest.raises(ValidationError):
        VerificationResult(
            accepted=True,
            issues=(
                worker_models.VerificationIssue(
                    stage="evidence",
                    code=worker_models.IssueCode.WRONG_PAGE,
                ),
            ),
        )


def test_worker_ports_have_only_narrow_capabilities_and_verified_handoff() -> None:
    expected = {
        worker_ports.ImmutableSourcePages: {"read_bound_source"},
        worker_ports.AcceptedEvidenceLookup: {"read_accepted_evidence", "read_accepted_corpus"},
        worker_ports.ReadOnlyCorpus: {"list_records", "get_record"},
        worker_ports.CandidateAnalyst: {"analyze"},
        worker_ports.CandidateInvestigator: {"investigate"},
        worker_ports.VerifiedOutputPersistence: {"handoff_verified"},
    }
    for port, methods in expected.items():
        assert {
            n for n, v in vars(port).items() if callable(v) and not n.startswith("_")
        } == methods
    assert set(inspect.signature(worker_ports.CandidateAnalyst.analyze).parameters) == {
        "self",
        "source",
    }
    assert set(inspect.signature(worker_ports.CandidateInvestigator.investigate).parameters) == {
        "self",
        "obligations",
        "corpus",
    }
    assert get_type_hints(worker_ports.CandidateAnalyst.analyze)["return"] is AnalystDraftOutput
    assert get_type_hints(worker_ports.CandidateInvestigator.investigate)["return"] is (
        InvestigatorDraftOutput
    )
    assert get_type_hints(worker_ports.VerifiedOutputPersistence.handoff_verified)["output"] is (
        VerifiedWorkerOutput
    )
    assert not any(
        name in vars(worker_ports)
        for name in (
            "ActionController",
            "ActionPolicy",
            "ApprovalService",
            "RepositoryBundle",
            "FirestoreRepositories",
            "RuntimeStoragePort",
            "ReviewerIdentityProvider",
        )
    )
