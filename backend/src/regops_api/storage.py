"""Private Cloud Storage object layout and backend-only signed downloads."""

from __future__ import annotations

import re
from datetime import timedelta
from hashlib import sha256
from hmac import compare_digest
from pathlib import PurePosixPath
from typing import Any, Protocol
from urllib.parse import urlsplit

from google.auth.transport.requests import Request as AuthRequest
from google.cloud.storage.client import Client as StorageClient

from regops_api.domain_models import SourceDocumentRecord, StoredSourceObject
from regops_api.integrations import IntegrationUnavailableError

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


class RefreshableCredentials(Protocol):
    token: str | None
    valid: bool

    def refresh(self, request: Any) -> None: ...


def sanitize_filename(filename: str) -> str:
    leaf = PurePosixPath(filename.replace("\\", "/")).name
    sanitized = _SAFE_FILENAME.sub("-", leaf).strip(".-")
    return sanitized[:200] or "regulation.pdf"


def source_object_name(run_id: str) -> str:
    return f"runs/{run_id}/source/regulation.pdf"


def audit_object_name(run_id: str) -> str:
    return f"runs/{run_id}/audit/audit-package.json"


class GoogleCloudStorageAdapter:
    """Stores private run-scoped objects and signs downloads without logging URLs."""

    def __init__(
        self,
        *,
        client: StorageClient,
        bucket_name: str,
        signed_url_ttl_seconds: int,
        credentials: RefreshableCredentials | None = None,
        auth_request: Any | None = None,
        signer_service_account: str | None = None,
    ) -> None:
        self._bucket = client.bucket(bucket_name)
        self._bucket_name = bucket_name
        self._signed_url_ttl = signed_url_ttl_seconds
        self._credentials = credentials
        self._auth_request = auth_request
        self._signer_service_account = signer_service_account

    def store_source(
        self,
        *,
        run_id: str,
        content: bytes,
        content_type: str,
    ) -> StoredSourceObject:
        object_name = source_object_name(run_id)
        try:
            blob = self._bucket.blob(object_name)
            blob.upload_from_string(
                content,
                content_type=content_type,
                if_generation_match=0,
            )
        except Exception as error:
            raise IntegrationUnavailableError("private source storage is unavailable") from error
        return StoredSourceObject(
            object_name=object_name,
            gcs_uri=f"gs://{self._bucket_name}/{object_name}",
        )

    def delete_source(self, *, run_id: str, object_name: str) -> None:
        expected = source_object_name(run_id)
        if object_name != expected:
            raise ValueError("source cleanup is restricted to the exact run object")
        try:
            self._bucket.blob(expected).delete()
        except Exception as error:
            raise IntegrationUnavailableError("private source cleanup is unavailable") from error

    def read_bound_source(self, *, record: SourceDocumentRecord, max_bytes: int) -> bytes:
        expected = source_object_name(record.run_id)
        expected_uri = f"gs://{self._bucket_name}/{expected}"
        if (
            record.object_name != expected
            or record.gcs_uri != expected_uri
            or record.size_bytes > max_bytes
            or record.content_type != "application/pdf"
            or record.synthetic is not True
        ):
            raise ValueError("source binding does not identify the exact run object")
        try:
            content = self._bucket.blob(expected).download_as_bytes(
                start=0,
                end=max_bytes,
            )
        except Exception as error:
            raise IntegrationUnavailableError("private source reading is unavailable") from error
        if (
            len(content) > max_bytes
            or len(content) != record.size_bytes
            or not compare_digest(sha256(content).hexdigest(), record.source_sha256)
        ):
            raise ValueError("source content does not match persisted metadata")
        return bytes(content)

    def store_audit_package_and_sign(
        self,
        *,
        run_id: str,
        content: bytes,
    ) -> str:
        object_name = audit_object_name(run_id)
        try:
            blob = self._bucket.blob(object_name)
            blob.upload_from_string(
                content,
                content_type="application/json",
            )
            signing: dict[str, object] = {}
            if self._signer_service_account is not None:
                if self._credentials is None:
                    raise ValueError("ADC signer credentials are unavailable")
                if not self._credentials.valid or not self._credentials.token:
                    request = self._auth_request or AuthRequest()
                    self._credentials.refresh(request)
                if not self._credentials.token:
                    raise ValueError("ADC refresh returned no access token")
                signing = {
                    "service_account_email": self._signer_service_account,
                    "access_token": self._credentials.token,
                }
            signed_url = str(
                blob.generate_signed_url(
                    version="v4",
                    expiration=timedelta(seconds=self._signed_url_ttl),
                    method="GET",
                    **signing,
                )
            )
            parsed = urlsplit(signed_url)
            if parsed.scheme.lower() != "https" or not parsed.hostname:
                raise ValueError("signer did not return an absolute HTTPS URL")
            return signed_url
        except Exception as error:
            raise IntegrationUnavailableError("audit package signing is unavailable") from error
