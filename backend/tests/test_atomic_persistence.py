from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
from google.api_core.exceptions import Aborted, AlreadyExists, ServiceUnavailable
from google.cloud import firestore

from regops_api.action_policy import ActionPolicy, AllowlistedActionService
from regops_api.domain_models import (
    ApprovalDecisionCommit,
    AuditEvent,
    AuditEventType,
    PendingApprovalSlot,
    ProposedAmendment,
    RegulationRecord,
    RunCheckpoint,
    RunIntakeCommit,
    SourceDocumentRecord,
)
from regops_api.firestore import (
    FirestoreRepositories,
    checkpoint_document_id,
    serialize_model,
)
from regops_api.integrations import IntegrationUnavailableError
from regops_api.repositories import DuplicateRecordError, StaleRecordError
from regops_api.schemas import (
    ActionStatus,
    ActionType,
    ApprovalStatus,
    FindingStatus,
    Run,
    RunState,
)
from regops_api.state_machine import plan_run_transition
from tests.factories import NOW, make_finding, make_run
from tests.test_runtime_api import seed_awaiting_approval


class RetryTransaction:
    _read_only = False
    _max_attempts = 3

    def __init__(self) -> None:
        self._id: bytes | None = None
        self.callback_attempts = 0
        self.commit_attempts = 0
        self.rollback_attempts = 0

    def _clean_up(self) -> None:
        self._id = None

    def _begin(self, *, retry_id: bytes | None) -> None:
        self._id = retry_id or b"transaction-1"

    def _commit(self) -> None:
        self.commit_attempts += 1
        if self.commit_attempts == 1:
            raise cast(Any, Aborted)("retry transaction")

    def _rollback(self) -> None:
        self.rollback_attempts += 1


@dataclass(frozen=True)
class FakeSnapshot:
    payload: dict[str, Any] | None

    @property
    def exists(self) -> bool:
        return self.payload is not None

    def to_dict(self) -> dict[str, Any] | None:
        return deepcopy(self.payload)


@dataclass(frozen=True)
class FakeQuery:
    client: FakeFirestoreClient
    collection_name: str
    field: str
    value: object

    def stream(self) -> list[FakeSnapshot]:
        return [
            FakeSnapshot(deepcopy(payload))
            for (collection, _document_id), payload in self.client.documents.items()
            if collection == self.collection_name
            and payload.get(self.field) == self.value
        ]


class FakeDocumentReference:
    def __init__(self, client: FakeFirestoreClient, collection: str, document_id: str):
        self.client = client
        self.collection_name = collection
        self.document_id = document_id

    @property
    def key(self) -> tuple[str, str]:
        return (self.collection_name, self.document_id)

    def get(self, *, transaction: FakeTransaction | None = None) -> FakeSnapshot:
        if transaction is not None:
            return transaction.read(self)
        return FakeSnapshot(deepcopy(self.client.documents.get(self.key)))


class FakeCollection:
    def __init__(self, client: FakeFirestoreClient, name: str) -> None:
        self.client = client
        self.name = name

    def document(self, document_id: str) -> FakeDocumentReference:
        return FakeDocumentReference(self.client, self.name, document_id)

    def where(self, *, filter: Any) -> FakeQuery:
        return FakeQuery(self.client, self.name, str(filter.field_path), filter.value)


