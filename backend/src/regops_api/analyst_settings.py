"""Worker-only settings: do not change the API's startup/composition."""

from __future__ import annotations

import os
from typing import Self

from pydantic import Field, ValidationError, model_validator

from regops_api.analyst_errors import AnalystCode, AnalystError
from regops_api.config import DEFAULT_MAX_UPLOAD_BYTES, RuntimeMode, RuntimeSettings
from regops_api.worker_models import MAX_PAGE_TEXT, WorkerModel


class PdfLimits(WorkerModel):
    max_bytes: int = Field(default=DEFAULT_MAX_UPLOAD_BYTES, ge=1024, le=DEFAULT_MAX_UPLOAD_BYTES)
    max_pages: int = Field(default=100, ge=1, le=100)
    max_page_chars: int = Field(default=MAX_PAGE_TEXT, ge=1, le=MAX_PAGE_TEXT)
    max_total_chars: int = Field(default=200_000, ge=1, le=2_000_000)
    timeout_seconds: int = Field(default=10, ge=1, le=30)


class AnalystSettings(WorkerModel):
    model: str = Field(default="gemini-3.5-flash", pattern=r"^gemini-[a-zA-Z0-9.-]{1,100}$")
    pdf: PdfLimits = PdfLimits()
    max_output_tokens: int = Field(default=8192, ge=128, le=16384)
    max_output_chars: int = Field(default=32_000, ge=1, le=64_000)
    max_response_bytes: int = Field(default=128_000, ge=1, le=256_000)
    timeout_seconds: int = Field(default=90, ge=1, le=90)
    stage_timeout_seconds: int = Field(default=210, ge=1, le=210)
    max_attempts: int = Field(default=3, ge=1, le=3)
    armor_timeout_seconds: int = Field(default=10, ge=1, le=30)
    armor_input_template: str | None = Field(default=None, repr=False)
    armor_output_template: str | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def bounded_timeout(self) -> Self:
        if self.timeout_seconds > self.stage_timeout_seconds:
            raise ValueError("INVALID_TIMEOUT_BUDGET")
        return self

    @classmethod
    def from_env(cls, runtime: RuntimeSettings) -> AnalystSettings:
        try:
            return cls(
                model=os.getenv("REGOPS_GEMINI_MODEL", "gemini-3.5-flash"),
                pdf=PdfLimits(
                    max_bytes=min(runtime.max_upload_bytes, DEFAULT_MAX_UPLOAD_BYTES),
                    max_pages=int(os.getenv("REGOPS_PDF_MAX_PAGES", "100")),
                    max_page_chars=int(os.getenv("REGOPS_PDF_MAX_PAGE_CHARS", "20000")),
                    max_total_chars=int(os.getenv("REGOPS_PDF_MAX_TOTAL_CHARS", "200000")),
                ),
                armor_input_template=os.getenv("REGOPS_ARMOR_INPUT_TEMPLATE"),
                armor_output_template=os.getenv("REGOPS_ARMOR_OUTPUT_TEMPLATE"),
            )
        except (ValueError, ValidationError):
            pass
        raise AnalystError(AnalystCode.ANALYST_CONFIGURATION_INVALID)

    def validate_demo(self, runtime: RuntimeSettings) -> None:
        import re

        if (
            runtime.mode is not RuntimeMode.DEMO
            or not runtime.project_id
            or not runtime.armor_location
            or not runtime.gemini_location
            or not re.fullmatch(r"[a-z][a-z0-9-]{2,62}", runtime.project_id)
            or not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", runtime.armor_location)
            or not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", runtime.gemini_location)
            or self.pdf.max_bytes > runtime.max_upload_bytes
        ):
            raise AnalystError(AnalystCode.ANALYST_CONFIGURATION_INVALID)
        prefix = f"projects/{runtime.project_id}/locations/{runtime.armor_location}/templates/"
        for template in (self.armor_input_template, self.armor_output_template):
            if not template or not re.fullmatch(re.escape(prefix) + r"[A-Za-z0-9_-]+", template):
                raise AnalystError(AnalystCode.ANALYST_CONFIGURATION_INVALID)
        # Do not let ambient SDK modes, alternate endpoints or message capture
        # turn a cloud deployment into a Developer API or diagnostic fallback.
        forbidden = (
            "GOOGLE_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_GEMINI_BASE_URL",
            "GOOGLE_VERTEX_BASE_URL",
            "GOOGLE_GENAI_BASE_URL",
        )
        if any(os.getenv(name) for name in forbidden) or os.getenv(
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "false"
        ).lower() not in {"false", "0", ""}:
            raise AnalystError(AnalystCode.ANALYST_CONFIGURATION_INVALID)
