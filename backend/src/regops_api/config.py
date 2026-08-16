"""Explicit runtime modes and fail-closed startup configuration."""

from __future__ import annotations

import os
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from regops_api.runtime_errors import RuntimeConfigurationError

DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class RuntimeMode(StrEnum):
    TEST = "test"
    DEMO = "demo"
    PRODUCTION = "production"


class RuntimeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: RuntimeMode = RuntimeMode.PRODUCTION
    project_id: str | None = None
    region: str | None = None
    bucket: str | None = None
    workflow_name: str | None = None
    max_upload_bytes: int = Field(default=DEFAULT_MAX_UPLOAD_BYTES, ge=1024)
    signed_url_ttl_seconds: int = Field(default=300, ge=60, le=900)

    @classmethod
    def from_env(cls) -> RuntimeSettings:
        max_upload = os.getenv("REGOPS_MAX_UPLOAD_BYTES")
        signed_url_ttl = os.getenv("REGOPS_SIGNED_URL_TTL_SECONDS")
        return cls(
            mode=RuntimeMode(
                os.getenv("REGOPS_MODE", RuntimeMode.PRODUCTION.value)
            ),
            project_id=os.getenv("GOOGLE_CLOUD_PROJECT"),
            region=os.getenv("REGOPS_REGION"),
            bucket=os.getenv("REGOPS_BUCKET"),
            workflow_name=os.getenv("REGOPS_WORKFLOW"),
            max_upload_bytes=(
                int(max_upload) if max_upload is not None else DEFAULT_MAX_UPLOAD_BYTES
            ),
            signed_url_ttl_seconds=(
                int(signed_url_ttl) if signed_url_ttl is not None else 300
            ),
        )

    def validate_startup(self) -> None:
        if self.mode is RuntimeMode.TEST:
            return
        missing = [
            name
            for name, value in (
                ("GOOGLE_CLOUD_PROJECT", self.project_id),
                ("REGOPS_REGION", self.region),
                ("REGOPS_BUCKET", self.bucket),
                ("REGOPS_WORKFLOW", self.workflow_name),
            )
            if not value
        ]
        if missing:
            raise RuntimeConfigurationError(
                "persistent runtime configuration is incomplete: " + ", ".join(missing)
            )
