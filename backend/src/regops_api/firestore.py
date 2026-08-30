"""Firestore-backed typed repositories and atomic Phase 1B transaction boundaries."""

from __future__ import annotations

from typing import Any, cast

from google.api_core.exceptions import AlreadyExists, GoogleAPICallError
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from pydantic import BaseModel

from regops_api.domain_models import (
    ActionAttemptResult,
    ActionRecord,
    ApprovalDecisionCommit,
    ApprovalRequiredActionCommit,
    AuditEvent,
    CaseTag,
    InternalReviewTask,
    PendingApprovalSlot,
    RegulationRecord,
    RunCheckpoint,
    RunIntakeCommit,
    ShadowContractSnapshot,
    SourceDocumentRecord,
    SyntheticContract,
    VerifiedWorkerHandoffCommit,
    WorkerHandoffRecord,
)
from regops_api.integrations import IntegrationUnavailableError
from regops_api.repositories import (
    DuplicateRecordError,
    RecordNotFoundError,
    StaleRecordError,
    validate_approval_decision_outputs,
)
from regops_api.schemas import (
    AffectedCase,
    Approval,
    ApprovalStatus,
    AuditReport,
    Finding,
    FindingStatus,
    Obligation,
    Run,
    RunState,
)
from regops_api.state_machine import (
    InvalidRunTransitionError,
    RunStateMachine,
    validate_authoritative_run_update,
    validate_initial_run,
)

COLLECTIONS = {
    "runs": "runs",
    "regulations": "regulations",
    "source_documents": "source_documents",
    "obligations": "obligations",
    "synthetic_contracts": "synthetic_contracts",
    "synthetic_cases": "synthetic_cases",
    "shadow_snapshots": "shadow_snapshots",
    "findings": "findings",
    "review_tasks": "review_tasks",
    "approvals": "approvals",
    "audit_events": "audit_events",
    "audit_reports": "audit_reports",
    "proposed_actions": "proposed_actions",
    "checkpoints": "checkpoints",
    "case_tags": "case_tags",
    "action_idempotency": "action_idempotency",
    "pending_approval_slots": "pending_approval_slots",
    "worker_handoffs": "worker_handoffs",
}


