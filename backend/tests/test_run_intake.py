import inspect

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from regops_api.domain_models import RunIntakeCommit, WorkflowLaunchRequest
from regops_api.in_memory import InMemoryRepositories
from regops_api.integrations import IntegrationUnavailableError
from regops_api.main import create_app
from regops_api.repositories import RecordNotFoundError
from regops_api.runtime import RunIntakeService, RuntimeContainer
from regops_api.schemas import RunState
from tests.runtime_helpers import RecordingStorage, RecordingWorkflow, make_runtime


def make_client(
    *,
    fail_workflow: bool = False,
    max_upload_bytes: int = 10 * 1024 * 1024,
    repositories: InMemoryRepositories | None = None,
    storage: RecordingStorage | None = None,
    workflows: RecordingWorkflow | None = None,
) -> tuple[TestClient, RuntimeContainer, RecordingStorage, RecordingWorkflow]:
    storage = storage or RecordingStorage()
    workflows = workflows or RecordingWorkflow(fail=fail_workflow)
    runtime = make_runtime(
        repositories=repositories,
        storage=storage,
        workflows=workflows,
        max_upload_bytes=max_upload_bytes,
    )
    client = TestClient(create_app(settings=runtime.settings, runtime=runtime))
    return client, runtime, storage, workflows


