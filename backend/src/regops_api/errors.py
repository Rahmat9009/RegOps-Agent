"""Structured API exceptions and FastAPI exception handlers."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from regops_api.schemas import APIError, ErrorDetail


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
