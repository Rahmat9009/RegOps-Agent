from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from google.auth.credentials import Credentials, Signing
from google.cloud.storage._signing import generate_signed_url_v4
from google.cloud.storage.client import Client as StorageClient
from google.oauth2.credentials import Credentials as OAuthCredentials

from regops_api.domain_models import SourceDocumentRecord, WorkflowLaunchRequest
from regops_api.integrations import IntegrationUnavailableError
from regops_api.storage import (
    CLOUD_PLATFORM_SCOPE,
    IAM_SCOPE,
    IAM_SIGNING_SCOPES,
    GoogleCloudStorageAdapter,
    IamSignBlobCredentials,
    audit_object_name,
    build_iam_signing_credentials,
    sanitize_filename,
    signing_scope_valid,
    source_object_name,
)
from regops_api.workflows import GoogleWorkflowsLauncher

SIGNER_EMAIL = "audit-signer@project.iam.gserviceaccount.com"


def v4_url(*, run_id: str = "run-1", ttl: int = 300) -> str:
    query = urlencode(
        {
            "X-Goog-Algorithm": "GOOG4-RSA-SHA256",
            "X-Goog-Credential": f"{SIGNER_EMAIL}/20260829/auto/storage/goog4_request",
            "X-Goog-Date": "20260829T120000Z",
            "X-Goog-Expires": str(ttl),
            "X-Goog-SignedHeaders": "host",
            "X-Goog-Signature": "synthetic-signature",
        }
    )
    return (
        f"https://storage.googleapis.com/private-bucket/runs/{run_id}/audit/"
        f"audit-package.json?{query}"
    )


class StaticSigningCredentials(Signing):
    @property
    def signer_email(self) -> str:
        return SIGNER_EMAIL

    @property
    def signer(self) -> SimpleNamespace:
        return SimpleNamespace(sign=lambda _message: b"synthetic-signature")

    def sign_bytes(self, _message: bytes) -> bytes:
        return b"synthetic-signature"


class FakeBlob:
    def __init__(
        self,
        name: str,
        *,
        signed_url: str | Exception,
        download: bytes = b"",
        upload_error: Exception | None = None,
    ) -> None:
        self.name = name
        self.signed_url = signed_url
        self.uploads: list[tuple[bytes, dict[str, object]]] = []
        self.delete_calls = 0
        self.download = download
        self.signed_kwargs: list[dict[str, object]] = []
        self.upload_error = upload_error

    def upload_from_string(self, content: bytes, **kwargs: object) -> None:
        if self.upload_error is not None:
            raise self.upload_error
        self.uploads.append((content, kwargs))

    def generate_signed_url(self, **kwargs: object) -> str:
        self.signed_kwargs.append(kwargs)
        if isinstance(self.signed_url, Exception):
            raise self.signed_url
        return self.signed_url

    def download_as_bytes(self, *, start: int, end: int) -> bytes:
        return self.download[start : end + 1]

    def delete(self) -> None:
        self.delete_calls += 1


class FakeBucket:
    def __init__(
        self,
        signed_url: str | Exception,
        download: bytes = b"",
        upload_error: Exception | None = None,
    ) -> None:
        self.signed_urls = [signed_url]
        self.download = download
        self.upload_error = upload_error
        self.blobs: dict[str, FakeBlob] = {}
        self.created: list[FakeBlob] = []

    def blob(self, name: str) -> FakeBlob:
        result = self.signed_urls[min(len(self.created), len(self.signed_urls) - 1)]
        blob = FakeBlob(
            name,
            signed_url=result,
            download=self.download,
            upload_error=self.upload_error,
        )
        self.blobs[name] = blob
        self.created.append(blob)
        return blob


class FakeStorageClient:
    def __init__(
        self,
        signed_url: str | Exception,
        download: bytes = b"",
        upload_error: Exception | None = None,
    ) -> None:
        self.bucket_name: str | None = None
        self.fake_bucket = FakeBucket(signed_url, download, upload_error)

    def bucket(self, name: str) -> FakeBucket:
        self.bucket_name = name
        return self.fake_bucket


class FakeExecutionsClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.requests: list[dict[str, object]] = []
        self.fail = fail

    def create_execution(self, *, request: dict[str, object]) -> SimpleNamespace:
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("projects/secret-project credential detail")
        return SimpleNamespace(name="executions/execution-1")


def test_storage_uses_private_deterministic_paths_and_safe_signed_urls(
    caplog: pytest.LogCaptureFixture,
) -> None:
    signed_url = v4_url()
    client = FakeStorageClient(signed_url)
    adapter = GoogleCloudStorageAdapter(
        client=cast(Any, client),
        bucket_name="private-bucket",
        signed_url_ttl_seconds=300,
        signing_credentials=StaticSigningCredentials(),
    )
    caplog.set_level(logging.DEBUG)

    stored = adapter.store_source(
        run_id="run-1",
        content=b"%PDF-1.7\nexact",
        content_type="application/pdf",
    )
    returned_url = adapter.store_audit_package_and_sign(run_id="run-1", content=b"{}")

    assert source_object_name("run-1") == "runs/run-1/source/regulation.pdf"
    assert audit_object_name("run-1") == "runs/run-1/audit/audit-package.json"
    assert stored.gcs_uri == "gs://private-bucket/runs/run-1/source/regulation.pdf"
    source_upload = client.fake_bucket.blobs[stored.object_name].uploads[0]
    assert source_upload == (
        b"%PDF-1.7\nexact",
        {"content_type": "application/pdf", "if_generation_match": 0},
    )
    assert returned_url == signed_url
    assert signed_url not in caplog.text
    audit_blob = client.fake_bucket.blobs[audit_object_name("run-1")]
    signing = audit_blob.signed_kwargs[0]
    assert set(signing) == {"version", "expiration", "method", "credentials"}
    assert signing["version"] == "v4" and signing["method"] == "GET"
    assert cast(timedelta, signing["expiration"]).total_seconds() == 300
    assert isinstance(signing["credentials"], StaticSigningCredentials)