def test_create_run_accepts_required_multipart_fields() -> None:
    client, runtime, _storage, workflows = make_client()
    response = client.post(
        "/api/v1/runs",
        files={"regulation_file": ("rule.pdf", b"%PDF-1.7\n", "application/pdf")},
        data={"synthetic_ack": "true"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["state"] == "INGESTED"
    assert payload["regulation"]["source_filename"] == "rule.pdf"
    assert payload["regulation"]["synthetic"] is True
    assert payload["progress"]["documents_total"] == 1
    source = runtime.repositories.get_source_document(payload["run_id"])
    assert source.object_name == f"runs/{payload['run_id']}/source/regulation.pdf"
    assert len(source.source_sha256) == 64
    assert workflows.requests[0].source_gcs_uri == source.gcs_uri


def test_create_run_requires_multipart_fields_with_structured_error() -> None:
    client, _runtime, _storage, _workflows = make_client()
    response = client.post("/api/v1/runs")

    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == "VALIDATION_ERROR"
    assert payload["message"] == "Request validation failed"
    assert {detail["location"][-1] for detail in payload["details"]} == {
        "regulation_file",
        "synthetic_ack",
    }


def test_create_run_rejects_non_pdf_content() -> None:
    client, _runtime, _storage, _workflows = make_client()
    response = client.post(
        "/api/v1/runs",
        files={"regulation_file": ("rule.pdf", b"not a pdf", "application/pdf")},
        data={"synthetic_ack": "true"},
    )

    assert response.status_code == 415
    assert response.json()["code"] == "UNSUPPORTED_DOCUMENT"


def test_create_run_requires_true_synthetic_acknowledgement() -> None:
    client, _runtime, _storage, _workflows = make_client()
    response = client.post(
        "/api/v1/runs",
        files={"regulation_file": ("rule.pdf", b"%PDF-1.7\n", "application/pdf")},
        data={"synthetic_ack": "false"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "SYNTHETIC_ACK_REQUIRED"


def test_create_run_rejects_oversized_pdf_without_launching_workflow() -> None:
    client, _runtime, _storage, workflows = make_client(max_upload_bytes=1024)

    response = client.post(
        "/api/v1/runs",
        files={
            "regulation_file": (
                "rule.pdf",
                b"%PDF-1.7\n" + b"x" * 1024,
                "application/pdf",
            )
        },
        data={"synthetic_ack": "true"},
    )

    assert response.status_code == 413
    assert response.json()["code"] == "DOCUMENT_TOO_LARGE"
    assert workflows.requests == []


def test_workflow_launch_failure_leaves_a_recoverable_run_and_hides_detail() -> None:
    client, runtime, storage, _workflows = make_client(fail_workflow=True)

    response = client.post(
        "/api/v1/runs",
        files={"regulation_file": ("rule.pdf", b"%PDF-1.7\n", "application/pdf")},
        data={"synthetic_ack": "true"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "code": "SERVICE_UNAVAILABLE",
        "message": "A required service is unavailable",
        "details": None,
    }
    run = runtime.repositories.list_regulations_by_source("rule.pdf")[0]
    persisted = runtime.repositories.get_run(storage.sources[0][0])
    assert run.regulation.reg_id == persisted.regulation.reg_id
    assert persisted.state is RunState.FAILED_RECOVERABLE
    assert persisted.recovery is not None
    assert persisted.recovery.last_error_code == "WORKFLOW_LAUNCH_FAILED"
    assert storage.deleted_sources == []


class FailingIntakeRepositories(InMemoryRepositories):
    def __init__(self) -> None:
        super().__init__(purpose="test")
        self.commits: list[RunIntakeCommit] = []

    def commit_run_intake(self, commit: RunIntakeCommit) -> None:
        self.commits.append(commit)
        raise IntegrationUnavailableError("firestore secret persistence detail")


def test_failed_intake_transaction_leaves_no_metadata_and_cleans_exact_object() -> None:
    repositories = FailingIntakeRepositories()
    storage = RecordingStorage()
    client, _runtime, _storage, workflows = make_client(
        repositories=repositories,
        storage=storage,
    )

    response = client.post(
        "/api/v1/runs",
        files={"regulation_file": ("rule.pdf", b"%PDF-1.7\n", "application/pdf")},
        data={"synthetic_ack": "true"},
    )

    assert response.status_code == 503
    assert response.json()["message"] == "A required service is unavailable"
    assert len(repositories.commits) == 1
    run_id = storage.sources[0][0]
    with pytest.raises(RecordNotFoundError):
        repositories.get_run(run_id)
    with pytest.raises(RecordNotFoundError):
        repositories.get_source_document(run_id)
    assert repositories.list_checkpoints(run_id) == []
    assert repositories.list_regulations_by_source("rule.pdf") == []
    assert storage.deleted_sources == [
        (run_id, f"runs/{run_id}/source/regulation.pdf")
    ]
    assert workflows.requests == []


class CleanupFailingStorage(RecordingStorage):
    def delete_source(self, *, run_id: str, object_name: str) -> None:
        super().delete_source(run_id=run_id, object_name=object_name)
        raise IntegrationUnavailableError("cleanup secret detail")


def test_cleanup_failure_does_not_hide_original_persistence_failure() -> None:
    repositories = FailingIntakeRepositories()
    storage = CleanupFailingStorage()
    runtime = make_runtime(repositories=repositories, storage=storage)

    with pytest.raises(
        IntegrationUnavailableError,
        match="firestore secret persistence detail",
    ):
        RunIntakeService(runtime).create(
            filename="rule.pdf",
            content=b"%PDF-1.7\n",
        )

    assert len(storage.deleted_sources) == 1


class MetadataCheckingWorkflow(RecordingWorkflow):
    def __init__(self, repositories: InMemoryRepositories) -> None:
        super().__init__()
        self._repositories = repositories

    def launch(self, request: WorkflowLaunchRequest) -> str:
        assert self._repositories.get_run(request.run_id).state is RunState.INGESTED
        assert self._repositories.get_source_document(request.run_id).gcs_uri == (
            request.source_gcs_uri
        )
        assert self._repositories.latest_checkpoint(request.run_id) is not None
        return super().launch(request)


def test_successful_intake_launches_only_after_atomic_metadata_commit() -> None:
    repositories = InMemoryRepositories.for_tests()
    workflow = MetadataCheckingWorkflow(repositories)
    client, _runtime, storage, workflows = make_client(
        repositories=repositories,
        workflows=workflow,
    )

    response = client.post(
        "/api/v1/runs",
        files={"regulation_file": ("rule.pdf", b"%PDF-1.7\n", "application/pdf")},
        data={"synthetic_ack": "true"},
    )

    assert response.status_code == 202
    assert len(workflows.requests) == 1
    assert storage.deleted_sources == []


def test_cloud_work_is_not_called_directly_by_async_route_handlers() -> None:
    runtime = make_runtime()
    application = create_app(settings=runtime.settings, runtime=runtime)
    routes = {
        route.path: route
        for route in application.routes
        if isinstance(route, APIRoute)
    }

    intake = routes["/api/v1/runs"].endpoint
    assert inspect.iscoroutinefunction(intake)
    assert "run_in_threadpool" in inspect.getsource(intake)
    for path in (
        "/api/v1/runs/{run_id}",
        "/api/v1/runs/{run_id}/findings",
        "/api/v1/findings/{finding_id}",
        "/api/v1/actions/{action_id}/preview",
        "/api/v1/approvals/{approval_id}/decision",
        "/api/v1/runs/{run_id}/audit",
    ):
        assert not inspect.iscoroutinefunction(routes[path].endpoint)
