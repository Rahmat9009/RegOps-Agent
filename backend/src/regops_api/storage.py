"""Private Cloud Storage object layout and backend-only signed downloads."""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from hashlib import sha256
from hmac import compare_digest
from pathlib import PurePosixPath
from typing import Any, cast
from urllib.parse import parse_qs, unquote, urlsplit

import google.auth
from google.auth import iam
from google.auth.credentials import (
    Credentials,
    ReadOnlyScoped,
    Signing,
    with_scopes_if_required,
)
from google.auth.transport.requests import Request as AuthRequest
from google.cloud.storage.client import Client as StorageClient

from regops_api.domain_models import SourceDocumentRecord, StoredSourceObject
from regops_api.integrations import IntegrationUnavailableError

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_LOGGER = logging.getLogger(__name__)

IAM_SCOPE = "https://www.googleapis.com/auth/iam"
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
IAM_SIGNING_SCOPES = (CLOUD_PLATFORM_SCOPE,)


def _validate_run_id(run_id: str) -> None:
    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise ValueError("run ID cannot identify a private object path")


def signing_scope_valid(credentials: object) -> bool:
    if not isinstance(credentials, ReadOnlyScoped):
        return False
    return any(
        cast(Any, credentials).has_scopes((scope,))
        for scope in (IAM_SCOPE, CLOUD_PLATFORM_SCOPE)
    )


class IamSignBlobCredentials(Signing):
    """V4 Signing interface backed only by remote IAM signBlob."""

    def __init__(
        self,
        *,
        request: Any,
        caller_credentials: Credentials,
        signer_service_account: str,
    ) -> None:
        if isinstance(caller_credentials, Signing):
            raise ValueError("key-backed or self-signing credentials are not accepted")
        if not signing_scope_valid(caller_credentials):
            raise ValueError("IAM signing credentials lack an approved scope")
        caller_email = getattr(caller_credentials, "service_account_email", None)
        if isinstance(caller_email, str) and caller_email == signer_service_account:
            raise ValueError("IAM caller and dedicated signer must be distinct")
        self._signer_email = signer_service_account
        self._signer = iam.Signer(  # type: ignore[no-untyped-call]
            request, caller_credentials, signer_service_account
        )

    @property
    def signer_email(self) -> str:
        return self._signer_email

    @property
    def signer(self) -> iam.Signer:
        return self._signer

    def sign_bytes(self, message: bytes) -> bytes:
        return cast(bytes, self._signer.sign(message))


def build_iam_signing_credentials(
    *,
    signer_service_account: str,
    caller_credentials: Credentials | None = None,
    auth_request: Any | None = None,
) -> IamSignBlobCredentials:
    """Build a keyless signer from separately scoped ADC caller credentials."""
    request = auth_request or AuthRequest()
    if caller_credentials is None:
        caller_credentials, _ = google.auth.default(
            scopes=IAM_SIGNING_SCOPES,
            request=request,
        )
    else:
        caller_credentials = with_scopes_if_required(  # type: ignore[no-untyped-call]
            caller_credentials,
            scopes=IAM_SIGNING_SCOPES,
        )
    return IamSignBlobCredentials(
        request=request,
        caller_credentials=caller_credentials,
        signer_service_account=signer_service_account,
    )


def sanitize_filename(filename: str) -> str:
    leaf = PurePosixPath(filename.replace("\\", "/")).name
    sanitized = _SAFE_FILENAME.sub("-", leaf).strip(".-")
    return sanitized[:200] or "regulation.pdf"


def source_object_name(run_id: str) -> str:
    _validate_run_id(run_id)
    return f"runs/{run_id}/source/regulation.pdf"


def audit_object_name(run_id: str) -> str:
    _validate_run_id(run_id)
    return f"runs/{run_id}/audit/audit-package.json"


class GoogleCloudStorageAdapter:
    """Stores private run-scoped objects and signs downloads without logging URLs."""

    def __init__(
        self,
        *,
        client: StorageClient,
        bucket_name: str,
        signed_url_ttl_seconds: int,
        signing_credentials: Signing | None = None,
    ) -> None:
        if not 60 <= signed_url_ttl_seconds <= 900:
            raise ValueError("signed URL expiry must be between 60 and 900 seconds")
        self._bucket = client.bucket(bucket_name)
        self._bucket_name = bucket_name
        self._signed_url_ttl = signed_url_ttl_seconds
        self._signing_credentials = signing_credentials

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
    ) -> str | None:
        object_name = audit_object_name(run_id)
        upload_succeeded = False
        try:
            blob = self._bucket.blob(object_name)
            blob.upload_from_string(
                content,
                content_type="application/json",
            )
        except Exception:
            pass
        else:
            upload_succeeded = True
        if not upload_succeeded:
            raise IntegrationUnavailableError("audit package upload is unavailable")
        try:
            if self._signing_credentials is None:
                raise ValueError("keyless IAM signer is unavailable")
            signed_url = str(
                blob.generate_signed_url(
                    version="v4",
                    expiration=timedelta(seconds=self._signed_url_ttl),
                    method="GET",
                    credentials=self._signing_credentials,
                )
            )
            parsed = urlsplit(signed_url)
            query = parse_qs(parsed.query, keep_blank_values=True)
            expected_path = f"/{self._bucket_name}/{object_name}"
            credential = query.get("X-Goog-Credential", [""])
            expires = query.get("X-Goog-Expires", [""])
            if (
                parsed.scheme.lower() != "https"
                or parsed.hostname != "storage.googleapis.com"
                or unquote(parsed.path) != expected_path
                or query.get("X-Goog-Algorithm") != ["GOOG4-RSA-SHA256"]
                or len(credential) != 1
                or not credential[0].startswith(
                    f"{self._signing_credentials.signer_email}/"
                )
                or expires != [str(self._signed_url_ttl)]
                or len(query.get("X-Goog-Date", [])) != 1
                or len(query.get("X-Goog-SignedHeaders", [])) != 1
                or len(query.get("X-Goog-Signature", [])) != 1
                or not query["X-Goog-Signature"][0]
            ):
                raise ValueError("signer did not return the exact V4 HTTPS URL")
            return signed_url
        except Exception:
            _LOGGER.warning("AUDIT_SIGNING_UNAVAILABLE")
            return None
