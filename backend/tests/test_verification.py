from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

import pytest

from regops_api.schemas import FindingVerdict, Relationship, RunState, Severity
from regops_api.state_machine import ALLOWED_TRANSITIONS
from regops_api.verification import FindingVerifier, duplicate_source_completion, verify_obligations
from regops_api.worker_ids import (
    audit_event_id,
    canonical_bytes,
    finding_id,
    obligation_id,
    stage_output_id,
)
from regops_api.worker_models import (
    AcceptedEvidenceCatalog,
    AnalystDraftOutput,
    CandidateFinding,
    CorpusSnapshot,
    FindingVerification,
    InvestigatorDraftOutput,
    IssueCode,
    PreviouslyVerifiedSource,
    SourceDocument,
    VerifiedObligationSet,
)
from tests.test_worker_models import (
    FIXTURES,
    analyst_fixture,
    catalog_fixture,
    corpus_fixture,
    fixture_data,
    source_fixture,
)

RUN_ID = "eval-run-2026-0417"


@dataclass(frozen=True)
class Inputs:
    source: SourceDocument
    accepted: AcceptedEvidenceCatalog
    obligations: VerifiedObligationSet
    corpus: CorpusSnapshot
    candidates: InvestigatorDraftOutput


def inputs() -> Inputs:
    source, accepted = source_fixture(), catalog_fixture()
    extracted = verify_obligations(
        run_id=RUN_ID, source=source, accepted=accepted, candidates=analyst_fixture()
    )
    assert extracted.output is not None
    ids_by_statement = {o.statement: o.obligation_id for o in extracted.output.obligations}
    benchmark = fixture_data("benchmark.json")
    ids = {o["evaluation_id"]: ids_by_statement[o["statement"]] for o in benchmark["obligations"]}
    findings = tuple(
        CandidateFinding.model_validate_json(
            json.dumps(
                {
                    key: value
                    for key, value in item.items()
                    if key not in {"evaluation_id", "obligation_evaluation_id", "expected_action"}
                }
                | {"obligation_id": ids[item["obligation_evaluation_id"]]}
            )
        )
        for item in benchmark["findings"]
    )
    return Inputs(
        source,
        accepted,
        extracted.output,
        corpus_fixture(),
        InvestigatorDraftOutput(findings=findings),
    )


def verify(data: Inputs, **updates: object) -> FindingVerification:
    arguments = {
        "source": data.source,
        "accepted": data.accepted,
        "obligations": data.obligations,
        "corpus": data.corpus,
        "candidates": data.candidates,
    } | updates
    return FindingVerifier().verify(**arguments)  # type: ignore[arg-type]


def test_benchmark_verifies_three_obligations_and_37_findings() -> None:
    result = verify(inputs())
    assert result.output is not None
    assert result.result.accepted
    assert (result.result.obligation_count, result.result.finding_count) == (3, 37)
    assert Counter(f.severity.value for f in result.output.findings) == {
        "high": 6,
        "medium": 11,
        "low": 20,
    }
    first = next(f for f in result.output.findings if f.target_id == "CNT-0001")
    assert first.target_clause == "7.2" and first.affected_case_id == "CASE-0142"
    assert first.obligation.statement == catalog_fixture().obligations[0].statement
    assert first.human_review_required is True and first.severity is Severity.HIGH
    assert first.verdict is FindingVerdict.SURVIVED
    assert {a.doc_id for a in first.evidence} == {"REG-2026-0417", "CNT-0001", "CASE-0142"}
    assert all(UUID(f.finding_id).version == 5 for f in result.output.findings)
    assert all(f.run_id == RUN_ID for f in result.output.findings)
    assert "proposed_action" not in first.model_dump()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("statement", "The agency may collect unlimited fees."),
        ("exceptions", ("Fees may be recovered from the worker.",)),
        ("effective_date", None),
    ],
)
def test_valid_quote_cannot_authorize_an_unsupported_obligation(field: str, value: object) -> None:
    draft = analyst_fixture()
    candidate = draft.obligations[0].model_copy(update={field: value})
    result = verify_obligations(
        run_id=RUN_ID,
        source=source_fixture(),
        accepted=catalog_fixture(),
        candidates=AnalystDraftOutput(obligations=(candidate,)),
    )
    assert result.output is None
    assert {i.code for i in result.result.issues} == {IssueCode.UNSUPPORTED_OBLIGATION}


