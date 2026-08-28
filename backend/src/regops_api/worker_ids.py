"""Versioned UUIDv5 identifiers from verified canonical material only."""

from __future__ import annotations

import json
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, TypeAdapter

from regops_api.evidence import anchor_key, canonicalize_safe_text, sorted_anchors
from regops_api.schemas import Relationship
from regops_api.worker_models import Digest, EvidenceAnchor, Identifier, ResourceId

_NAMESPACE = uuid5(NAMESPACE_URL, "regops:worker:v1")


def canonical_bytes(value: BaseModel) -> bytes:
    """Serialize canonical verifier outputs, not unordered candidate collections."""
    return json.dumps(
        value.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _derive(kind: str, *parts: str) -> str:
    if any("\x00" in part for part in parts):
        raise ValueError("INVALID_IDENTIFIER_MATERIAL")
    return str(uuid5(_NAMESPACE, "\x00".join((kind, *parts))))


def obligation_id(
    run_id: str,
    source_sha256: str,
    statement: str,
    evidence: tuple[EvidenceAnchor, ...],
) -> str:
    TypeAdapter(Identifier).validate_python(run_id)
    TypeAdapter(Digest).validate_python(source_sha256)
    anchors = tuple(
        json.dumps(anchor_key(a), ensure_ascii=False, separators=(",", ":"))
        for a in sorted_anchors(evidence)
    )
    return _derive("obligation", run_id, source_sha256, canonicalize_safe_text(statement), *anchors)


def finding_id(
    run_id: str,
    obligation_id: str,
    target_id: str,
    relationship: Relationship,
    affected_case_id: str | None,
) -> str:
    for value in (run_id, target_id, *(() if affected_case_id is None else (affected_case_id,))):
        TypeAdapter(Identifier).validate_python(value)
    TypeAdapter(ResourceId).validate_python(obligation_id)
    return _derive(
        "finding", run_id, obligation_id, target_id, relationship.value, affected_case_id or ""
    )


def stage_output_id(run_id: str, stage: str, input_digest: str, schema_version: str) -> str:
    for value in (run_id, stage, schema_version):
        TypeAdapter(Identifier).validate_python(value)
    TypeAdapter(Digest).validate_python(input_digest)
    return _derive("stage", run_id, stage, input_digest, schema_version)


def audit_event_id(run_id: str, checkpoint_sequence: int, event_type: str, attempt: int) -> str:
    for value in (run_id, event_type):
        TypeAdapter(Identifier).validate_python(value)
    if type(checkpoint_sequence) is not int or type(attempt) is not int:
        raise ValueError("INVALID_IDENTIFIER_MATERIAL")
    if checkpoint_sequence < 0 or attempt < 1:
        raise ValueError("INVALID_IDENTIFIER_MATERIAL")
    return _derive("audit", run_id, str(checkpoint_sequence), event_type, str(attempt))
