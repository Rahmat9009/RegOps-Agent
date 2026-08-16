"""FastAPI boundary for the persistent Phase 1B data plane."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, cast

import uvicorn
from fastapi import FastAPI, File, Form, Query, Request, UploadFile, status
from fastapi import Path as PathParameter
from starlette.concurrency import run_in_threadpool

from regops_api import __version__
from regops_api.composition import build_cloud_runtime
from regops_api.config import RuntimeSettings
from regops_api.errors import APIException, register_exception_handlers
from regops_api.integrations import IntegrationUnavailableError
from regops_api.runtime import (
    RunIntakeService,
    RuntimeActionService,
    RuntimeApprovalService,
    RuntimeAuditService,
    RuntimeContainer,
    RuntimeQueryService,
)
from regops_api.runtime_errors import DocumentTooLargeError, UnsupportedDocumentError
from regops_api.schemas import (
    APIError,
    Approval,
    ApprovalDecision,
    AuditReport,
    CounterfactualPreview,
    Finding,
    FindingList,
    HealthStatus,
    Run,
    Severity,
)

API_PREFIX = "/api/v1"

VALIDATION_RESPONSE: dict[int | str, dict[str, Any]] = {
    422: {"model": APIError, "description": "Request validation failed"},
}
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    **VALIDATION_RESPONSE,
    501: {"model": APIError, "description": "Not implemented in Phase 0"},
}
NOT_FOUND_RESPONSE: dict[int | str, dict[str, Any]] = {
    404: {"model": APIError, "description": "Resource not found"}
}


def create_app(
    *,
    settings: RuntimeSettings | None = None,
    runtime: RuntimeContainer | None = None,
) -> FastAPI:
    configured_settings = settings or RuntimeSettings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if not hasattr(application.state, "runtime"):
            application.state.runtime = build_cloud_runtime(configured_settings)
        yield

    application = FastAPI(
        title="RegOps API",
        version=__version__,
        description=(
            "RegOps identifies potential conflicts and supports review. It does not "
            "determine legal compliance. All contracts and cases are synthetic and labeled."
        ),
        openapi_version="3.1.0",
        lifespan=lifespan,
    )
    application.state.settings = configured_settings
    if runtime is not None:
        application.state.runtime = runtime
    register_exception_handlers(application)

    def require_runtime(request: Request) -> RuntimeContainer:
        container = getattr(request.app.state, "runtime", None)
        if container is None:
            raise IntegrationUnavailableError("runtime composition is unavailable")
        return cast(RuntimeContainer, container)

    @application.get(
        f"{API_PREFIX}/health",
        response_model=HealthStatus,
        operation_id="getHealth",
        summary="Liveness and readiness probe",
    )
    async def get_health() -> HealthStatus:
        return HealthStatus(status="ok", version=__version__)

    @application.post(
        f"{API_PREFIX}/runs",
        response_model=Run,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="createRun",
        summary="Accept a synthetic regulation PDF and create an ingested run",
        responses=VALIDATION_RESPONSE,
    )
    async def create_run(
        request: Request,
        regulation_file: Annotated[
            UploadFile,
            File(
                description="Required PDF binary for a synthetic regulation",
                json_schema_extra={"contentMediaType": "application/pdf"},
            ),
        ],
        synthetic_ack: Annotated[
            bool,
            Form(description="Confirms that the uploaded demo document is synthetic"),
        ],
    ) -> Run:
        if not synthetic_ack:
            raise APIException(
                status_code=422,
                code="SYNTHETIC_ACK_REQUIRED",
                message="synthetic_ack must be true",
            )
        filename = regulation_file.filename or ""
        max_bytes = int(request.app.state.settings.max_upload_bytes)
        try:
            if regulation_file.content_type != "application/pdf":
                raise UnsupportedDocumentError
            content = await regulation_file.read(max_bytes + 1)
        finally:
            await regulation_file.close()
        if len(content) > max_bytes:
            raise DocumentTooLargeError
        if not filename.lower().endswith(".pdf") or not content.startswith(b"%PDF-"):
            raise UnsupportedDocumentError
        return await run_in_threadpool(
            RunIntakeService(require_runtime(request)).create,
            filename=filename,
            content=content,
        )

    @application.get(
        f"{API_PREFIX}/runs/{{run_id}}",
        response_model=Run,
        operation_id="getRun",
        summary="Get run state and polling progress",
        responses=NOT_FOUND_RESPONSE | ERROR_RESPONSES,
    )
    def get_run(
        request: Request,
        run_id: Annotated[str, PathParameter(min_length=1)],
    ) -> Run:
        return RuntimeQueryService(require_runtime(request).repositories).get_run(run_id)

    @application.get(
        f"{API_PREFIX}/runs/{{run_id}}/findings",
        response_model=FindingList,
        operation_id="listRunFindings",
        summary="List findings for a run",
        responses=NOT_FOUND_RESPONSE | ERROR_RESPONSES,
    )
    def list_run_findings(
        request: Request,
        run_id: Annotated[str, PathParameter(min_length=1)],
        severity: Annotated[Severity | None, Query()] = None,
        q: Annotated[str | None, Query(min_length=1)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> FindingList:
        runtime_service = RuntimeQueryService(require_runtime(request).repositories)
        return runtime_service.list_findings(
            run_id,
            severity=severity,
            query=q,
            limit=limit,
            offset=offset,
        )

    @application.get(
        f"{API_PREFIX}/findings/{{finding_id}}",
        response_model=Finding,
        operation_id="getFinding",
        summary="Get a finding and its evidence chain",
        responses=NOT_FOUND_RESPONSE | ERROR_RESPONSES,
    )
    def get_finding(
        request: Request,
        finding_id: Annotated[str, PathParameter(min_length=1)],
    ) -> Finding:
        return RuntimeQueryService(require_runtime(request).repositories).get_finding(
            finding_id
        )

    @application.post(
        f"{API_PREFIX}/actions/{{action_id}}/preview",
        response_model=CounterfactualPreview,
        operation_id="previewAction",
        summary="Get a deterministic shadow-state counterfactual preview",
        responses=NOT_FOUND_RESPONSE | ERROR_RESPONSES,
    )
    def preview_action(
        request: Request,
        action_id: Annotated[str, PathParameter(min_length=1)],
    ) -> CounterfactualPreview:
        return RuntimeActionService(require_runtime(request)).preview(action_id)

    @application.post(
        f"{API_PREFIX}/approvals/{{approval_id}}/decision",
        response_model=Approval,
        operation_id="decideApproval",
        summary="Record a human approval decision",
        responses={
            **NOT_FOUND_RESPONSE,
            **ERROR_RESPONSES,
            409: {"model": APIError, "description": "Approval already decided"},
        },
    )
    def decide_approval(
        request: Request,
        approval_id: Annotated[str, PathParameter(min_length=1)],
        decision: ApprovalDecision,
    ) -> Approval:
        return RuntimeApprovalService(require_runtime(request)).decide(
            approval_id, decision
        )

    @application.get(
        f"{API_PREFIX}/runs/{{run_id}}/audit",
        response_model=AuditReport,
        operation_id="getRunAudit",
        summary="Get a run audit report",
        responses=NOT_FOUND_RESPONSE | ERROR_RESPONSES,
    )
    def get_run_audit(
        request: Request,
        run_id: Annotated[str, PathParameter(min_length=1)],
    ) -> AuditReport:
        return RuntimeAuditService(require_runtime(request)).get(run_id)

    return application


app = create_app()


def run() -> None:
    uvicorn.run("regops_api.main:app", host="0.0.0.0", port=8080)
