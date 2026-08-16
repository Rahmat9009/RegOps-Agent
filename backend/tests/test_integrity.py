from __future__ import annotations

from hashlib import sha256
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def normalized_sha256(path: Path) -> str:
    return sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def test_frozen_contract_integrity() -> None:
    assert normalized_sha256(REPOSITORY_ROOT / "contracts" / "openapi.yaml") == (
        "5ed1eb8c795dba8ba0a8f77c9501c871a45c3402472c8100a4ec8ff6794d7904"
    )
    assert normalized_sha256(REPOSITORY_ROOT / "contracts" / "run-states.md") == (
        "6ef855cc15857c0b009cd32e91bfd1b33a1f39a08c4211d2e9ca9b48df7ae2ee"
    )
