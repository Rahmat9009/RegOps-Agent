"""Immutable, package-owned synthetic corpus and five exact-ID read tools.

The investigator receives closures over this already validated snapshot.  It
never receives a path, repository, network client, query language, or mutable
storage handle.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
from importlib.resources import files
from types import MappingProxyType
from typing import Annotated, Any, Literal, Self

from pydantic import Field, ValidationError, model_validator

from regops_api.schemas import DocumentKind
from regops_api.worker_models import (
    CorpusRecord,
    CorpusSnapshot,
    Digest,
    Identifier,
    SafeText,
    WorkerModel,
)

CORPUS_MANIFEST_VERSION: Literal["synthetic-corpus-manifest-v1"] = (
    "synthetic-corpus-manifest-v1"
)
CORPUS_TOOL_SCHEMA_VERSION: Literal["investigator-tools-v1"] = "investigator-tools-v1"
INTERNAL_FEE_POLICY_ID = "syn-policy-fees-001"
EXPECTED_RECORD_IDS = frozenset(
    {
        "syn-contract-worker-001",
        "syn-case-fee-001",
        INTERNAL_FEE_POLICY_ID,
        "syn-contract-worker-002",
        "syn-case-fee-002",
    }
)

ClauseIds = Annotated[tuple[Identifier, ...], Field(max_length=20)]
Facts = Annotated[tuple[SafeText, ...], Field(min_length=1, max_length=20)]


class CorpusEntry(WorkerModel):
    record_id: Identifier
    summary: Annotated[SafeText, Field(min_length=1, max_length=500)]
    clause_ids: ClauseIds = ()
    facts: Facts


class SyntheticCorpusManifest(WorkerModel):
    manifest_version: Literal["synthetic-corpus-manifest-v1"]
    canonical_sha256: Digest
    snapshot: CorpusSnapshot
    entries: Annotated[tuple[CorpusEntry, ...], Field(min_length=1, max_length=500)]
    synthetic: Literal[True]

    @model_validator(mode="after")
    def complete_and_bound(self) -> Self:
        records = {record.document.identity.doc_id: record for record in self.snapshot.records}
        entries = {entry.record_id: entry for entry in self.entries}
        if (
            set(records) != EXPECTED_RECORD_IDS
            or set(entries) != EXPECTED_RECORD_IDS
            or len(records) != len(self.snapshot.records)
            or len(entries) != len(self.entries)
            or self.snapshot.impacts
        ):
            raise ValueError("CORPUS_MANIFEST_INVALID")
        for record_id, record in records.items():
            identity = record.document.identity
            entry = entries[record_id]
            page_text = "".join(page.text for page in record.document.pages).encode("utf-8")
            if not compare_digest(sha256(page_text).hexdigest(), identity.source_sha256):
                raise ValueError("CORPUS_SOURCE_DIGEST_MISMATCH")
            pages = {page.page: page.text for page in record.document.pages}
            if any(
                anchor.doc_id != record_id
                or anchor.doc_kind is not identity.doc_kind
                or not compare_digest(anchor.source_sha256, identity.source_sha256)
                or anchor.quote not in pages.get(anchor.page, "")
                for anchor in record.evidence
            ):
                raise ValueError("CORPUS_EVIDENCE_INVALID")
            if (identity.doc_kind is DocumentKind.CONTRACT) != bool(entry.clause_ids):
                raise ValueError("CORPUS_METADATA_INVALID")
        return self


def _manifest_material(manifest: SyntheticCorpusManifest) -> bytes:
    material = manifest.model_dump(mode="json", exclude={"canonical_sha256"})
    return json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def manifest_digest(manifest: SyntheticCorpusManifest) -> str:
    return sha256(_manifest_material(manifest)).hexdigest()


@dataclass(frozen=True, slots=True)
class ImmutableSyntheticCorpus:
    """Validated immutable view used by tools and the deterministic verifier."""

    manifest: SyntheticCorpusManifest
    _records: MappingProxyType[str, CorpusRecord]
    _entries: MappingProxyType[str, CorpusEntry]

    @classmethod
    def from_manifest(cls, manifest: SyntheticCorpusManifest) -> ImmutableSyntheticCorpus:
        manifest = SyntheticCorpusManifest.model_validate(manifest)
        if not compare_digest(manifest_digest(manifest), manifest.canonical_sha256):
            raise ValueError("CORPUS_MANIFEST_DIGEST_MISMATCH")
        return cls(
            manifest=manifest,
            _records=MappingProxyType(
                {
                    record.document.identity.doc_id: record
                    for record in manifest.snapshot.records
                }
            ),
            _entries=MappingProxyType({entry.record_id: entry for entry in manifest.entries}),
        )

    @property
    def snapshot(self) -> CorpusSnapshot:
        return self.manifest.snapshot

    @property
    def canonical_sha256(self) -> str:
        return self.manifest.canonical_sha256

    def list_records(self) -> tuple[CorpusRecord, ...]:
        return tuple(self._records[key] for key in sorted(self._records))

    def get_record(self, target_id: str) -> CorpusRecord | None:
        return self._records.get(target_id)

    def get_entry(self, target_id: str) -> CorpusEntry | None:
        return self._entries.get(target_id)


def load_synthetic_corpus() -> ImmutableSyntheticCorpus:
    """Load only the package-owned manifest; callers cannot select a path."""
    try:
        content = (
            files("regops_api")
            .joinpath("synthetic_corpus/manifest.json")
            .read_text(encoding="utf-8")
        )
        manifest = SyntheticCorpusManifest.model_validate_json(content)
        return ImmutableSyntheticCorpus.from_manifest(manifest)
    except (OSError, UnicodeError, ValueError, ValidationError):
        raise ValueError("CORPUS_MANIFEST_INVALID") from None


def _evidence(record: CorpusRecord) -> list[dict[str, Any]]:
    return [anchor.model_dump(mode="json") for anchor in record.evidence]


class InvestigatorCorpusTools:
    """The entire model-callable corpus capability surface: exactly five reads."""

    __slots__ = ("_corpus",)

    def __init__(self, corpus: ImmutableSyntheticCorpus) -> None:
        self._corpus = corpus

    def list_contract_summaries(self) -> dict[str, Any]:
        """List synthetic contract IDs, titles, summaries, and available clause IDs."""
        contracts = []
        for record in self._corpus.list_records():
            if record.document.identity.doc_kind is not DocumentKind.CONTRACT:
                continue
            entry = self._corpus.get_entry(record.document.identity.doc_id)
            assert entry is not None
            contracts.append(
                {
                    "contract_id": entry.record_id,
                    "title": record.title,
                    "summary": entry.summary,
                    "synthetic": True,
                    "clause_ids": list(entry.clause_ids),
                }
            )
        return {"status": "success", "contracts": contracts}

    def get_contract_clause(self, contract_id: str, clause_id: str) -> dict[str, Any]:
        """Get one exact clause from one known synthetic contract."""
        record = self._corpus.get_record(contract_id)
        entry = self._corpus.get_entry(contract_id)
        if (
            record is None
            or entry is None
            or record.document.identity.doc_kind is not DocumentKind.CONTRACT
            or clause_id not in entry.clause_ids
        ):
            return {"status": "error", "code": "UNKNOWN_CONTRACT_CLAUSE"}
        return {
            "status": "success",
            "synthetic": True,
            "label": record.title,
            "contract_id": contract_id,
            "clause_id": clause_id,
            "evidence": _evidence(record),
        }

    def list_case_summaries(self) -> dict[str, Any]:
        """List bounded summaries for the known synthetic cases."""
        cases = []
        for record in self._corpus.list_records():
            if record.document.identity.doc_kind is not DocumentKind.CASE:
                continue
            entry = self._corpus.get_entry(record.document.identity.doc_id)
            assert entry is not None
            cases.append(
                {
                    "case_id": entry.record_id,
                    "title": record.title,
                    "summary": entry.summary,
                    "synthetic": True,
                }
            )
        return {"status": "success", "cases": cases}

    def get_case_evidence(self, case_id: str) -> dict[str, Any]:
        """Get bounded facts and exact evidence for one known synthetic case."""
        record = self._corpus.get_record(case_id)
        entry = self._corpus.get_entry(case_id)
        if (
            record is None
            or entry is None
            or record.document.identity.doc_kind is not DocumentKind.CASE
        ):
            return {"status": "error", "code": "UNKNOWN_CASE"}
        return {
            "status": "success",
            "synthetic": True,
            "label": record.title,
            "case_id": case_id,
            "facts": list(entry.facts),
            "evidence": _evidence(record),
        }

    def get_internal_fee_policy(self, policy_id: str) -> dict[str, Any]:
        """Get the one fixed synthetic internal fee policy and its exact evidence."""
        if policy_id != INTERNAL_FEE_POLICY_ID:
            return {"status": "error", "code": "UNKNOWN_POLICY"}
        record = self._corpus.get_record(policy_id)
        entry = self._corpus.get_entry(policy_id)
        if record is None or entry is None:
            return {"status": "error", "code": "UNKNOWN_POLICY"}
        return {
            "status": "success",
            "synthetic": True,
            "label": record.title,
            "policy_id": policy_id,
            "policy_text": list(entry.facts),
            "evidence": _evidence(record),
        }


TOOL_NAMES = (
    "list_contract_summaries",
    "get_contract_clause",
    "list_case_summaries",
    "get_case_evidence",
    "get_internal_fee_policy",
)


def tool_functions(corpus: ImmutableSyntheticCorpus) -> tuple[Any, ...]:
    """Return a stable allowlist; no generic registration or discovery occurs."""
    tools = InvestigatorCorpusTools(corpus)
    return tuple(getattr(tools, name) for name in TOOL_NAMES)
