"""Deterministic audit-report assembly from persisted domain events."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from regops_api.domain_models import AuditEventType, IdempotencyResult
from regops_api.repositories import (
    ActionRepository,
    AuditRepository,
    FindingRepository,
    RunRepository,
)
from regops_api.schemas import (
    ActionStatus,
    AuditIdempotency,
    AuditProcessing,
    AuditReport,
    AuditRevalidation,
    FindingStatus,
)

Clock = Callable[[], datetime]


class AuditReportService:
    def __init__(
        self,
        *,
        runs: RunRepository,
        actions: ActionRepository,
        findings: FindingRepository,
        audits: AuditRepository,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._runs = runs
        self._actions = actions
        self._findings = findings
        self._audits = audits
        self._clock = clock

    def generate(self, run_id: str) -> AuditReport:
        run = self._runs.get_run(run_id)
        events = self._audits.list_audit_events(run_id)
        attempts = sum(
            event.event_type is AuditEventType.ACTION_ATTEMPTED for event in events
        )
        duplicates = sum(
            event.idempotency_result is IdempotencyResult.DUPLICATE_PREVENTED
            for event in events
        )
        duplicate_rate = 0.0 if attempts == 0 else duplicates / attempts
        findings = self._findings.list_findings(run_id)
        report = AuditReport(
            run_id=run_id,
            generated_at=self._clock(),
            executed_actions=[
                record.action
                for record in self._actions.list_actions(run_id)
                if record.action.status
                in {ActionStatus.EXECUTED, ActionStatus.APPROVED_DRAFT}
            ],
            idempotency=AuditIdempotency(
                duplicate_actions_prevented=duplicates,
                duplicate_action_rate=duplicate_rate,
            ),
            revalidation=AuditRevalidation(
                findings_resolved=sum(
                    finding.status is FindingStatus.RESOLVED for finding in findings
                ),
                findings_remaining=sum(
                    finding.status is not FindingStatus.RESOLVED for finding in findings
                ),
            ),
            processing=AuditProcessing(
                total_seconds=max(0.0, (run.updated_at - run.created_at).total_seconds()),
                documents_processed=run.progress.documents_processed,
            ),
        )
        self._audits.save_audit_report(report)
        return report
