"""Fail-closed application composition for test, demo, and production modes."""

from __future__ import annotations

from google.auth.credentials import Credentials
from google.cloud import firestore
from google.cloud.storage.client import Client as StorageClient
from google.cloud.workflows import executions_v1

from regops_api.analyst_errors import AnalystCode, AnalystError
from regops_api.analyst_settings import AnalystSettings
from regops_api.config import RuntimeMode, RuntimeSettings
from regops_api.counterfactual import DeterministicCounterfactual
from regops_api.firestore import FirestoreRepositories
from regops_api.gemini_analyst import build_demo_analyst, build_demo_detector
from regops_api.integrations import ReviewerIdentityProvider
from regops_api.internal_auth import GoogleWorkflowIdentityVerifier
from regops_api.live_fixture import minimum_live_counterfactual
from regops_api.runtime import RuntimeContainer, StaticReviewerIdentity
from regops_api.runtime_errors import RuntimeConfigurationError
from regops_api.storage import GoogleCloudStorageAdapter, build_iam_signing_credentials
from regops_api.worker_runtime import MinimumLiveWorker
from regops_api.workflows import GoogleWorkflowsLauncher


def build_cloud_runtime(
    settings: RuntimeSettings,
    *,
    reviewer_identity: ReviewerIdentityProvider | None = None,
    counterfactual: DeterministicCounterfactual | None = None,
    firestore_client: firestore.Client | None = None,
    storage_client: StorageClient | None = None,
    workflows_client: executions_v1.ExecutionsClient | None = None,
    iam_caller_credentials: Credentials | None = None,
    iam_signing_request: object | None = None,
) -> RuntimeContainer:
    settings.validate_startup()
    if settings.mode is RuntimeMode.TEST:
        raise RuntimeConfigurationError(
            "test mode requires an explicitly injected RuntimeContainer"
        )
    if settings.mode is RuntimeMode.PRODUCTION and reviewer_identity is None:
        raise RuntimeConfigurationError("production requires a trusted reviewer identity provider")
    if settings.mode is RuntimeMode.PRODUCTION:
        raise RuntimeConfigurationError("minimum live worker requires explicit synthetic demo mode")
    if settings.mode is RuntimeMode.DEMO:
        reviewer_identity = StaticReviewerIdentity("demo-reviewer")
    assert settings.project_id is not None
    assert settings.bucket is not None
    assert settings.workflow_region is not None
    assert settings.workflow_name is not None
    assert settings.workflow_service_account is not None
    assert settings.worker_audience is not None
    assert settings.audit_signer_service_account is not None
    assert reviewer_identity is not None
    firestore_client = firestore_client or firestore.Client(project=settings.project_id)
    storage_client = storage_client or StorageClient(project=settings.project_id)
    workflows_client = workflows_client or executions_v1.ExecutionsClient()
    repositories = FirestoreRepositories(firestore_client)
    try:
        audit_signing_credentials = build_iam_signing_credentials(
            signer_service_account=settings.audit_signer_service_account,
            caller_credentials=iam_caller_credentials,
            auth_request=iam_signing_request,
        )
    except Exception:
        raise RuntimeConfigurationError(
            "keyless IAM audit signing configuration is unavailable"
        ) from None
    storage = GoogleCloudStorageAdapter(
        client=storage_client,
        bucket_name=settings.bucket,
        signed_url_ttl_seconds=settings.signed_url_ttl_seconds,
        signing_credentials=audit_signing_credentials,
    )
    try:
        analyst_settings = AnalystSettings.from_env(settings)
        analyst_settings.validate_demo(settings)
        if analyst_settings.model != "gemini-3.5-flash":
            raise AnalystError(AnalystCode.ANALYST_CONFIGURATION_INVALID)
    except AnalystError:
        raise RuntimeConfigurationError(
            "Gemini or Model Armor runtime configuration is incomplete"
        ) from None
    if counterfactual is None:
        counterfactual = minimum_live_counterfactual()
    worker = MinimumLiveWorker(
        repositories=repositories,
        storage=storage,
        analyst_factory=lambda content: build_demo_analyst(
            content=content,
            runtime=settings,
            settings=analyst_settings,
        ),
        analyst_settings=analyst_settings,
        max_source_bytes=settings.max_upload_bytes,
        fixture_detector_factory=lambda content: build_demo_detector(
            content=content,
            runtime=settings,
            settings=analyst_settings,
        ),
        runtime_mode=settings.mode,
    )
    return RuntimeContainer(
        settings=settings,
        repositories=repositories,
        storage=storage,
        workflows=GoogleWorkflowsLauncher(
            client=workflows_client,
            project_id=settings.project_id,
            region=settings.workflow_region,
            workflow_name=settings.workflow_name,
        ),
        reviewer_identity=reviewer_identity,
        counterfactual=counterfactual,
        workflow_identity=GoogleWorkflowIdentityVerifier(
            audience=settings.worker_audience,
            service_account=settings.workflow_service_account,
        ),
        worker=worker,
    )