class FakeTransaction:
    _read_only = False
    _max_attempts = 1

    def __init__(
        self,
        client: FakeFirestoreClient,
        *,
        fail_create_collection: str | None,
    ) -> None:
        self.client = client
        self.fail_create_collection = fail_create_collection
        self._id: bytes | None = None
        self._writes: list[
            tuple[str, FakeDocumentReference, dict[str, Any] | None]
        ] = []

    def _clean_up(self) -> None:
        self._id = None
        self._writes = []

    def _begin(self, *, retry_id: bytes | None) -> None:
        self._id = retry_id or b"fake-transaction"
        self._writes = []

    def _commit(self) -> None:
        for operation, reference, payload in self._writes:
            if operation == "create" and reference.key in self.client.documents:
                raise cast(Any, AlreadyExists)("already exists")
            if operation == "delete":
                self.client.documents.pop(reference.key, None)
            else:
                assert payload is not None
                self.client.documents[reference.key] = deepcopy(payload)

    def _rollback(self) -> None:
        self._writes = []

    def read(self, reference: FakeDocumentReference) -> FakeSnapshot:
        return FakeSnapshot(deepcopy(self.client.documents.get(reference.key)))

    def get(self, query: FakeQuery) -> list[FakeSnapshot]:
        return [
            FakeSnapshot(deepcopy(payload))
            for (collection, _document_id), payload in self.client.documents.items()
            if collection == query.collection_name
            and payload.get(query.field) == query.value
        ]

    def create(
        self, reference: FakeDocumentReference, payload: dict[str, Any]
    ) -> None:
        if reference.collection_name == self.fail_create_collection:
            raise cast(Any, ServiceUnavailable)(
                "simulated transactional create failure"
            )
        self._writes.append(("create", reference, deepcopy(payload)))

    def set(self, reference: FakeDocumentReference, payload: dict[str, Any]) -> None:
        self._writes.append(("set", reference, deepcopy(payload)))

    def delete(self, reference: FakeDocumentReference) -> None:
        self._writes.append(("delete", reference, None))


class FakeFirestoreClient:
    def __init__(self, *, fail_create_collection: str | None = None) -> None:
        self.documents: dict[tuple[str, str], dict[str, Any]] = {}
        self.fail_create_collection = fail_create_collection

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self, name)

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(
            self,
            fail_create_collection=self.fail_create_collection,
        )


def make_intake_commit() -> RunIntakeCommit:
    run = make_run()
    return RunIntakeCommit(
        run=run,
        checkpoint=RunCheckpoint(
            run_id=run.run_id,
            sequence=0,
            state=RunState.INGESTED,
            recorded_at=run.created_at,
        ),
        regulation=RegulationRecord(
            regulation=run.regulation,
            content_sha256="a" * 64,
            version=1,
            created_at=NOW,
        ),
        source_document=SourceDocumentRecord(
            run_id=run.run_id,
            regulation_id=run.regulation.reg_id,
            object_name=f"runs/{run.run_id}/source/regulation.pdf",
            gcs_uri=f"gs://private/runs/{run.run_id}/source/regulation.pdf",
            source_sha256="a" * 64,
            size_bytes=10,
            content_type="application/pdf",
            sanitized_filename=run.regulation.source_filename,
            synthetic=True,
            created_at=NOW,
        ),
    )


def make_firestore_action_service(
    repositories: FirestoreRepositories,
) -> AllowlistedActionService:
    return AllowlistedActionService(
        actions=repositories,
        findings=repositories,
        review_tasks=repositories,
        case_tags=repositories,
        approvals=repositories,
        audits=repositories,
        clock=lambda: NOW,
    )


def test_official_firestore_transaction_retries_aborted_commit_safely() -> None:
    transaction = RetryTransaction()

    @firestore.transactional
    def operation(current_transaction: RetryTransaction) -> int:
        current_transaction.callback_attempts += 1
        return current_transaction.callback_attempts

    result = operation(cast(Any, transaction))

    assert result == 2
    assert transaction.callback_attempts == 2
    assert transaction.commit_attempts == 2
    assert transaction.rollback_attempts == 0


