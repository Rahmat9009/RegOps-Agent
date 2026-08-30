"""OIDC authentication for private Workflow-owned HTTP entrypoints."""

from __future__ import annotations

import re
from typing import Any, Protocol

from google.auth.transport.requests import Request as AuthRequest
from google.oauth2 import id_token


class WorkerAuthenticationError(RuntimeError):
    def __init__(self, *, wrong_caller: bool = False) -> None:
        self.wrong_caller = wrong_caller
        super().__init__("workflow caller authentication failed")


class WorkflowIdentityVerifier(Protocol):
    def verify(self, authorization: str | None) -> None: ...


class GoogleWorkflowIdentityVerifier:
    """Validates audience and exact service-account identity with Google OIDC."""

    def __init__(
        self,
        *,
        audience: str,
        service_account: str,
        request: Any | None = None,
    ) -> None:
        if not audience.strip() or not re.fullmatch(
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.gserviceaccount\.com",
            service_account,
        ):
            raise ValueError("invalid Workflow OIDC configuration")
        self._audience = audience
        self._service_account = service_account
        self._request = request or AuthRequest()

    def verify(self, authorization: str | None) -> None:
        if authorization is None or not authorization.startswith("Bearer "):
            raise WorkerAuthenticationError
        token = authorization.removeprefix("Bearer ")
        if not token or not re.fullmatch(r"[A-Za-z0-9._~-]+", token):
            raise WorkerAuthenticationError
        try:
            claims = id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
                token,
                self._request,
                audience=self._audience,
            )
        except Exception:
            raise WorkerAuthenticationError from None
        if (
            claims.get("email") != self._service_account
            or claims.get("email_verified") is not True
            or claims.get("sub") is None
        ):
            raise WorkerAuthenticationError(wrong_caller=True)
