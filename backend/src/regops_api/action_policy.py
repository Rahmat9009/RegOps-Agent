"""Allowlisted action policy and idempotent automatic-action coordination."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from typing import ClassVar
from uuid import NAMESPACE_URL, uuid4, uuid5

from regops_api.domain_models import (
    ActionAttemptResult,
    ActionRecord,
    AuditEvent,
    AuditEventType,
    CaseTag,
    IdempotencyResult,
    InternalReviewTask,
    ProposedAmendment,
)
from regops_api.repositories import (
    ActionRepository,
    ApprovalRepository,
    AuditRepository,
    CaseTagRepository,
    FindingRepository,
    ReviewTaskRepository,
)
from regops_api.schemas import (
    ActionAutonomy,
    ActionStatus,
    ActionType,
    Approval,
    ApprovalStatus,
    Finding,
    FindingStatus,
    ProposedAction,
)

Clock = Callable[[], datetime]


def derive_idempotency_key(run_id: str, finding_id: str, action_type: ActionType) -> str:
    material = "\x00".join((run_id, finding_id, action_type.value)).encode()
    return sha256(material).hexdigest()


class ActionPolicy:
    _AUTONOMY: ClassVar[dict[ActionType, ActionAutonomy]] = {
        ActionType.TAG_CASE: ActionAutonomy.AUTO,
        ActionType.CREATE_REVIEW_TASK: ActionAutonomy.AUTO,
        ActionType.DRAFT_AMENDMENT: ActionAutonomy.APPROVAL_REQUIRED,
    }

    def propose(self, finding: Finding, action_type: ActionType) -> ProposedAction:
        key = derive_idempotency_key(finding.run_id, finding.finding_id, action_type)
        autonomy = self._AUTONOMY[action_type]
        status = (
            ActionStatus.PENDING
            if autonomy is ActionAutonomy.AUTO
            else ActionStatus.AWAITING_APPROVAL
        )
        return ProposedAction(
            action_id=str(uuid5(NAMESPACE_URL, f"regops:action:{key}")),
            finding_id=finding.finding_id,
            type=action_type,
            autonomy=autonomy,
            status=status,
            idempotency_key=key,
        )


class AllowlistedActionService:
    """The Action Controller implementation for exactly the three policy actions."""

    def __init__(
        self,
        *,
        actions: ActionRepository,
        findings: FindingRepository,
        review_tasks: ReviewTaskRepository,
        case_tags: CaseTagRepository,
        approvals: ApprovalRepository,
        audits: AuditRepository,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._actions = actions
        self._findings = findings
        self._review_tasks = review_tasks
        self._case_tags = case_tags
        self._approvals = approvals
        self._audits = audits
        self._clock = clock
        self._policy = ActionPolicy()

    def attempt(
        self,
        *,
        finding: Finding,
        action_type: ActionType,
        amendment: ProposedAmendment | None = None,
    ) -> ActionAttemptResult:
        # Revalidation through the strict contract model is intentional at the action boundary.
        validated_finding = Finding.model_validate(finding.model_dump())
        proposal = self._policy.propose(validated_finding, action_type)
        now = self._clock()
        self._audit(
            run_id=finding.run_id,
            event_type=AuditEventType.ACTION_ATTEMPTED,
            action_id=proposal.action_id,
            now=now,
        )
        existing = self._actions.find_action_by_idempotency_key(proposal.idempotency_key)
        if existing is not None:
            self._audits.append_audit_event(
                AuditEvent(
                    event_id=str(uuid4()),
                    run_id=finding.run_id,
                    event_type=AuditEventType.IDEMPOTENCY_RESULT,
                    occurred_at=now,
                    action_id=existing.action.action_id,
                    idempotency_result=IdempotencyResult.DUPLICATE_PREVENTED,
                )
            )
            approval = self._approval_for(existing.action.action_id, finding.run_id)
            return ActionAttemptResult(
                action=existing.action,
                duplicate_prevented=True,
                approval=approval,
            )

        if action_type is ActionType.DRAFT_AMENDMENT and (
            amendment is None or amendment.action_id != proposal.action_id
        ):
            raise ValueError(
                "draft amendment must carry the deterministic proposed action_id"
            )
        if amendment is not None and (
            amendment.finding_id != finding.finding_id
            or amendment.contract_id != finding.target_id
        ):
            raise ValueError("draft amendment target must match the validated finding")
        if action_type is ActionType.TAG_CASE and finding.affected_case is None:
            raise ValueError("tag_case requires a finding with an affected synthetic case")
        record = ActionRecord(
            run_id=finding.run_id,
            action=proposal,
            amendment=amendment,
        )
        self._actions.add_action(record)
        self._audits.append_audit_event(
            AuditEvent(
                event_id=str(uuid4()),
                run_id=finding.run_id,
                event_type=AuditEventType.IDEMPOTENCY_RESULT,
                occurred_at=now,
                action_id=proposal.action_id,
                idempotency_result=IdempotencyResult.FIRST_EXECUTION,
            )
        )

        if action_type is ActionType.TAG_CASE:
            assert finding.affected_case is not None
            self._case_tags.add_case_tag(
                CaseTag(
                    case_id=finding.affected_case.case_id,
                    run_id=finding.run_id,
                    finding_id=finding.finding_id,
                    tag="potential-regulatory-conflict",
                    created_at=now,
                )
            )
            executed = proposal.model_copy(update={"status": ActionStatus.EXECUTED})
            self._actions.update_action(record.model_copy(update={"action": executed}))
            self._mark_finding_action(finding, executed)
            self._audit_executed(finding.run_id, executed.action_id, now)
            return ActionAttemptResult(action=executed, duplicate_prevented=False)

        if action_type is ActionType.CREATE_REVIEW_TASK:
            self._review_tasks.add_review_task(
                InternalReviewTask(
                    task_id=str(uuid5(NAMESPACE_URL, f"regops:task:{proposal.idempotency_key}")),
                    run_id=finding.run_id,
                    finding_id=finding.finding_id,
                    title=f"Review potential conflict {finding.finding_id}",
                    synthetic=True,
                    created_at=now,
                )
            )
            executed = proposal.model_copy(update={"status": ActionStatus.EXECUTED})
            self._actions.update_action(record.model_copy(update={"action": executed}))
            self._mark_finding_action(finding, executed)
            self._audit_executed(finding.run_id, executed.action_id, now)
            return ActionAttemptResult(action=executed, duplicate_prevented=False)

        approval = Approval(
            approval_id=str(uuid5(NAMESPACE_URL, f"regops:approval:{proposal.action_id}")),
            action_id=proposal.action_id,
            run_id=finding.run_id,
            finding_id=finding.finding_id,
            status=ApprovalStatus.PENDING,
        )
        self._approvals.add_approval(approval)
        self._mark_finding_action(
            finding.model_copy(update={"status": FindingStatus.AWAITING_APPROVAL}),
            proposal,
        )
        return ActionAttemptResult(
            action=proposal,
            duplicate_prevented=False,
            approval=approval,
        )

    def _mark_finding_action(self, finding: Finding, action: ProposedAction) -> None:
        self._findings.update_finding(finding.model_copy(update={"proposed_action": action}))

    def _approval_for(self, action_id: str, run_id: str) -> Approval | None:
        return next(
            (
                approval
                for approval in self._approvals.list_approvals(run_id)
                if approval.action_id == action_id
            ),
            None,
        )

    def _audit_executed(self, run_id: str, action_id: str, now: datetime) -> None:
        self._audit(
            run_id=run_id,
            event_type=AuditEventType.ACTION_EXECUTED,
            action_id=action_id,
            now=now,
        )

    def _audit(
        self,
        *,
        run_id: str,
        event_type: AuditEventType,
        action_id: str,
        now: datetime,
    ) -> None:
        self._audits.append_audit_event(
            AuditEvent(
                event_id=str(uuid4()),
                run_id=run_id,
                event_type=event_type,
                occurred_at=now,
                action_id=action_id,
            )
        )