def test_atomic_approval_preflight_rejects_stale_checkpoint_without_partial_writes() -> None:
    seeded = seed_awaiting_approval()
    approval = seeded.repositories.get_approval(seeded.approval_id)
    action = seeded.repositories.get_action(seeded.action_id)
    finding = seeded.repositories.get_finding("finding-1")
    run = seeded.repositories.get_run("run-1")
    invalid = ApprovalDecisionCommit(
        expected_approval=approval,
        expected_action=action,
        expected_finding=finding,
        expected_run_state=run.state,
        approval=approval.model_copy(update={"status": ApprovalStatus.REJECTED}),
        action=action,
        finding=finding,
        run=run,
        snapshot=None,
        checkpoints=[
            RunCheckpoint(
                run_id=run.run_id,
                sequence=999,
                state=RunState.COMPLETED,
                recorded_at=NOW,
            )
        ],
        audit_events=[],
    )

    with pytest.raises(StaleRecordError, match="checkpoint sequence"):
        seeded.repositories.commit_approval_decision(invalid)

    assert seeded.repositories.get_approval(seeded.approval_id) == approval
    assert seeded.repositories.get_action(seeded.action_id) == action
    assert seeded.repositories.get_finding("finding-1") == finding
    assert seeded.repositories.get_run("run-1") == run


def test_firestore_intake_callback_commits_all_metadata_together() -> None:
    client = FakeFirestoreClient()
    repositories = FirestoreRepositories(cast(Any, client))
    commit = make_intake_commit()

    repositories.commit_run_intake(commit)

    assert set(client.documents) == {
        ("runs", "run-1"),
        ("checkpoints", "run-1:00000000"),
        ("regulations", "reg-1"),
        ("source_documents", "run-1"),
    }


def test_firestore_intake_callback_rejects_partial_metadata_without_writes() -> None:
    client = FakeFirestoreClient()
    commit = make_intake_commit()
    client.documents[("runs", "run-1")] = serialize_model(commit.run)
    repositories = FirestoreRepositories(cast(Any, client))

    with pytest.raises(DuplicateRecordError, match="intake metadata"):
        repositories.commit_run_intake(commit)

    assert set(client.documents) == {("runs", "run-1")}


def test_firestore_draft_callback_enforces_pending_slot() -> None:
    client = FakeFirestoreClient()
    run = make_run()
    first_finding = make_finding()
    second_finding = make_finding("finding-2")
    client.documents[("runs", run.run_id)] = serialize_model(run)
    client.documents[("findings", first_finding.finding_id)] = serialize_model(
        first_finding
    )
    client.documents[("findings", second_finding.finding_id)] = serialize_model(
        second_finding
    )
    repositories = FirestoreRepositories(cast(Any, client))
    service = make_firestore_action_service(repositories)
    first = ActionPolicy().propose(first_finding, ActionType.DRAFT_AMENDMENT)
    second = ActionPolicy().propose(second_finding, ActionType.DRAFT_AMENDMENT)

    created = service.attempt(
        finding=first_finding,
        action_type=ActionType.DRAFT_AMENDMENT,
        amendment=ProposedAmendment(
            action_id=first.action_id,
            finding_id=first_finding.finding_id,
            contract_id=first_finding.target_id,
            clause_updates={"retention": "retain for 30 days"},
        ),
    )
    with pytest.raises(DuplicateRecordError, match="already has a pending"):
        service.attempt(
            finding=second_finding,
            action_type=ActionType.DRAFT_AMENDMENT,
            amendment=ProposedAmendment(
                action_id=second.action_id,
                finding_id=second_finding.finding_id,
                contract_id=second_finding.target_id,
                clause_updates={"retention": "retain for 60 days"},
            ),
        )

    assert created.approval is not None
    assert len(
        [key for key in client.documents if key[0] == "proposed_actions"]
    ) == 1
    assert len([key for key in client.documents if key[0] == "approvals"]) == 1
    assert len(
        [key for key in client.documents if key[0] == "pending_approval_slots"]
    ) == 1


