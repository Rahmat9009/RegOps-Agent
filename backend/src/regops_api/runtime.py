"""Phase 1B persistent API services composed behind frozen HTTP schemas."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from regops_api.audit import AuditReportService
from regops_api.change_detection import Sha256ChangeDetector
from regops_api.config import RuntimeSettings
from regops_api.counterfactual import DeterministicCounterfactual
from regops_api.domain_models import (
    ActionRecord,
    ApprovalDecisionCommit,
    AuditEvent,
    AuditEventType,
    RegulationRecord,
    RevalidationResult,
    RunCheckpoint,
    RunIntakeCommit,
    SourceDocumentRecord,
    WorkflowLaunchRequest,
)
from regops_api.integrations import (
    IntegrationUnavailableError,
    ReviewerIdentityProvider,
    RuntimeStoragePort,
    WorkflowLauncher,
)
from regops_api.internal_auth import WorkflowIdentityVerifier
from regops_api.repositories import RepositoryBundle
from regops_api.runtime_errors import DomainConflictError
from regops_api.schemas import (
    ActionAutonomy,
    ActionStatus,
    ActionType,
    Approval,
    ApprovalDecision,
    ApprovalDecisionValue,
    ApprovalStatus,
    AuditReport,
    ChangeDetection,
    CounterfactualPreview,
    Finding,
    FindingList,
    FindingsBySeverity,
    FindingStatus,
    FindingSummary,
    Regulation,
    Run,
    RunProgress,
    RunState,
    RunTransition,
    Severity,
)
from regops_api.state_machine import RunStateCoordinator, plan_run_transition
from regops_api.storage import sanitize_filename
from regops_api.worker_runtime import MinimumLiveWorker

Clock = Callable[[], datetime]


@dataclass(frozen=True)
class RuntimeContainer:
    settings: RuntimeSettings
    repositories: RepositoryBundle
    storage: RuntimeStoragePort
    workflows: WorkflowLauncher
    reviewer_identity: ReviewerIdentityProvider
    counterfactual: DeterministicCounterfactual | None
    workflow_identity: WorkflowIdentityVerifier | None = None
    worker: MinimumLiveWorker | None = None


class StaticReviewerIdentity:
    def __init__(self, identity: str) -> None:
        if not identity.strip():
            raise ValueError("reviewer identity must be non-empty")
        self._identity = identity

    def reviewer_id(self) -> str:
        return self._identity


class RunIntakeService:
    def __init__(
        self,
        runtime: RuntimeContainer,
        *,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._runtime = runtime
        self._clock = clock

    def create(
        self,
        *,
        filename: str,
        content: bytes,
    ) -> Run:
        now = self._clock()
        run_id = str(uuid4())
        regulation_id = str(uuid4())
        safe_filename = sanitize_filename(filename)
        detector = Sha256ChangeDetector(self._runtime.repositories)
        detection = detector.detect(source_filename=safe_filename, content=content)
        previous_hash: str | None = None
        if detection.previous_regulation_id is not None:
            previous_hash = self._runtime.repositories.get_regulation(
                detection.previous_regulation_id
            ).content_sha256
        stored = self._runtime.storage.store_source(
            run_id=run_id,
            content=content,
            content_type="application/pdf",
        )
        regulation = Regulation(
            reg_id=regulation_id,
            title=Path(safe_filename).stem,
            source_filename=safe_filename,
            synthetic=True,
        )
        run = Run(
            run_id=run_id,
            state=RunState.INGESTED,
            created_at=now,
            updated_at=now,
            regulation=regulation,
            progress=RunProgress(
                documents_total=1,
                documents_processed=0,
                partitions_total=0,
                partitions_complete=0,
                percent=0,
            ),
            transitions=[
                RunTransition(
                    from_state=None,
                    to_state=RunState.INGESTED,
                    occurred_at=now,
                    reason="Synthetic regulation accepted",
                    actor="system",
                )
            ],
            change_detection=ChangeDetection(
                source_sha256=detection.sha256,
                previous_source_sha256=previous_hash,
                changed=detection.classification.value != "duplicate",
                detected_at=now,
            ),
            findings_by_severity=FindingsBySeverity(low=0, medium=0, high=0),
        )
        checkpoint = RunCheckpoint(
            run_id=run_id,
            sequence=0,
            state=RunState.INGESTED,
            recorded_at=now,
        )
        intake = RunIntakeCommit(
            run=run,
            checkpoint=checkpoint,
            regulation=RegulationRecord(
                regulation=regulation,
                content_sha256=detection.sha256,
                version=detection.next_version,
                supersedes_regulation_id=detection.previous_regulation_id,
                created_at=now,
            ),
            source_document=SourceDocumentRecord(
                run_id=run_id,
                regulation_id=regulation_id,
                object_name=stored.object_name,
                gcs_uri=stored.gcs_uri,
                source_sha256=detection.sha256,
                size_bytes=len(content),
                content_type="application/pdf",
                sanitized_filename=safe_filename,
                synthetic=True,
                created_at=now,
            ),
        )
        try:
            self._runtime.repositories.commit_run_intake(intake)
        except Exception:
            with suppress(Exception):
                self._runtime.storage.delete_source(
                    run_id=run_id,
                    object_name=stored.object_name,
                )
            raise
        states = RunStateCoordinator(
            self._runtime.repositories,
            self._runtime.repositories,
            self._runtime.repositories,
            atomic=self._runtime.repositories,
            clock=self._clock,
        )
        try:
            self._runtime.workflows.launch(
                WorkflowLaunchRequest(
                    run_id=run_id,
                    source_gcs_uri=stored.gcs_uri,
                    source_sha256=detection.sha256,
                    synthetic=True,
                )
            )
        except IntegrationUnavailableError:
            states.transition(
                run_id,
                RunState.FAILED_RECOVERABLE,
                failure_code="WORKFLOW_LAUNCH_FAILED",
                reason="Workflow launch unavailable",
                actor="orchestrator",
            )
            raise
        return run


class RuntimeQueryService:
    def __init__(self, repositories: RepositoryBundle) -> None:
        self._repositories = repositories

    def get_run(self, run_id: str) -> Run:
        run = self._repositories.get_run(run_id)
        findings = self._repositories.list_findings(run_id)
        approvals = [
            approval
            for approval in self._repositories.list_approvals(run_id)
            if approval.status is ApprovalStatus.PENDING
        ]
        completed = [
            record.action
            for record in self._repositories.list_actions(run_id)
            if record.action.status in {ActionStatus.EXECUTED, ActionStatus.APPROVED_DRAFT}
        ]
        counts = FindingsBySeverity(
            low=sum(finding.severity is Severity.LOW for finding in findings),
            medium=sum(finding.severity is Severity.MEDIUM for finding in findings),
            high=sum(finding.severity is Severity.HIGH for finding in findings),
        )
        return Run.model_validate(
            run.model_dump()
            | {
                "findings_by_severity": counts,
                "pending_approvals": sorted(
                    approvals, key=lambda item: item.approval_id
                ),
                "completed_actions": sorted(
                    completed, key=lambda item: item.action_id
                ),
            }
        )

    def list_findings(
        self,
        run_id: str,
        *,
        severity: Severity | None,
        query: str | None,
        limit: int,
        offset: int,
    ) -> FindingList:
        self._repositories.get_run(run_id)
        normalized_query = None if query is None else query.casefold()
        findings = [
            finding
            for finding in self._repositories.list_findings(run_id)
            if (severity is None or finding.severity is severity)
            and (
                normalized_query is None
                or normalized_query in finding.target_id.casefold()
                or normalized_query in finding.obligation.statement.casefold()
            )
        ]
        findings.sort(key=lambda item: item.finding_id)
        counts = FindingsBySeverity(
            low=sum(finding.severity is Severity.LOW for finding in findings),
            medium=sum(finding.severity is Severity.MEDIUM for finding in findings),
            high=sum(finding.severity is Severity.HIGH for finding in findings),
        )
        page = findings[offset : offset + limit]
        return FindingList(
            items=[self._summary(finding) for finding in page],
            total=len(findings),
            limit=limit,
            offset=offset,
            by_severity=counts,
        )

    def get_finding(self, finding_id: str) -> Finding:
        return self._repositories.get_finding(finding_id)

    @staticmethod
    def _summary(finding: Finding) -> FindingSummary:
        return FindingSummary(
            finding_id=finding.finding_id,
            run_id=finding.run_id,
            target_id=finding.target_id,
            relationship=finding.relationship,
            severity=finding.severity,
            verdict=finding.verdict,
            status=finding.status,
            human_review_required=finding.human_review_required,
            scores=finding.scores,
        )


class RuntimeActionService:
    def __init__(self, runtime: RuntimeContainer) -> None:
        self._runtime = runtime

    def preview(self, action_id: str) -> CounterfactualPreview:
        action = self._runtime.repositories.get_action(action_id)
        finding = self._runtime.repositories.get_finding(action.action.finding_id)
        self._validate_binding(action, finding)
        if action.amendment is None:
            raise DomainConflictError("action has no immutable amendment preview")
        if self._runtime.counterfactual is None:
            raise IntegrationUnavailableError(
                "deterministic matching pipeline is unavailable"
            )
        contract = self._runtime.repositories.get_synthetic_contract(
            action.amendment.contract_id
        )
        result = self._runtime.counterfactual.evaluate(
            run_id=action.run_id,
            contract=contract,
            amendment=action.amendment,
            obligations=self._runtime.repositories.list_obligations(action.run_id),
        )
        return result.preview

    @staticmethod
    def _validate_binding(action: ActionRecord, finding: Finding) -> None:
        amendment = action.amendment
        if (
            action.run_id != finding.run_id
            or action.action.finding_id != finding.finding_id
            or (
                amendment is not None
                and (
                    amendment.action_id != action.action.action_id
                    or amendment.finding_id != finding.finding_id
                    or amendment.contract_id != finding.target_id
                )
            )
        ):
            raise DomainConflictError("action binding is invalid")


class RuntimeApprovalService:
    def __init__(
        self,
        runtime: RuntimeContainer,
        *,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._runtime = runtime
        self._clock = clock

    def decide(self, approval_id: str, decision: ApprovalDecision) -> Approval:
        repositories = self._runtime.repositories
        approval = repositories.get_approval(approval_id)
        if approval.status is not ApprovalStatus.PENDING:
            raise DomainConflictError("approval was already decided")
        action = repositories.get_action(approval.action_id)
        finding = repositories.get_finding(approval.finding_id)
        run = repositories.get_run(approval.run_id)
        RuntimeActionService._validate_binding(action, finding)
        if (
            approval.action_id != action.action.action_id
            or approval.finding_id != action.action.finding_id
            or approval.run_id != action.run_id
            or run.run_id != action.run_id
            or run.state is not RunState.AWAITING_APPROVAL
            or action.action.type is not ActionType.DRAFT_AMENDMENT
            or action.action.autonomy is not ActionAutonomy.APPROVAL_REQUIRED
            or action.action.status is not ActionStatus.AWAITING_APPROVAL
        ):
            raise DomainConflictError("approval binding or lifecycle is invalid")
        reviewer = self._runtime.reviewer_identity.reviewer_id()
        if not reviewer.strip():
            raise IntegrationUnavailableError("trusted reviewer identity is unavailable")
        now = self._clock()
        approved = decision.decision is ApprovalDecisionValue.APPROVE
        decided = approval.model_copy(
            update={
                "status": ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED,
                "decided_at": now,
                "decided_by": reviewer,
                "note": decision.note,
            }
        )
        pending = sorted(
            [
                item
                for item in repositories.list_approvals(run.run_id)
                if item.status is ApprovalStatus.PENDING
            ],
            key=lambda item: item.approval_id,
        )
        if [item.approval_id for item in pending] != [approval_id]:
            raise DomainConflictError("pending approval guard is inconsistent")
        remaining_pending = [
            item
            for item in pending
            if item.approval_id != approval_id
        ]
        base_run = Run.model_validate(
            run.model_dump()
            | {
                "pending_approvals": remaining_pending,
                "completed_actions": [
                    item
                    for item in run.completed_actions
                    if item.status is not ActionStatus.REJECTED
                ],
            }
        )
        checkpoints = []
        state_events = []
        snapshot = None
        extra_events: list[AuditEvent] = []
        latest = repositories.latest_checkpoint(run.run_id)
        if latest is None:
            raise DomainConflictError("approval run has no checkpoint")
        if approved:
            if action.amendment is None or self._runtime.counterfactual is None:
                raise IntegrationUnavailableError(
                    "approved amendment revalidation is unavailable"
                )
            contract = repositories.get_synthetic_contract(action.amendment.contract_id)
            result = self._runtime.counterfactual.evaluate(
                run_id=run.run_id,
                contract=contract,
                amendment=action.amendment,
                obligations=repositories.list_obligations(run.run_id),
                now=now,
            )
            snapshot = result.snapshot
            updated_action = action.action.model_copy(
                update={"status": ActionStatus.APPROVED_DRAFT}
            )
            updated_finding = finding.model_copy(
                update={
                    "status": (
                        FindingStatus.RESOLVED
                        if finding.finding_id in result.preview.resolved_finding_ids
                        else finding.status
                    ),
                    "proposed_action": updated_action,
                }
            )
            updated_record = action.model_copy(update={"action": updated_action})
            current_run = base_run
            current_checkpoint = latest
            for index, target in enumerate(
                (RunState.EXECUTING, RunState.REVALIDATING, RunState.COMPLETED),
                start=1,
            ):
                planned = plan_run_transition(
                    run=current_run,
                    checkpoint=current_checkpoint,
                    target=target,
                    now=now + timedelta(microseconds=index),
                    reason="Approved amendment lifecycle",
                    actor="action-controller",
                )
                checkpoints.append(planned.checkpoint)
                state_events.append(planned.audit_event)
                current_run = planned.run
                current_checkpoint = planned.checkpoint
            final_run = Run.model_validate(
                current_run.model_dump()
                | {
                    "completed_actions": sorted(
                        [*base_run.completed_actions, updated_action],
                        key=lambda item: item.action_id,
                    )
                }
            )
            extra_events.extend(
                [
                    AuditEvent(
                        event_id=str(uuid4()),
                        run_id=run.run_id,
                        event_type=AuditEventType.ACTION_EXECUTED,
                        occurred_at=now,
                        action_id=action.action.action_id,
                    ),
                    AuditEvent(
                        event_id=str(uuid4()),
                        run_id=run.run_id,
                        event_type=AuditEventType.REVALIDATION_RESULT,
                        occurred_at=now,
                        action_id=action.action.action_id,
                        revalidation_result=RevalidationResult(
                            resolved_finding_ids=result.preview.resolved_finding_ids,
                            unchanged_finding_ids=result.preview.unchanged_finding_ids,
                            new_conflict_ids=result.preview.new_conflict_ids,
                        ),
                    ),
                ]
            )
        else:
            rejected_action = action.action.model_copy(
                update={"status": ActionStatus.REJECTED}
            )
            updated_record = action.model_copy(update={"action": rejected_action})
            updated_finding = finding.model_copy(
                update={
                    "status": FindingStatus.OPEN,
                    "proposed_action": rejected_action,
                }
            )
            final_run = base_run
            planned = plan_run_transition(
                run=base_run,
                checkpoint=latest,
                target=RunState.COMPLETED,
                now=now + timedelta(microseconds=1),
                reason="Proposed amendment rejected",
                actor="action-controller",
            )
            checkpoints.append(planned.checkpoint)
            state_events.append(planned.audit_event)
            final_run = planned.run
        decision_event = AuditEvent(
            event_id=str(uuid4()),
            run_id=run.run_id,
            event_type=AuditEventType.APPROVAL_DECIDED,
            occurred_at=now,
            action_id=action.action.action_id,
            approval_id=approval.approval_id,
            actor=reviewer,
        )
        repositories.commit_approval_decision(
            ApprovalDecisionCommit(
                expected_approval=approval,
                expected_action=action,
                expected_finding=finding,
                expected_run_state=run.state,
                approval=decided,
                action=updated_record,
                finding=updated_finding,
                run=final_run,
                snapshot=snapshot,
                checkpoints=checkpoints,
                audit_events=[*extra_events, decision_event, *state_events],
            )
        )
        return decided


class RuntimeAuditService:
    def __init__(
        self,
        runtime: RuntimeContainer,
        *,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._runtime = runtime
        self._clock = clock

    def get(self, run_id: str) -> AuditReport:
        report = AuditReportService(
            runs=self._runtime.repositories,
            actions=self._runtime.repositories,
            findings=self._runtime.repositories,
            audits=self._runtime.repositories,
            clock=self._clock,
        ).generate(run_id)
        package = report.model_dump_json(exclude={"audit_package_url"}).encode("utf-8")
        signed_url = self._runtime.storage.store_audit_package_and_sign(
            run_id=run_id,
            content=package,
        )
        signed_report = AuditReport.model_validate(
            report.model_dump() | {"audit_package_url": signed_url}
        )
        self._runtime.repositories.save_audit_report(signed_report)
        return signed_report
