"""Sanitized runtime errors mapped centrally to frozen APIError responses."""


class RuntimeConfigurationError(RuntimeError):
    """Required mode configuration is absent or unsafe."""


class DocumentTooLargeError(ValueError):
    """Uploaded content exceeds the configured intake limit."""


class UnsupportedDocumentError(ValueError):
    """Uploaded content is not an accepted synthetic PDF."""


class DomainConflictError(RuntimeError):
    """A binding, lifecycle, or idempotency invariant rejected the operation."""