def test_obligations_reject_foreign_source_and_duplicate_anchors() -> None:
    source, accepted, draft = source_fixture(), catalog_fixture(), analyst_fixture()
    foreign = accepted.model_copy(
        update={
            "source": accepted.source.model_copy(update={"source_sha256": "f" * 64}),
        }
    )
    result = verify_obligations(run_id=RUN_ID, source=source, accepted=foreign, candidates=draft)
    assert result.output is None
    assert result.result.issues[0].code is IssueCode.SOURCE_BINDING_MISMATCH
    candidate = draft.obligations[0]
    duplicate = candidate.model_copy(
        update={"evidence": (*candidate.evidence, candidate.evidence[0])}
    )
    result = verify_obligations(
        run_id=RUN_ID,
        source=source,
        accepted=accepted,
        candidates=AnalystDraftOutput(obligations=(duplicate,)),
    )
    assert result.output is None
    assert IssueCode.DUPLICATE_ANCHOR in {i.code for i in result.result.issues}


def test_obligation_citation_cannot_be_borrowed_from_another_obligation() -> None:
    draft = analyst_fixture()
    unsupported = draft.obligations[0].model_copy(
        update={"evidence": draft.obligations[1].evidence}
    )
    result = verify_obligations(
        run_id=RUN_ID,
        source=source_fixture(),
        accepted=catalog_fixture(),
        candidates=AnalystDraftOutput(obligations=(unsupported,)),
    )
    assert result.output is None and not result.result.accepted


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("target_id", "CNT-FOREIGN", IssueCode.FOREIGN_TARGET),
        ("target_clause", "99", IssueCode.UNSUPPORTED_FINDING),
        ("relationship", Relationship.NO_IMPACT, IssueCode.UNSUPPORTED_FINDING),
        ("affected_case_id", "CASE-FOREIGN", IssueCode.FOREIGN_TARGET),
        ("affected_case_id", "CASE-0218", IssueCode.UNSUPPORTED_FINDING),
        (
            "obligation_id",
            "7fd187e1-e22a-5a91-978a-b49a9db29824",
            IssueCode.MISSING_OBLIGATION_BINDING,
        ),
    ],
)
def test_unsupported_or_foreign_finding_is_rejected(
    field: str, value: object, code: IssueCode
) -> None:
    data = inputs()
    candidate = data.candidates.findings[0].model_copy(update={field: value})
    result = verify(data, candidates=InvestigatorDraftOutput(findings=(candidate,)))
    assert result.output is None
    assert code in {i.code for i in result.result.issues}


def test_missing_obligation_field_is_sanitized_without_raw_output() -> None:
    data = inputs()
    candidate = data.candidates.findings[0].model_dump()
    del candidate["obligation_id"]
    result = verify(data, candidates={"findings": (candidate,)})
    assert result.output is None and result.result.issues[0].code is IssueCode.INVALID_SCHEMA
    assert data.candidates.findings[0].evidence[0].quote not in result.result.model_dump_json()


@pytest.mark.parametrize("side", ["regulation", "contract", "case"])
def test_complete_evidence_path_is_required(side: str) -> None:
    data = inputs()
    candidate = data.candidates.findings[0]
    changed = candidate.model_copy(
        update={
            "evidence": tuple(a for a in candidate.evidence if a.doc_kind.value != side),
        }
    )
    result = verify(data, candidates=InvestigatorDraftOutput(findings=(changed,)))
    assert result.output is None
    assert IssueCode.MISSING_EVIDENCE in {i.code for i in result.result.issues}


