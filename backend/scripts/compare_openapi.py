"""Compare material API semantics between FastAPI and the authored contract."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, cast

import yaml

from regops_api.main import API_PREFIX, app

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
HTTPS_URL_PATTERN = r"^[Hh][Tt][Tt][Pp][Ss]://[^/?#\s]+"
REQUIRED_SCHEMAS = {
    "Run",
    "RunTransition",
    "RecoveryInfo",
    "ChangeDetection",
    "RunProgress",
    "Regulation",
    "Obligation",
    "EvidenceReference",
    "Finding",
    "FindingSummary",
    "FindingScores",
    "FindingList",
    "FindingsBySeverity",
    "ProposedAction",
    "CounterfactualPreview",
    "Approval",
    "ApprovalDecision",
    "AuditReport",
    "APIError",
}


def operations(spec: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        (path, method)
        for path, path_item in spec["paths"].items()
        for method in path_item
        if method in HTTP_METHODS
    }


def resolve_schema(spec: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    if "$ref" not in schema:
        return schema
    name = schema["$ref"].rsplit("/", 1)[-1]
    return cast(dict[str, Any], spec["components"]["schemas"][name])


def compare() -> list[str]:
    contract_file = Path(__file__).resolve().parents[2] / "contracts" / "openapi.yaml"
    contract = yaml.safe_load(contract_file.read_text(encoding="utf-8"))
    generated = app.openapi()
    differences: list[str] = []

    contract_operations = {
        (f"{API_PREFIX}{path}", method) for path, method in operations(contract)
    }
    generated_operations = operations(generated)
    if contract_operations != generated_operations:
        differences.append(
            f"operations differ: contract={sorted(contract_operations)}, "
            f"generated={sorted(generated_operations)}"
        )

    for relative_path, method in operations(contract):
        generated_path = f"{API_PREFIX}{relative_path}"
        if (generated_path, method) not in generated_operations:
            continue
        contract_operation = contract["paths"][relative_path][method]
        generated_operation = generated["paths"][generated_path][method]
        if contract_operation.get("operationId") != generated_operation.get("operationId"):
            differences.append(f"{method.upper()} {relative_path} operationId differs")
        if set(contract_operation["responses"]) != set(generated_operation["responses"]):
            differences.append(f"{method.upper()} {relative_path} response codes differ")

    contract_schemas = contract["components"]["schemas"]
    generated_schemas = generated["components"]["schemas"]
    missing_contract_schemas = REQUIRED_SCHEMAS - set(contract_schemas)
    missing_generated_schemas = REQUIRED_SCHEMAS - set(generated_schemas)
    for name in sorted(missing_contract_schemas):
        differences.append(f"contract is missing required schema {name}")
    for name in sorted(missing_generated_schemas):
        differences.append(f"FastAPI is missing required schema {name}")

    generated_only = set(generated_schemas) - set(contract_schemas) - {"Body_createRun"}
    if generated_only:
        differences.append(f"FastAPI has unexpected schemas: {sorted(generated_only)}")

    for name in sorted(set(contract_schemas) & set(generated_schemas)):
        contract_properties = set(contract_schemas[name].get("properties", {}))
        generated_properties = set(generated_schemas[name].get("properties", {}))
        if contract_properties != generated_properties:
            differences.append(
                f"{name} properties differ: contract={sorted(contract_properties)}, "
                f"generated={sorted(generated_properties)}"
            )
        if set(contract_schemas[name].get("required", [])) != set(
            generated_schemas[name].get("required", [])
        ):
            differences.append(f"{name} required fields differ")
        if contract_schemas[name].get("enum") != generated_schemas[name].get("enum"):
            differences.append(f"{name} enum values differ")

    contract_run_states = contract_schemas["RunState"]["enum"]
    generated_run_states = generated_schemas["RunState"]["enum"]
    if contract_run_states != generated_run_states:
        differences.append("RunState enum differs")

    for label, schemas in (
        ("contract", contract_schemas),
        ("generated", generated_schemas),
    ):
        approval_decision = schemas["ApprovalDecision"]
        if set(approval_decision.get("properties", {})) != {"decision", "note"}:
            differences.append(
                f"{label} ApprovalDecision exposes fields beyond decision and note"
            )
        if approval_decision.get("required") != ["decision"]:
            differences.append(f"{label} ApprovalDecision required fields differ")
        if "scores" not in schemas["FindingSummary"].get("required", []):
            differences.append(f"{label} FindingSummary does not require scores")
        if "finding_id" not in schemas["Approval"].get("required", []):
            differences.append(f"{label} Approval does not require finding_id")
        if "transitions" not in schemas["Run"].get("required", []):
            differences.append(f"{label} Run does not require transitions")
        transitions = schemas["Run"]["properties"]["transitions"]
        if transitions.get("minItems") != 1:
            differences.append(f"{label} Run.transitions is not non-empty")
        prefix_items = transitions.get("prefixItems", [])
        first_transition = prefix_items[0] if prefix_items else {}
        first_rules = first_transition.get("allOf", [])
        first_transition_ref = "#/components/schemas/RunTransition"
        initial_state_rule: dict[str, Any] = next(
            (
                rule
                for rule in first_rules
                if "from_state" in rule.get("properties", {})
            ),
            {},
        )
        if (
            not any(rule.get("$ref") == first_transition_ref for rule in first_rules)
            or "from_state" not in initial_state_rule.get("required", [])
            or initial_state_rule.get("properties", {})
            .get("from_state", {})
            .get("type")
            != "null"
        ):
            differences.append(
                f"{label} Run.transitions does not require an initial null from_state"
            )
        run_transition = schemas["RunTransition"]
        if set(run_transition.get("required", [])) != {
            "from_state",
            "to_state",
            "occurred_at",
            "reason",
            "actor",
        }:
            differences.append(f"{label} RunTransition required fields differ")
        if run_transition["properties"]["actor"].get("minLength") != 1:
            differences.append(f"{label} RunTransition.actor may be empty")
        reason_variants = run_transition["properties"]["reason"].get("anyOf", [])
        if not any(
            variant.get("type") == "string" and variant.get("minLength") == 1
            for variant in reason_variants
        ):
            differences.append(f"{label} RunTransition.reason may be empty")
        for property_name in ("recovery", "change_detection"):
            variants = schemas["Run"]["properties"][property_name].get("anyOf", [])
            if not any(variant.get("type") == "null" for variant in variants):
                differences.append(f"{label} Run.{property_name} is not nullable")
        change_properties = schemas["ChangeDetection"]["properties"]
        if change_properties["source_sha256"].get("pattern") != r"^[0-9a-f]{64}$":
            differences.append(f"{label} source_sha256 constraint differs")
        previous_variants = change_properties["previous_source_sha256"].get(
            "anyOf", []
        )
        if not any(
            variant.get("pattern") == r"^[0-9a-f]{64}$"
            for variant in previous_variants
        ):
            differences.append(f"{label} previous_source_sha256 constraint differs")
        audit_package_url = schemas["AuditReport"]["properties"][
            "audit_package_url"
        ]
        audit_url_variants = audit_package_url.get("anyOf", [])
        audit_url_schema: dict[str, Any] = next(
            (
                variant
                for variant in audit_url_variants
                if variant.get("type") == "string"
            ),
            {},
        )
        if audit_url_schema.get("format") != "uri":
            differences.append(f"{label} audit_package_url is missing format: uri")
        if (
            audit_url_schema.get("pattern") != HTTPS_URL_PATTERN
            and audit_package_url.get("pattern") != HTTPS_URL_PATTERN
        ):
            differences.append(
                f"{label} audit_package_url is missing the HTTPS host constraint"
            )

    contract_create = contract["paths"]["/runs"]["post"]
    generated_create = generated["paths"][f"{API_PREFIX}/runs"]["post"]
    for label, operation, spec in (
        ("contract", contract_create, contract),
        ("generated", generated_create, generated),
    ):
        content = operation["requestBody"]["content"]
        if set(content) != {"multipart/form-data"}:
            differences.append(f"{label} createRun is not multipart/form-data only")
            continue
        body = resolve_schema(spec, content["multipart/form-data"]["schema"])
        if set(body.get("required", [])) != {"regulation_file", "synthetic_ack"}:
            differences.append(f"{label} createRun required multipart fields differ")
        properties = body.get("properties", {})
        file_schema = properties.get("regulation_file", {})
        binary_file = file_schema.get("format") == "binary"
        pdf_file = file_schema.get("contentMediaType") == "application/pdf"
        if not (binary_file or pdf_file):
            differences.append(f"{label} regulation_file is not a PDF binary")
        if properties.get("synthetic_ack", {}).get("type") != "boolean":
            differences.append(f"{label} synthetic_ack is not boolean")
        if "202" not in operation["responses"]:
            differences.append(f"{label} createRun does not return 202")

    contract_findings = contract["paths"]["/runs/{run_id}/findings"]["get"]
    generated_findings = generated["paths"][
        f"{API_PREFIX}/runs/{{run_id}}/findings"
    ]["get"]
    for label, operation in (
        ("contract", contract_findings),
        ("generated", generated_findings),
    ):
        query_parameters = {
            parameter["name"]: parameter["schema"]
            for parameter in operation["parameters"]
            if parameter.get("in") == "query"
        }
        expected_constraints = {
            "limit": {"default": 50, "minimum": 1, "maximum": 100},
            "offset": {"default": 0, "minimum": 0},
        }
        for parameter_name, constraints in expected_constraints.items():
            schema = query_parameters.get(parameter_name, {})
            if any(schema.get(key) != value for key, value in constraints.items()):
                differences.append(
                    f"{label} findings {parameter_name} constraints differ"
                )

    return differences


def main() -> int:
    differences = compare()
    if differences:
        print("Material OpenAPI differences found:")
        for difference in differences:
            print(f"- {difference}")
        return 1
    print("No material differences between FastAPI and contracts/openapi.yaml.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
