from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from typing import Any, cast

import pytest

from regops_api.domain_models import SourceDocumentRecord, WorkflowLaunchRequest
from regops_api.integrations import IntegrationUnavailableError
from regops_api.storage import (
    GoogleCloudStorageAdapter,
    audit_object_name,
    sanitize_filename,
    source_object_name,
)
from regops_api.workflows import GoogleWorkflowsLauncher


class FakeBlob:
    def __init__(self, name: str, *, signed_url: str, download: bytes = b"") -> None:
        self.name = name
        self.signed_url = signed_url
        self.uploads: list[tuple[bytes, dict[str, object]]] = []
        self.delete_calls = 0
        self.download = download
        self.signed_kwargs: list[dict[str, object]] = []

    def upload_from_string(self, content: bytes, **kwargs: object) -> None:
        self.uploads.append((content, kwargs))

    def generate_signed_url(self, **kwargs: object) -> str:
        self.signed_kwargs.append(kwargs)
        return self.signed_url

    def download_as_bytes(self, *, start: int, end: int) -> bytes:
        return self.download[start : end + 1]

    def delete(self) -> None:
        self.delete_calls += 1


class FakeBucket:
    def __init__(self, signed_url: str, download: bytes = b"") -> None:
        self.signed_url = signed_url
        self.download = download
        self.blobs: dict[str, FakeBlob] = {}

    def blob(self, name: str) -> FakeBlob:
        blob = FakeBlob(name, signed_url=self.signed_url, download=self.download)
        self.blobs[name] = blob
        return blob


class FakeStorageClient:
    def __init__(self, signed_url: str, download: bytes = b"") -> None:
        self.bucket_name: str | None = None
        self.fake_bucket = FakeBucket(signed_url, download)

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
    signed_url = (
        "https://storage.googleapis.com/private-bucket/runs/run-1/audit/"
        "audit-package.json?X-Goog-Signature=secret"
    )
    client = FakeStorageClient(signed_url)
    adapter = GoogleCloudStorageAdapter(
        client=cast(Any, client),
        bucket_name="private-bucket",
        signed_url_ttl_seconds=300,
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


def test_storage_sanitizes_names_and_rejects_non_https_signer_output() -> None:
    assert sanitize_filename("../unsafe folder/../../rule ?.pdf") == "rule-.pdf"
    client = FakeStorageClient("https://?signature=missing-host")
    adapter = GoogleCloudStorageAdapter(
        client=cast(Any, client),
        bucket_name="private-bucket",
        signed_url_ttl_seconds=300,
    )

    with pytest.raises(IntegrationUnavailableError, match="signing is unavailable"):
        adapter.store_audit_package_and_sign(run_id="run-1", content=b"{}")


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


class RefreshCredentials:
    token: str | None = None
    valid = False

    def __init__(self) -> None:
        self.refreshes = 0

    def refresh(self, _request: object) -> None:
        self.refreshes += 1
        self.token = "adc-access-token"
        self.valid = True


def test_iam_signing_refreshes_adc_and_passes_only_configured_signer(
    caplog: pytest.LogCaptureFixture,
) -> None:
    signed_url = (
        "https://storage.googleapis.com/private-bucket/runs/run-1/audit/"
        "audit-package.json?X-Goog-Signature=secret-signature"
    )
    client = FakeStorageClient(signed_url)
    credentials = RefreshCredentials()
    adapter = GoogleCloudStorageAdapter(
        client=cast(Any, client),
        bucket_name="private-bucket",
        signed_url_ttl_seconds=120,
        credentials=credentials,
        auth_request=object(),
        signer_service_account="audit-signer@project.iam.gserviceaccount.com",
    )
    caplog.set_level(logging.DEBUG)

    assert adapter.store_audit_package_and_sign(run_id="run-1", content=b"{}") == signed_url

    blob = client.fake_bucket.blobs[audit_object_name("run-1")]
    assert credentials.refreshes == 1
    assert blob.signed_kwargs[0]["service_account_email"] == (
        "audit-signer@project.iam.gserviceaccount.com"
    )
    assert blob.signed_kwargs[0]["access_token"] == "adc-access-token"
    assert signed_url not in caplog.text
    assert "adc-access-token" not in caplog.text


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
