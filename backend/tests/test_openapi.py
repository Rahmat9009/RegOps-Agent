from pathlib import Path
from typing import Any, cast

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
EXPECTED_RUN_STATES = [
    "INGESTED",
    "EXTRACTING",
    "EXTRACTED",
    "MAPPING",
    "MAPPED",
    "VERIFYING",
    "VERIFIED",
    "AWAITING_APPROVAL",
    "EXECUTING",
    "REVALIDATING",
    "COMPLETED",
    "FAILED_RECOVERABLE",
    "FAILED",
]
HTTPS_URL_PATTERN = r"^[Hh][Tt][Tt][Pp][Ss]://[^/?#\s]+"


def authored_openapi() -> dict[str, Any]:
    contract_path = Path(__file__).resolve().parents[2] / "contracts" / "openapi.yaml"
    return cast(
        dict[str, Any], yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    )


def test_fastapi_exposes_exactly_eight_api_paths() -> None:
    paths = {
        route.path
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith(API_PREFIX)
    }

    assert paths == EXPECTED_PATHS

    authored = authored_openapi()
    assert {f"{API_PREFIX}{path}" for path in authored["paths"]} == EXPECTED_PATHS


def test_all_thirteen_run_states_are_unchanged_in_both_specs() -> None:
    generated = app.openapi()
    authored = authored_openapi()

    for spec in (authored, generated):
        assert spec["components"]["schemas"]["RunState"]["enum"] == EXPECTED_RUN_STATES


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
    authored = authored_openapi()
    authored_schema = authored["components"]["schemas"]["ApprovalDecision"]

    for schema in (authored_schema, generated_schema):
        assert set(schema["properties"]) == {"decision", "note"}
        assert schema["required"] == ["decision"]
        assert schema["additionalProperties"] is False


def test_workflow_metadata_and_relationships_match_both_specs() -> None:
    for spec in (authored_openapi(), app.openapi()):
        schemas = spec["components"]["schemas"]
        assert "scores" in schemas["FindingSummary"]["required"]
        assert "finding_id" in schemas["Approval"]["required"]
        assert "transitions" in schemas["Run"]["required"]
        assert schemas["Run"]["properties"]["recovery"]["anyOf"][-1] == {
            "type": "null"
        }
        assert schemas["Run"]["properties"]["change_detection"]["anyOf"][-1] == {
            "type": "null"
        }
        assert set(schemas["RunTransition"]["required"]) == {
            "from_state",
            "to_state",
            "occurred_at",
            "reason",
            "actor",
        }
        assert set(schemas["RecoveryInfo"]["properties"]) == {
            "recovery_available",
            "checkpoint_state",
            "attempt_count",
            "last_error_code",
            "last_error_message",
        }
        assert schemas["RecoveryInfo"]["if"] == {
            "properties": {"recovery_available": {"const": True}},
            "required": ["recovery_available"],
        }
        assert schemas["RecoveryInfo"]["then"] == {
            "properties": {"checkpoint_state": {"not": {"type": "null"}}}
        }
        assert schemas["Run"]["properties"]["transitions"]["minItems"] == 1
        transition_list = schemas["Run"]["properties"]["transitions"]
        first_transition_rules = transition_list["prefixItems"][0]["allOf"]
        assert {rule.get("$ref") for rule in first_transition_rules} == {
            None,
            "#/components/schemas/RunTransition",
        }
        initial_state_rule = next(
            rule for rule in first_transition_rules if "properties" in rule
        )
        assert initial_state_rule["properties"]["from_state"] == {
            "type": "null"
        }
        transition = schemas["RunTransition"]["properties"]
        assert transition["actor"]["minLength"] == 1
        assert transition["reason"]["anyOf"][0]["minLength"] == 1
        change = schemas["ChangeDetection"]["properties"]
        assert change["source_sha256"]["pattern"] == "^[0-9a-f]{64}$"
        assert change["previous_source_sha256"]["anyOf"][0]["pattern"] == (
            "^[0-9a-f]{64}$"
        )


def test_findings_pagination_matches_both_specs() -> None:
    for path, spec in (
        ("/runs/{run_id}/findings", authored_openapi()),
        ("/api/v1/runs/{run_id}/findings", app.openapi()),
    ):
        operation = spec["paths"][path]["get"]
        parameters = {item["name"]: item for item in operation["parameters"] if "name" in item}

        assert parameters["limit"]["schema"] == {
            "type": "integer",
            "default": 50,
            "minimum": 1,
            "maximum": 100,
        } | ({"title": "Limit"} if path.startswith("/api/v1") else {})
        assert parameters["offset"]["schema"] == {
            "type": "integer",
            "default": 0,
            "minimum": 0,
        } | ({"title": "Offset"} if path.startswith("/api/v1") else {})
        finding_list = spec["components"]["schemas"]["FindingList"]
        assert set(finding_list["required"]) == {
            "items",
            "total",
            "limit",
            "offset",
            "by_severity",
        }
        properties = finding_list["properties"]
        assert "selected page" in properties["items"]["description"].lower()
        assert "active filters before pagination" in properties["total"][
            "description"
        ].lower()
        assert "complete filtered result before pagination" in properties[
            "by_severity"
        ]["description"].lower()


def test_audit_url_and_rejection_semantics_are_authored() -> None:
    authored = authored_openapi()
    decision = authored["paths"]["/approvals/{approval_id}/decision"]["post"]

    for spec in (authored, app.openapi()):
        audit_url = spec["components"]["schemas"]["AuditReport"]["properties"][
            "audit_package_url"
        ]
        non_null = next(
            variant for variant in audit_url["anyOf"] if variant.get("type") == "string"
        )
        assert non_null["format"] == "uri"
        assert non_null["pattern"] == HTTPS_URL_PATTERN
        assert "short-lived, absolute https signed download url" in audit_url[
            "description"
        ].lower()
        assert "clients never submit this response-only value" in audit_url[
            "description"
        ].lower()
    assert "never executes" in decision["description"]
    assert "directly from AWAITING_APPROVAL to COMPLETED" in decision["description"]
    assert "never transitions a run to FAILED" in decision["description"]

    for path_item in authored["paths"].values():
        for operation in path_item.values():
            request_body = operation.get("requestBody", {})
            assert "audit_package_url" not in yaml.safe_dump(request_body)
