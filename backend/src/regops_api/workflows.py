"""Asynchronous Google Workflows execution launcher."""

from __future__ import annotations

import json

from google.cloud.workflows import executions_v1

from regops_api.domain_models import WorkflowLaunchRequest
from regops_api.integrations import IntegrationUnavailableError


class GoogleWorkflowsLauncher:
    def __init__(
        self,
        *,
        client: executions_v1.ExecutionsClient,
        project_id: str,
        region: str,
        workflow_name: str,
    ) -> None:
        self._client = client
        self._parent = (
            f"projects/{project_id}/locations/{region}/workflows/{workflow_name}"
        )

    def launch(self, request: WorkflowLaunchRequest) -> str:
        safe_argument = json.dumps(request.model_dump(mode="json"), separators=(",", ":"))
        try:
            execution = self._client.create_execution(
                request={
                    "parent": self._parent,
                    "execution": {"argument": safe_argument},
                }
            )
        except Exception as error:
            raise IntegrationUnavailableError(
                "workflow execution could not be started"
            ) from error
        return str(execution.name)
