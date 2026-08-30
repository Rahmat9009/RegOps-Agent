from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from regops_api.action_policy import ActionPolicy, AllowlistedActionService
from regops_api.counterfactual import DeterministicCounterfactual
from regops_api.domain_models import ConflictMatch, ProposedAmendment, SyntheticContract
from regops_api.in_memory import InMemoryRepositories
from regops_api.integrations import IntegrationUnavailableError
from regops_api.main import create_app
from regops_api.repositories import DuplicateRecordError, StaleRecordError
from regops_api.schemas import (
    ActionStatus,
    ActionType,
    ApprovalStatus,
    Obligation,
    RunState,
    Severity,
)
from regops_api.state_machine import RunStateCoordinator
from tests.factories import NOW, make_contract, make_finding, make_obligation, make_run
from tests.runtime_helpers import RecordingStorage, make_runtime


def matching_pipeline(
    contract: SyntheticContract, obligations: list[Obligation]
) -> list[ConflictMatch]:
    assert obligations
    if "forever" in contract.clauses["retention"]:
        return [ConflictMatch(conflict_id="finding-1", severity=Severity.HIGH)]
    return []


@dataclass(frozen=True)
class SeededRuntime:
    client: TestClient
    repositories: InMemoryRepositories
    storage: RecordingStorage
    action_id: str
    approval_id: str


def seed_awaiting_approval(storage: RecordingStorage | None = None) -> SeededRuntime:
    repositories = InMemoryRepositories.for_tests()
    states = RunStateCoordinator(
        repositories,
        repositories,
        repositories,
        clock=lambda: NOW,
    )
    states.initialize(make_run())
    for state in (
        RunState.EXTRACTING,
        RunState.EXTRACTED,
        RunState.MAPPING,
        RunState.MAPPED,
        RunState.VERIFYING,
        RunState.VERIFIED,
        RunState.AWAITING_APPROVAL,
    ):
        states.transition("run-1", state)
    finding = make_finding()
    repositories.add_findings([finding])
    repositories.add_obligations("run-1", [make_obligation()])
    repositories.add_synthetic_contract(make_contract())
    action = ActionPolicy().propose(finding, ActionType.DRAFT_AMENDMENT)
    attempt = AllowlistedActionService(
        actions=repositories,
        findings=repositories,
        review_tasks=repositories,
        case_tags=repositories,
        approvals=repositories,
        audits=repositories,
        clock=lambda: NOW,
    ).attempt(
        finding=finding,
        action_type=ActionType.DRAFT_AMENDMENT,
        amendment=ProposedAmendment(
            action_id=action.action_id,
            finding_id=finding.finding_id,
            contract_id=finding.target_id,
            clause_updates={"retention": "retain for 30 days"},
        ),
    )
    assert attempt.approval is not None
    storage = storage or RecordingStorage()
    runtime = make_runtime(
        repositories=repositories,
        storage=storage,
        counterfactual=DeterministicCounterfactual(matching_pipeline),
    )
    return SeededRuntime(
        client=TestClient(create_app(settings=runtime.settings, runtime=runtime)),
        repositories=repositories,
        storage=storage,
        action_id=attempt.action.action_id,
        approval_id=attempt.approval.approval_id,
    )


def test_query_preview_rejection_and_audit_endpoints_use_persistent_state() -> None:
    seeded = seed_awaiting_approval()

    run_response = seeded.client.get("/api/v1/runs/run-1")
    findings_response = seeded.client.get(
        "/api/v1/runs/run-1/findings", params={"limit": 1, "offset": 0}
    )
    finding_response = seeded.client.get("/api/v1/findings/finding-1")
    preview_response = seeded.client.post(
        f"/api/v1/actions/{seeded.action_id}/preview"
    )

    assert run_response.status_code == 200
    assert run_response.json()["state"] == "AWAITING_APPROVAL"
    assert len(run_response.json()["pending_approvals"]) == 1
    assert findings_response.status_code == 200
    assert findings_response.json()["total"] == 1
    assert findings_response.json()["by_severity"] == {
        "low": 0,
        "medium": 0,
        "high": 1,
    }
    assert len(findings_response.json()["items"]) == 1
    assert finding_response.status_code == 200
    assert len(finding_response.json()["evidence_path"]) == 2
    assert preview_response.status_code == 200
    assert preview_response.json()["resolved_finding_ids"] == ["finding-1"]

    rejection = seeded.client.post(
        f"/api/v1/approvals/{seeded.approval_id}/decision",
        json={"decision": "reject", "note": "Keep the original synthetic clause."},
    )
    repeated = seeded.client.post(
        f"/api/v1/approvals/{seeded.approval_id}/decision",
        json={"decision": "approve"},
    )
    audit = seeded.client.get("/api/v1/runs/run-1/audit")

    assert rejection.status_code == 200
    assert rejection.json()["status"] == "REJECTED"
    assert rejection.json()["decided_by"] == "test-reviewer"
    assert repeated.status_code == 409
    assert seeded.repositories.get_run("run-1").state is RunState.COMPLETED
    assert (
        seeded.repositories.get_action(seeded.action_id).action.status
        is ActionStatus.REJECTED
    )
    assert audit.status_code == 200
    assert isinstance(audit.json()["audit_package_url"], str)
    assert "X-Goog-Signature=test" in audit.json()["audit_package_url"]
    assert seeded.storage.audit_packages[0][0] == "run-1"
    assert seeded.repositories.get_audit_report("run-1").audit_package_url is None