def test_other_accepted_corpus_evidence_cannot_rescue_a_finding() -> None:
    data = inputs()
    candidate = data.candidates.findings[0]
    foreign = data.corpus.records[-1].evidence[0]
    changed = candidate.model_copy(update={"evidence": (*candidate.evidence[:-1], foreign)})
    result = verify(data, candidates=InvestigatorDraftOutput(findings=(changed,)))
    assert result.output is None
    assert IssueCode.FOREIGN_EVIDENCE in {i.code for i in result.result.issues}


def test_mixed_valid_and_invalid_batch_has_no_partial_persistence_payload() -> None:
    data = inputs()
    bad = data.candidates.findings[0].model_copy(update={"target_id": "FOREIGN"})
    result = verify(
        data, candidates=InvestigatorDraftOutput(findings=(*data.candidates.findings, bad))
    )
    assert result.output is None
    assert result.result.obligation_count == result.result.finding_count == 0


def test_verified_type_name_does_not_authorize_forged_or_foreign_obligations() -> None:
    data = inputs()
    for update in (
        {"run_id": "another-run"},
        {"source_sha256": "f" * 64},
        {"statement": "Unsupported"},
        {"obligation_id": "7fd187e1-e22a-5a91-978a-b49a9db29824"},
    ):
        forged = data.obligations.obligations[0].model_copy(update=update)
        obligations = data.obligations.model_copy(
            update={
                "obligations": (forged, *data.obligations.obligations[1:]),
            }
        )
        result = verify(data, obligations=obligations)
        assert result.output is None
        assert result.result.issues[0].code is IssueCode.MISSING_OBLIGATION_BINDING


def test_backend_recomputes_severity_review_and_caps_scores() -> None:
    data = inputs()
    candidate = data.candidates.findings[0].model_copy(
        update={
            "severity": Severity.LOW,
            "human_review_required": False,
            "evidence_strength": 1.0,
            "interpretation_confidence": 1.0,
        }
    )
    result = verify(data, candidates=InvestigatorDraftOutput(findings=(candidate,)))
    assert result.output is not None
    finding = result.output.findings[0]
    assert finding.severity is Severity.HIGH and finding.human_review_required
    assert (finding.evidence_strength, finding.interpretation_confidence) == (0.95, 0.9)


def test_duplicate_findings_merge_conservatively_independent_of_order() -> None:
    data = inputs()
    original = data.candidates.findings[0]
    disagreement = original.model_copy(
        update={
            "verdict": FindingVerdict.REFUTED,
            "evidence_strength": 0.5,
            "interpretation_confidence": 0.4,
            "evidence": tuple(reversed(original.evidence)),
        }
    )
    first = verify(data, candidates=InvestigatorDraftOutput(findings=(original, disagreement)))
    second = verify(data, candidates=InvestigatorDraftOutput(findings=(disagreement, original)))
    assert first.output is not None and second.output is not None
    assert canonical_bytes(first.output) == canonical_bytes(second.output)
    assert len(first.output.findings) == 1
    merged = first.output.findings[0]
    assert merged.verdict is FindingVerdict.UNCERTAIN and merged.human_review_required
    assert (merged.evidence_strength, merged.interpretation_confidence) == (0.5, 0.4)


def test_explicit_refutation_is_preserved_and_cannot_be_overridden_by_positive_candidate() -> None:
    data = inputs()
    original = data.candidates.findings[0]
    rules = (
        data.corpus.impacts[0].model_copy(
            update={
                "relationship": Relationship.NO_IMPACT,
                "verdict": FindingVerdict.REFUTED,
            }
        ),
    )
    corpus = data.corpus.model_copy(update={"impacts": rules})
    candidate = original.model_copy(
        update={
            "relationship": Relationship.NO_IMPACT,
            "verdict": FindingVerdict.REFUTED,
        }
    )
    result = verify(data, corpus=corpus, candidates=InvestigatorDraftOutput(findings=(candidate,)))
    assert result.output is not None
    assert result.output.findings[0].verdict is FindingVerdict.REFUTED
    assert result.output.findings[0].severity is Severity.LOW
    result = verify(
        data,
        corpus=corpus,
        candidates=InvestigatorDraftOutput(
            findings=(candidate.model_copy(update={"verdict": FindingVerdict.SURVIVED}),)
        ),
    )
    assert result.output is not None
    assert result.output.findings[0].verdict is FindingVerdict.UNCERTAIN
    assert result.output.findings[0].human_review_required


