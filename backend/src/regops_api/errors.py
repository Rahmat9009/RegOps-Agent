"""Structured API exceptions and FastAPI exception handlers."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from regops_api.approvals import ApprovalAlreadyDecidedError
from regops_api.integrations import IntegrationUnavailableError
from regops_api.repositories import (
    DuplicateRecordError,
    RecordNotFoundError,
    StaleRecordError,
)
from regops_api.runtime_errors import (
    DocumentTooLargeError,
    DomainConflictError,
    RuntimeConfigurationError,
    UnsupportedDocumentError,
)
from regops_api.schemas import APIError, ErrorDetail
from regops_api.state_machine import InvalidRunTransitionError
from regops_api.worker_runtime import WorkerExecutionError


class APIException(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[ErrorDetail] | None = None,
    ) -> None:
        self.status_code = status_code
        self.error = APIError(code=code, message=message, details=details)
        super().__init__(message)


def _error_response(status_code: int, error: APIError) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=error.model_dump(mode="json"))


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIException)
    async def handle_api_exception(_request: Request, exc: APIException) -> JSONResponse:
        return _error_response(exc.status_code, exc.error)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            ErrorDetail(
                location=[part for part in error["loc"] if isinstance(part, (str, int))],
                message=error["msg"],
                type=error["type"],
            )
            for error in exc.errors()
        ]
        return _error_response(
            422,
            APIError(
                code="VALIDATION_ERROR",
                message="Request validation failed",
                details=details,
            ),
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exception(_request: Request, exc: HTTPException) -> JSONResponse:
        detail: Any = exc.detail
        message = detail if isinstance(detail, str) else "HTTP request failed"
        return _error_response(
            exc.status_code,
            APIError(code=f"HTTP_{exc.status_code}", message=message),
        )

    @app.exception_handler(RecordNotFoundError)
    async def handle_not_found(
        _request: Request, _exc: RecordNotFoundError
    ) -> JSONResponse:
        return _error_response(
            404,
            APIError(code="NOT_FOUND", message="Requested resource was not found"),
        )

    conflict_types = (
        ApprovalAlreadyDecidedError,
        DomainConflictError,
        DuplicateRecordError,
        InvalidRunTransitionError,
        StaleRecordError,
    )

    async def handle_conflict(_request: Request, _exc: Exception) -> JSONResponse:
        return _error_response(
            409,
            APIError(code="CONFLICT", message="Request conflicts with current state"),
        )

    for conflict_type in conflict_types:
        app.add_exception_handler(conflict_type, handle_conflict)

    @app.exception_handler(DocumentTooLargeError)
    async def handle_oversized(
        _request: Request, _exc: DocumentTooLargeError
    ) -> JSONResponse:
        return _error_response(
            413,
            APIError(code="DOCUMENT_TOO_LARGE", message="Uploaded document is too large"),
        )

    @app.exception_handler(UnsupportedDocumentError)
    async def handle_unsupported(
        _request: Request, _exc: UnsupportedDocumentError
    ) -> JSONResponse:
        return _error_response(
            415,
            APIError(code="UNSUPPORTED_DOCUMENT", message="A valid PDF is required"),
        )

    unavailable_types = (
        IntegrationUnavailableError,
        RuntimeConfigurationError,
        WorkerExecutionError,
    )

    async def handle_unavailable(_request: Request, _exc: Exception) -> JSONResponse:
        return _error_response(
            503,
            APIError(
                code="SERVICE_UNAVAILABLE",
                message="A required service is unavailable",
            ),
        )

    for unavailable_type in unavailable_types:
        app.add_exception_handler(unavailable_type, handle_unavailable)
