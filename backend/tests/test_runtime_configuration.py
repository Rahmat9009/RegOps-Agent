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
        bucket="private-bucket",
        workflow_name="regops-run",
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


def test_demo_mode_builds_persistent_adapters_with_backend_reviewer() -> None:
    runtime = build_cloud_runtime(
        cloud_settings(RuntimeMode.DEMO),
        firestore_client=cast(Any, object()),
        storage_client=cast(Any, FakeStorageClient()),
        workflows_client=cast(Any, object()),
    )

    assert isinstance(runtime.repositories, FirestoreRepositories)
    assert runtime.reviewer_identity.reviewer_id() == "demo-reviewer"


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
    }