def test_ambiguous_corpus_and_non_synthetic_records_fail_closed() -> None:
    data = inputs()
    for update in (
        {"records": (*data.corpus.records, data.corpus.records[0])},
        {"impacts": (*data.corpus.impacts, data.corpus.impacts[0])},
        {"synthetic": False},
    ):
        result = verify(data, corpus=data.corpus.model_copy(update=update))
        assert result.output is None
    rule = data.corpus.impacts[0]
    invalid = rule.model_copy(update={"evidence": rule.evidence[1:]})
    result = verify(data, corpus=data.corpus.model_copy(update={"impacts": (invalid,)}))
    assert result.output is None and result.result.issues[0].code is IssueCode.INVALID_CATALOG


def test_repeated_and_permuted_verification_is_byte_identical_and_has_no_side_effects() -> None:
    data = inputs()
    before = tuple(
        canonical_bytes(value)
        for value in (
            data.source,
            data.accepted,
            data.obligations,
            data.corpus,
            data.candidates,
        )
    )
    first = verify(data)
    assert first.output is not None
    expected = canonical_bytes(first.output)
    for seed in range(5):
        rng = random.Random(seed)
        findings = list(data.candidates.findings)
        rng.shuffle(findings)
        candidates = InvestigatorDraftOutput(
            findings=tuple(
                finding.model_copy(update={"evidence": tuple(reversed(finding.evidence))})
                for finding in findings
            )
        )
        corpus = data.corpus.model_copy(
            update={
                "records": tuple(reversed(data.corpus.records)),
                "impacts": tuple(
                    rule.model_copy(update={"evidence": tuple(reversed(rule.evidence))})
                    for rule in reversed(data.corpus.impacts)
                ),
            }
        )
        result = verify(
            data,
            candidates=candidates,
            corpus=corpus,
            source=data.source.model_copy(update={"pages": tuple(reversed(data.source.pages))}),
        )
        assert result.output is not None
        assert canonical_bytes(result.output) == expected
    assert before == tuple(
        canonical_bytes(value)
        for value in (
            data.source,
            data.accepted,
            data.obligations,
            data.corpus,
            data.candidates,
        )
    )
    keys = [
        (f.obligation.obligation_id, f.target_id, f.relationship.value, f.affected_case_id or "")
        for f in first.output.findings
    ]
    assert keys == sorted(keys)


def test_obligation_order_and_duplicates_do_not_change_canonical_output() -> None:
    source, accepted, candidates = source_fixture(), catalog_fixture(), analyst_fixture()
    first = verify_obligations(
        run_id=RUN_ID, source=source, accepted=accepted, candidates=candidates
    )
    reversed_candidates = AnalystDraftOutput(
        obligations=tuple(
            c.model_copy(update={"evidence": tuple(reversed(c.evidence))})
            for c in (*reversed(candidates.obligations), candidates.obligations[0])
        )
    )
    second = verify_obligations(
        run_id=RUN_ID,
        source=source,
        accepted=accepted.model_copy(
            update={
                "obligations": tuple(reversed(accepted.obligations)),
            }
        ),
        candidates=reversed_candidates,
    )
    assert first.output is not None and second.output is not None
    assert canonical_bytes(first.output) == canonical_bytes(second.output)


