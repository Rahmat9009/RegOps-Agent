"""Default tests cannot reach a network or discover cloud credentials."""

import os
import socket
from contextvars import ContextVar
from typing import Any

import google.auth
import pytest


@pytest.fixture(autouse=True)
def offline_by_default(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    live_gemini_enabled = any(
        os.getenv(name) == "1"
        for name in (
            "REGOPS_LIVE_GEMINI",
            "REGOPS_LIVE_GEMINI_DIAGNOSTIC",
            "REGOPS_LIVE_GEMINI_ARMOR_DIAGNOSTIC",
            "REGOPS_LIVE_OBLIGATION_DIAGNOSTIC",
            "REGOPS_LIVE_DETECTION_DIAGNOSTIC",
        )
    )
    if request.node.get_closest_marker("live_gemini") and live_gemini_enabled:
        return
    if request.node.get_closest_marker("firestore_emulator") and os.getenv(
        "FIRESTORE_EMULATOR_HOST"
    ):
        return

    def blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("DEFAULT_TEST_NETWORK_OR_ADC_FORBIDDEN")

    # Windows implements socketpair with a loopback connection. Permit only that
    # synchronous stdlib operation, not arbitrary loopback or external requests.
    in_socketpair: ContextVar[bool] = ContextVar("offline_socketpair", default=False)
    original_connect = socket.socket.connect
    original_socketpair = socket.socketpair

    def connect(sock: socket.socket, address: Any) -> None:
        if in_socketpair.get() and isinstance(address, tuple) and address[0] in {
            "127.0.0.1",
            "::1",
        }:
            original_connect(sock, address)
            return
        blocked()

    def socketpair(
        family: int | None = None, type: int = socket.SOCK_STREAM, proto: int = 0
    ) -> tuple[socket.socket, socket.socket]:
        token = in_socketpair.set(True)
        try:
            if family is None:
                return original_socketpair(type=type, proto=proto)
            return original_socketpair(family, type, proto)
        finally:
            in_socketpair.reset(token)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "socketpair", socketpair)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(google.auth, "default", blocked)
