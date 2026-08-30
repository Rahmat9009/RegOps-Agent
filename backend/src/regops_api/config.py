"""Explicit runtime modes and fail-closed startup configuration."""

from __future__ import annotations

import os
import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    workflow_region: str | None = None
    armor_location: str | None = None
    gemini_location: str | None = None
    bucket: str | None = None
    workflow_name: str | None = None
    workflow_service_account: str | None = None
    worker_audience: str | None = None
    audit_signer_service_account: str | None = None
    cors_origins: tuple[str, ...] = ()
    max_upload_bytes: int = Field(default=DEFAULT_MAX_UPLOAD_BYTES, ge=1024)
    signed_url_ttl_seconds: int = Field(default=300, ge=60, le=900)

    @model_validator(mode="after")
    def legacy_region_fallback(self) -> RuntimeSettings:
        if self.region:
            self.workflow_region = self.workflow_region or self.region
            self.armor_location = self.armor_location or self.region
            self.gemini_location = self.gemini_location or self.region
        return self

    @classmethod
    def from_env(cls) -> RuntimeSettings:
        max_upload = os.getenv("REGOPS_MAX_UPLOAD_BYTES")
        signed_url_ttl = os.getenv("REGOPS_SIGNED_URL_TTL_SECONDS")
        legacy_region = os.getenv("REGOPS_REGION")
        origins = tuple(
            origin.strip()
            for origin in os.getenv("REGOPS_CORS_ORIGINS", "").split(",")
            if origin.strip()
        )
        return cls(
            mode=RuntimeMode(os.getenv("REGOPS_MODE", RuntimeMode.PRODUCTION.value)),
            project_id=os.getenv("GOOGLE_CLOUD_PROJECT"),
            region=legacy_region,
            workflow_region=os.getenv("REGOPS_WORKFLOW_REGION") or legacy_region,
            armor_location=os.getenv("REGOPS_ARMOR_LOCATION") or legacy_region,
            gemini_location=os.getenv("REGOPS_GEMINI_LOCATION") or legacy_region,
            bucket=os.getenv("REGOPS_BUCKET"),
            workflow_name=os.getenv("REGOPS_WORKFLOW"),
            workflow_service_account=os.getenv("REGOPS_WORKFLOW_SERVICE_ACCOUNT"),
            worker_audience=os.getenv("REGOPS_WORKER_AUDIENCE"),
            audit_signer_service_account=os.getenv("REGOPS_AUDIT_SIGNER_SERVICE_ACCOUNT"),
            cors_origins=origins,
            max_upload_bytes=(
                int(max_upload) if max_upload is not None else DEFAULT_MAX_UPLOAD_BYTES
            ),
            signed_url_ttl_seconds=(int(signed_url_ttl) if signed_url_ttl is not None else 300),
        )

    def validate_startup(self) -> None:
        if self.mode is RuntimeMode.TEST:
            self.validate_cors()
            return
        missing = [
            name
            for name, value in (
                ("GOOGLE_CLOUD_PROJECT", self.project_id),
                ("REGOPS_WORKFLOW_REGION", self.workflow_region),
                ("REGOPS_ARMOR_LOCATION", self.armor_location),
                ("REGOPS_GEMINI_LOCATION", self.gemini_location),
                ("REGOPS_BUCKET", self.bucket),
                ("REGOPS_WORKFLOW", self.workflow_name),
                ("REGOPS_WORKFLOW_SERVICE_ACCOUNT", self.workflow_service_account),
                ("REGOPS_WORKER_AUDIENCE", self.worker_audience),
                (
                    "REGOPS_AUDIT_SIGNER_SERVICE_ACCOUNT",
                    self.audit_signer_service_account,
                ),
                ("REGOPS_CORS_ORIGINS", self.cors_origins),
            )
            if not value
        ]
        if missing:
            raise RuntimeConfigurationError(
                "persistent runtime configuration is incomplete: " + ", ".join(missing)
            )
        service_account = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.gserviceaccount\.com"
        if (
            not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", self.workflow_region or "")
            or not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", self.armor_location or "")
            or not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", self.gemini_location or "")
            or not re.fullmatch(service_account, self.workflow_service_account or "")
            or not re.fullmatch(
                service_account, self.audit_signer_service_account or ""
            )
            or not re.fullmatch(r"https://[^/?#\s]+(?:/[^?#\s]*)?", self.worker_audience or "")
        ):
            raise RuntimeConfigurationError("persistent cloud identity or location is invalid")
        self.validate_cors()

    def validate_cors(self) -> None:
        if len(set(self.cors_origins)) != len(self.cors_origins):
            raise RuntimeConfigurationError("CORS origins must be unique")
        for origin in self.cors_origins:
            if origin == "*" or origin.endswith("/"):
                raise RuntimeConfigurationError("CORS origins must be exact origins")
            if re.fullmatch(r"https://[A-Za-z0-9.-]+(?::[0-9]{1,5})?", origin):
                continue
            if self.mode in {RuntimeMode.TEST, RuntimeMode.DEMO} and re.fullmatch(
                r"http://(?:localhost|127\.0\.0\.1)(?::[0-9]{1,5})?", origin
            ):
                continue
            raise RuntimeConfigurationError("cloud CORS origins must be exact HTTPS origins")