def test_uuid5_material_is_run_scoped_and_versioned() -> None:
    o = catalog_fixture().obligations[0]
    digest = source_fixture().identity.source_sha256
    first = obligation_id(RUN_ID, digest, o.statement, o.evidence)
    assert first == obligation_id(RUN_ID, digest, o.statement, tuple(reversed(o.evidence)))
    assert first != obligation_id("another-run", digest, o.statement, o.evidence)
    assert first != obligation_id(RUN_ID, "f" * 64, o.statement, o.evidence)
    assert first != obligation_id(RUN_ID, digest, o.statement + " Changed.", o.evidence)
    finding = finding_id(RUN_ID, first, "CNT-0001", Relationship.CONFLICTS_WITH, "CASE-0142")
    assert finding != finding_id(RUN_ID, first, "CNT-0001", Relationship.CONFLICTS_WITH, None)
    stage = stage_output_id(RUN_ID, "EXTRACTED", digest, "v1")
    assert stage == stage_output_id(RUN_ID, "EXTRACTED", digest, "v1")
    assert stage != stage_output_id(RUN_ID, "EXTRACTED", digest, "v2")
    audit = audit_event_id(RUN_ID, 1, "verified", 1)
    assert audit == audit_event_id(RUN_ID, 1, "verified", 1)
    assert audit != audit_event_id(RUN_ID, 1, "verified", 2)
    assert all(UUID(value).version == 5 for value in (first, finding, stage, audit))
    with pytest.raises(ValueError):
        obligation_id("run\x00id", digest, o.statement, o.evidence)


def test_canonical_output_is_independent_of_python_hash_seed() -> None:
    code = (
        "from tests.test_verification import inputs, verify; "
        "from regops_api.worker_ids import canonical_bytes; "
        "import sys; result=verify(inputs()); assert result.output is not None; "
        "sys.stdout.buffer.write(canonical_bytes(result.output))"
    )
    outputs = [
        subprocess.run(
            [sys.executable, "-c", code],
            cwd=FIXTURES.parents[1],
            env=os.environ | {"PYTHONHASHSEED": seed},
            capture_output=True,
            check=True,
            timeout=30,
        ).stdout
        for seed in ("1", "4321")
    ]
    assert outputs[0] == outputs[1]
    assert len(json.loads(outputs[0])["findings"]) == 37


def test_duplicate_source_returns_only_empty_deterministic_completion_plan() -> None:
    source = source_fixture().identity
    prior = PreviouslyVerifiedSource(run_id="previous-run", source=source)
    first = duplicate_source_completion(run_id=RUN_ID, source=source, prior=prior)
    second = duplicate_source_completion(run_id=RUN_ID, source=source, prior=prior)
    assert canonical_bytes(first) == canonical_bytes(second)
    assert first.result == "duplicate_source_skipped"
    assert first.terminal_state == "COMPLETED"
    assert (
        first.analysis_calls,
        first.obligations_created,
        first.findings_created,
        first.actions_created,
        first.approvals_created,
    ) == (0, 0, 0, 0, 0)
    for previous, current in zip(first.state_path, first.state_path[1:], strict=False):
        assert RunState(current) in ALLOWED_TRANSITIONS[RunState(previous)]
    assert "AWAITING_APPROVAL" not in first.state_path


def test_duplicate_source_requires_prior_verified_hash_binding() -> None:
    source = source_fixture().identity
    for prior in (
        PreviouslyVerifiedSource(
            run_id="previous-run",
            source=source.model_copy(
                update={
                    "source_sha256": "f" * 64,
                }
            ),
        ),
        PreviouslyVerifiedSource(run_id=RUN_ID, source=source),
    ):
        with pytest.raises(ValueError, match=r"^SOURCE_BINDING_MISMATCH$"):
            duplicate_source_completion(run_id=RUN_ID, source=source, prior=prior)


