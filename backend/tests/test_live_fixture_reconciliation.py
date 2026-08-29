from __future__ import annotations

from datetime import date

import pytest

from regops_api.live_fixture import (
    KNOWN_SOURCE_SHA256,
    load_minimum_live_fixture,
    reconcile_minimum_live_candidates,
)
from regops_api.schemas import ObligationType
from regops_api.verification import verify_obligations
from regops_api.worker_models import (
    AnalystDraftOutput,
    CandidateObligation,
    SourceDocument,
)
from tests.test_worker_models import source_fixture


def _fixture_output() -> AnalystDraftOutput:
    fixture = load_minimum_live_fixture(KNOWN_SOURCE_SHA256)
    return AnalystDraftOutput(
        obligations=tuple(
            CandidateObligation(**item.model_dump())
            for item in fixture.accepted_obligations
        )
    )


def _replace_first(
    output: AnalystDraftOutput,
    **updates: object,
) -> AnalystDraftOutput:
    return AnalystDraftOutput(
        obligations=(
            output.obligations[0].model_copy(update=updates),
            *output.obligations[1:],
        )
    )


def test_exact_accepted_output_passes_general_verifier_without_reconciliation_change() -> None:
    fixture = load_minimum_live_fixture(KNOWN_SOURCE_SHA256)
    source = source_fixture()
    output = _fixture_output()

    reconciled = reconcile_minimum_live_candidates(
        fixture=fixture,
        source=source,
        candidates=output,
    )
    checked = verify_obligations(
        run_id="fixture-reconciliation-test",
        source=source,
        accepted=fixture.accepted_catalog(source),
        candidates=reconciled,
    )

    assert reconciled == output
    assert checked.result.accepted and checked.output is not None


def test_unique_complete_exact_evidence_canonicalizes_only_generated_statement() -> None:
    fixture = load_minimum_live_fixture(KNOWN_SOURCE_SHA256)
    source = source_fixture()
    output = _replace_first(
        _fixture_output(),
        statement="A non-authoritative synthetic wording variant.",
    )
    original_evidence = output.obligations[0].evidence

    reconciled = reconcile_minimum_live_candidates(
        fixture=fixture,
        source=source,
        candidates=output,
    )
    checked = verify_obligations(
        run_id="fixture-reconciliation-test",
        source=source,
        accepted=fixture.accepted_catalog(source),
        candidates=reconciled,
    )

    assert reconciled.obligations[0].statement == fixture.accepted_obligations[0].statement
    assert reconciled.obligations[0].evidence == original_evidence
    assert checked.result.accepted and checked.output is not None
    assert all(
        item.statement in {accepted.statement for accepted in fixture.accepted_obligations}
        for item in checked.output.obligations
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "quote",
        "quote_layout",
        "page",
        "document",
        "digest",
        "type",
        "date",
        "exceptions",
    ],
)
def test_any_non_statement_mismatch_disables_reconciliation(mutation: str) -> None:
    fixture = load_minimum_live_fixture(KNOWN_SOURCE_SHA256)
    source = source_fixture()
    output = _fixture_output()
    candidate = output.obligations[0]
    if mutation in {"quote", "quote_layout", "page", "document", "digest"}:
        anchor = candidate.evidence[0]
        anchor = anchor.model_copy(
            update={
                "quote": anchor.quote + " altered" if mutation == "quote" else anchor.quote,
                "page": 2 if mutation == "page" else anchor.page,
                "doc_id": "REG-OTHER" if mutation == "document" else anchor.doc_id,
                "source_sha256": "f" * 64
                if mutation == "digest"
                else anchor.source_sha256,
            }
        )
        if mutation == "quote_layout":
            anchor = anchor.model_copy(update={"quote": anchor.quote.replace(" ", "  ", 1)})
        changed = _replace_first(
            output,
            evidence=(anchor, *candidate.evidence[1:]),
        )
    elif mutation == "type":
        changed = _replace_first(output, type=ObligationType.LIMIT)
    elif mutation == "date":
        changed = _replace_first(output, effective_date=date(2026, 10, 2))
    else:
        changed = _replace_first(
            output,
            exceptions=("Different synthetic exception.",),
        )

    reconciled = reconcile_minimum_live_candidates(
        fixture=fixture,
        source=source,
        candidates=changed,
    )
    checked = verify_obligations(
        run_id="fixture-reconciliation-test",
        source=source,
        accepted=fixture.accepted_catalog(source),
        candidates=reconciled,
    )

    assert reconciled is changed
    assert not checked.result.accepted and checked.output is None


def test_partial_ambiguous_and_duplicate_evidence_sets_are_not_reconciled() -> None:
    fixture = load_minimum_live_fixture(KNOWN_SOURCE_SHA256)
    source = source_fixture()
    output = _fixture_output()
    partial = _replace_first(
        output,
        statement="Synthetic variant.",
        evidence=(output.obligations[0].evidence[0],),
    )
    ambiguous_fixture = fixture.model_copy(
        update={
            "accepted_obligations": (
                fixture.accepted_obligations[0],
                fixture.accepted_obligations[0].model_copy(
                    update={"statement": "A second canonical synthetic statement."}
                ),
                fixture.accepted_obligations[2],
            )
        }
    )
    duplicate = AnalystDraftOutput(
        obligations=(
            output.obligations[0],
            output.obligations[0].model_copy(update={"statement": "Duplicate variant."}),
            output.obligations[2],
        )
    )

    assert reconcile_minimum_live_candidates(
        fixture=fixture, source=source, candidates=partial
    ) is partial
    assert reconcile_minimum_live_candidates(
        fixture=ambiguous_fixture, source=source, candidates=output
    ) is output
    assert reconcile_minimum_live_candidates(
        fixture=fixture, source=source, candidates=duplicate
    ) is duplicate


def test_wrong_fixture_version_and_arbitrary_document_receive_no_reconciliation() -> None:
    fixture = load_minimum_live_fixture(KNOWN_SOURCE_SHA256)
    output = _replace_first(_fixture_output(), statement="Synthetic variant.")
    wrong_version = fixture.model_copy(update={"fixture_version": "minimum-live-slice-v2"})
    source = source_fixture()
    other_digest = "f" * 64
    other_source = SourceDocument.model_validate(
        {
            "identity": {
                **source.identity.model_dump(),
                "doc_id": "REG-OTHER",
                "source_sha256": other_digest,
            },
            "pages": tuple(
                {
                    **page.model_dump(),
                    "doc_id": "REG-OTHER",
                    "source_sha256": other_digest,
                }
                for page in source.pages
            ),
        }
    )

    assert reconcile_minimum_live_candidates(
        fixture=wrong_version, source=source, candidates=output
    ) is output
    assert reconcile_minimum_live_candidates(
        fixture=fixture, source=other_source, candidates=output
    ) is output
