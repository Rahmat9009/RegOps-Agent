"""Deterministic, side-effect-free gate from candidates to verified records.

The accepted claim catalog and immutable corpus are trusted inputs supplied by
the backend. This is deliberately a closed-world verifier, not a general-purpose
natural-language entailment engine. No production fallback or model call exists.
"""

from __future__ import annotations

from hashlib import sha256
from hmac import compare_digest

from pydantic import TypeAdapter, ValidationError

from regops_api.evidence import canonicalize_safe_text, sorted_anchors, verify_anchor_set
from regops_api.schemas import DocumentKind, FindingVerdict, ObligationType, Relationship, Severity
from regops_api.worker_ids import canonical_bytes, finding_id, obligation_id
from regops_api.worker_models import (
    AcceptedEvidenceCatalog,
    AcceptedImpact,
    AcceptedObligation,
    AnalystDraftOutput,
    CandidateFinding,
    CandidateObligation,
    CorpusSnapshot,
    DuplicateSourceCompletion,
    FindingVerification,
    Identifier,
    ImmutableSourceIdentity,
    InvestigatorDraftOutput,
    IssueCode,
    ObligationClaim,
    ObligationVerification,
    PreviouslyVerifiedSource,
    SourceDocument,
    VerificationIssue,
    VerificationResult,
    VerifiedFinding,
    VerifiedObligation,
    VerifiedObligationSet,
    VerifiedWorkerOutput,
)

SEVERITY_RULE_VERSION = "synthetic-severity-v1"
SURVIVED_THRESHOLD = 0.8


def _failure(code: IssueCode, *, finding: bool = False) -> VerificationResult:
    return VerificationResult(
        accepted=False,
        issues=(
            VerificationIssue(
                code=code,
                stage="findings" if finding else "obligations",
            ),
        ),
    )


def _rejected(issues: set[VerificationIssue]) -> VerificationResult:
    return VerificationResult(
        accepted=False,
        issues=tuple(sorted(issues, key=lambda i: (i.stage, i.code))),
    )


def _claim(value: ObligationClaim) -> AcceptedObligation:
    return AcceptedObligation(
        statement=canonicalize_safe_text(value.statement),
        type=value.type,
        exceptions=tuple(sorted({canonicalize_safe_text(e) for e in value.exceptions})),
        effective_date=value.effective_date,
        evidence=sorted_anchors(value.evidence),
    )


def _same_claim(left: ObligationClaim, right: ObligationClaim) -> bool:
    return _claim(left).model_dump(exclude={"evidence"}) == _claim(right).model_dump(
        exclude={"evidence"},
    )


def _catalog_valid(source: SourceDocument, catalog: AcceptedEvidenceCatalog) -> bool:
    return (
        source.identity == catalog.source
        and source.identity.doc_kind is DocumentKind.REGULATION
        and len({_claim(o) for o in catalog.obligations}) == len(catalog.obligations)
        # Types, dates and exceptions are not ID material in the frozen strategy.
        # Reject ambiguous accepted records before either variant can be emitted.
        and len({(_claim(o).statement, _claim(o).evidence) for o in catalog.obligations})
        == len(catalog.obligations)
        and all(
            not verify_anchor_set(
                o.evidence,
                accepted=o.evidence,
                documents=(source,),
            )
            for o in catalog.obligations
        )
    )