def test_json_fixture_provenance_anchors_and_counterfactual_expectations() -> None:
    benchmark = fixture_data("benchmark.json")
    source = source_fixture()
    catalog = catalog_fixture()
    assert benchmark["source_document_id"] == source.identity.doc_id == "REG-2026-0417"
    assert benchmark["effective_date"] == "2026-10-01"
    assert all(str(o.effective_date) == "2026-10-01" for o in catalog.obligations)
    assert catalog.obligations[0].evidence[0].quote == (
        "No licensed recruitment agency shall charge a migrant worker any placement fee; "
        "permissible costs are limited to those defined in §4(b)."
    )
    assert all(o.evidence[0].page == 3 for o in catalog.obligations)
    assert catalog.obligations[1].evidence[0].quote == (
        "Each licensed recruitment agency must reissue its published fee schedule within 30 days "
        "after this amendment is issued. The reissued schedule must identify the BDT 0 worker-paid "
        "placement fee limit and distinguish employer-paid costs."
    )
    assert catalog.obligations[2].evidence[0].quote == (
        "Employer-paid medical examination costs remain permissible under this amended synthetic "
        "rule when no amount is transferred to, deducted from, or reclaimed from the worker."
    )
    assert len(benchmark["obligations"]) == 3 and len(benchmark["findings"]) == 37
    assert Counter(f["severity"] for f in benchmark["findings"]) == {
        "high": 6,
        "medium": 11,
        "low": 20,
    }
    ids = {f["evaluation_id"] for f in benchmark["findings"]}
    assert len(ids) == 37
    cf = benchmark["counterfactual"]
    assert (
        cf["baseline_finding_count"],
        cf["predicted_resolved_count"],
        cf["remaining_count"],
        cf["new_conflicts_count"],
        cf["remaining_high_risk_count"],
    ) == (37, 31, 6, 2, 1)
    resolved, remaining, new, high = (
        set(cf[key])
        for key in (
            "resolved_finding_ids",
            "unchanged_finding_ids",
            "new_conflict_ids",
            "remaining_high_risk_ids",
        )
    )
    assert (len(resolved), len(remaining), len(new), len(high)) == (31, 6, 2, 1)
    assert resolved | remaining == ids and not resolved & remaining and not new & ids
    assert high <= remaining
    assert high <= {f["evaluation_id"] for f in benchmark["findings"] if f["severity"] == "high"}
    first = benchmark["findings"][0]
    assert first["evaluation_id"] == "FND-0001" and first["target_clause"] == "7.2"
    assert first["expected_action"] == {
        "type": "draft_amendment",
        "autonomy": "approval_required",
        "shadow_only": True,
        "approved_status": "APPROVED_DRAFT",
    }
    corpus = corpus_fixture()
    assert {"CNT-0001", "CASE-0142", "POL-0007"} <= {
        r.document.identity.doc_id for r in corpus.records
    }
    for record in corpus.records:
        assert sha256(record.document.pages[0].text.encode()).hexdigest() == (
            record.document.identity.source_sha256
        )
    provenance = fixture_data("provenance.json")
    assert provenance["source_sha256"] == source.identity.source_sha256
    assert provenance["scorecard_available"] is False


def test_signed_zero_scores_do_not_depend_on_duplicate_order() -> None:
    data = inputs()
    original = data.candidates.findings[0]
    candidates = tuple(
        original.model_copy(update={"evidence_strength": score}) for score in (0.0, -0.0)
    )
    first = verify(data, candidates=InvestigatorDraftOutput(findings=candidates))
    second = verify(data, candidates=InvestigatorDraftOutput(findings=tuple(reversed(candidates))))
    assert first.output is not None and second.output is not None
    assert canonical_bytes(first.output) == canonical_bytes(second.output)
    assert b"-0.0" not in canonical_bytes(first.output)


def test_ambiguous_obligation_identifier_material_fails_before_verification() -> None:
    source, accepted, draft = source_fixture(), catalog_fixture(), analyst_fixture()
    duplicate = accepted.obligations[0].model_copy(update={"effective_date": None})
    ambiguous = accepted.model_copy(update={"obligations": (*accepted.obligations, duplicate)})
    result = verify_obligations(run_id=RUN_ID, source=source, accepted=ambiguous, candidates=draft)
    assert result.output is None and result.result.issues[0].code is IssueCode.INVALID_CATALOG
