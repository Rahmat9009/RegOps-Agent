from __future__ import annotations

import pytest

from regops_api.evidence import canonicalize_safe_text, verify_anchor, verify_anchor_set
from regops_api.schemas import DocumentKind
from regops_api.worker_models import EvidenceAnchor, IssueCode, SourceDocument
from tests.test_worker_models import catalog_fixture, source_fixture


def codes(
    anchor: EvidenceAnchor,
    *,
    document: SourceDocument | None = None,
    digest: str | None = None,
) -> set[IssueCode]:
    accepted = catalog_fixture().obligations[0].evidence[0]
    return {
        i.code
        for i in verify_anchor(
            anchor,
            accepted=accepted,
            document=document or source_fixture(),
            expected_source_sha256=digest or accepted.source_sha256,
        )
    }


def test_exact_accepted_citation() -> None:
    assert codes(catalog_fixture().obligations[0].evidence[0]) == set()


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("doc_id", "FOREIGN-REG", IssueCode.WRONG_DOCUMENT),
        ("doc_kind", DocumentKind.CONTRACT, IssueCode.WRONG_DOCUMENT_KIND),
        ("page", 2, IssueCode.WRONG_PAGE),
        ("page", 5, IssueCode.WRONG_PAGE),
        ("page", 0, IssueCode.INVALID_SCHEMA),
        ("page", True, IssueCode.INVALID_SCHEMA),
        ("page", "3", IssueCode.INVALID_SCHEMA),
        ("page", 3.0, IssueCode.INVALID_SCHEMA),
        ("quote", "Fabricated statement.", IssueCode.QUOTE_MISMATCH),
        ("quote", "", IssueCode.INVALID_SCHEMA),
        ("quote", " \t\r\n", IssueCode.INVALID_SCHEMA),
        ("source_sha256", "f" * 64, IssueCode.SOURCE_BINDING_MISMATCH),
    ],
)
def test_invalid_citation_fails_closed(field: str, value: object, expected: IssueCode) -> None:
    # model_copy deliberately bypasses initial validation: the verifier revalidates.
    anchor = catalog_fixture().obligations[0].evidence[0].model_copy(update={field: value})
    assert expected in codes(anchor)


def test_truncation_and_layout_changes_in_emitted_quote_are_not_accepted() -> None:
    anchor = catalog_fixture().obligations[0].evidence[0]
    for quote in (
        anchor.quote[:-1],
        anchor.quote[:40],
        anchor.quote.replace(" ", "\n"),
        anchor.quote.replace("shall", "may"),
        anchor.quote + " ",
    ):
        assert IssueCode.QUOTE_MISMATCH in codes(anchor.model_copy(update={"quote": quote}))


def test_quote_absent_from_referenced_page_even_if_on_another_page() -> None:
    source = source_fixture()
    quote = catalog_fixture().obligations[0].evidence[0]
    pages = tuple(
        page.model_copy(update={"text": quote.quote if page.page == 2 else "No evidence"})
        for page in source.pages
    )
    assert codes(quote, document=source.model_copy(update={"pages": pages})) == {
        IssueCode.QUOTE_NOT_ON_PAGE,
    }


def test_only_locator_folds_line_endings_and_pdf_layout_whitespace() -> None:
    source = source_fixture()
    anchor = catalog_fixture().obligations[0].evidence[0]
    pages = tuple(
        page.model_copy(update={"text": anchor.quote.replace(" ", "\r\n\t\u00a0 ")})
        if page.page == 3
        else page
        for page in source.pages
    )
    assert codes(anchor, document=source.model_copy(update={"pages": pages})) == set()
    assert anchor.quote == catalog_fixture().obligations[0].evidence[0].quote


def test_locator_does_not_repair_case_punctuation_or_hyphenation() -> None:
    source = source_fixture()
    anchor = catalog_fixture().obligations[0].evidence[0]
    for text in (
        anchor.quote.upper(),
        anchor.quote.replace("placement", "place-\nment"),
        anchor.quote.replace(";", ","),
    ):
        pages = tuple(
            page.model_copy(update={"text": text}) if page.page == 3 else page
            for page in source.pages
        )
        assert IssueCode.QUOTE_NOT_ON_PAGE in codes(
            anchor,
            document=source.model_copy(
                update={"pages": pages},
            ),
        )


def test_foreign_expected_digest_fails_even_when_quote_is_valid() -> None:
    assert IssueCode.SOURCE_BINDING_MISMATCH in codes(
        catalog_fixture().obligations[0].evidence[0],
        digest="a" * 64,
    )


def test_duplicate_missing_and_foreign_anchors_are_rejected() -> None:
    evidence = catalog_fixture().obligations[0].evidence
    for candidate, expected in [
        ((*evidence, evidence[0]), IssueCode.DUPLICATE_ANCHOR),
        ((), IssueCode.MISSING_EVIDENCE),
        (
            (evidence[0].model_copy(update={"doc_id": "OTHER"}), evidence[1]),
            IssueCode.FOREIGN_EVIDENCE,
        ),
    ]:
        assert expected in {
            i.code
            for i in verify_anchor_set(
                candidate,
                accepted=evidence,
                documents=(source_fixture(),),
            )
        }


def test_evidence_issue_payloads_never_leak_source_or_candidate_text() -> None:
    anchor = catalog_fixture().obligations[0].evidence[0]
    bad = anchor.model_copy(update={"quote": "private prompt and fabricated source text"})
    results = verify_anchor(
        bad, accepted=anchor, document=source_fixture(), expected_source_sha256=anchor.source_sha256
    )
    payload = "".join(i.model_dump_json() for i in results)
    assert "private" not in payload and anchor.quote not in payload and anchor.doc_id not in payload
    assert all(set(i.model_dump()) == {"code", "stage"} for i in results)


def test_safe_canonicalization_preserves_semantics() -> None:
    assert canonicalize_safe_text("Cafe\u0301\r\nFee: 0; MUST NOT charge.") == (
        "Café\nFee: 0; MUST NOT charge."
    )
    assert canonicalize_safe_text("① BDT 0 — not 1") == "① BDT 0 — not 1"
    with pytest.raises(ValueError, match="UNSAFE_TEXT"):
        canonicalize_safe_text("hidden\x00instruction")
