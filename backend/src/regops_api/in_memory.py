"""Explicitly non-production in-memory persistence for development and tests only."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from threading import RLock
from typing import Literal, TypeVar

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
)
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
    validate_authoritative_run_update,
    validate_initial_run,
)

RecordT = TypeVar("RecordT")


class InMemoryRepositories:
    """NON-PRODUCTION adapter that must be explicitly labelled development or test."""

    is_production = False

    def __init__(self, *, purpose: Literal["development", "test"]) -> None:
        if purpose not in {"development", "test"}:
            raise ValueError(
                "InMemoryRepositories is non-production and requires development or test purpose"
            )
        self.purpose = purpose
        self._lock = RLock()
        self._runs: dict[str, Run] = {}
        self._regulations: dict[str, RegulationRecord] = {}
        self._source_documents: dict[str, SourceDocumentRecord] = {}
        self._obligations: dict[str, list[Obligation]] = {}
        self._contracts: dict[str, SyntheticContract] = {}
        self._cases: dict[str, AffectedCase] = {}
        self._snapshots: dict[str, ShadowContractSnapshot] = {}
        self._findings: dict[str, Finding] = {}
        self._tasks: dict[str, InternalReviewTask] = {}
        self._approvals: dict[str, Approval] = {}
        self._reports: dict[str, AuditReport] = {}
        self._events: dict[str, list[AuditEvent]] = {}
        self._actions: dict[str, ActionRecord] = {}
        self._action_keys: dict[str, str] = {}
        self._checkpoints: dict[str, list[RunCheckpoint]] = {}
        self._case_tags: dict[str, list[CaseTag]] = {}
        self._pending_approval_slots: dict[str, PendingApprovalSlot] = {}

    @classmethod
    def for_tests(cls) -> InMemoryRepositories:
        return cls(purpose="test")

    @classmethod
    def for_development(cls) -> InMemoryRepositories:
        return cls(purpose="development")

    def add_run(self, run: Run) -> None:
        with self._lock:
            self._insert_unique(self._runs, run.run_id, run)

    def get_run(self, run_id: str) -> Run:
        return self._get(self._runs, run_id, "run")

    def update_run(self, run: Run) -> None:
        with self._lock:
            self._require(self._runs, run.run_id, "run")
            self._runs[run.run_id] = deepcopy(run)

    def add_regulation(self, record: RegulationRecord) -> None:
        with self._lock:
            self._insert_unique(
                self._regulations, record.regulation.reg_id, record
            )

    def add_source_document(self, record: SourceDocumentRecord) -> None:
        with self._lock:
            self._insert_unique(self._source_documents, record.run_id, record)

    def get_source_document(self, run_id: str) -> SourceDocumentRecord:
        return self._get(self._source_documents, run_id, "source document")

    def get_regulation(self, regulation_id: str) -> RegulationRecord:
        return self._get(self._regulations, regulation_id, "regulation")

    def find_regulation_by_hash(self, content_sha256: str) -> RegulationRecord | None:
        with self._lock:
            match = next(
                (
                    record
                    for record in self._regulations.values()
                    if record.content_sha256 == content_sha256
                ),
                None,
            )
            return deepcopy(match)

    def list_regulations_by_source(self, source_filename: str) -> list[RegulationRecord]:
        with self._lock:
            records = [
                record
                for record in self._regulations.values()
                if record.regulation.source_filename == source_filename
            ]
            return deepcopy(sorted(records, key=lambda item: item.version))

    def add_obligations(self, run_id: str, obligations: list[Obligation]) -> None:
        with self._lock:
            existing_ids = {
                obligation.obligation_id
                for values in self._obligations.values()
                for obligation in values
            }
            incoming_ids = [obligation.obligation_id for obligation in obligations]
            if len(set(incoming_ids)) != len(incoming_ids) or existing_ids.intersection(
                incoming_ids
            ):
                raise DuplicateRecordError("obligation identifier already exists")
            self._obligations.setdefault(run_id, []).extend(deepcopy(obligations))

    def list_obligations(self, run_id: str) -> list[Obligation]:
        with self._lock:
            return deepcopy(self._obligations.get(run_id, []))

    def add_synthetic_contract(self, contract: SyntheticContract) -> None:
        with self._lock:
            self._insert_unique(self._contracts, contract.contract_id, contract)

    def get_synthetic_contract(self, contract_id: str) -> SyntheticContract:
        return self._get(self._contracts, contract_id, "synthetic contract")

    def list_synthetic_contracts(self) -> list[SyntheticContract]:
        with self._lock:
            return deepcopy(list(self._contracts.values()))

    def add_synthetic_case(self, case: AffectedCase) -> None:
        with self._lock:
            self._insert_unique(self._cases, case.case_id, case)

    def get_synthetic_case(self, case_id: str) -> AffectedCase:
        return self._get(self._cases, case_id, "synthetic case")

    def list_synthetic_cases(self) -> list[AffectedCase]:
        with self._lock:
            return deepcopy(list(self._cases.values()))

    def save_shadow_snapshot(self, snapshot: ShadowContractSnapshot) -> None:
        with self._lock:
            self._insert_unique(self._snapshots, snapshot.snapshot_id, snapshot)

    def get_shadow_snapshot(self, snapshot_id: str) -> ShadowContractSnapshot:
        return self._get(self._snapshots, snapshot_id, "shadow snapshot")

    def add_findings(self, findings: list[Finding]) -> None:
        with self._lock:
            for finding in findings:
                if finding.finding_id in self._findings:
                    raise DuplicateRecordError(
                        f"finding {finding.finding_id!r} already exists"
                    )
            for finding in findings:
                self._findings[finding.finding_id] = deepcopy(finding)

    def get_finding(self, finding_id: str) -> Finding:
        return self._get(self._findings, finding_id, "finding")

    def list_findings(self, run_id: str) -> list[Finding]:
        with self._lock:
            return deepcopy(
                [finding for finding in self._findings.values() if finding.run_id == run_id]
            )

    def update_finding(self, finding: Finding) -> None:
        with self._lock:
            self._require(self._findings, finding.finding_id, "finding")
            self._findings[finding.finding_id] = deepcopy(finding)

    def add_review_task(self, task: InternalReviewTask) -> None:
        with self._lock:
            self._insert_unique(self._tasks, task.task_id, task)

    def get_review_task(self, task_id: str) -> InternalReviewTask:
        return self._get(self._tasks, task_id, "review task")

    def list_review_tasks(self, run_id: str) -> list[InternalReviewTask]:
        with self._lock:
            return deepcopy([task for task in self._tasks.values() if task.run_id == run_id])

    def add_approval(self, approval: Approval) -> None:
        with self._lock:
            self._insert_unique(self._approvals, approval.approval_id, approval)

    def get_approval(self, approval_id: str) -> Approval:
        return self._get(self._approvals, approval_id, "approval")

    def update_approval(self, approval: Approval) -> None:
        with self._lock:
            self._require(self._approvals, approval.approval_id, "approval")
            self._approvals[approval.approval_id] = deepcopy(approval)

    def list_approvals(self, run_id: str) -> list[Approval]:
        with self._lock:
            return deepcopy(
                [approval for approval in self._approvals.values() if approval.run_id == run_id]
            )

    def append_audit_event(self, event: AuditEvent) -> None:
        with self._lock:
            self._events.setdefault(event.run_id, []).append(deepcopy(event))

    def list_audit_events(self, run_id: str) -> list[AuditEvent]:
        with self._lock:
            return deepcopy(self._events.get(run_id, []))

    def save_audit_report(self, report: AuditReport) -> None:
        with self._lock:
            self._reports[report.run_id] = deepcopy(report)

    def get_audit_report(self, run_id: str) -> AuditReport:
        return self._get(self._reports, run_id, "audit report")

    def add_action(self, record: ActionRecord) -> None:
        with self._lock:
            key = record.action.idempotency_key
            if key in self._action_keys:
                raise DuplicateRecordError(f"action idempotency key {key!r} already exists")
            self._insert_unique(self._actions, record.action.action_id, record)
            self._action_keys[key] = record.action.action_id

    def get_action(self, action_id: str) -> ActionRecord:
        return self._get(self._actions, action_id, "action")

    def find_action_by_idempotency_key(self, idempotency_key: str) -> ActionRecord | None:
        with self._lock:
            action_id = self._action_keys.get(idempotency_key)
            return None if action_id is None else deepcopy(self._actions[action_id])

    def update_action(self, record: ActionRecord) -> None:
        with self._lock:
            self._require(self._actions, record.action.action_id, "action")
            self._actions[record.action.action_id] = deepcopy(record)

    def list_actions(self, run_id: str) -> list[ActionRecord]:
        with self._lock:
            return deepcopy(
                [record for record in self._actions.values() if record.run_id == run_id]
            )

    def append_checkpoint(self, checkpoint: RunCheckpoint) -> None:
        with self._lock:
            checkpoints = self._checkpoints.setdefault(checkpoint.run_id, [])
            expected = 0 if not checkpoints else checkpoints[-1].sequence + 1
            if checkpoint.sequence != expected:
                raise DuplicateRecordError(
                    f"checkpoint sequence must be {expected}, got {checkpoint.sequence}"
                )
            checkpoints.append(deepcopy(checkpoint))

    def latest_checkpoint(self, run_id: str) -> RunCheckpoint | None:
        with self._lock:
            checkpoints = self._checkpoints.get(run_id, [])
            return None if not checkpoints else deepcopy(checkpoints[-1])

    def list_checkpoints(self, run_id: str) -> list[RunCheckpoint]:
        with self._lock:
            return deepcopy(self._checkpoints.get(run_id, []))

    def add_case_tag(self, tag: CaseTag) -> None:
        with self._lock:
            tags = self._case_tags.setdefault(tag.run_id, [])
            if any(existing.finding_id == tag.finding_id for existing in tags):
                raise DuplicateRecordError("case tag already exists for finding")
            tags.append(deepcopy(tag))

    def list_case_tags(self, run_id: str) -> list[CaseTag]:
        with self._lock:
            return deepcopy(self._case_tags.get(run_id, []))

    def initialize_run_state(self, run: Run, checkpoint: RunCheckpoint) -> None:
        with self._lock:
            validate_initial_run(run, checkpoint)
            self._insert_unique(self._runs, run.run_id, run)
            checkpoints = self._checkpoints.setdefault(run.run_id, [])
            if checkpoints:
                raise DuplicateRecordError("initial checkpoint already exists")
            checkpoints.append(deepcopy(checkpoint))

    def commit_run_intake(self, commit: RunIntakeCommit) -> None:
        with self._lock:
            validate_initial_run(commit.run, commit.checkpoint)
            regulation_id = commit.regulation.regulation.reg_id
            if (
                commit.run.run_id in self._runs
                or regulation_id in self._regulations
                or commit.source_document.run_id in self._source_documents
                or self._checkpoints.get(commit.run.run_id)
            ):
                raise DuplicateRecordError("run intake metadata already exists")
            self._runs[commit.run.run_id] = deepcopy(commit.run)
            self._regulations[regulation_id] = deepcopy(commit.regulation)
            self._source_documents[commit.source_document.run_id] = deepcopy(
                commit.source_document
            )
            self._checkpoints[commit.run.run_id] = [deepcopy(commit.checkpoint)]

    def create_approval_required_action(
        self, commit: ApprovalRequiredActionCommit
    ) -> ActionAttemptResult:
        with self._lock:
            proposed = commit.action.action
            current_run = self._get(self._runs, commit.action.run_id, "run")
            current_finding = self._get(
                self._findings, proposed.finding_id, "finding"
            )
            pending = sorted(
                (
                    approval
                    for approval in self._approvals.values()
                    if approval.run_id == commit.action.run_id
                    and approval.status is ApprovalStatus.PENDING
                ),
                key=lambda item: item.approval_id,
            )
            claimed_action_id = self._action_keys.get(proposed.idempotency_key)
            if claimed_action_id is not None:
                existing = self._actions.get(claimed_action_id)
                approval = self._approvals.get(commit.approval.approval_id)
                slot = self._pending_approval_slots.get(commit.action.run_id)
                if (
                    existing is None
                    or claimed_action_id != proposed.action_id
                    or existing.action.idempotency_key != proposed.idempotency_key
                    or existing.run_id != commit.action.run_id
                    or approval is None
                    or approval.action_id != existing.action.action_id
                    or approval.finding_id != existing.action.finding_id
                    or approval.run_id != existing.run_id
                    or approval.status is not ApprovalStatus.PENDING
                    or slot != commit.pending_slot
                    or [item.approval_id for item in pending]
                    != [approval.approval_id]
                    or current_finding.run_id != existing.run_id
                    or current_finding.status is not FindingStatus.AWAITING_APPROVAL
                    or current_finding.proposed_action != existing.action
                    or current_run.state in {RunState.COMPLETED, RunState.FAILED}
                ):
                    raise StaleRecordError(
                        "idempotency claim is not bound to a coherent approval"
                    )
                self._events.setdefault(existing.run_id, []).extend(
                    deepcopy([commit.action_attempt_event, commit.duplicate_event])
                )
                return ActionAttemptResult(
                    action=deepcopy(existing.action),
                    duplicate_prevented=True,
                    approval=deepcopy(approval),
                )
            if (
                proposed.action_id in self._actions
                or commit.approval.approval_id in self._approvals
            ):
                raise DuplicateRecordError("approval-required action identifier exists")
            if pending or commit.action.run_id in self._pending_approval_slots:
                raise DuplicateRecordError(
                    "run already has a pending draft-amendment approval"
                )
            if (
                current_finding != commit.expected_finding
                or current_finding.run_id != commit.action.run_id
                or current_run.run_id != commit.action.run_id
                or current_run.state in {RunState.COMPLETED, RunState.FAILED}
            ):
                raise StaleRecordError("approval-required action binding changed")
            self._actions[proposed.action_id] = deepcopy(commit.action)
            self._action_keys[proposed.idempotency_key] = proposed.action_id
            self._approvals[commit.approval.approval_id] = deepcopy(commit.approval)
            self._findings[commit.finding.finding_id] = deepcopy(commit.finding)
            self._pending_approval_slots[commit.action.run_id] = deepcopy(
                commit.pending_slot
            )
            self._events.setdefault(commit.action.run_id, []).extend(
                deepcopy(
                    [commit.action_attempt_event, commit.first_execution_event]
                )
            )
            return ActionAttemptResult(
                action=deepcopy(proposed),
                duplicate_prevented=False,
                approval=deepcopy(commit.approval),
            )

    def commit_run_transition(
        self,
        *,
        expected_state: RunState,
        run: Run,
        checkpoint: RunCheckpoint,
        audit_event: AuditEvent,
    ) -> None:
        with self._lock:
            current = self._get(self._runs, run.run_id, "run")
            if current.state is not expected_state:
                raise StaleRecordError("run state changed before transition commit")
            if run.state is RunState.COMPLETED and (
                run.run_id in self._pending_approval_slots
                or any(
                    approval.run_id == run.run_id
                    and approval.status is ApprovalStatus.PENDING
                    for approval in self._approvals.values()
                )
            ):
                raise StaleRecordError("completed run cannot retain a pending approval")
            expected_sequence = len(self._checkpoints.get(run.run_id, []))
            if checkpoint.sequence != expected_sequence:
                raise StaleRecordError("checkpoint sequence changed before transition commit")
            previous = self._checkpoints[run.run_id][-1]
            try:
                validate_authoritative_run_update(
                    current=current,
                    updated=run,
                    previous_checkpoint=previous,
                    checkpoints=[checkpoint],
                    audit_events=[audit_event],
                )
            except InvalidRunTransitionError as error:
                raise StaleRecordError("run transition binding changed") from error
            self._runs[run.run_id] = deepcopy(run)
            self._checkpoints.setdefault(run.run_id, []).append(deepcopy(checkpoint))
            self._events.setdefault(run.run_id, []).append(deepcopy(audit_event))

    def commit_approval_decision(self, commit: ApprovalDecisionCommit) -> None:
        with self._lock:
            current_approval = self._get(
                self._approvals, commit.approval.approval_id, "approval"
            )
            current_action = self._get(
                self._actions, commit.action.action.action_id, "action"
            )
            current_finding = self._get(
                self._findings, commit.finding.finding_id, "finding"
            )
            current_run = self._get(self._runs, commit.run.run_id, "run")
            current_slot = self._pending_approval_slots.get(commit.run.run_id)
            pending_ids = sorted(
                approval.approval_id
                for approval in self._approvals.values()
                if approval.run_id == commit.run.run_id
                and approval.status is ApprovalStatus.PENDING
            )
            if current_approval != commit.expected_approval:
                raise StaleRecordError("approval changed before decision commit")
            if current_action != commit.expected_action:
                raise StaleRecordError("action changed before decision commit")
            if current_finding != commit.expected_finding:
                raise StaleRecordError("finding binding changed before decision commit")
            if current_run.state is not commit.expected_run_state:
                raise StaleRecordError("run changed before decision commit")
            if (
                current_slot is None
                or current_slot.approval_id != current_approval.approval_id
                or current_slot.action_id != current_action.action.action_id
                or current_slot.finding_id != current_finding.finding_id
                or pending_ids != [current_approval.approval_id]
            ):
                raise StaleRecordError("pending approval guard is inconsistent")
            checkpoints = self._checkpoints.get(commit.run.run_id, [])
            next_sequence = len(checkpoints)
            if any(
                checkpoint.run_id != commit.run.run_id
                or checkpoint.sequence != next_sequence + offset
                for offset, checkpoint in enumerate(commit.checkpoints)
            ):
                raise StaleRecordError("approval checkpoint sequence changed")
            if not checkpoints:
                raise StaleRecordError("approval run has no previous checkpoint")
            if (
                commit.approval.status is ApprovalStatus.PENDING
                or commit.run.pending_approvals
                or commit.run.state is not RunState.COMPLETED
            ):
                raise StaleRecordError("approval decision must clear pending state")
            validate_approval_decision_outputs(commit)
            try:
                validate_authoritative_run_update(
                    current=current_run,
                    updated=commit.run,
                    previous_checkpoint=checkpoints[-1],
                    checkpoints=commit.checkpoints,
                    audit_events=commit.audit_events,
                )
            except InvalidRunTransitionError as error:
                raise StaleRecordError("approval transition binding changed") from error
            if commit.snapshot is not None:
                amendment = current_action.amendment
                if amendment is None:
                    raise StaleRecordError("approved action has no bound amendment")
                source = self._get(
                    self._contracts, amendment.contract_id, "synthetic contract"
                )
                if (
                    commit.snapshot.run_id != current_action.run_id
                    or commit.snapshot.action_id != current_action.action.action_id
                    or commit.snapshot.original != source
                    or commit.snapshot.shadow.contract_id != source.contract_id
                ):
                    raise StaleRecordError("shadow snapshot binding changed")
                if commit.snapshot.snapshot_id in self._snapshots:
                    raise DuplicateRecordError("shadow snapshot already exists")
            if commit.snapshot is not None:
                self._snapshots[commit.snapshot.snapshot_id] = deepcopy(commit.snapshot)
            self._approvals[commit.approval.approval_id] = deepcopy(commit.approval)
            self._actions[commit.action.action.action_id] = deepcopy(commit.action)
            self._findings[commit.finding.finding_id] = deepcopy(commit.finding)
            self._runs[commit.run.run_id] = deepcopy(commit.run)
            del self._pending_approval_slots[commit.run.run_id]
            for checkpoint in commit.checkpoints:
                self._checkpoints.setdefault(checkpoint.run_id, []).append(
                    deepcopy(checkpoint)
                )
            self._events.setdefault(commit.run.run_id, []).extend(
                deepcopy(commit.audit_events)
            )

    def _insert_unique(
        self, collection: dict[str, RecordT], key: str, value: RecordT
    ) -> None:
        if key in collection:
            raise DuplicateRecordError(f"record {key!r} already exists")
        collection[key] = deepcopy(value)

    def _get(
        self, collection: dict[str, RecordT], key: str, label: str
    ) -> RecordT:
        with self._lock:
            self._require(collection, key, label)
            return deepcopy(collection[key])

    @staticmethod
    def _require(collection: Mapping[str, object], key: str, label: str) -> None:
        if key not in collection:
            raise RecordNotFoundError(f"{label} {key!r} was not found")
