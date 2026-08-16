from pathlib import Path

import yaml
from fastapi.routing import APIRoute

from regops_api.main import API_PREFIX, app

EXPECTED_PATHS = {
    "/api/v1/health",
    "/api/v1/runs",
    "/api/v1/runs/{run_id}",
    "/api/v1/runs/{run_id}/findings",
    "/api/v1/findings/{finding_id}",
    "/api/v1/actions/{action_id}/preview",
    "/api/v1/approvals/{approval_id}/decision",
    "/api/v1/runs/{run_id}/audit",
}


def test_fastapi_exposes_exactly_eight_api_paths() -> None:
    paths = {
        route.path
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith(API_PREFIX)
    }

    assert paths == EXPECTED_PATHS


def test_run_intake_openapi_is_multipart_and_accepted() -> None:
    operation = app.openapi()["paths"]["/api/v1/runs"]["post"]
    request_body = operation["requestBody"]
    body_schema = request_body["content"]["multipart/form-data"]["schema"]
    component_name = body_schema["$ref"].rsplit("/", 1)[-1]
    component = app.openapi()["components"]["schemas"][component_name]

    assert request_body["required"] is True
    assert set(component["required"]) == {"regulation_file", "synthetic_ack"}
    assert (
        component["properties"]["regulation_file"]["contentMediaType"]
        == "application/pdf"
    )
    assert "202" in operation["responses"]


def test_approval_decision_openapi_never_exposes_reviewer_identity() -> None:
    generated_schema = app.openapi()["components"]["schemas"]["ApprovalDecision"]
    contract_path = Path(__file__).resolve().parents[2] / "contracts" / "openapi.yaml"
    authored = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    authored_schema = authored["components"]["schemas"]["ApprovalDecision"]

    for schema in (authored_schema, generated_schema):
        assert set(schema["properties"]) == {"decision", "note"}
        assert schema["required"] == ["decision"]
        assert schema["additionalProperties"] is False
