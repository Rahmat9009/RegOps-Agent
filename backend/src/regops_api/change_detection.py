"""Deterministic SHA-256 document change classification."""

from __future__ import annotations

from hashlib import sha256

from regops_api.domain_models import ChangeClassification, DetectionResult
from regops_api.repositories import RegulationRepository


class Sha256ChangeDetector:
    def __init__(self, regulations: RegulationRepository) -> None:
        self._regulations = regulations

    def detect(self, *, source_filename: str, content: bytes) -> DetectionResult:
        digest = sha256(content).hexdigest()
        duplicate = self._regulations.find_regulation_by_hash(digest)
        source_versions = self._regulations.list_regulations_by_source(source_filename)
        if duplicate is not None:
            return DetectionResult(
                classification=ChangeClassification.DUPLICATE,
                sha256=digest,
                previous_regulation_id=duplicate.regulation.reg_id,
                next_version=duplicate.version,
            )
        if source_versions:
            latest = source_versions[-1]
            return DetectionResult(
                classification=ChangeClassification.REVISED,
                sha256=digest,
                previous_regulation_id=latest.regulation.reg_id,
                next_version=latest.version + 1,
            )
        return DetectionResult(
            classification=ChangeClassification.NEW,
            sha256=digest,
            next_version=1,
        )