def verify_obligations(
    *,
    run_id: str,
    source: SourceDocument,
    accepted: AcceptedEvidenceCatalog,
    candidates: AnalystDraftOutput,
) -> ObligationVerification:
    """All-or-nothing extraction gate. Unknown prose/date/exception claims fail."""
    try:
        TypeAdapter(Identifier).validate_python(run_id)
        source = SourceDocument.model_validate(source)
        accepted = AcceptedEvidenceCatalog.model_validate(accepted)
        candidates = AnalystDraftOutput.model_validate(candidates)
    except ValidationError:
        return ObligationVerification(result=_failure(IssueCode.INVALID_SCHEMA))
    if source.identity != accepted.source:
        return ObligationVerification(result=_failure(IssueCode.SOURCE_BINDING_MISMATCH))
    if not _catalog_valid(source, accepted):
        return ObligationVerification(result=_failure(IssueCode.INVALID_CATALOG))
    issues: set[VerificationIssue] = set()
    records: dict[str, VerifiedObligation] = {}
    for candidate in candidates.obligations:
        supported = sorted(
            (o for o in accepted.obligations if _same_claim(candidate, o)),
            key=canonical_bytes,
        )
        if not supported:
            issues.add(
                VerificationIssue(code=IssueCode.UNSUPPORTED_OBLIGATION, stage="obligations")
            )
            continue
        # A quotation from another obligation cannot rescue a claim.
        reference = next(
            (o for o in supported if set(o.evidence) == set(candidate.evidence)), supported[0]
        )
        citation_issues = verify_anchor_set(
            candidate.evidence,
            accepted=reference.evidence,
            documents=(source,),
        )
        issues.update(citation_issues)
        if citation_issues:
            continue
        claim = _claim(reference)
        identifier = obligation_id(
            run_id, source.identity.source_sha256, claim.statement, claim.evidence
        )
        record = VerifiedObligation(
            **claim.model_dump(),
            run_id=run_id,
            source_sha256=source.identity.source_sha256,
            obligation_id=identifier,
        )
        if identifier in records and records[identifier] != record:
            issues.add(VerificationIssue(code=IssueCode.IDENTIFIER_COLLISION, stage="obligations"))
        records[identifier] = record
    if issues:
        return ObligationVerification(result=_rejected(issues))
    ordered = tuple(records[key] for key in sorted(records))
    return ObligationVerification(
        result=VerificationResult(accepted=True, obligation_count=len(ordered)),
        output=VerifiedObligationSet(run_id=run_id, source=source.identity, obligations=ordered),
    )


def _canonical_corpus(corpus: CorpusSnapshot) -> CorpusSnapshot:
    records = tuple(
        record.model_copy(
            update={
                "evidence": sorted_anchors(record.evidence),
                "document": record.document.model_copy(
                    update={
                        "pages": tuple(sorted(record.document.pages, key=lambda p: p.page)),
                    }
                ),
            }
        )
        for record in sorted(corpus.records, key=lambda r: r.document.identity.doc_id)
    )
    impacts = tuple(
        sorted(
            (
                rule.model_copy(
                    update={
                        "obligation": _claim(rule.obligation),
                        "evidence": sorted_anchors(rule.evidence),
                    }
                )
                for rule in corpus.impacts
            ),
            key=canonical_bytes,
        )
    )
    return corpus.model_copy(update={"records": records, "impacts": impacts})


def corpus_digest(corpus: CorpusSnapshot) -> str:
    return sha256(canonical_bytes(_canonical_corpus(corpus))).hexdigest()


def _corpus_valid(
    source: SourceDocument,
    accepted: AcceptedEvidenceCatalog,
    corpus: CorpusSnapshot,
) -> bool:
    records = {record.document.identity.doc_id: record for record in corpus.records}
    if len(records) != len(corpus.records) or source.identity.doc_id in records:
        return False
    for record in records.values():
        if record.document.identity.doc_kind is DocumentKind.REGULATION or verify_anchor_set(
            record.evidence,
            accepted=record.evidence,
            documents=(record.document,),
        ):
            return False
    keys: set[tuple[AcceptedObligation, str, Relationship, str | None]] = set()
    for rule in corpus.impacts:
        target = records.get(rule.target_id)
        case = records.get(rule.affected_case_id) if rule.affected_case_id else None
        key = (_claim(rule.obligation), rule.target_id, rule.relationship, rule.affected_case_id)
        if (
            key in keys
            or target is None
            or _claim(rule.obligation) not in {_claim(o) for o in accepted.obligations}
            or (
                rule.affected_case_id is not None
                and (case is None or case.document.identity.doc_kind is not DocumentKind.CASE)
            )
            or (
                rule.target_clause is not None
                and target.document.identity.doc_kind is not DocumentKind.CONTRACT
            )
            or (
                rule.relationship is Relationship.NO_IMPACT
                and rule.verdict is not FindingVerdict.REFUTED
            )
        ):
            return False
        keys.add(key)
        permitted = set(rule.obligation.evidence) | set(target.evidence)
        if case:
            permitted.update(case.evidence)
        if (
            not set(rule.evidence) <= permitted
            or not set(rule.obligation.evidence) <= set(rule.evidence)
            or not set(rule.evidence).intersection(target.evidence)
            or (case is not None and not set(rule.evidence).intersection(case.evidence))
            or verify_anchor_set(
                rule.evidence,
                accepted=rule.evidence,
                documents=(
                    source,
                    *(record.document for record in records.values()),
                ),
            )
        ):
            return False
    return True


