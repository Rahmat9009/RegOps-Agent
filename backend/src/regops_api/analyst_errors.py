"""Fixed internal failures; never retain a vendor exception or payload."""

from enum import StrEnum
from math import isfinite


class AnalystCode(StrEnum):
    PDF_INVALID = "PDF_INVALID"
    PDF_ENCRYPTED = "PDF_ENCRYPTED"
    PDF_TOO_LARGE = "PDF_TOO_LARGE"
    PDF_PAGE_LIMIT = "PDF_PAGE_LIMIT"
    PDF_TEXT_UNAVAILABLE = "PDF_TEXT_UNAVAILABLE"
    PDF_TEXT_LIMIT = "PDF_TEXT_LIMIT"
    SOURCE_BINDING_MISMATCH = "SOURCE_BINDING_MISMATCH"
    ANALYST_CONFIGURATION_INVALID = "ANALYST_CONFIGURATION_INVALID"
    MODEL_ARMOR_INPUT_BLOCKED = "MODEL_ARMOR_INPUT_BLOCKED"
    MODEL_ARMOR_OUTPUT_BLOCKED = "MODEL_ARMOR_OUTPUT_BLOCKED"
    MODEL_ARMOR_UNAVAILABLE = "MODEL_ARMOR_UNAVAILABLE"
    MODEL_ARMOR_MALFORMED_RESPONSE = "MODEL_ARMOR_MALFORMED_RESPONSE"
    MODEL_ARMOR_REJECTED = "MODEL_ARMOR_REJECTED"
    GEMINI_TIMEOUT = "GEMINI_TIMEOUT"
    GEMINI_RATE_LIMITED = "GEMINI_RATE_LIMITED"
    GEMINI_UNAVAILABLE = "GEMINI_UNAVAILABLE"
    GEMINI_REQUEST_REJECTED = "GEMINI_REQUEST_REJECTED"
    GEMINI_REFUSED = "GEMINI_REFUSED"
    GEMINI_MALFORMED_OUTPUT = "GEMINI_MALFORMED_OUTPUT"


class AnalystError(RuntimeError):
    def __init__(self, code: AnalystCode, *, retry_after_seconds: float = 0) -> None:
        self.code = code
        self.retry_after_seconds = (
            min(4.0, max(0.0, retry_after_seconds)) if isfinite(retry_after_seconds) else 0.0
        )
        super().__init__(code.value)

    @property
    def transient(self) -> bool:
        return self.code in {
            AnalystCode.MODEL_ARMOR_UNAVAILABLE,
            AnalystCode.GEMINI_TIMEOUT,
            AnalystCode.GEMINI_RATE_LIMITED,
            AnalystCode.GEMINI_UNAVAILABLE,
        }