def test_storage_sanitizes_names_and_rejects_non_https_signer_output(
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert sanitize_filename("../unsafe folder/../../rule ?.pdf") == "rule-.pdf"
    client = FakeStorageClient("https://?signature=missing-host")
    adapter = GoogleCloudStorageAdapter(
        client=cast(Any, client),
        bucket_name="private-bucket",
        signed_url_ttl_seconds=300,
        signing_credentials=StaticSigningCredentials(),
    )

    assert adapter.store_audit_package_and_sign(run_id="run-1", content=b"{}") is None
    assert caplog.messages == ["AUDIT_SIGNING_UNAVAILABLE"]


def test_source_cleanup_is_restricted_to_the_exact_run_scoped_object() -> None:
    client = FakeStorageClient("https://storage.googleapis.com/private/signed")
    adapter = GoogleCloudStorageAdapter(
        client=cast(Any, client),
        bucket_name="private-bucket",
        signed_url_ttl_seconds=300,
    )

    with pytest.raises(ValueError, match="exact run object"):
        adapter.delete_source(
            run_id="run-1",
            object_name="runs/run-1/source/other.pdf",
        )

    exact = source_object_name("run-1")
    adapter.delete_source(run_id="run-1", object_name=exact)
    assert set(client.fake_bucket.blobs) == {exact}
    assert client.fake_bucket.blobs[exact].delete_calls == 1


def test_bound_source_reader_enforces_object_size_and_digest() -> None:
    content = b"%PDF-1.7\nexact"
    digest = sha256(content).hexdigest()
    client = FakeStorageClient("https://storage.googleapis.com/private/signed", content)
    adapter = GoogleCloudStorageAdapter(
        client=cast(Any, client),
        bucket_name="private-bucket",
        signed_url_ttl_seconds=300,
    )
    record = SourceDocumentRecord(
        run_id="run-1",
        regulation_id="reg-1",
        object_name="runs/run-1/source/regulation.pdf",
        gcs_uri="gs://private-bucket/runs/run-1/source/regulation.pdf",
        source_sha256=digest,
        size_bytes=len(content),
        content_type="application/pdf",
        sanitized_filename="rule.pdf",
        synthetic=True,
        created_at=datetime.now(UTC),
    )

    assert adapter.read_bound_source(record=record, max_bytes=len(content)) == content
    with pytest.raises(ValueError, match="persisted metadata"):
        adapter.read_bound_source(
            record=record.model_copy(update={"source_sha256": "f" * 64}),
            max_bytes=len(content),
        )
    with pytest.raises(ValueError, match="exact run object"):
        adapter.read_bound_source(
            record=record.model_copy(update={"gcs_uri": "gs://other/source.pdf"}),
            max_bytes=len(content),
        )
    with pytest.raises(ValueError, match="exact run object"):
        adapter.read_bound_source(
            record=record.model_copy(update={"size_bytes": len(content) + 1}),
            max_bytes=len(content),
        )


def test_storage_default_scopes_are_not_reused_for_iam_signing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert set(StorageClient.SCOPE).isdisjoint({IAM_SCOPE, CLOUD_PLATFORM_SCOPE})
    caller = OAuthCredentials(  # type: ignore[no-untyped-call]
        token=None, scopes=[CLOUD_PLATFORM_SCOPE]
    )
    captured: dict[str, object] = {}

    def default(*, scopes: tuple[str, ...], request: object) -> tuple[Credentials, str]:
        captured.update(scopes=scopes, request=request)
        return caller, "synthetic-project"

    monkeypatch.setattr("regops_api.storage.google.auth.default", default)
    credentials = build_iam_signing_credentials(
        signer_service_account=SIGNER_EMAIL,
        auth_request=object(),
    )

    assert captured["scopes"] == IAM_SIGNING_SCOPES
    assert signing_scope_valid(caller)
    assert credentials.signer_email == SIGNER_EMAIL


def test_iam_signer_targets_only_configured_dedicated_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caller = OAuthCredentials(  # type: ignore[no-untyped-call]
        token=None, scopes=[CLOUD_PLATFORM_SCOPE]
    )
    captured: dict[str, object] = {}

    class RemoteSigner:
        def __init__(self, request: object, credentials: Credentials, email: str) -> None:
            captured.update(request=request, credentials=credentials, email=email)

        def sign(self, _message: bytes) -> bytes:
            return b"synthetic-signature"

    request = object()
    monkeypatch.setattr("regops_api.storage.iam.Signer", RemoteSigner)
    credentials = build_iam_signing_credentials(
        signer_service_account=SIGNER_EMAIL,
        caller_credentials=caller,
        auth_request=request,
    )

    assert captured == {"request": request, "credentials": caller, "email": SIGNER_EMAIL}
    assert credentials.signer_email == SIGNER_EMAIL
    assert isinstance(credentials, Signing) and not isinstance(credentials, Credentials)
    assert credentials.sign_bytes(b"canonical-request") == b"synthetic-signature"


def test_installed_v4_signing_uses_dedicated_signer_credential_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caller = OAuthCredentials(  # type: ignore[no-untyped-call]
        token=None, scopes=[CLOUD_PLATFORM_SCOPE]
    )

    class RemoteSigner:
        def __init__(self, _request: object, _credentials: Credentials, _email: str) -> None:
            pass

        def sign(self, _message: bytes) -> bytes:
            return b"synthetic-signature"

    monkeypatch.setattr("regops_api.storage.iam.Signer", RemoteSigner)
    credentials = build_iam_signing_credentials(
        signer_service_account=SIGNER_EMAIL,
        caller_credentials=caller,
        auth_request=object(),
    )
    url = generate_signed_url_v4(
        credentials,
        resource="/private-bucket/runs/run-1/audit/audit-package.json",
        expiration=120,
        method="GET",
        _request_timestamp="20260829T120000Z",
    )
    query = parse_qs(urlsplit(url).query)

    assert query["X-Goog-Credential"] == [
        f"{SIGNER_EMAIL}/20260829/auto/storage/goog4_request"
    ]
    assert query["X-Goog-Expires"] == ["120"]


class KeyBackedCredentials(Credentials, Signing):
    def refresh(self, _request: object) -> None:
        self.token = None

    @property
    def signer_email(self) -> str:
        return "key-backed@project.iam.gserviceaccount.com"

    @property
    def signer(self) -> SimpleNamespace:
        return SimpleNamespace(sign=lambda _message: b"key-signature")

    def sign_bytes(self, _message: bytes) -> bytes:
        return b"key-signature"


def test_key_backed_credentials_and_invalid_scopes_fail_closed() -> None:
    with pytest.raises(ValueError, match="key-backed"):
        IamSignBlobCredentials(
            request=object(),
            caller_credentials=KeyBackedCredentials(),  # type: ignore[no-untyped-call]
            signer_service_account=SIGNER_EMAIL,
        )
    storage_scoped = OAuthCredentials(  # type: ignore[no-untyped-call]
        token=None, scopes=[StorageClient.SCOPE[0]]
    )
    with pytest.raises(ValueError, match="approved scope"):
        IamSignBlobCredentials(
            request=object(),
            caller_credentials=storage_scoped,
            signer_service_account=SIGNER_EMAIL,
        )
    self_signing = OAuthCredentials(  # type: ignore[no-untyped-call]
        token=None, scopes=[CLOUD_PLATFORM_SCOPE]
    )
    cast(Any, self_signing).service_account_email = SIGNER_EMAIL
    with pytest.raises(ValueError, match="must be distinct"):
        IamSignBlobCredentials(
            request=object(),
            caller_credentials=self_signing,
            signer_service_account=SIGNER_EMAIL,
        )


def test_audit_upload_failure_remains_sanitized_service_unavailable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = FakeStorageClient(
        v4_url(),
        upload_error=RuntimeError("private object and credential detail"),
    )
    adapter = GoogleCloudStorageAdapter(
        client=cast(Any, client),
        bucket_name="private-bucket",
        signed_url_ttl_seconds=300,
        signing_credentials=StaticSigningCredentials(),
    )

    with pytest.raises(IntegrationUnavailableError, match="upload is unavailable") as caught:
        adapter.store_audit_package_and_sign(run_id="run-1", content=b"{}")

    assert "private" not in str(caught.value) + caplog.text
    assert caught.value.__context__ is None and caught.value.__cause__ is None


def test_signing_only_failure_returns_null_and_logs_only_fixed_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = FakeStorageClient(RuntimeError("private token signature URL detail"))
    adapter = GoogleCloudStorageAdapter(
        client=cast(Any, client),
        bucket_name="private-bucket",
        signed_url_ttl_seconds=300,
        signing_credentials=StaticSigningCredentials(),
    )

    result = adapter.store_audit_package_and_sign(run_id="run-1", content=b"{}")

    assert result is None
    assert caplog.messages == ["AUDIT_SIGNING_UNAVAILABLE"]
    assert client.fake_bucket.blobs[audit_object_name("run-1")].uploads
    assert "private" not in caplog.text


def test_signing_retry_reuses_exact_object_and_returns_absolute_v4_https_url() -> None:
    client = FakeStorageClient(RuntimeError("temporary"))
    client.fake_bucket.signed_urls = [RuntimeError("temporary"), v4_url(ttl=120)]
    adapter = GoogleCloudStorageAdapter(
        client=cast(Any, client),
        bucket_name="private-bucket",
        signed_url_ttl_seconds=120,
        signing_credentials=StaticSigningCredentials(),
    )

    first = adapter.store_audit_package_and_sign(run_id="run-1", content=b"{}")
    second = adapter.store_audit_package_and_sign(run_id="run-1", content=b"{}")

    assert first is None and second == v4_url(ttl=120)
    assert [blob.name for blob in client.fake_bucket.created] == [
        audit_object_name("run-1"),
        audit_object_name("run-1"),
    ]
    assert all(
        blob.uploads == [(b"{}", {"content_type": "application/json"})]
        for blob in client.fake_bucket.created
    )
    assert all(blob.signed_kwargs[0]["method"] == "GET" for blob in client.fake_bucket.created)


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "http://storage.googleapis.com/private-bucket/runs/run-1/audit/audit-package.json",
        "https://attacker.example/runs/run-1/audit/audit-package.json",
        v4_url(run_id="other-run"),
        "https://storage.googleapis.com/private-bucket/runs/run-1/audit/audit-package.json",
    ],
)
def test_partial_malformed_or_wrong_object_signed_urls_fail_closed_to_null(
    unsafe_url: str,
) -> None:
    adapter = GoogleCloudStorageAdapter(
        client=cast(Any, FakeStorageClient(unsafe_url)),
        bucket_name="private-bucket",
        signed_url_ttl_seconds=300,
        signing_credentials=StaticSigningCredentials(),
    )

    assert adapter.store_audit_package_and_sign(run_id="run-1", content=b"{}") is None


