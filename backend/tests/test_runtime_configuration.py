from __future__ import annotations

from typing import Any, cast

import pytest

from regops_api.composition import build_cloud_runtime
from regops_api.config import RuntimeMode, RuntimeSettings
from regops_api.firestore import (
    COLLECTIONS,
    FirestoreRepositories,
    deserialize_model,
    serialize_model,
)
from regops_api.runtime_errors import RuntimeConfigurationError
from tests.factories import make_run


def cloud_settings(mode: RuntimeMode) -> RuntimeSettings:
    return RuntimeSettings(
        mode=mode,
        project_id="project-1",
        region="us-central1",
        workflow_region="europe-west3",
        armor_location="europe-west3",
        gemini_location="eu",
        bucket="private-bucket",
        workflow_name="regops-run",
        workflow_service_account="workflow@project-1.iam.gserviceaccount.com",
        worker_audience="https://worker.example.test/internal/v1/workflow/run",
        audit_signer_service_account=("audit-signer@project-1.iam.gserviceaccount.com"),
        cors_origins=("https://review.example.test",),
    )


def test_modes_fail_closed_without_persistent_or_trusted_dependencies() -> None:
    with pytest.raises(RuntimeConfigurationError, match="explicitly injected"):
        build_cloud_runtime(RuntimeSettings(mode=RuntimeMode.TEST))
    with pytest.raises(RuntimeConfigurationError, match="incomplete"):
        build_cloud_runtime(RuntimeSettings(mode=RuntimeMode.DEMO))
    with pytest.raises(RuntimeConfigurationError, match="trusted reviewer"):
        build_cloud_runtime(cloud_settings(RuntimeMode.PRODUCTION))


class FakeStorageClient:
    def bucket(self, _name: str) -> object:
        return object()


def test_demo_mode_builds_persistent_adapters_with_backend_reviewer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = "projects/project-1/locations/europe-west3/templates/"
    monkeypatch.setenv("REGOPS_ARMOR_INPUT_TEMPLATE", prefix + "input")
    monkeypatch.setenv("REGOPS_ARMOR_OUTPUT_TEMPLATE", prefix + "output")
    runtime = build_cloud_runtime(
        cloud_settings(RuntimeMode.DEMO),
        firestore_client=cast(Any, object()),
        storage_client=cast(Any, FakeStorageClient()),
        workflows_client=cast(Any, object()),
    )

    assert isinstance(runtime.repositories, FirestoreRepositories)
    assert runtime.reviewer_identity.reviewer_id() == "demo-reviewer"
    assert runtime.worker is not None
    assert runtime.worker._fixture_detector_factory is not None
    assert runtime.worker._runtime_mode is RuntimeMode.DEMO


def test_firestore_serialization_round_trips_strict_models_and_layout_is_stable() -> None:
    run = make_run()
    payload = serialize_model(run)

    assert payload["state"] == "INGESTED"
    assert payload["transitions"][0]["from_state"] is None
    assert deserialize_model(type(run), payload) == run
    assert COLLECTIONS == {
        "runs": "runs",
        "regulations": "regulations",
        "source_documents": "source_documents",
        "obligations": "obligations",
        "synthetic_contracts": "synthetic_contracts",
        "synthetic_cases": "synthetic_cases",
        "shadow_snapshots": "shadow_snapshots",
        "findings": "findings",
        "review_tasks": "review_tasks",
        "approvals": "approvals",
        "audit_events": "audit_events",
        "audit_reports": "audit_reports",
        "proposed_actions": "proposed_actions",
        "checkpoints": "checkpoints",
        "case_tags": "case_tags",
        "action_idempotency": "action_idempotency",
        "pending_approval_slots": "pending_approval_slots",
        "worker_handoffs": "worker_handoffs",
    }


def test_runtime_locations_are_independent_with_legacy_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REGOPS_MODE", "test")
    monkeypatch.setenv("REGOPS_REGION", "legacy-region")
    monkeypatch.setenv("REGOPS_WORKFLOW_REGION", "europe-west3")
    monkeypatch.setenv("REGOPS_ARMOR_LOCATION", "europe-west3")
    monkeypatch.setenv("REGOPS_GEMINI_LOCATION", "eu")

    explicit = RuntimeSettings.from_env()
    fallback = RuntimeSettings(mode=RuntimeMode.TEST, region="legacy-region")

    assert (
        explicit.workflow_region,
        explicit.armor_location,
        explicit.gemini_location,
    ) == ("europe-west3", "europe-west3", "eu")
    assert (
        fallback.workflow_region,
        fallback.armor_location,
        fallback.gemini_location,
    ) == ("legacy-region", "legacy-region", "legacy-region")