def _severity(
    relationship: Relationship,
    verdict: FindingVerdict,
    target_kind: DocumentKind,
    obligation_type: ObligationType,
) -> Severity:
    """synthetic-severity-v1: categorical, never derived from a model's score."""
    if relationship is Relationship.NO_IMPACT or verdict is FindingVerdict.REFUTED:
        return Severity.LOW
    if relationship is Relationship.CONFLICTS_WITH:
        return (
            Severity.HIGH
            if target_kind is DocumentKind.CONTRACT
            and obligation_type is ObligationType.PROHIBITION
            else Severity.MEDIUM
        )
    return Severity.LOW if target_kind is DocumentKind.CASE else Severity.MEDIUM


def _review(verdict: FindingVerdict, severity: Severity) -> bool:
    return verdict is FindingVerdict.UNCERTAIN or (
        verdict is FindingVerdict.SURVIVED and severity is Severity.HIGH
    )


def _finding_key(value: VerifiedFinding) -> tuple[str, str, str, str]:
    return (
        value.obligation.obligation_id,
        value.target_id,
        value.relationship.value,
        value.affected_case_id or "",
    )


class FindingVerifier:
    """No constructor capabilities and no persistence, network or action calls."""

    def verify(
        self,
        *,
        source: SourceDocument,
        accepted: AcceptedEvidenceCatalog,
        obligations: VerifiedObligationSet,
        corpus: CorpusSnapshot,
        candidates: InvestigatorDraftOutput,
    ) -> FindingVerification:
        try:
            source = SourceDocument.model_validate(source)
            accepted = AcceptedEvidenceCatalog.model_validate(accepted)
            obligations = VerifiedObligationSet.model_validate(obligations)
            corpus = CorpusSnapshot.model_validate(corpus)
            candidates = InvestigatorDraftOutput.model_validate(candidates)
        except ValidationError:
            return FindingVerification(result=_failure(IssueCode.INVALID_SCHEMA, finding=True))
        # Recheck provenance instead of accepting a 'Verified' class name as proof.
        checked = verify_obligations(
            run_id=obligations.run_id,
            source=source,
            accepted=accepted,
            candidates=AnalystDraftOutput(
                obligations=tuple(
                    CandidateObligation(**_claim(o).model_dump()) for o in obligations.obligations
                )
            ),
        )
        if checked.output != obligations:
            return FindingVerification(
                result=_failure(
                    IssueCode.MISSING_OBLIGATION_BINDING,
                    finding=True,
                )
            )
        if not _corpus_valid(source, accepted, corpus):
            return FindingVerification(result=_failure(IssueCode.INVALID_CATALOG, finding=True))
        verified = {o.obligation_id: o for o in obligations.obligations}
        targets = {r.document.identity.doc_id: r for r in corpus.records}
        documents = (source, *(r.document for r in corpus.records))
        issues: set[VerificationIssue] = set()
        records: dict[tuple[str, str, str, str], VerifiedFinding] = {}
        for candidate in candidates.findings:
            obligation = verified.get(candidate.obligation_id)
            if obligation is None:
                issues.add(
                    VerificationIssue(
                        code=IssueCode.MISSING_OBLIGATION_BINDING,
                        stage="findings",
                    )
                )
                continue
            if candidate.target_id not in targets or (
                candidate.affected_case_id is not None and candidate.affected_case_id not in targets
            ):
                issues.add(VerificationIssue(code=IssueCode.FOREIGN_TARGET, stage="findings"))
                continue
            rule = next(
                (
                    rule
                    for rule in corpus.impacts
                    if (
                        _claim(rule.obligation) == _claim(obligation)
                        and rule.target_id == candidate.target_id
                        and rule.target_clause == candidate.target_clause
                        and rule.relationship == candidate.relationship
                        and rule.affected_case_id == candidate.affected_case_id
                    )
                ),
                None,
            )
            if rule is None:
                issues.add(VerificationIssue(code=IssueCode.UNSUPPORTED_FINDING, stage="findings"))
                continue
            evidence_issues = verify_anchor_set(
                candidate.evidence,
                accepted=rule.evidence,
                documents=documents,
            )
            issues.update(evidence_issues)
            if evidence_issues:
                continue
            target_kind = targets[candidate.target_id].document.identity.doc_kind
            finding = self._record(candidate, rule, obligation, target_kind)
            key = _finding_key(finding)
            if key in records:
                finding = self._merge(records[key], finding, target_kind)
            records[key] = finding
        if issues:
            return FindingVerification(result=_rejected(issues))
        ordered = tuple(records[key] for key in sorted(records))
        return FindingVerification(
            result=VerificationResult(
                accepted=True,
                obligation_count=len(verified),
                finding_count=len(ordered),
            ),
            output=VerifiedWorkerOutput(
                run_id=obligations.run_id,
                source=source.identity,
                corpus_sha256=corpus_digest(corpus),
                obligations=obligations.obligations,
                findings=ordered,
            ),
        )

    @staticmethod
    def _record(
        candidate: CandidateFinding,
        rule: AcceptedImpact,
        obligation: VerifiedObligation,
        target_kind: DocumentKind,
    ) -> VerifiedFinding:
        strength = min(candidate.evidence_strength, rule.evidence_strength)
        confidence = min(candidate.interpretation_confidence, rule.interpretation_confidence)
        verdict = rule.verdict
        if candidate.verdict is not rule.verdict or (
            verdict is FindingVerdict.SURVIVED and min(strength, confidence) < SURVIVED_THRESHOLD
        ):
            verdict = FindingVerdict.UNCERTAIN
        severity = _severity(rule.relationship, verdict, target_kind, obligation.type)
        return VerifiedFinding(
            finding_id=finding_id(
                obligation.run_id,
                obligation.obligation_id,
                rule.target_id,
                rule.relationship,
                rule.affected_case_id,
            ),
            run_id=obligation.run_id,
            obligation=obligation,
            target_id=rule.target_id,
            target_clause=rule.target_clause,
            affected_case_id=rule.affected_case_id,
            relationship=rule.relationship,
            severity=severity,
            verdict=verdict,
            human_review_required=_review(verdict, severity),
            evidence=sorted_anchors(rule.evidence),
            evidence_strength=strength,
            interpretation_confidence=confidence,
        )

    @staticmethod
    def _merge(
        left: VerifiedFinding,
        right: VerifiedFinding,
        target_kind: DocumentKind,
    ) -> VerifiedFinding:
        verdict = left.verdict if left.verdict is right.verdict else FindingVerdict.UNCERTAIN
        severity = _severity(left.relationship, verdict, target_kind, left.obligation.type)
        return left.model_copy(
            update={
                "verdict": verdict,
                "severity": severity,
                "human_review_required": _review(verdict, severity),
                "evidence": sorted_anchors((*left.evidence, *right.evidence)),
                "evidence_strength": min(left.evidence_strength, right.evidence_strength),
                "interpretation_confidence": min(
                    left.interpretation_confidence, right.interpretation_confidence
                ),
            }
        )


def duplicate_source_completion(
    *,
    run_id: str,
    source: ImmutableSourceIdentity,
    prior: PreviouslyVerifiedSource,
) -> DuplicateSourceCompletion:
    """Plan an empty completion only for a separately verified identical source.

    The caller must obtain prior from an authoritative successful checkpoint,
    not intake's hash index. This helper never calls analysts or writes state.
    """
    try:
        TypeAdapter(Identifier).validate_python(run_id)
        source = ImmutableSourceIdentity.model_validate(source)
        prior = PreviouslyVerifiedSource.model_validate(prior)
    except ValidationError:
        raise ValueError("SOURCE_BINDING_MISMATCH") from None
    if (
        run_id == prior.run_id
        or source.doc_kind is not DocumentKind.REGULATION
        or prior.source.doc_kind is not DocumentKind.REGULATION
        or source.page_count != prior.source.page_count
        or not compare_digest(source.source_sha256, prior.source.source_sha256)
    ):
        raise ValueError("SOURCE_BINDING_MISMATCH")
    return DuplicateSourceCompletion(run_id=run_id, source_sha256=source.source_sha256)