@pytest.mark.parametrize("ttl", [59, 901])
def test_signed_url_expiry_is_bounded(ttl: int) -> None:
    with pytest.raises(ValueError, match="between 60 and 900"):
        GoogleCloudStorageAdapter(
            client=cast(Any, FakeStorageClient(v4_url())),
            bucket_name="private-bucket",
            signed_url_ttl_seconds=ttl,
            signing_credentials=StaticSigningCredentials(),
        )


@pytest.mark.parametrize("run_id", ["../other", "run/other", "", " run-1"])
def test_audit_object_path_rejects_unbounded_run_ids(run_id: str) -> None:
    with pytest.raises(ValueError, match="private object path"):
        audit_object_name(run_id)


def test_workflows_launcher_passes_only_safe_references_and_returns_immediately() -> None:
    client = FakeExecutionsClient()
    launcher = GoogleWorkflowsLauncher(
        client=cast(Any, client),
        project_id="project-1",
        region="us-central1",
        workflow_name="regops-run",
    )

    execution_name = launcher.launch(
        WorkflowLaunchRequest(
            run_id="run-1",
            source_gcs_uri="gs://private/runs/run-1/source/regulation.pdf",
            source_sha256="a" * 64,
            synthetic=True,
        )
    )

    assert execution_name == "executions/execution-1"
    request = client.requests[0]
    assert request["parent"] == ("projects/project-1/locations/us-central1/workflows/regops-run")
    argument = json.loads(cast(str, cast(dict[str, object], request["execution"])["argument"]))
    assert argument == {
        "run_id": "run-1",
        "source_gcs_uri": "gs://private/runs/run-1/source/regulation.pdf",
        "source_sha256": "a" * 64,
        "synthetic": True,
    }
    assert "PDF" not in json.dumps(request)
    assert "https://" not in json.dumps(request)


def test_workflows_errors_are_sanitized() -> None:
    launcher = GoogleWorkflowsLauncher(
        client=cast(Any, FakeExecutionsClient(fail=True)),
        project_id="project-1",
        region="us-central1",
        workflow_name="regops-run",
    )

    with pytest.raises(
        IntegrationUnavailableError,
        match="workflow execution could not be started",
    ) as captured:
        launcher.launch(
            WorkflowLaunchRequest(
                run_id="run-1",
                source_gcs_uri="gs://private/source.pdf",
                source_sha256="b" * 64,
                synthetic=True,
            )
        )

    assert "secret-project" not in str(captured.value)
