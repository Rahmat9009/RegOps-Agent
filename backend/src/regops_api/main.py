"""Minimal Phase 0 FastAPI application."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, NoReturn
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, File, Form, Query, UploadFile, status
from fastapi import Path as PathParameter

from regops_api import __version__
from regops_api.errors import APIException, register_exception_handlers
from regops_api.schemas import (
    APIError,
    Approval,
    ApprovalDecision,
    AuditReport,
    CounterfactualPreview,
    Finding,
    FindingList,
    FindingsBySeverity,
    HealthStatus,
    Regulation,
    Run,
    RunProgress,
    RunState,
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

app = FastAPI(
    title="RegOps API",
    version=__version__,
    description=(
        "RegOps identifies potential conflicts and supports review. It does not determine "
        "legal compliance. All contracts and cases are synthetic and labeled."
    ),
    openapi_version="3.1.0",
)
register_exception_handlers(app)


def _phase_zero_stub() -> NoReturn:
    raise APIException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        code="NOT_IMPLEMENTED",
        message="This operation is declared for integration but begins after Phase 0",
    )


@app.get(
    f"{API_PREFIX}/health",
    response_model=HealthStatus,
    operation_id="getHealth",
    summary="Liveness and readiness probe",
)
async def get_health() -> HealthStatus:
    return HealthStatus(status="ok", version=__version__)


@app.post(
    f"{API_PREFIX}/runs",
    response_model=Run,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="createRun",
    summary="Accept a synthetic regulation PDF and create an ingested run",
    responses=VALIDATION_RESPONSE,
)
async def create_run(
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
    filename = regulation_file.filename or ""
    try:
        if regulation_file.content_type != "application/pdf":
            raise APIException(
                status_code=422,
                code="INVALID_PDF",
                message="regulation_file must use the application/pdf media type",
            )
        if not filename.lower().endswith(".pdf"):
            raise APIException(
                status_code=422,
                code="INVALID_PDF",
                message="regulation_file must have a .pdf filename",
            )
        if await regulation_file.read(5) != b"%PDF-":
            raise APIException(
                status_code=422,
                code="INVALID_PDF",
                message="regulation_file does not contain a PDF header",
            )
    finally:
        await regulation_file.close()

    if not synthetic_ack:
        raise APIException(
            status_code=422,
            code="SYNTHETIC_ACK_REQUIRED",
            message="synthetic_ack must be true",
        )

    now = datetime.now(UTC)
    run_id = str(uuid4())
    regulation_id = str(uuid4())
    return Run(
        run_id=run_id,
        state=RunState.INGESTED,
        created_at=now,
        updated_at=now,
        regulation=Regulation(
            reg_id=regulation_id,
            title=Path(filename).stem,
            source_filename=filename,
            synthetic=True,
        ),
        progress=RunProgress(
            documents_total=1,
            documents_processed=0,
            partitions_total=0,
            partitions_complete=0,
            percent=0,
        ),
        findings_by_severity=FindingsBySeverity(low=0, medium=0, high=0),
    )


@app.get(
    f"{API_PREFIX}/runs/{{run_id}}",
    response_model=Run,
    operation_id="getRun",
    summary="Get run state and polling progress",
    responses=NOT_FOUND_RESPONSE | ERROR_RESPONSES,
)
async def get_run(run_id: Annotated[str, PathParameter(min_length=1)]) -> Run:
    _phase_zero_stub()


@app.get(
    f"{API_PREFIX}/runs/{{run_id}}/findings",
    response_model=FindingList,
    operation_id="listRunFindings",
    summary="List findings for a run",
    responses=NOT_FOUND_RESPONSE | ERROR_RESPONSES,
)
async def list_run_findings(
    run_id: Annotated[str, PathParameter(min_length=1)],
    severity: Annotated[Severity | None, Query()] = None,
    q: Annotated[str | None, Query(min_length=1)] = None,
) -> FindingList:
    _phase_zero_stub()


@app.get(
    f"{API_PREFIX}/findings/{{finding_id}}",
    response_model=Finding,
    operation_id="getFinding",
    summary="Get a finding and its evidence chain",
    responses=NOT_FOUND_RESPONSE | ERROR_RESPONSES,
)
async def get_finding(
    finding_id: Annotated[str, PathParameter(min_length=1)],
) -> Finding:
    _phase_zero_stub()


@app.post(
    f"{API_PREFIX}/actions/{{action_id}}/preview",
    response_model=CounterfactualPreview,
    operation_id="previewAction",
    summary="Get a deterministic shadow-state counterfactual preview",
    responses=NOT_FOUND_RESPONSE | ERROR_RESPONSES,
)
async def preview_action(
    action_id: Annotated[str, PathParameter(min_length=1)],
) -> CounterfactualPreview:
    _phase_zero_stub()


@app.post(
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
async def decide_approval(
    approval_id: Annotated[str, PathParameter(min_length=1)],
    decision: ApprovalDecision,
) -> Approval:
    _phase_zero_stub()


@app.get(
    f"{API_PREFIX}/runs/{{run_id}}/audit",
    response_model=AuditReport,
    operation_id="getRunAudit",
    summary="Get a run audit report",
    responses=NOT_FOUND_RESPONSE | ERROR_RESPONSES,
)
async def get_run_audit(
    run_id: Annotated[str, PathParameter(min_length=1)],
) -> AuditReport:
    _phase_zero_stub()


def run() -> None:
    uvicorn.run("regops_api.main:app", host="0.0.0.0", port=8080)
