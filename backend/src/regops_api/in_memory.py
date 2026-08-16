"""Explicitly non-production in-memory persistence for development and tests only."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from threading import RLock
from typing import Literal, TypeVar

from regops_api.domain_models import (
    ActionRecord,
    AuditEvent,
    CaseTag,
    InternalReviewTask,
    RegulationRecord,
    RunCheckpoint,
    ShadowContractSnapshot,
    SyntheticContract,
)
from regops_api.repositories import DuplicateRecordError, RecordNotFoundError
from regops_api.schemas import Approval, AuditReport, Finding, Obligation, Run

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
        self._obligations: dict[str, list[Obligation]] = {}
        self._contracts: dict[str, SyntheticContract] = {}
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
