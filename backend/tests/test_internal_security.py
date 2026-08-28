from __future__ import annotations

import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from regops_api.config import RuntimeMode, RuntimeSettings
from regops_api.internal_auth import (
    GoogleWorkflowIdentityVerifier,
    WorkerAuthenticationError,
)
from regops_api.main import create_app
from regops_api.runtime_errors import RuntimeConfigurationError
from tests.runtime_helpers import make_runtime

WORKFLOW_IDENTITY = "workflow@project.iam.gserviceaccount.com"


def test_google_oidc_verifier_accepts_exact_audience_and_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def verify(token: str, request: object, *, audience: str) -> dict[str, object]:
        seen.update(token=token, request=request, audience=audience)
        return {
            "email": WORKFLOW_IDENTITY,
            "email_verified": True,
            "sub": "subject-1",
        }

    monkeypatch.setattr("regops_api.internal_auth.id_token.verify_oauth2_token", verify)
    request = object()
    verifier = GoogleWorkflowIdentityVerifier(
        audience="https://worker.example.test/internal/v1/workflow/run",
        service_account=WORKFLOW_IDENTITY,
        request=request,
    )

    verifier.verify("Bearer header.payload.signature")

    assert seen == {
        "token": "header.payload.signature",
        "request": request,
        "audience": "https://worker.example.test/internal/v1/workflow/run",
    }


@pytest.mark.parametrize("authorization", [None, "", "Basic token", "Bearer ", "Bearer bad token"])
def test_google_oidc_verifier_rejects_missing_or_malformed_tokens(
    authorization: str | None,
) -> None:
    verifier = GoogleWorkflowIdentityVerifier(
        audience="https://worker.example.test/internal/v1/workflow/run",
        service_account=WORKFLOW_IDENTITY,
        request=object(),
    )
    with pytest.raises(WorkerAuthenticationError):
        verifier.verify(authorization)


def test_google_oidc_verifier_rejects_wrong_audience_and_wrong_caller(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    verifier = GoogleWorkflowIdentityVerifier(
        audience="https://worker.example.test/internal/v1/workflow/run",
        service_account=WORKFLOW_IDENTITY,
        request=object(),
    )
    monkeypatch.setattr(
        "regops_api.internal_auth.id_token.verify_oauth2_token",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("wrong audience")),
    )
    caplog.set_level(logging.DEBUG)
    with pytest.raises(WorkerAuthenticationError):
        verifier.verify("Bearer secret.token.value")
    monkeypatch.setattr(
        "regops_api.internal_auth.id_token.verify_oauth2_token",
        lambda *_args, **_kwargs: {
            "email": "other@project.iam.gserviceaccount.com",
            "email_verified": True,
            "sub": "subject-2",
        },
    )
    with pytest.raises(WorkerAuthenticationError) as wrong:
        verifier.verify("Bearer secret.token.value")
    assert wrong.value.wrong_caller
    assert "secret.token.value" not in caplog.text


def test_exact_origin_cors_preflight_and_rejection() -> None:
    settings = RuntimeSettings(
        mode=RuntimeMode.TEST,
        cors_origins=("https://review.example.test",),
    )
    client = TestClient(create_app(settings=settings, runtime=make_runtime()))
    headers = {
        "Origin": "https://review.example.test",
        "Access-Control-Request-Method": "GET",
    }

    allowed = client.options("/api/v1/health", headers=headers)
    rejected = client.options(
        "/api/v1/health",
        headers=headers | {"Origin": "https://attacker.example.test"},
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == headers["Origin"]
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers


def test_cloud_cors_rejects_wildcard_and_local_http() -> None:
    for origins in (("*",), ("http://localhost:3000",)):
        with pytest.raises(RuntimeConfigurationError):
            RuntimeSettings(
                mode=RuntimeMode.PRODUCTION,
                cors_origins=origins,
            ).validate_cors()