def serialize_model(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")


def deserialize_model[ModelT: BaseModel](model: type[ModelT], payload: dict[str, Any]) -> ModelT:
    return model.model_validate(payload)


def checkpoint_document_id(run_id: str, sequence: int) -> str:
    return f"{run_id}:{sequence:08d}"


class FirestoreRepositories:
    """One adapter implements all repository ports using stable top-level collections."""

    is_production = True

    def __init__(self, client: firestore.Client) -> None:
        self._client = client

    def _collection(self, name: str) -> Any:
        return self._client.collection(COLLECTIONS[name])

    def _document(self, collection: str, document_id: str) -> Any:
        return self._collection(collection).document(document_id)

    def _create(self, collection: str, document_id: str, model: BaseModel) -> None:
        try:
            self._document(collection, document_id).create(serialize_model(model))
        except AlreadyExists as error:
            raise DuplicateRecordError(f"{collection} record already exists") from error
        except GoogleAPICallError as error:
            raise IntegrationUnavailableError("persistent storage is unavailable") from error

    def _set(self, collection: str, document_id: str, model: BaseModel) -> None:
        try:
            self._document(collection, document_id).set(serialize_model(model))
        except GoogleAPICallError as error:
            raise IntegrationUnavailableError("persistent storage is unavailable") from error

    def _get[ModelT: BaseModel](
        self, collection: str, document_id: str, model: type[ModelT]
    ) -> ModelT:
        try:
            snapshot = self._document(collection, document_id).get()
        except GoogleAPICallError as error:
            raise IntegrationUnavailableError("persistent storage is unavailable") from error
        if not snapshot.exists:
            raise RecordNotFoundError(f"{collection} record was not found")
        return deserialize_model(model, cast(dict[str, Any], snapshot.to_dict()))

    def _query[ModelT: BaseModel](
        self,
        collection: str,
        model: type[ModelT],
        *,
        field: str | None = None,
        value: object | None = None,
    ) -> list[ModelT]:
        try:
            query = self._collection(collection)
            if field is not None:
                query = query.where(filter=FieldFilter(field, "==", value))
            snapshots = query.stream()
            return [
                deserialize_model(model, cast(dict[str, Any], snapshot.to_dict()))
                for snapshot in snapshots
            ]
        except GoogleAPICallError as error:
            raise IntegrationUnavailableError("persistent storage is unavailable") from error

    def add_run(self, run: Run) -> None:
        self._create("runs", run.run_id, run)

    def get_run(self, run_id: str) -> Run:
        return self._get("runs", run_id, Run)

    def update_run(self, run: Run) -> None:
        self.get_run(run.run_id)
        self._set("runs", run.run_id, run)

    def add_regulation(self, record: RegulationRecord) -> None:
        self._create("regulations", record.regulation.reg_id, record)

    def get_regulation(self, regulation_id: str) -> RegulationRecord:
        return self._get("regulations", regulation_id, RegulationRecord)

    def find_regulation_by_hash(self, content_sha256: str) -> RegulationRecord | None:
        records = self._query(
            "regulations",
            RegulationRecord,
            field="content_sha256",
            value=content_sha256,
        )
        return min(records, key=lambda item: item.created_at) if records else None

    def list_regulations_by_source(self, source_filename: str) -> list[RegulationRecord]:
        records = self._query(
            "regulations",
            RegulationRecord,
            field="regulation.source_filename",
            value=source_filename,
        )
        return sorted(records, key=lambda item: item.version)

    def add_source_document(self, record: SourceDocumentRecord) -> None:
        self._create("source_documents", record.run_id, record)

    def get_source_document(self, run_id: str) -> SourceDocumentRecord:
        return self._get("source_documents", run_id, SourceDocumentRecord)

    def add_obligations(self, run_id: str, obligations: list[Obligation]) -> None:
        batch = self._client.batch()
        try:
            for obligation in obligations:
                reference = self._document("obligations", obligation.obligation_id)
                batch.create(reference, serialize_model(obligation) | {"run_id": run_id})
            batch.commit()
        except AlreadyExists as error:
            raise DuplicateRecordError("obligation record already exists") from error
        except GoogleAPICallError as error:
            raise IntegrationUnavailableError("persistent storage is unavailable") from error

    def list_obligations(self, run_id: str) -> list[Obligation]:
        records = self._query_raw("obligations", field="run_id", value=run_id)
        return sorted(
            (Obligation.model_validate(self._without(record, "run_id")) for record in records),
            key=lambda item: item.obligation_id,
        )

    def add_synthetic_contract(self, contract: SyntheticContract) -> None:
        self._create("synthetic_contracts", contract.contract_id, contract)

    def get_synthetic_contract(self, contract_id: str) -> SyntheticContract:
        return self._get("synthetic_contracts", contract_id, SyntheticContract)

    def list_synthetic_contracts(self) -> list[SyntheticContract]:
        return sorted(
            self._query("synthetic_contracts", SyntheticContract),
            key=lambda item: item.contract_id,
        )

    def add_synthetic_case(self, case: AffectedCase) -> None:
        self._create("synthetic_cases", case.case_id, case)

    def get_synthetic_case(self, case_id: str) -> AffectedCase:
        return self._get("synthetic_cases", case_id, AffectedCase)

    def list_synthetic_cases(self) -> list[AffectedCase]:
        return sorted(
            self._query("synthetic_cases", AffectedCase),
            key=lambda item: item.case_id,
        )

    def save_shadow_snapshot(self, snapshot: ShadowContractSnapshot) -> None:
        source = self.get_synthetic_contract(snapshot.original.contract_id)
        if (
            snapshot.original != source
            or snapshot.shadow.contract_id != source.contract_id
            or snapshot.source_revision != source.revision
        ):
            raise StaleRecordError("shadow snapshot does not match immutable source")
        self._create("shadow_snapshots", snapshot.snapshot_id, snapshot)

    def get_shadow_snapshot(self, snapshot_id: str) -> ShadowContractSnapshot:
        return self._get("shadow_snapshots", snapshot_id, ShadowContractSnapshot)

    def add_findings(self, findings: list[Finding]) -> None:
        batch = self._client.batch()
        try:
            for finding in findings:
                batch.create(
                    self._document("findings", finding.finding_id),
                    serialize_model(finding),
                )
                if finding.affected_case is not None:
                    batch.set(
                        self._document("synthetic_cases", finding.affected_case.case_id),
                        serialize_model(finding.affected_case),
                    )
            batch.commit()
        except AlreadyExists as error:
            raise DuplicateRecordError("finding record already exists") from error
        except GoogleAPICallError as error:
            raise IntegrationUnavailableError("persistent storage is unavailable") from error

    def get_finding(self, finding_id: str) -> Finding:
        return self._get("findings", finding_id, Finding)

    def list_findings(self, run_id: str) -> list[Finding]:
        return sorted(
            self._query("findings", Finding, field="run_id", value=run_id),
            key=lambda item: item.finding_id,
        )

    def update_finding(self, finding: Finding) -> None:
        self.get_finding(finding.finding_id)
        self._set("findings", finding.finding_id, finding)

    def add_review_task(self, task: InternalReviewTask) -> None:
        self._create("review_tasks", task.task_id, task)

    def get_review_task(self, task_id: str) -> InternalReviewTask:
        return self._get("review_tasks", task_id, InternalReviewTask)

    def list_review_tasks(self, run_id: str) -> list[InternalReviewTask]:
        return sorted(
            self._query("review_tasks", InternalReviewTask, field="run_id", value=run_id),
            key=lambda item: item.task_id,
        )

    def add_approval(self, approval: Approval) -> None:
        self._create("approvals", approval.approval_id, approval)

    def get_approval(self, approval_id: str) -> Approval:
        return self._get("approvals", approval_id, Approval)

    def update_approval(self, approval: Approval) -> None:
        self.get_approval(approval.approval_id)
        self._set("approvals", approval.approval_id, approval)

    def list_approvals(self, run_id: str) -> list[Approval]:
        return sorted(
            self._query("approvals", Approval, field="run_id", value=run_id),
            key=lambda item: item.approval_id,
        )

    def append_audit_event(self, event: AuditEvent) -> None:
        self._create("audit_events", event.event_id, event)

    def list_audit_events(self, run_id: str) -> list[AuditEvent]:
        return sorted(
            self._query("audit_events", AuditEvent, field="run_id", value=run_id),
            key=lambda item: (item.occurred_at, item.event_id),
        )

    def save_audit_report(self, report: AuditReport) -> None:
        self._set("audit_reports", report.run_id, report)

    def get_audit_report(self, run_id: str) -> AuditReport:
        return self._get("audit_reports", run_id, AuditReport)

    def add_action(self, record: ActionRecord) -> None:
        action_reference = self._document("proposed_actions", record.action.action_id)
        key_reference = self._document("action_idempotency", record.action.idempotency_key)
        transaction = self._client.transaction()

        @firestore.transactional
        def claim(current_transaction: Any) -> None:
            if key_reference.get(transaction=current_transaction).exists:
                raise DuplicateRecordError("action idempotency key already claimed")
            current_transaction.create(action_reference, serialize_model(record))
            current_transaction.create(
                key_reference,
                {
                    "action_id": record.action.action_id,
                    "run_id": record.run_id,
                    "finding_id": record.action.finding_id,
                },
            )

        try:
            claim(transaction)
        except DuplicateRecordError:
            raise
        except AlreadyExists as error:
            raise DuplicateRecordError("action idempotency key already claimed") from error
        except GoogleAPICallError as error:
            raise IntegrationUnavailableError("persistent storage is unavailable") from error

    def get_action(self, action_id: str) -> ActionRecord:
        return self._get("proposed_actions", action_id, ActionRecord)

    def find_action_by_idempotency_key(self, idempotency_key: str) -> ActionRecord | None:
        try:
            snapshot = self._document("action_idempotency", idempotency_key).get()
        except GoogleAPICallError as error:
            raise IntegrationUnavailableError("persistent storage is unavailable") from error
        if not snapshot.exists:
            return None
        payload = cast(dict[str, Any], snapshot.to_dict())
        return self.get_action(str(payload["action_id"]))

    def update_action(self, record: ActionRecord) -> None:
        self.get_action(record.action.action_id)
        self._set("proposed_actions", record.action.action_id, record)

    def list_actions(self, run_id: str) -> list[ActionRecord]:
        return sorted(
            self._query("proposed_actions", ActionRecord, field="run_id", value=run_id),
            key=lambda item: item.action.action_id,
        )

    def append_checkpoint(self, checkpoint: RunCheckpoint) -> None:
        self._create(
            "checkpoints",
            checkpoint_document_id(checkpoint.run_id, checkpoint.sequence),
            checkpoint,
        )

    def latest_checkpoint(self, run_id: str) -> RunCheckpoint | None:
        checkpoints = self.list_checkpoints(run_id)
        return checkpoints[-1] if checkpoints else None

    def list_checkpoints(self, run_id: str) -> list[RunCheckpoint]:
        return sorted(
            self._query("checkpoints", RunCheckpoint, field="run_id", value=run_id),
            key=lambda item: item.sequence,
        )

    def add_case_tag(self, tag: CaseTag) -> None:
        self._create("case_tags", f"{tag.run_id}:{tag.finding_id}", tag)

    def list_case_tags(self, run_id: str) -> list[CaseTag]:
        return sorted(
            self._query("case_tags", CaseTag, field="run_id", value=run_id),
            key=lambda item: item.finding_id,
        )

    def initialize_run_state(self, run: Run, checkpoint: RunCheckpoint) -> None:
        validate_initial_run(run, checkpoint)
        run_reference = self._document("runs", run.run_id)
        checkpoint_reference = self._document(
            "checkpoints", checkpoint_document_id(run.run_id, checkpoint.sequence)
        )
        transaction = self._client.transaction()

        @firestore.transactional
        def initialize(current_transaction: Any) -> None:
            if run_reference.get(transaction=current_transaction).exists:
                raise DuplicateRecordError("run already exists")
            current_transaction.create(run_reference, serialize_model(run))
            current_transaction.create(checkpoint_reference, serialize_model(checkpoint))

        try:
            initialize(transaction)
        except DuplicateRecordError:
            raise
        except AlreadyExists as error:
            raise DuplicateRecordError("run already exists") from error
        except GoogleAPICallError as error:
            raise IntegrationUnavailableError("persistent storage is unavailable") from error

    def commit_run_intake(self, commit: RunIntakeCommit) -> None:
        validate_initial_run(commit.run, commit.checkpoint)
        run_reference = self._document("runs", commit.run.run_id)
        checkpoint_reference = self._document(
            "checkpoints",
            checkpoint_document_id(commit.run.run_id, commit.checkpoint.sequence),
        )
        regulation_reference = self._document("regulations", commit.regulation.regulation.reg_id)
        source_reference = self._document("source_documents", commit.source_document.run_id)
        transaction = self._client.transaction()

        @firestore.transactional
        def commit_metadata(current_transaction: Any) -> None:
            snapshots = (
                run_reference.get(transaction=current_transaction),
                checkpoint_reference.get(transaction=current_transaction),
                regulation_reference.get(transaction=current_transaction),
                source_reference.get(transaction=current_transaction),
            )
            if any(snapshot.exists for snapshot in snapshots):
                raise DuplicateRecordError("run intake metadata already exists")
            current_transaction.create(run_reference, serialize_model(commit.run))
            current_transaction.create(checkpoint_reference, serialize_model(commit.checkpoint))
            current_transaction.create(regulation_reference, serialize_model(commit.regulation))
            current_transaction.create(source_reference, serialize_model(commit.source_document))

        try:
            commit_metadata(transaction)
        except DuplicateRecordError:
            raise
        except AlreadyExists as error:
            raise DuplicateRecordError("run intake metadata already exists") from error
        except GoogleAPICallError as error:
            raise IntegrationUnavailableError("persistent storage is unavailable") from error

    def get_worker_handoff(self, run_id: str) -> WorkerHandoffRecord:
        return self._get("worker_handoffs", run_id, WorkerHandoffRecord)

    def commit_verified_worker_handoff(self, commit: VerifiedWorkerHandoffCommit) -> bool:
        run_id = commit.run.run_id
        run_reference = self._document("runs", run_id)
        source_reference = self._document("source_documents", run_id)
        handoff_reference = self._document("worker_handoffs", run_id)
        contract_reference = self._document("synthetic_contracts", commit.contract.contract_id)
        finding_reference = self._document("findings", commit.finding.finding_id)
        action_reference = self._document("proposed_actions", commit.action.action.action_id)
        approval_reference = self._document("approvals", commit.approval.approval_id)
        slot_reference = self._document("pending_approval_slots", run_id)
        key_reference = self._document("action_idempotency", commit.action.action.idempotency_key)
        previous_reference = self._document(
            "checkpoints",
            checkpoint_document_id(run_id, commit.checkpoints[0].sequence - 1),
        )
        obligations_query = self._collection("obligations").where(
            filter=FieldFilter("run_id", "==", run_id)
        )
        findings_query = self._collection("findings").where(
            filter=FieldFilter("run_id", "==", run_id)
        )
        actions_query = self._collection("proposed_actions").where(
            filter=FieldFilter("run_id", "==", run_id)
        )
        approvals_query = self._collection("approvals").where(
            filter=FieldFilter("run_id", "==", run_id)
        )
        transaction = self._client.transaction()

        @firestore.transactional
        def handoff(current_transaction: Any) -> bool:
            run_snapshot = run_reference.get(transaction=current_transaction)
            source_snapshot = source_reference.get(transaction=current_transaction)
            handoff_snapshot = handoff_reference.get(transaction=current_transaction)
            contract_snapshot = contract_reference.get(transaction=current_transaction)
            finding_snapshot = finding_reference.get(transaction=current_transaction)
            action_snapshot = action_reference.get(transaction=current_transaction)
            approval_snapshot = approval_reference.get(transaction=current_transaction)
            slot_snapshot = slot_reference.get(transaction=current_transaction)
            key_snapshot = key_reference.get(transaction=current_transaction)
            previous_snapshot = previous_reference.get(transaction=current_transaction)
            obligation_snapshots = list(current_transaction.get(obligations_query))
            finding_snapshots = list(current_transaction.get(findings_query))
            action_snapshots = list(current_transaction.get(actions_query))
            approval_snapshots = list(current_transaction.get(approvals_query))
            if not run_snapshot.exists or not source_snapshot.exists:
                raise StaleRecordError("worker handoff base binding is missing")
            current_run = Run.model_validate(run_snapshot.to_dict())
            source = SourceDocumentRecord.model_validate(source_snapshot.to_dict())
            if handoff_snapshot.exists:
                existing = WorkerHandoffRecord.model_validate(handoff_snapshot.to_dict())
                obligations = sorted(
                    (
                        Obligation.model_validate(
                            self._without(cast(dict[str, Any], snapshot.to_dict()), "run_id")
                        )
                        for snapshot in obligation_snapshots
                        if snapshot.exists
                    ),
                    key=lambda item: item.obligation_id,
                )
                if (
                    existing != commit.handoff
                    or source != commit.expected_source
                    or current_run.state is not RunState.AWAITING_APPROVAL
                    or not all(
                        snapshot.exists
                        for snapshot in (
                            finding_snapshot,
                            action_snapshot,
                            approval_snapshot,
                            slot_snapshot,
                            key_snapshot,
                        )
                    )
                    or Finding.model_validate(finding_snapshot.to_dict()) != commit.finding
                    or ActionRecord.model_validate(action_snapshot.to_dict()) != commit.action
                    or Approval.model_validate(approval_snapshot.to_dict()) != commit.approval
                    or PendingApprovalSlot.model_validate(slot_snapshot.to_dict())
                    != commit.pending_slot
                    or obligations
                    != sorted(commit.obligations, key=lambda item: item.obligation_id)
                    or current_run.pending_approvals != [commit.approval]
                ):
                    raise StaleRecordError("committed worker handoff is not coherent")
                return True
            if not previous_snapshot.exists:
                raise StaleRecordError("worker handoff checkpoint is missing")
            previous = RunCheckpoint.model_validate(previous_snapshot.to_dict())
            if current_run.state is not RunState.MAPPED or source != commit.expected_source:
                raise StaleRecordError("worker handoff base binding changed")
            if (
                obligation_snapshots
                or finding_snapshots
                or action_snapshots
                or approval_snapshots
                or finding_snapshot.exists
                or action_snapshot.exists
                or approval_snapshot.exists
                or slot_snapshot.exists
                or key_snapshot.exists
            ):
                raise StaleRecordError("partial worker handoff state exists")
            try:
                validate_authoritative_run_update(
                    current=current_run,
                    updated=commit.run,
                    previous_checkpoint=previous,
                    checkpoints=commit.checkpoints,
                    audit_events=commit.audit_events,
                )
            except InvalidRunTransitionError as error:
                raise StaleRecordError("worker transition binding changed") from error
            if contract_snapshot.exists:
                if SyntheticContract.model_validate(contract_snapshot.to_dict()) != commit.contract:
                    raise StaleRecordError("synthetic target conflicts with fixture")
            else:
                current_transaction.create(contract_reference, serialize_model(commit.contract))
            for obligation in commit.obligations:
                current_transaction.create(
                    self._document("obligations", obligation.obligation_id),
                    serialize_model(obligation) | {"run_id": run_id},
                )
            current_transaction.create(finding_reference, serialize_model(commit.finding))
            current_transaction.create(action_reference, serialize_model(commit.action))
            current_transaction.create(
                key_reference,
                {
                    "action_id": commit.action.action.action_id,
                    "run_id": run_id,
                    "finding_id": commit.finding.finding_id,
                },
            )
            current_transaction.create(approval_reference, serialize_model(commit.approval))
            current_transaction.create(slot_reference, serialize_model(commit.pending_slot))
            current_transaction.set(run_reference, serialize_model(commit.run))
            for checkpoint in commit.checkpoints:
                current_transaction.create(
                    self._document(
                        "checkpoints",
                        checkpoint_document_id(run_id, checkpoint.sequence),
                    ),
                    serialize_model(checkpoint),
                )
            for event in commit.audit_events:
                current_transaction.create(
                    self._document("audit_events", event.event_id),
                    serialize_model(event),
                )
            current_transaction.create(handoff_reference, serialize_model(commit.handoff))
            return False

        try:
            return bool(handoff(transaction))
        except StaleRecordError:
            raise
        except AlreadyExists as error:
            raise StaleRecordError("worker handoff changed during commit") from error
        except GoogleAPICallError as error:
            raise IntegrationUnavailableError("persistent storage is unavailable") from error

    def create_approval_required_action(
        self, commit: ApprovalRequiredActionCommit
    ) -> ActionAttemptResult:
        proposed = commit.action.action
        run_reference = self._document("runs", commit.action.run_id)
        finding_reference = self._document("findings", proposed.finding_id)
        action_reference = self._document("proposed_actions", proposed.action_id)
        key_reference = self._document("action_idempotency", proposed.idempotency_key)
        approval_reference = self._document("approvals", commit.approval.approval_id)
        slot_reference = self._document("pending_approval_slots", commit.action.run_id)
        approval_query = self._collection("approvals").where(
            filter=FieldFilter("run_id", "==", commit.action.run_id)
        )
        transaction = self._client.transaction()

        @firestore.transactional
        def create_draft(current_transaction: Any) -> ActionAttemptResult:
            run_snapshot = run_reference.get(transaction=current_transaction)
            finding_snapshot = finding_reference.get(transaction=current_transaction)
            action_snapshot = action_reference.get(transaction=current_transaction)
            key_snapshot = key_reference.get(transaction=current_transaction)
            approval_snapshot = approval_reference.get(transaction=current_transaction)
            slot_snapshot = slot_reference.get(transaction=current_transaction)
            approval_snapshots = list(current_transaction.get(approval_query))
            approvals = [
                Approval.model_validate(snapshot.to_dict())
                for snapshot in approval_snapshots
                if snapshot.exists
            ]
            pending = sorted(
                (approval for approval in approvals if approval.status is ApprovalStatus.PENDING),
                key=lambda item: item.approval_id,
            )
            if not run_snapshot.exists or not finding_snapshot.exists:
                raise StaleRecordError("approval-required action binding is missing")
            current_run = Run.model_validate(run_snapshot.to_dict())
            current_finding = Finding.model_validate(finding_snapshot.to_dict())
            if key_snapshot.exists:
                key_payload = cast(dict[str, Any], key_snapshot.to_dict())
                if not all(
                    snapshot.exists
                    for snapshot in (action_snapshot, approval_snapshot, slot_snapshot)
                ):
                    raise StaleRecordError("idempotency claim is not bound to a coherent approval")
                existing = ActionRecord.model_validate(action_snapshot.to_dict())
                approval = Approval.model_validate(approval_snapshot.to_dict())
                slot = PendingApprovalSlot.model_validate(slot_snapshot.to_dict())
                if (
                    key_payload.get("action_id") != proposed.action_id
                    or key_payload.get("run_id") != commit.action.run_id
                    or key_payload.get("finding_id") != proposed.finding_id
                    or existing.action.idempotency_key != proposed.idempotency_key
                    or existing.run_id != commit.action.run_id
                    or approval.action_id != existing.action.action_id
                    or approval.finding_id != existing.action.finding_id
                    or approval.run_id != existing.run_id
                    or approval.status is not ApprovalStatus.PENDING
                    or slot != commit.pending_slot
                    or [item.approval_id for item in pending] != [approval.approval_id]
                    or current_finding.run_id != existing.run_id
                    or current_finding.status is not FindingStatus.AWAITING_APPROVAL
                    or current_finding.proposed_action != existing.action
                    or current_run.run_id != existing.run_id
                    or current_run.state in {RunState.COMPLETED, RunState.FAILED}
                ):
                    raise StaleRecordError("idempotency claim is not bound to a coherent approval")
                current_transaction.create(
                    self._document("audit_events", commit.action_attempt_event.event_id),
                    serialize_model(commit.action_attempt_event),
                )
                current_transaction.create(
                    self._document("audit_events", commit.duplicate_event.event_id),
                    serialize_model(commit.duplicate_event),
                )
                return ActionAttemptResult(
                    action=existing.action,
                    duplicate_prevented=True,
                    approval=approval,
                )
            if action_snapshot.exists or approval_snapshot.exists:
                raise DuplicateRecordError("approval-required action identifier exists")
            if slot_snapshot.exists or pending:
                raise DuplicateRecordError("run already has a pending draft-amendment approval")
            if (
                current_finding != commit.expected_finding
                or current_finding.run_id != commit.action.run_id
                or current_run.run_id != commit.action.run_id
                or current_run.state in {RunState.COMPLETED, RunState.FAILED}
            ):
                raise StaleRecordError("approval-required action binding changed")
            current_transaction.create(action_reference, serialize_model(commit.action))
            current_transaction.create(
                key_reference,
                {
                    "action_id": proposed.action_id,
                    "run_id": commit.action.run_id,
                    "finding_id": proposed.finding_id,
                },
            )
            current_transaction.create(approval_reference, serialize_model(commit.approval))
            current_transaction.set(finding_reference, serialize_model(commit.finding))
            current_transaction.create(slot_reference, serialize_model(commit.pending_slot))
            for event in (
                commit.action_attempt_event,
                commit.first_execution_event,
            ):
                current_transaction.create(
                    self._document("audit_events", event.event_id),
                    serialize_model(event),
                )
            return ActionAttemptResult(
                action=proposed,
                duplicate_prevented=False,
                approval=commit.approval,
            )

        try:
            return cast(ActionAttemptResult, create_draft(transaction))
        except (DuplicateRecordError, StaleRecordError):
            raise
        except AlreadyExists as error:
            raise StaleRecordError("approval-required action changed during commit") from error
        except GoogleAPICallError as error:
            raise IntegrationUnavailableError("persistent storage is unavailable") from error

    def commit_run_transition(
        self,
        *,
        expected_state: RunState,
        run: Run,
        checkpoint: RunCheckpoint,
        audit_event: AuditEvent,
    ) -> None:
        run_reference = self._document("runs", run.run_id)
        previous_reference = self._document(
            "checkpoints", checkpoint_document_id(run.run_id, checkpoint.sequence - 1)
        )
        checkpoint_reference = self._document(
            "checkpoints", checkpoint_document_id(run.run_id, checkpoint.sequence)
        )
        event_reference = self._document("audit_events", audit_event.event_id)
        slot_reference = self._document("pending_approval_slots", run.run_id)
        approval_query = self._collection("approvals").where(
            filter=FieldFilter("run_id", "==", run.run_id)
        )
        transaction = self._client.transaction()

        @firestore.transactional
        def transition(current_transaction: Any) -> None:
            run_snapshot = run_reference.get(transaction=current_transaction)
            previous_snapshot = previous_reference.get(transaction=current_transaction)
            slot_snapshot = slot_reference.get(transaction=current_transaction)
            approval_snapshots = list(current_transaction.get(approval_query))
            if not run_snapshot.exists or not previous_snapshot.exists:
                raise StaleRecordError("run transition base record is missing")
            current_run = Run.model_validate(run_snapshot.to_dict())
            previous = RunCheckpoint.model_validate(previous_snapshot.to_dict())
            if current_run.state is not expected_state:
                raise StaleRecordError("run state changed before transition commit")
            if run.state is RunState.COMPLETED and (
                slot_snapshot.exists
                or any(
                    Approval.model_validate(snapshot.to_dict()).status is ApprovalStatus.PENDING
                    for snapshot in approval_snapshots
                    if snapshot.exists
                )
            ):
                raise StaleRecordError("completed run cannot retain a pending approval")
            RunStateMachine().validate(
                current_run.state,
                checkpoint.state,
                checkpoint=previous,
            )
            if checkpoint.sequence != previous.sequence + 1:
                raise StaleRecordError("checkpoint sequence changed")
            try:
                validate_authoritative_run_update(
                    current=current_run,
                    updated=run,
                    previous_checkpoint=previous,
                    checkpoints=[checkpoint],
                    audit_events=[audit_event],
                )
            except InvalidRunTransitionError as error:
                raise StaleRecordError("run transition binding changed") from error
            current_transaction.set(run_reference, serialize_model(run))
            current_transaction.create(checkpoint_reference, serialize_model(checkpoint))
            current_transaction.create(event_reference, serialize_model(audit_event))

        try:
            transition(transaction)
        except (StaleRecordError, DuplicateRecordError):
            raise
        except AlreadyExists as error:
            raise StaleRecordError("transition was already committed") from error
        except GoogleAPICallError as error:
            raise IntegrationUnavailableError("persistent storage is unavailable") from error

    def commit_approval_decision(self, commit: ApprovalDecisionCommit) -> None:
        if not commit.checkpoints:
            raise StaleRecordError("approval decision requires a state checkpoint")
        approval_reference = self._document("approvals", commit.approval.approval_id)
        action_reference = self._document("proposed_actions", commit.action.action.action_id)
        finding_reference = self._document("findings", commit.finding.finding_id)
        run_reference = self._document("runs", commit.run.run_id)
        first_sequence = commit.checkpoints[0].sequence
        previous_checkpoint_reference = self._document(
            "checkpoints",
            checkpoint_document_id(commit.run.run_id, first_sequence - 1),
        )
        slot_reference = self._document("pending_approval_slots", commit.run.run_id)
        approval_query = self._collection("approvals").where(
            filter=FieldFilter("run_id", "==", commit.run.run_id)
        )
        transaction = self._client.transaction()

        @firestore.transactional
        def decide(current_transaction: Any) -> None:
            approval_snapshot = approval_reference.get(transaction=current_transaction)
            action_snapshot = action_reference.get(transaction=current_transaction)
            finding_snapshot = finding_reference.get(transaction=current_transaction)
            run_snapshot = run_reference.get(transaction=current_transaction)
            previous_checkpoint_snapshot = previous_checkpoint_reference.get(
                transaction=current_transaction
            )
            slot_snapshot = slot_reference.get(transaction=current_transaction)
            approval_snapshots = list(current_transaction.get(approval_query))
            if not all(
                snapshot.exists
                for snapshot in (
                    approval_snapshot,
                    action_snapshot,
                    finding_snapshot,
                    run_snapshot,
                    previous_checkpoint_snapshot,
                    slot_snapshot,
                )
            ):
                raise StaleRecordError("approval decision binding is missing")
            approval = Approval.model_validate(approval_snapshot.to_dict())
            action = ActionRecord.model_validate(action_snapshot.to_dict())
            finding = Finding.model_validate(finding_snapshot.to_dict())
            run = Run.model_validate(run_snapshot.to_dict())
            previous_checkpoint = RunCheckpoint.model_validate(
                previous_checkpoint_snapshot.to_dict()
            )
            slot = PendingApprovalSlot.model_validate(slot_snapshot.to_dict())
            pending_ids = sorted(
                approval.approval_id
                for approval in (
                    Approval.model_validate(snapshot.to_dict())
                    for snapshot in approval_snapshots
                    if snapshot.exists
                )
                if approval.status is ApprovalStatus.PENDING
            )
            if approval.status is not ApprovalStatus.PENDING:
                raise StaleRecordError("approval was already decided")
            if (
                approval != commit.expected_approval
                or action != commit.expected_action
                or finding != commit.expected_finding
                or run.state is not commit.expected_run_state
                or approval.action_id != action.action.action_id
                or approval.finding_id != finding.finding_id
                or approval.run_id != action.run_id
                or slot.approval_id != approval.approval_id
                or slot.action_id != action.action.action_id
                or slot.finding_id != finding.finding_id
                or slot.run_id != action.run_id
                or pending_ids != [approval.approval_id]
            ):
                raise StaleRecordError("approval decision binding changed")
            if (
                commit.approval.status is ApprovalStatus.PENDING
                or commit.run.pending_approvals
                or commit.run.state is not RunState.COMPLETED
            ):
                raise StaleRecordError("approval decision must clear pending state")
            validate_approval_decision_outputs(commit)
            try:
                validate_authoritative_run_update(
                    current=run,
                    updated=commit.run,
                    previous_checkpoint=previous_checkpoint,
                    checkpoints=commit.checkpoints,
                    audit_events=commit.audit_events,
                )
            except InvalidRunTransitionError as error:
                raise StaleRecordError("approval transition binding changed") from error
            if commit.snapshot is not None:
                amendment = action.amendment
                if amendment is None:
                    raise StaleRecordError("approved action has no amendment")
                source_reference = self._document("synthetic_contracts", amendment.contract_id)
                source_snapshot = source_reference.get(transaction=current_transaction)
                if not source_snapshot.exists:
                    raise StaleRecordError("source contract is missing")
                source = SyntheticContract.model_validate(source_snapshot.to_dict())
                if (
                    commit.snapshot.original != source
                    or commit.snapshot.action_id != action.action.action_id
                    or commit.snapshot.run_id != action.run_id
                ):
                    raise StaleRecordError("shadow snapshot binding changed")
                current_transaction.create(
                    self._document("shadow_snapshots", commit.snapshot.snapshot_id),
                    serialize_model(commit.snapshot),
                )
            current_transaction.set(approval_reference, serialize_model(commit.approval))
            current_transaction.set(action_reference, serialize_model(commit.action))
            current_transaction.set(finding_reference, serialize_model(commit.finding))
            current_transaction.set(run_reference, serialize_model(commit.run))
            current_transaction.delete(slot_reference)
            for checkpoint in commit.checkpoints:
                current_transaction.create(
                    self._document(
                        "checkpoints",
                        checkpoint_document_id(checkpoint.run_id, checkpoint.sequence),
                    ),
                    serialize_model(checkpoint),
                )
            for event in commit.audit_events:
                current_transaction.create(
                    self._document("audit_events", event.event_id),
                    serialize_model(event),
                )

        try:
            decide(transaction)
        except StaleRecordError:
            raise
        except AlreadyExists as error:
            raise StaleRecordError("approval decision was already committed") from error
        except GoogleAPICallError as error:
            raise IntegrationUnavailableError("persistent storage is unavailable") from error

    def _query_raw(self, collection: str, *, field: str, value: object) -> list[dict[str, Any]]:
        try:
            query = self._collection(collection).where(filter=FieldFilter(field, "==", value))
            return [cast(dict[str, Any], snapshot.to_dict()) for snapshot in query.stream()]
        except GoogleAPICallError as error:
            raise IntegrationUnavailableError("persistent storage is unavailable") from error

    @staticmethod
    def _without(payload: dict[str, Any], key: str) -> dict[str, Any]:
        return {name: value for name, value in payload.items() if name != key}
