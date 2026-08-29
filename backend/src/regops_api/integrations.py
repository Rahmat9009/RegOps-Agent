"""Fail-closed ports for cloud integrations deferred beyond Phase 1A."""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

from regops_api.domain_models import (
    AnalystOutput,
    InvestigatorOutput,
    SourceDocumentRecord,
    StoredSourceObject,
    WorkflowLaunchRequest,
)
from regops_api.schemas import Obligation, Regulation

StructuredOutput = TypeVar("StructuredOutput", bound=BaseModel)


class IntegrationUnavailableError(RuntimeError):
    """Raised when production requires an integration that has not been configured."""


class GeminiStructuredClient(Protocol):
    def generate_structured(
        self,
        *,
        prompt: str,
        output_model: type[StructuredOutput],
    ) -> StructuredOutput: ...


class GoogleAdkRuntime(Protocol):
    def run_agent(self, *, role: str, payload: BaseModel) -> BaseModel: ...


class CloudStoragePort(Protocol):
    def put(self, *, object_name: str, content: bytes, content_type: str) -> str: ...

    def get(self, *, object_name: str) -> bytes: ...


class RuntimeStoragePort(Protocol):
    def store_source(
        self,
        *,
        run_id: str,
        content: bytes,
        content_type: str,
    ) -> StoredSourceObject: ...

    def delete_source(self, *, run_id: str, object_name: str) -> None: ...

    def read_bound_source(self, *, record: SourceDocumentRecord, max_bytes: int) -> bytes: ...

    def store_audit_package_and_sign(
        self,
        *,
        run_id: str,
        content: bytes,
    ) -> str | None: ...


class WorkflowLauncher(Protocol):
    def launch(self, request: WorkflowLaunchRequest) -> str: ...


class ReviewerIdentityProvider(Protocol):
    def reviewer_id(self) -> str: ...


class GoogleWorkflowsApprovalPort(Protocol):
    def request_approval(self, *, approval_id: str, callback_payload: BaseModel) -> None: ...


class MissingIntegration:
    """Explicit production placeholder that always fails; it never returns demo data."""

    def __init__(self, integration_name: str) -> None:
        self._integration_name = integration_name

    def fail(self) -> None:
        raise IntegrationUnavailableError(
            f"required production integration {self._integration_name!r} is unavailable"
        )


class UnavailableRegulationAnalyst:
    """Fail-closed production role; it never fabricates an extraction."""

    def analyze(self, *, regulation: Regulation, content: bytes) -> AnalystOutput:
        del regulation, content
        raise IntegrationUnavailableError(
            "Gemini/Vertex analyst integration is required and unavailable"
        )


class UnavailableImpactInvestigator:
    """Fail-closed production role; it never fabricates findings."""

    def investigate(
        self, *, run_id: str, obligations: list[Obligation]
    ) -> InvestigatorOutput:
        del run_id, obligations
        raise IntegrationUnavailableError(
            "impact-investigator integration is required and unavailable"
        )
