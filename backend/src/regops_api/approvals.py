"""Backend-owned approval decisions and approved shadow-draft execution."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from regops_api.counterfactual import CounterfactualResult, DeterministicCounterfactual
from regops_api.domain_models import (
    AuditEvent,
    AuditEventType,
    RevalidationResult,
)
from regops_api.repositories import (
    ActionRepository,
    ApprovalRepository,
    AuditRepository,
    FindingRepository,
    ObligationRepository,
    SyntheticContractRepository,
)
from regops_api.schemas import (
    ActionStatus,
    Approval,
    ApprovalDecision,
    ApprovalDecisionValue,
    ApprovalStatus,
    FindingStatus,
)

Clock = Callable[[], datetime]
DEMO_REVIEWER = "demo-reviewer"


class ApprovalAlreadyDecidedError(RuntimeError):
    """Maps to HTTP 409 at the API boundary."""


class ApprovalDecisionResult:
    def __init__(
        self,
        *,
        approval: Approval,
        counterfactual: CounterfactualResult | None,
    ) -> None:
        self.approval = approval
        self.counterfactual = counterfactual


class ApprovalService:
    def __init__(
        self,
        *,
        approvals: ApprovalRepository,
        actions: ActionRepository,
        contracts: SyntheticContractRepository,
        obligations: ObligationRepository,
        findings: FindingRepository,
        audits: AuditRepository,
        counterfactual: DeterministicCounterfactual,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._approvals = approvals
        self._actions = actions
        self._contracts = contracts
        self._obligations = obligations
        self._findings = findings
        self._audits = audits
        self._counterfactual = counterfactual
        self._clock = clock

    def decide(
        self, approval_id: str, decision: ApprovalDecision
    ) -> ApprovalDecisionResult:
        # Revalidate to reject all extra client fields before any state mutation.
        validated = ApprovalDecision.model_validate(decision.model_dump())
        approval = self._approvals.get_approval(approval_id)
        if approval.status is not ApprovalStatus.PENDING:
            raise ApprovalAlreadyDecidedError(f"approval {approval_id!r} is already decided")
        now = self._clock()
        status = (
            ApprovalStatus.APPROVED
            if validated.decision is ApprovalDecisionValue.APPROVE
            else ApprovalStatus.REJECTED
        )
        decided = approval.model_copy(
            update={
                "status": status,
                "decided_at": now,
                "decided_by": DEMO_REVIEWER,
                "note": validated.note,
            }
        )
        action_record = self._actions.get_action(approval.action_id)
        counterfactual_result: CounterfactualResult | None = None
        if status is ApprovalStatus.APPROVED:
            if action_record.amendment is None:
                raise ValueError("approval action does not contain a proposed amendment")
            contract = self._contracts.get_synthetic_contract(
                action_record.amendment.contract_id
            )
            counterfactual_result = self._counterfactual.evaluate(
                run_id=approval.run_id,
                contract=contract,
                amendment=action_record.amendment,
                obligations=self._obligations.list_obligations(approval.run_id),
                now=now,
            )
            self._contracts.save_shadow_snapshot(counterfactual_result.snapshot)
            updated_action = action_record.action.model_copy(
                update={"status": ActionStatus.APPROVED_DRAFT}
            )
            self._actions.update_action(
                action_record.model_copy(update={"action": updated_action})
            )
            finding = self._findings.get_finding(action_record.action.finding_id)
            finding_status = (
                FindingStatus.RESOLVED
                if finding.finding_id
                in counterfactual_result.preview.resolved_finding_ids
                else finding.status
            )
            self._findings.update_finding(
                finding.model_copy(
                    update={
                        "status": finding_status,
                        "proposed_action": updated_action,
                    }
                )
            )
            self._audits.append_audit_event(
                AuditEvent(
                    event_id=str(uuid4()),
                    run_id=approval.run_id,
                    event_type=AuditEventType.ACTION_EXECUTED,
                    occurred_at=now,
                    action_id=approval.action_id,
                )
            )
            preview = counterfactual_result.preview
            self._audits.append_audit_event(
                AuditEvent(
                    event_id=str(uuid4()),
                    run_id=approval.run_id,
                    event_type=AuditEventType.REVALIDATION_RESULT,
                    occurred_at=now,
                    action_id=approval.action_id,
                    revalidation_result=RevalidationResult(
                        resolved_finding_ids=preview.resolved_finding_ids,
                        unchanged_finding_ids=preview.unchanged_finding_ids,
                        new_conflict_ids=preview.new_conflict_ids,
                    ),
                )
            )
        else:
            rejected = action_record.action.model_copy(
                update={"status": ActionStatus.REJECTED}
            )
            self._actions.update_action(action_record.model_copy(update={"action": rejected}))
            finding = self._findings.get_finding(action_record.action.finding_id)
            self._findings.update_finding(
                finding.model_copy(
                    update={
                        "status": FindingStatus.OPEN,
                        "proposed_action": rejected,
                    }
                )
            )

        self._approvals.update_approval(decided)
        self._audits.append_audit_event(
            AuditEvent(
                event_id=str(uuid4()),
                run_id=approval.run_id,
                event_type=AuditEventType.APPROVAL_DECIDED,
                occurred_at=now,
                action_id=approval.action_id,
                approval_id=approval.approval_id,
                actor=DEMO_REVIEWER,
            )
        )
        return ApprovalDecisionResult(
            approval=decided,
            counterfactual=counterfactual_result,
        )
