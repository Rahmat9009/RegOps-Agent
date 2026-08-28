"""Pure exact-citation verification over already extracted, bounded pages."""

from __future__ import annotations

import unicodedata
from typing import Annotated

from pydantic import Field, TypeAdapter, ValidationError

from regops_api.worker_models import (
    EvidenceAnchor,
    IssueCode,
    SourceDocument,
    VerificationIssue,
    safe_text,
)


def canonicalize_safe_text(text: str) -> str:
    """NFC and line endings only; preserve case, punctuation and word boundaries."""
    safe_text(text)
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def locator_text(text: str) -> str:
    """Fold layout whitespace solely for locating an EXACT accepted quotation.

    No case folding, compatibility normalization or dehyphenation: those can
    change meaning. Emitted quotations are never rewritten with this helper.
    """
    return " ".join(text.split())


def anchor_key(anchor: EvidenceAnchor) -> tuple[str, str, str, int, str]:
    return (anchor.doc_id, anchor.doc_kind.value, anchor.source_sha256, anchor.page, anchor.quote)


def sorted_anchors(anchors: tuple[EvidenceAnchor, ...]) -> tuple[EvidenceAnchor, ...]:
    return tuple(sorted(set(anchors), key=anchor_key))


def issue(code: IssueCode) -> VerificationIssue:
    return VerificationIssue(code=code, stage="evidence")


def verify_anchor(
    candidate: EvidenceAnchor,
    *,
    accepted: EvidenceAnchor,
    document: SourceDocument,
    expected_source_sha256: str,
) -> tuple[VerificationIssue, ...]:
    """Compare every binding independently; never search another page/document."""
    try:
        candidate = EvidenceAnchor.model_validate(candidate)
        accepted = EvidenceAnchor.model_validate(accepted)
        document = SourceDocument.model_validate(document)
    except ValidationError:
        return (issue(IssueCode.INVALID_SCHEMA),)
    codes: set[IssueCode] = set()
    identity = document.identity
    if not (candidate.doc_id == accepted.doc_id == identity.doc_id):
        codes.add(IssueCode.WRONG_DOCUMENT)
    if not (candidate.doc_kind == accepted.doc_kind == identity.doc_kind):
        codes.add(IssueCode.WRONG_DOCUMENT_KIND)
    if not (
        candidate.source_sha256
        == accepted.source_sha256
        == identity.source_sha256
        == expected_source_sha256
    ):
        codes.add(IssueCode.SOURCE_BINDING_MISMATCH)
    if candidate.page != accepted.page or candidate.page > identity.page_count:
        codes.add(IssueCode.WRONG_PAGE)
    if candidate.quote != accepted.quote:
        codes.add(IssueCode.QUOTE_MISMATCH)
    page = next((page for page in document.pages if page.page == candidate.page), None)
    if page is None or locator_text(candidate.quote) not in locator_text(page.text):
        codes.add(IssueCode.QUOTE_NOT_ON_PAGE)
    return tuple(issue(code) for code in sorted(codes))


def verify_anchor_set(
    candidates: tuple[EvidenceAnchor, ...],
    *,
    accepted: tuple[EvidenceAnchor, ...],
    documents: tuple[SourceDocument, ...],
) -> tuple[VerificationIssue, ...]:
    """Require the complete accepted path, with no duplicate or foreign anchors."""
    try:
        bounded: TypeAdapter[tuple[EvidenceAnchor, ...]] = TypeAdapter(
            Annotated[tuple[EvidenceAnchor, ...], Field(max_length=50)]
        )
        candidates = bounded.validate_python(candidates, strict=True)
        accepted = bounded.validate_python(accepted, strict=True)
        page_adapter: TypeAdapter[tuple[SourceDocument, ...]] = TypeAdapter(
            Annotated[tuple[SourceDocument, ...], Field(min_length=1, max_length=501)],
        )
        documents = page_adapter.validate_python(documents, strict=True)
    except ValidationError:
        return (issue(IssueCode.INVALID_SCHEMA),)
    if len(set(accepted)) != len(accepted) or len(
        {doc.identity.doc_id for doc in documents}
    ) != len(documents):
        return (issue(IssueCode.INVALID_CATALOG),)
    issues: set[VerificationIssue] = set()
    if not candidates or not accepted:
        issues.add(issue(IssueCode.MISSING_EVIDENCE))
    if len(set(candidates)) != len(candidates):
        issues.add(issue(IssueCode.DUPLICATE_ANCHOR))
    if len(candidates) != len(accepted):
        issues.add(issue(IssueCode.MISSING_EVIDENCE))
    for candidate in candidates:
        document = next((doc for doc in documents if doc.identity.doc_id == candidate.doc_id), None)
        same_doc = tuple(anchor for anchor in accepted if anchor.doc_id == candidate.doc_id)
        if document is None or not same_doc:
            issues.add(issue(IssueCode.FOREIGN_EVIDENCE))
            continue
        # Exact match first, then a deterministic diagnostic fallback in this doc.
        reference = next((anchor for anchor in same_doc if anchor == candidate), None)
        if reference is None:
            reference = min(
                same_doc,
                key=lambda a: (a.page != candidate.page, a.quote != candidate.quote, anchor_key(a)),
            )
        issues.update(
            verify_anchor(
                candidate,
                accepted=reference,
                document=document,
                expected_source_sha256=document.identity.source_sha256,
            )
        )
    if set(candidates) != set(accepted) and not issues:
        issues.add(issue(IssueCode.MISSING_EVIDENCE))
    return tuple(sorted(issues, key=lambda item: (item.stage, item.code)))
