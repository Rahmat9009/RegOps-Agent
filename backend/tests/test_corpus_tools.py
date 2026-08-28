from __future__ import annotations

import inspect
from hashlib import sha256

import pytest
from pydantic import ValidationError

from regops_api.corpus import (
    CORPUS_MANIFEST_VERSION,
    CORPUS_TOOL_SCHEMA_VERSION,
    EXPECTED_RECORD_IDS,
    INTERNAL_FEE_POLICY_ID,
    TOOL_NAMES,
    ImmutableSyntheticCorpus,
    InvestigatorCorpusTools,
    load_synthetic_corpus,
    manifest_digest,
    tool_functions,
)
from regops_api.schemas import DocumentKind


@pytest.fixture
def corpus() -> ImmutableSyntheticCorpus:
    return load_synthetic_corpus()


def test_checked_in_manifest_is_complete_canonical_and_immutable(
    corpus: ImmutableSyntheticCorpus,
) -> None:
    assert corpus.manifest.manifest_version == CORPUS_MANIFEST_VERSION
    assert corpus.manifest.snapshot.schema_version == "worker-corpus-v1"
    assert corpus.canonical_sha256 == manifest_digest(corpus.manifest)
    assert {record.document.identity.doc_id for record in corpus.list_records()} == (
        EXPECTED_RECORD_IDS
    )
    assert corpus.snapshot.impacts == ()
    for record in corpus.list_records():
        text = "".join(page.text for page in record.document.pages)
        assert sha256(text.encode()).hexdigest() == record.document.identity.source_sha256
        assert record.title.startswith("SYNTHETIC DEMO ")
        assert record.document.identity.synthetic is True
        for anchor in record.evidence:
            assert anchor.quote in record.document.pages[anchor.page - 1].text
    with pytest.raises(ValidationError, match="frozen"):
        corpus.snapshot.synthetic = False  # type: ignore[assignment]


def test_manifest_digest_or_record_tampering_fails_closed(
    corpus: ImmutableSyntheticCorpus,
) -> None:
    bad_digest = corpus.manifest.model_copy(update={"canonical_sha256": "f" * 64})
    with pytest.raises(ValueError, match="CORPUS_MANIFEST_DIGEST_MISMATCH"):
        ImmutableSyntheticCorpus.from_manifest(bad_digest)

    record = corpus.snapshot.records[0]
    page = record.document.pages[0].model_copy(update={"text": "SYNTHETIC DEMO changed"})
    document = record.document.model_copy(update={"pages": (page,)})
    changed = record.model_copy(update={"document": document})
    snapshot = corpus.snapshot.model_copy(
        update={"records": (changed, *corpus.snapshot.records[1:])}
    )
    manifest = corpus.manifest.model_copy(update={"snapshot": snapshot})
    with pytest.raises(ValidationError, match="CORPUS_SOURCE_DIGEST_MISMATCH"):
        ImmutableSyntheticCorpus.from_manifest(manifest)


def test_tool_allowlist_and_signatures_are_exact(corpus: ImmutableSyntheticCorpus) -> None:
    functions = tool_functions(corpus)
    assert CORPUS_TOOL_SCHEMA_VERSION == "investigator-tools-v1"
    assert tuple(function.__name__ for function in functions) == TOOL_NAMES
    assert [tuple(inspect.signature(function).parameters) for function in functions] == [
        (),
        ("contract_id", "clause_id"),
        (),
        ("case_id",),
        ("policy_id",),
    ]
    assert not any(
        name in inspect.signature(function).parameters
        for function in functions
        for name in (
            "path",
            "uri",
            "query",
            "prompt",
            "collection",
            "repository",
            "firestore",
            "action_controller",
            "approval",
        )
    )


def test_contract_tools_return_only_bounded_synthetic_records(
    corpus: ImmutableSyntheticCorpus,
) -> None:
    tools = InvestigatorCorpusTools(corpus)
    listed = tools.list_contract_summaries()
    assert listed["status"] == "success"
    assert [item["contract_id"] for item in listed["contracts"]] == [
        "syn-contract-worker-001",
        "syn-contract-worker-002",
    ]
    assert all(item["synthetic"] is True for item in listed["contracts"])
    assert all(item["clause_ids"] == ["placement-fee"] for item in listed["contracts"])

    clause = tools.get_contract_clause("syn-contract-worker-001", "placement-fee")
    assert clause["status"] == "success"
    assert clause["synthetic"] is True
    assert clause["evidence"][0]["doc_kind"] == "contract"
    assert "page" in clause["evidence"][0] and "quote" in clause["evidence"][0]
    assert "pages" not in clause and "document" not in clause


@pytest.mark.parametrize(
    ("method", "args", "code"),
    [
        ("get_contract_clause", ("unknown", "placement-fee"), "UNKNOWN_CONTRACT_CLAUSE"),
        (
            "get_contract_clause",
            ("syn-contract-worker-001", "unknown"),
            "UNKNOWN_CONTRACT_CLAUSE",
        ),
        ("get_case_evidence", ("unknown",), "UNKNOWN_CASE"),
        ("get_internal_fee_policy", ("unknown",), "UNKNOWN_POLICY"),
    ],
)
def test_unknown_ids_fail_closed_without_echo(
    corpus: ImmutableSyntheticCorpus,
    method: str,
    args: tuple[str, ...],
    code: str,
) -> None:
    result = getattr(InvestigatorCorpusTools(corpus), method)(*args)
    assert result == {"status": "error", "code": code}
    assert not any(value in str(result) for value in args)


def test_case_and_policy_tools_are_exact_id_reads(corpus: ImmutableSyntheticCorpus) -> None:
    tools = InvestigatorCorpusTools(corpus)
    cases = tools.list_case_summaries()
    assert [item["case_id"] for item in cases["cases"]] == [
        "syn-case-fee-001",
        "syn-case-fee-002",
    ]
    case = tools.get_case_evidence("syn-case-fee-001")
    assert case["status"] == "success" and case["synthetic"] is True
    assert case["evidence"][0]["doc_kind"] == "case"
    policy = tools.get_internal_fee_policy(INTERNAL_FEE_POLICY_ID)
    assert policy["status"] == "success" and policy["synthetic"] is True
    assert policy["policy_id"] == INTERNAL_FEE_POLICY_ID
    assert policy["evidence"][0]["doc_kind"] == "policy"


def test_tool_results_are_copies_and_no_generic_query_surface_exists(
    corpus: ImmutableSyntheticCorpus,
) -> None:
    tools = InvestigatorCorpusTools(corpus)
    first = tools.list_contract_summaries()
    first["contracts"][0]["title"] = "changed"
    assert tools.list_contract_summaries()["contracts"][0]["title"].startswith(
        "SYNTHETIC DEMO"
    )
    with pytest.raises(TypeError):
        tools.list_contract_summaries("search all")  # type: ignore[call-arg]
    assert not hasattr(tools, "search")
    assert not hasattr(tools, "write")
    assert not hasattr(tools, "get_record")


def test_record_kinds_match_the_fixed_tool_partition(corpus: ImmutableSyntheticCorpus) -> None:
    kinds = {
        record.document.identity.doc_id: record.document.identity.doc_kind
        for record in corpus.list_records()
    }
    assert list(kinds.values()).count(DocumentKind.CONTRACT) == 2
    assert list(kinds.values()).count(DocumentKind.CASE) == 2
    assert list(kinds.values()).count(DocumentKind.POLICY) == 1
