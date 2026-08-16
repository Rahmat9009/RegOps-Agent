"""Private Cloud Storage object layout and backend-only signed downloads."""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from google.cloud.storage.client import Client as StorageClient

from regops_api.domain_models import StoredSourceObject
from regops_api.integrations import IntegrationUnavailableError

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


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
    ) -> None:
        self._bucket = client.bucket(bucket_name)
        self._bucket_name = bucket_name
        self._signed_url_ttl = signed_url_ttl_seconds

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
            raise IntegrationUnavailableError(
                "private source storage is unavailable"
            ) from error
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
            raise IntegrationUnavailableError(
                "private source cleanup is unavailable"
            ) from error

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
            signed_url = str(
                blob.generate_signed_url(
                    version="v4",
                    expiration=timedelta(seconds=self._signed_url_ttl),
                    method="GET",
                )
            )
            parsed = urlsplit(signed_url)
            if parsed.scheme.lower() != "https" or not parsed.hostname:
                raise ValueError("signer did not return an absolute HTTPS URL")
            return signed_url
        except Exception as error:
            raise IntegrationUnavailableError(
                "audit package signing is unavailable"
            ) from error
