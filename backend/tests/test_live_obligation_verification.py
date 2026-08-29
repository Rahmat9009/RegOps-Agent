"""Opt-in, content-free live diagnosis of minimum-slice obligation verification."""

from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256

import pytest
from google.cloud import modelarmor_v1

from regops_api.adapter_logging import sensitive_io
from regops_api.analyst_errors import AnalystError
from regops_api.analyst_settings import AnalystSettings
from regops_api.config import RuntimeMode, RuntimeSettings
from regops_api.evidence import canonicalize_safe_text, locator_text
from regops_api.gemini_analyst import GeminiRegulationAnalyst, build_demo_analyst
from regops_api.live_fixture import KNOWN_SOURCE_SHA256, load_minimum_live_fixture
from regops_api.pdf_reader import parse_pdf
from regops_api.verification import verify_obligations
from regops_api.worker_models import (
    AcceptedObligation,
    AnalystDraftOutput,
    CandidateObligation,
)
from tests.test_pdf_reader import SAMPLE

_ENABLED = os.getenv("REGOPS_LIVE_OBLIGATION_DIAGNOSTIC") == "1"
_CATEGORIES = (
    "statement",
    "obligation_type",
    "exceptions",
    "effective_date",
    "evidence_document",
    "evidence_page",
    "evidence_quotation",
    "evidence_set_cardinality",
)


@dataclass(frozen=True)
class _SafeSummary:
    candidate_count: int
    accepted_count: int
    issues: tuple[tuple[str, int], ...]
    mismatches: tuple[tuple[str, int], ...]
    unique_evidence_true: int
    unique_evidence_false: int


def _template_location(template: str, project: str, name: str) -> str:
    match = re.fullmatch(
        rf"projects/{re.escape(project)}/locations/([a-z][a-z0-9-]{{1,62}})/"
        rf"templates/{re.escape(name)}",
        template,
    )
    if match is None:
        raise ValueError("INVALID_ARMOR_TEMPLATE_RESOURCE")
    return match.group(1)


def _evidence_key(value: CandidateObligation | AcceptedObligation) -> tuple[object, ...]:
    return tuple(
        sorted(
            (
                anchor.doc_id,
                anchor.doc_kind.value,
                anchor.source_sha256,
                anchor.page,
                locator_text(anchor.quote),
            )
            for anchor in value.evidence
        )
    )


def _mismatch_categories(
    candidate: CandidateObligation,
    accepted: AcceptedObligation,
) -> frozenset[str]:
    categories: set[str] = set()
    if canonicalize_safe_text(candidate.statement) != canonicalize_safe_text(
        accepted.statement
    ):
        categories.add("statement")
    if candidate.type is not accepted.type:
        categories.add("obligation_type")
    if tuple(sorted(map(canonicalize_safe_text, candidate.exceptions))) != tuple(
        sorted(map(canonicalize_safe_text, accepted.exceptions))
    ):
        categories.add("exceptions")
    if candidate.effective_date != accepted.effective_date:
        categories.add("effective_date")
    candidate_documents = sorted(
        (anchor.doc_id, anchor.doc_kind.value, anchor.source_sha256)
        for anchor in candidate.evidence
    )
    accepted_documents = sorted(
        (anchor.doc_id, anchor.doc_kind.value, anchor.source_sha256)
        for anchor in accepted.evidence
    )
    if candidate_documents != accepted_documents:
        categories.add("evidence_document")
    if sorted(anchor.page for anchor in candidate.evidence) != sorted(
        anchor.page for anchor in accepted.evidence
    ):
        categories.add("evidence_page")
    if sorted(locator_text(anchor.quote) for anchor in candidate.evidence) != sorted(
        locator_text(anchor.quote) for anchor in accepted.evidence
    ):
        categories.add("evidence_quotation")
    if len(candidate.evidence) != len(accepted.evidence):
        categories.add("evidence_set_cardinality")
    return frozenset(categories)


def _safe_summary(
    candidates: tuple[CandidateObligation, ...],
    accepted: tuple[AcceptedObligation, ...],
    issue_codes: tuple[str, ...],
) -> _SafeSummary:
    mismatch_counts: Counter[str] = Counter()
    unique_true = 0
    for candidate in candidates:
        evidence_matches = [
            item for item in accepted if _evidence_key(candidate) == _evidence_key(item)
        ]
        if len(evidence_matches) == 1:
            unique_true += 1
            reference = evidence_matches[0]
        else:
            reference = min(
                accepted,
                key=lambda item: (
                    len(_mismatch_categories(candidate, item)),
                    _evidence_key(item),
                ),
            )
        mismatch_counts.update(_mismatch_categories(candidate, reference))
    return _SafeSummary(
        candidate_count=len(candidates),
        accepted_count=len(accepted),
        issues=tuple(sorted(Counter(issue_codes).items())),
        mismatches=tuple((category, mismatch_counts[category]) for category in _CATEGORIES),
        unique_evidence_true=unique_true,
        unique_evidence_false=len(candidates) - unique_true,
    )