def test_audit_signing_outage_returns_metrics_with_null_url_and_later_retry() -> None:
    url = (
        "https://storage.googleapis.com/test-private/runs/run-1/audit/"
        "audit-package.json?X-Goog-Signature=test"
    )
    storage = RecordingStorage(audit_results=[None, url])
    seeded = seed_awaiting_approval(storage)

    unavailable = seeded.client.get("/api/v1/runs/run-1/audit")
    retried = seeded.client.get("/api/v1/runs/run-1/audit")

    assert unavailable.status_code == 200
    assert unavailable.json()["audit_package_url"] is None
    assert unavailable.json()["processing"]["documents_processed"] == 0
    assert retried.status_code == 200 and retried.json()["audit_package_url"] == url
    assert [run_id for run_id, _ in storage.audit_packages] == ["run-1", "run-1"]
    assert seeded.repositories.get_audit_report("run-1").audit_package_url is None


def test_audit_upload_failure_keeps_sanitized_service_unavailable() -> None:
    storage = RecordingStorage(
        audit_results=[IntegrationUnavailableError("audit package upload is unavailable")]
    )
    seeded = seed_awaiting_approval(storage)

    response = seeded.client.get("/api/v1/runs/run-1/audit")

    assert response.status_code == 503
    assert response.json() == {
        "code": "SERVICE_UNAVAILABLE",
        "message": "A required service is unavailable",
        "details": None,
    }
    assert seeded.repositories.get_audit_report("run-1").audit_package_url is None


def test_findings_filters_and_counts_apply_before_stable_pagination() -> None:
    seeded = seed_awaiting_approval()
    second = make_finding("finding-2").model_copy(update={"severity": Severity.MEDIUM})
    seeded.repositories.add_findings([second])

    page = seeded.client.get(
        "/api/v1/runs/run-1/findings",
        params={"q": "bounded", "limit": 1, "offset": 1},
    )
    high_only = seeded.client.get(
        "/api/v1/runs/run-1/findings", params={"severity": "high"}
    )

    assert page.status_code == 200
    assert page.json()["total"] == 2
    assert page.json()["by_severity"] == {"low": 0, "medium": 1, "high": 1}
    assert [item["finding_id"] for item in page.json()["items"]] == ["finding-2"]
    assert high_only.status_code == 200
    assert high_only.json()["total"] == 1
    assert high_only.json()["by_severity"] == {"low": 0, "medium": 0, "high": 1}