def test_firestore_approval_create_failure_cannot_leave_orphan_action() -> None:
    client = FakeFirestoreClient(fail_create_collection="approvals")
    run = make_run()
    finding = make_finding()
    client.documents[("runs", run.run_id)] = serialize_model(run)
    client.documents[("findings", finding.finding_id)] = serialize_model(finding)
    repositories = FirestoreRepositories(cast(Any, client))
    proposal = ActionPolicy().propose(finding, ActionType.DRAFT_AMENDMENT)

    with pytest.raises(IntegrationUnavailableError, match="persistent storage"):
        make_firestore_action_service(repositories).attempt(
            finding=finding,
            action_type=ActionType.DRAFT_AMENDMENT,
            amendment=ProposedAmendment(
                action_id=proposal.action_id,
                finding_id=finding.finding_id,
                contract_id=finding.target_id,
                clause_updates={"retention": "retain for 30 days"},
            ),
        )

    assert not [key for key in client.documents if key[0] == "proposed_actions"]
    assert not [key for key in client.documents if key[0] == "action_idempotency"]
    assert not [key for key in client.documents if key[0] == "approvals"]
    assert not [key for key in client.documents if key[0] == "audit_events"]
    assert client.documents[("findings", finding.finding_id)] == serialize_model(
        finding
    )


def test_firestore_decision_callback_verifies_and_clears_pending_guard() -> None:
    seeded = seed_awaiting_approval()
    approval = seeded.repositories.get_approval(seeded.approval_id)
    action = seeded.repositories.get_action(seeded.action_id)
    finding = seeded.repositories.get_finding(approval.finding_id)
    run = seeded.repositories.get_run(approval.run_id)
    latest = seeded.repositories.latest_checkpoint(run.run_id)
    assert latest is not None
    rejected_action = action.action.model_copy(update={"status": ActionStatus.REJECTED})
    rejected_record = action.model_copy(update={"action": rejected_action})
    open_finding = finding.model_copy(
        update={
            "status": FindingStatus.OPEN,
            "proposed_action": rejected_action,
        }
    )
    base_run = Run.model_validate(
        run.model_dump() | {"pending_approvals": []}
    )
    planned = plan_run_transition(
        run=base_run,
        checkpoint=latest,
        target=RunState.COMPLETED,
        now=NOW + timedelta(microseconds=1),
        reason="Proposed amendment rejected",
        actor="action-controller",
    )
    decided = approval.model_copy(
        update={
            "status": ApprovalStatus.REJECTED,
            "decided_at": NOW,
            "decided_by": "test-reviewer",
        }
    )
    decision_event = AuditEvent(
        event_id=str(uuid4()),
        run_id=run.run_id,
        event_type=AuditEventType.APPROVAL_DECIDED,
        occurred_at=NOW,
        action_id=action.action.action_id,
        approval_id=approval.approval_id,
        actor="test-reviewer",
    )
    commit = ApprovalDecisionCommit(
        expected_approval=approval,
        expected_action=action,
        expected_finding=finding,
        expected_run_state=run.state,
        approval=decided,
        action=rejected_record,
        finding=open_finding,
        run=planned.run,
        checkpoints=[planned.checkpoint],
        audit_events=[decision_event, planned.audit_event],
    )
    client = FakeFirestoreClient()
    client.documents.update(
        {
            ("approvals", approval.approval_id): serialize_model(approval),
            ("proposed_actions", action.action.action_id): serialize_model(action),
            ("findings", finding.finding_id): serialize_model(finding),
            ("runs", run.run_id): serialize_model(run),
            (
                "checkpoints",
                checkpoint_document_id(run.run_id, latest.sequence),
            ): serialize_model(latest),
            ("pending_approval_slots", run.run_id): serialize_model(
                PendingApprovalSlot(
                    run_id=run.run_id,
                    approval_id=approval.approval_id,
                    action_id=action.action.action_id,
                    finding_id=finding.finding_id,
                )
            ),
        }
    )
    repositories = FirestoreRepositories(cast(Any, client))

    repositories.commit_approval_decision(commit)

    assert ("pending_approval_slots", run.run_id) not in client.documents
    assert client.documents[("approvals", approval.approval_id)]["status"] == (
        "REJECTED"
    )
    assert client.documents[("runs", run.run_id)]["state"] == "COMPLETED"
    with pytest.raises(StaleRecordError, match="binding is missing"):
        repositories.commit_approval_decision(commit)
