from __future__ import annotations

from hashlib import sha256

from regops_api.config import RuntimeMode, RuntimeSettings
from regops_api.counterfactual import DeterministicCounterfactual
from regops_api.domain_models import (
    SourceDocumentRecord,
    StoredSourceObject,
    WorkflowLaunchRequest,
)
from regops_api.in_memory import InMemoryRepositories
from regops_api.integrations import IntegrationUnavailableError
from regops_api.runtime import RuntimeContainer, StaticReviewerIdentity


class RecordingStorage:
    def __init__(self, *, audit_results: list[str | Exception | None] | None = None) -> None:
        self.sources: list[tuple[str, bytes, str]] = []
        self.deleted_sources: list[tuple[str, str]] = []
        self.audit_packages: list[tuple[str, bytes]] = []
        self.audit_results = audit_results

    def store_source(self, *, run_id: str, content: bytes, content_type: str) -> StoredSourceObject:
        self.sources.append((run_id, content, content_type))
        object_name = f"runs/{run_id}/source/regulation.pdf"
        return StoredSourceObject(
            object_name=object_name,
            gcs_uri=f"gs://test-private/{object_name}",
        )

    def delete_source(self, *, run_id: str, object_name: str) -> None:
        expected = f"runs/{run_id}/source/regulation.pdf"
        if object_name != expected:
            raise ValueError("unexpected source cleanup target")
        self.deleted_sources.append((run_id, object_name))

    def read_bound_source(self, *, record: SourceDocumentRecord, max_bytes: int) -> bytes:
        expected = f"runs/{record.run_id}/source/regulation.pdf"
        content = next(item[1] for item in self.sources if item[0] == record.run_id)
        if (
            record.object_name != expected
            or record.gcs_uri != f"gs://test-private/{expected}"
            or len(content) > max_bytes
            or len(content) != record.size_bytes
            or sha256(content).hexdigest() != record.source_sha256
        ):
            raise ValueError("source binding mismatch")
        return content

    def store_audit_package_and_sign(self, *, run_id: str, content: bytes) -> str | None:
        self.audit_packages.append((run_id, content))
        if self.audit_results:
            result = self.audit_results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return (
            f"https://storage.googleapis.com/test-private/runs/{run_id}/audit/"
            "audit-package.json?X-Goog-Signature=test"
        )


class RecordingWorkflow:
    def __init__(self, *, fail: bool = False) -> None:
        self.requests: list[WorkflowLaunchRequest] = []
        self._fail = fail

    def launch(self, request: WorkflowLaunchRequest) -> str:
        self.requests.append(request)
        if self._fail:
            raise IntegrationUnavailableError("workflow unavailable: sensitive detail")
        return f"execution-{request.run_id}"


def make_runtime(
    *,
    repositories: InMemoryRepositories | None = None,
    storage: RecordingStorage | None = None,
    workflows: RecordingWorkflow | None = None,
    counterfactual: DeterministicCounterfactual | None = None,
    max_upload_bytes: int = 10 * 1024 * 1024,
) -> RuntimeContainer:
    return RuntimeContainer(
        settings=RuntimeSettings(
            mode=RuntimeMode.TEST,
            max_upload_bytes=max_upload_bytes,
        ),
        repositories=repositories or InMemoryRepositories.for_tests(),
        storage=storage or RecordingStorage(),
        workflows=workflows or RecordingWorkflow(),
        reviewer_identity=StaticReviewerIdentity("test-reviewer"),
        counterfactual=counterfactual,
    )