def _run_live(project: str, gemini_location: str) -> tuple[_SafeSummary | None, str]:
    summary: _SafeSummary | None = None
    failure = "LIVE_OBLIGATION_DIAGNOSTIC_FAILED"
    with sensitive_io():
        discovery: modelarmor_v1.ModelArmorClient | None = None
        analyst: GeminiRegulationAnalyst | None = None
        candidates: AnalystDraftOutput | None = None
        try:
            discovery = modelarmor_v1.ModelArmorClient()
            names: dict[str, list[str]] = {
                "regops-input": [],
                "regops-output": [],
            }
            for template in discovery.list_templates(
                parent=f"projects/{project}/locations/-",
                retry=None,
                timeout=20,
            ):
                for name in names:
                    if template.name.endswith(f"/templates/{name}"):
                        names[name].append(template.name)
            if any(len(matches) != 1 for matches in names.values()):
                failure = "REGOPS_ARMOR_TEMPLATES_NOT_UNIQUE"
                raise RuntimeError
            input_template = names["regops-input"][0]
            output_template = names["regops-output"][0]
            input_location = _template_location(input_template, project, "regops-input")
            output_location = _template_location(output_template, project, "regops-output")
            if input_location != output_location:
                failure = "REGOPS_ARMOR_TEMPLATE_LOCATIONS_DIFFER"
                raise RuntimeError
            content = SAMPLE.read_bytes()
            if sha256(content).hexdigest() != KNOWN_SOURCE_SHA256:
                failure = "TRACKED_SYNTHETIC_SOURCE_MISMATCH"
                raise RuntimeError
            fixture = load_minimum_live_fixture(KNOWN_SOURCE_SHA256)
            settings = AnalystSettings(
                armor_input_template=input_template,
                armor_output_template=output_template,
            )
            runtime = RuntimeSettings(
                mode=RuntimeMode.DEMO,
                project_id=project,
                armor_location=input_location,
                gemini_location=gemini_location,
            )
            source = parse_pdf(
                content=content,
                doc_id=fixture.source_doc_id,
                source_sha256=KNOWN_SOURCE_SHA256,
                limits=settings.pdf,
            )
            analyst = build_demo_analyst(content=content, runtime=runtime, settings=settings)
            candidates = analyst.analyze(source=source)
            accepted = fixture.accepted_catalog(source)
            result = verify_obligations(
                run_id="live-obligation-diagnostic",
                source=source,
                accepted=accepted,
                candidates=candidates,
            )
            summary = _safe_summary(
                candidates.obligations,
                accepted.obligations,
                tuple(issue.code.value for issue in result.result.issues),
            )
        except AnalystError as error:
            failure = error.code.value
        except Exception:
            pass
        finally:
            if analyst is not None:
                analyst.close()
            if candidates is not None:
                del candidates
            if discovery is not None:
                discovery.transport.close()  # type: ignore[no-untyped-call]
    return summary, failure


@pytest.mark.live_gemini
@pytest.mark.skipif(not _ENABLED, reason="live obligation diagnostic explicitly disabled")
def test_live_minimum_slice_reports_only_safe_verification_categories() -> None:
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    gemini_location = os.getenv("REGOPS_GEMINI_LOCATION") or os.getenv("REGOPS_REGION")
    if not project or not gemini_location:
        pytest.skip("explicit Gemini project/location configuration is incomplete")
    if os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"):
        pytest.fail("ADC_REQUIRED", pytrace=False)

    summary, failure = _run_live(project, gemini_location)
    if summary is None:
        pytest.fail(failure, pytrace=False)
    print(f"LIVE_OBLIGATION CANDIDATES={summary.candidate_count}")
    print(f"LIVE_OBLIGATION ACCEPTED={summary.accepted_count}")
    for code, count in summary.issues:
        print(f"LIVE_OBLIGATION ISSUE_{code}={count}")
    for category, count in summary.mismatches:
        print(f"LIVE_OBLIGATION MISMATCH_{category.upper()}={count}")
    print(f"LIVE_OBLIGATION UNIQUE_EVIDENCE_TRUE={summary.unique_evidence_true}")
    print(f"LIVE_OBLIGATION UNIQUE_EVIDENCE_FALSE={summary.unique_evidence_false}")