def test_approval_commits_shadow_and_full_completion_chain_atomically() -> None:
    seeded = seed_awaiting_approval()
    original = seeded.repositories.get_synthetic_contract("contract-1")

    response = seeded.client.post(
        f"/api/v1/approvals/{seeded.approval_id}/decision",
        json={"decision": "approve"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "APPROVED"
    assert seeded.repositories.get_synthetic_contract("contract-1") == original
    assert seeded.repositories.get_run("run-1").state is RunState.COMPLETED
    assert [
        checkpoint.state
        for checkpoint in seeded.repositories.list_checkpoints("run-1")[-3:]
    ] == [RunState.EXECUTING, RunState.REVALIDATING, RunState.COMPLETED]
    approved = seeded.repositories.get_action(seeded.action_id).action
    assert approved.status is ActionStatus.APPROVED_DRAFT
    snapshot_id = seeded.client.post(
        f"/api/v1/actions/{seeded.action_id}/preview"
    ).json()["shadow_run_id"]
    snapshot = seeded.repositories.get_shadow_snapshot(snapshot_id)
    assert snapshot.original == original
    assert snapshot.shadow.clauses["retention"] == "retain for 30 days"
    assert not [
        approval
        for approval in seeded.repositories.list_approvals("run-1")
        if approval.status is ApprovalStatus.PENDING
    ]


def test_rejected_run_has_zero_pending_approvals() -> None:
    seeded = seed_awaiting_approval()

    response = seeded.client.post(
        f"/api/v1/approvals/{seeded.approval_id}/decision",
        json={"decision": "reject"},
    )

    assert response.status_code == 200
    assert seeded.repositories.get_run("run-1").state is RunState.COMPLETED
    assert not [
        approval
        for approval in seeded.repositories.list_approvals("run-1")
        if approval.status is ApprovalStatus.PENDING
    ]


def test_second_pending_draft_amendment_for_run_is_rejected() -> None:
    seeded = seed_awaiting_approval()
    second = make_finding("finding-2")
    seeded.repositories.add_findings([second])
    proposal = ActionPolicy().propose(second, ActionType.DRAFT_AMENDMENT)
    service = AllowlistedActionService(
        actions=seeded.repositories,
        findings=seeded.repositories,
        review_tasks=seeded.repositories,
        case_tags=seeded.repositories,
        approvals=seeded.repositories,
        audits=seeded.repositories,
        clock=lambda: NOW,
    )

    with pytest.raises(DuplicateRecordError, match="already has a pending"):
        service.attempt(
            finding=second,
            action_type=ActionType.DRAFT_AMENDMENT,
            amendment=ProposedAmendment(
                action_id=proposal.action_id,
                finding_id=second.finding_id,
                contract_id=second.target_id,
                clause_updates={"retention": "retain for 60 days"},
            ),
        )

    assert len(seeded.repositories.list_actions("run-1")) == 1
    assert len(seeded.repositories.list_approvals("run-1")) == 1


def test_duplicate_draft_retry_returns_only_a_coherent_action_and_approval() -> None:
    seeded = seed_awaiting_approval()
    finding = make_finding()
    proposal = ActionPolicy().propose(finding, ActionType.DRAFT_AMENDMENT)
    service = AllowlistedActionService(
        actions=seeded.repositories,
        findings=seeded.repositories,
        review_tasks=seeded.repositories,
        case_tags=seeded.repositories,
        approvals=seeded.repositories,
        audits=seeded.repositories,
        clock=lambda: NOW,
    )

    duplicate = service.attempt(
        finding=finding,
        action_type=ActionType.DRAFT_AMENDMENT,
        amendment=ProposedAmendment(
            action_id=proposal.action_id,
            finding_id=finding.finding_id,
            contract_id=finding.target_id,
            clause_updates={"retention": "retain for 30 days"},
        ),
    )

    assert duplicate.duplicate_prevented is True
    assert duplicate.approval is not None
    assert duplicate.approval.action_id == duplicate.action.action_id
    assert duplicate.approval.status is ApprovalStatus.PENDING


def test_duplicate_draft_retry_fails_closed_when_approval_is_missing() -> None:
    seeded = seed_awaiting_approval()
    del seeded.repositories._approvals[seeded.approval_id]
    finding = make_finding()
    proposal = ActionPolicy().propose(finding, ActionType.DRAFT_AMENDMENT)
    service = AllowlistedActionService(
        actions=seeded.repositories,
        findings=seeded.repositories,
        review_tasks=seeded.repositories,
        case_tags=seeded.repositories,
        approvals=seeded.repositories,
        audits=seeded.repositories,
        clock=lambda: NOW,
    )

    with pytest.raises(StaleRecordError, match="coherent approval"):
        service.attempt(
            finding=finding,
            action_type=ActionType.DRAFT_AMENDMENT,
            amendment=ProposedAmendment(
                action_id=proposal.action_id,
                finding_id=finding.finding_id,
                contract_id=finding.target_id,
                clause_updates={"retention": "retain for 30 days"},
            ),
        )


def test_completed_transition_is_rejected_while_approval_is_pending() -> None:
    seeded = seed_awaiting_approval()
    states = RunStateCoordinator(
        seeded.repositories,
        seeded.repositories,
        seeded.repositories,
        clock=lambda: NOW,
    )

    with pytest.raises(StaleRecordError, match="cannot retain a pending approval"):
        states.transition("run-1", RunState.COMPLETED)

    assert seeded.repositories.get_run("run-1").state is RunState.AWAITING_APPROVAL


def test_corrupted_multiple_pending_approvals_fail_closed_without_decision() -> None:
    seeded = seed_awaiting_approval()
    original = seeded.repositories.get_approval(seeded.approval_id)
    seeded.repositories.add_approval(
        original.model_copy(update={"approval_id": "corrupt-second-approval"})
    )

    response = seeded.client.post(
        f"/api/v1/approvals/{seeded.approval_id}/decision",
        json={"decision": "reject"},
    )

    assert response.status_code == 409
    assert seeded.repositories.get_approval(seeded.approval_id) == original
    assert seeded.repositories.get_run("run-1").state is RunState.AWAITING_APPROVAL


def test_concurrent_approval_decisions_commit_once_and_fail_closed_once() -> None:
    seeded = seed_awaiting_approval()
    path = f"/api/v1/approvals/{seeded.approval_id}/decision"

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda _index: seeded.client.post(
                    path,
                    json={"decision": "reject"},
                ),
                range(2),
            )
        )

    assert sorted(response.status_code for response in responses) == [200, 409]
    assert seeded.repositories.get_run("run-1").state is RunState.COMPLETED
    assert not [
        approval
        for approval in seeded.repositories.list_approvals("run-1")
        if approval.status is ApprovalStatus.PENDING
    ]
