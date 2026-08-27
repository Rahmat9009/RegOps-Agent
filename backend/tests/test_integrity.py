from __future__ import annotations

import socket
from hashlib import sha256
from pathlib import Path

import google.auth
import pytest

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


def test_dependency_locks_share_runtime_pins_and_match_direct_requirements() -> None:
    import tomllib

    backend = REPOSITORY_ROOT / "backend"
    runtime = set((backend / "requirements-runtime.lock").read_text().splitlines())
    dev = set((backend / "requirements-dev.lock").read_text().splitlines())
    project = tomllib.loads((backend / "pyproject.toml").read_text())["project"]
    assert runtime <= dev
    assert set(project["dependencies"]) <= runtime
    assert set(project["optional-dependencies"]["dev"]) <= dev


def test_offline_guard_allows_internal_socketpair_but_not_network_or_adc() -> None:
    reader, writer = socket.socketpair()
    with reader, writer:
        writer.sendall(b"local-ipc")
        assert reader.recv(9) == b"local-ipc"
    for address in [("192.0.2.1", 443), ("127.0.0.1", 443)]:
        with socket.socket() as sock, pytest.raises(
            AssertionError, match="DEFAULT_TEST_NETWORK_OR_ADC_FORBIDDEN"
        ):
            sock.connect(address)
    with pytest.raises(AssertionError, match="DEFAULT_TEST_NETWORK_OR_ADC_FORBIDDEN"):
        google.auth.default()
