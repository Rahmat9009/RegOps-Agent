from datetime import timedelta
from hashlib import sha256

from regops_api.change_detection import Sha256ChangeDetector
from regops_api.domain_models import ChangeClassification, RegulationRecord
from regops_api.in_memory import InMemoryRepositories
from tests.factories import NOW, make_regulation


def test_sha256_change_detection_is_deterministic() -> None:
    repositories = InMemoryRepositories.for_tests()
    detector = Sha256ChangeDetector(repositories)
    content = b"synthetic regulation v1"

    first = detector.detect(source_filename="rule.pdf", content=content)
    second = detector.detect(source_filename="rule.pdf", content=content)

    assert first == second
    assert first.classification is ChangeClassification.NEW
    assert first.sha256 == sha256(content).hexdigest()


def test_change_detector_classifies_duplicate_and_revision() -> None:
    repositories = InMemoryRepositories.for_tests()
    original = b"synthetic regulation v1"
    repositories.add_regulation(
        RegulationRecord(
            regulation=make_regulation(),
            content_sha256=sha256(original).hexdigest(),
            version=1,
            created_at=NOW,
        )
    )
    repositories.add_regulation(
        RegulationRecord(
            regulation=make_regulation("reg-2"),
            content_sha256=sha256(b"synthetic regulation v2").hexdigest(),
            version=2,
            supersedes_regulation_id="reg-1",
            created_at=NOW + timedelta(days=1),
        )
    )
    detector = Sha256ChangeDetector(repositories)

    duplicate = detector.detect(source_filename="renamed.pdf", content=original)
    revised = detector.detect(
        source_filename="rule.pdf", content=b"synthetic regulation v3"
    )

    assert duplicate.classification is ChangeClassification.DUPLICATE
    assert duplicate.previous_regulation_id == "reg-1"
    assert revised.classification is ChangeClassification.REVISED
    assert revised.previous_regulation_id == "reg-2"
    assert revised.next_version == 3
