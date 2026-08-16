"""Fail-closed application composition for test, demo, and production modes."""

from __future__ import annotations

from google.cloud import firestore
from google.cloud.storage.client import Client as StorageClient
from google.cloud.workflows import executions_v1

from regops_api.config import RuntimeMode, RuntimeSettings
from regops_api.counterfactual import DeterministicCounterfactual
from regops_api.firestore import FirestoreRepositories
from regops_api.integrations import ReviewerIdentityProvider
from regops_api.runtime import RuntimeContainer, StaticReviewerIdentity
from regops_api.runtime_errors import RuntimeConfigurationError
from regops_api.storage import GoogleCloudStorageAdapter
from regops_api.workflows import GoogleWorkflowsLauncher


def build_cloud_runtime(
    settings: RuntimeSettings,
    *,
    reviewer_identity: ReviewerIdentityProvider | None = None,
    counterfactual: DeterministicCounterfactual | None = None,
    firestore_client: firestore.Client | None = None,
    storage_client: StorageClient | None = None,
    workflows_client: executions_v1.ExecutionsClient | None = None,
) -> RuntimeContainer:
    settings.validate_startup()
    if settings.mode is RuntimeMode.TEST:
        raise RuntimeConfigurationError(
            "test mode requires an explicitly injected RuntimeContainer"
        )
    if settings.mode is RuntimeMode.PRODUCTION and reviewer_identity is None:
        raise RuntimeConfigurationError(
            "production requires a trusted reviewer identity provider"
        )
    if settings.mode is RuntimeMode.DEMO:
        reviewer_identity = StaticReviewerIdentity("demo-reviewer")
    assert settings.project_id is not None
    assert settings.bucket is not None
    assert settings.region is not None
    assert settings.workflow_name is not None
    assert reviewer_identity is not None
    firestore_client = firestore_client or firestore.Client(project=settings.project_id)
    storage_client = storage_client or StorageClient(project=settings.project_id)
    workflows_client = workflows_client or executions_v1.ExecutionsClient()
    repositories = FirestoreRepositories(firestore_client)
    return RuntimeContainer(
        settings=settings,
        repositories=repositories,
        storage=GoogleCloudStorageAdapter(
            client=storage_client,
            bucket_name=settings.bucket,
            signed_url_ttl_seconds=settings.signed_url_ttl_seconds,
        ),
        workflows=GoogleWorkflowsLauncher(
            client=workflows_client,
            project_id=settings.project_id,
            region=settings.region,
            workflow_name=settings.workflow_name,
        ),
        reviewer_identity=reviewer_identity,
        counterfactual=counterfactual,
    )
