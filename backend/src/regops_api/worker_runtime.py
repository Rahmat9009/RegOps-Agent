"""Trusted minimum live worker orchestration and verified handoff."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import compare_digest
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import Field

from regops_api.action_policy import ActionPolicy
from regops_api.analyst_errors import AnalystError
from regops_api.analyst_settings import AnalystSettings
from regops_api.config import RuntimeMode
from regops_api.domain_models import (
    ActionRecord,
    AuditEvent,
    AuditEventType,
    IdempotencyResult,
    PendingApprovalSlot,
    ProposedAmendment,
    SourceDocumentRecord,
    VerifiedWorkerHandoffCommit,
    WorkerHandoffRecord,
    WorkflowLaunchRequest,
)
from regops_api.integrations import RuntimeStoragePort
from regops_api.live_fixture import (
    KNOWN_SOURCE_SHA256,
    MINIMUM_LIVE_FIXTURE_VERSION,
    load_minimum_live_fixture,
    resolve_minimum_live_detections,
)
from regops_api.pdf_reader import parse_pdf
from regops_api.repositories import (
    DuplicateRecordError,
    RecordNotFoundError,
    RepositoryBundle,
    StaleRecordError,
)
from regops_api.schemas import (
    ActionStatus,
    ActionType,
    Approval,
    ApprovalStatus,
    EvidenceReference,
    Finding,
    FindingsBySeverity,
    FindingScores,
    FindingStatus,
    Obligation,
    Run,
    RunProgress,
    RunState,
    SourceAuthority,
)
from regops_api.state_machine import RunStateCoordinator, plan_run_transition
from regops_api.verification import FindingVerifier, verify_obligations
from regops_api.worker_ids import canonical_bytes
from regops_api.worker_models import (
    InvestigatorDraftOutput,
    MinimumLiveDetection,
    SourceDocument,
    VerifiedFinding,
    VerifiedObligation,
    VerifiedWorkerOutput,
    WorkerModel,
)
from regops_api.worker_ports import CandidateAnalyst

Clock = Callable[[], datetime]


class AnalystFactory(Protocol):
    def __call__(self, content: bytes) -> CandidateAnalyst: ...


class FixtureDetector(Protocol):
    def detect(self, *, source: SourceDocument) -> MinimumLiveDetection: ...


class FixtureDetectorFactory(Protocol):
    def __call__(self, content: bytes) -> FixtureDetector: ...


class WorkflowRunResult(WorkerModel):
    run_id: str = Field(min_length=1, max_length=128)
    state: Literal["AWAITING_APPROVAL", "COMPLETED"] = "AWAITING_APPROVAL"
    obligation_count: int = Field(ge=1, le=50)
    finding_count: Literal[1] = 1
    finding_id: str = Field(min_length=1, max_length=128)
    action_id: str = Field(min_length=1, max_length=128)
    approval_id: str = Field(min_length=1, max_length=128)
    duplicate_delivery: bool
    synthetic: Literal[True] = True


class WorkerExecutionError(RuntimeError):
    """A safe fixed worker failure after a recoverable checkpoint is recorded."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _evidence(anchor: object) -> EvidenceReference:
    from regops_api.worker_models import EvidenceAnchor

    value = EvidenceAnchor.model_validate(anchor)
    return EvidenceReference(
        doc_id=value.doc_id,
        doc_kind=value.doc_kind,
        page=value.page,
        quote=value.quote,
    )


def _obligation(value: VerifiedObligation) -> Obligation:
    return Obligation(
        obligation_id=value.obligation_id,
        statement=value.statement,
        type=value.type,
        exceptions=list(value.exceptions),
        effective_date=value.effective_date,
        evidence=[_evidence(anchor) for anchor in value.evidence],
    )


def _finding(value: VerifiedFinding, obligation: Obligation) -> Finding:
    return Finding(
        finding_id=value.finding_id,
        run_id=value.run_id,
        target_id=value.target_id,
        relationship=value.relationship,
        severity=value.severity,
        verdict=value.verdict,
        status=FindingStatus.OPEN,
        human_review_required=value.human_review_required,
        obligation=obligation,
        affected_case=None,
        evidence_path=[_evidence(anchor) for anchor in value.evidence],
        scores=FindingScores(
            evidence_strength=value.evidence_strength,
            source_authority=SourceAuthority.PRIMARY_GOVERNMENT,
            interpretation_confidence=value.interpretation_confidence,
            operational_severity=value.severity,
            human_review_required=value.human_review_required,
        ),
    )


class MinimumLiveWorker:
    def __init__(
        self,
        *,
        repositories: RepositoryBundle,
        storage: RuntimeStoragePort,
        analyst_factory: AnalystFactory,
        analyst_settings: AnalystSettings,
        max_source_bytes: int,
        fixture_detector_factory: FixtureDetectorFactory | None = None,
        runtime_mode: RuntimeMode = RuntimeMode.TEST,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._repositories = repositories
        self._storage = storage
        self._analyst_factory = analyst_factory
        self._analyst_settings = AnalystSettings.model_validate(analyst_settings)
        self._max_source_bytes = max_source_bytes
        self._fixture_detector_factory = fixture_detector_factory
        self._runtime_mode = runtime_mode
        if fixture_detector_factory is not None and runtime_mode is not RuntimeMode.DEMO:
            raise ValueError("FIXTURE_DETECTION_REQUIRES_DEMO_MODE")
        self._clock = clock

    def run(self, envelope: WorkflowLaunchRequest) -> WorkflowRunResult:
        source = self._bind_envelope(envelope)
        run = self._repositories.get_run(envelope.run_id)
        if run.state in {RunState.AWAITING_APPROVAL, RunState.COMPLETED}:
            return self._existing_result(source)
        if run.state is RunState.FAILED:
            raise StaleRecordError("worker delivery conflicts with terminal run")
        states = RunStateCoordinator(
            self._repositories,
            self._repositories,
            self._repositories,
            atomic=self._repositories,
            clock=self._clock,
        )
        try:
            run = self._resume_if_needed(run, states)
            if run.state is RunState.INGESTED:
                run = states.transition(
                    run.run_id,
                    RunState.EXTRACTING,
                    reason="Bound private source processing started",
                    actor="workflow-worker",
                )
            fixture = load_minimum_live_fixture(source.source_sha256)
            content = self._storage.read_bound_source(
                record=source,
                max_bytes=self._max_source_bytes,
            )
            parsed = parse_pdf(
                content=content,
                doc_id=fixture.source_doc_id,
                source_sha256=source.source_sha256,
                limits=self._analyst_settings.pdf,
            )
            accepted = fixture.accepted_catalog(parsed)
            if self._fixture_detector_factory is not None:
                if (
                    self._runtime_mode is not RuntimeMode.DEMO
                    or fixture.fixture_version != MINIMUM_LIVE_FIXTURE_VERSION
                    or not compare_digest(source.source_sha256, KNOWN_SOURCE_SHA256)
                    or not compare_digest(parsed.identity.source_sha256, KNOWN_SOURCE_SHA256)
                    or parsed.identity.doc_id != fixture.source_doc_id
                ):
                    raise WorkerExecutionError("FIXTURE_DETECTION_BOUNDARY_REJECTED")
                detector = self._fixture_detector_factory(content)
                try:
                    detections = detector.detect(source=parsed)
                finally:
                    close = getattr(detector, "close", None)
                    if callable(close):
                        close()
                try:
                    candidates = resolve_minimum_live_detections(
                        fixture=fixture,
                        source=parsed,
                        detections=detections,
                    )
                except ValueError:
                    raise WorkerExecutionError("FIXTURE_DETECTION_REJECTED") from None
            else:
                analyst = self._analyst_factory(content)
                try:
                    candidates = analyst.analyze(source=parsed)
                finally:
                    close = getattr(analyst, "close", None)
                    if callable(close):
                        close()
            obligation_result = verify_obligations(
                run_id=run.run_id,
                source=parsed,
                accepted=accepted,
                candidates=candidates,
            )
            if obligation_result.output is None:
                raise WorkerExecutionError("OBLIGATION_VERIFICATION_REJECTED")
            if run.state is RunState.EXTRACTING:
                run = states.transition(
                    run.run_id,
                    RunState.EXTRACTED,
                    reason="Verified candidate extraction completed",
                    actor="workflow-worker",
                )
            if run.state is RunState.EXTRACTED:
                run = states.transition(
                    run.run_id,
                    RunState.MAPPING,
                    reason="Synthetic demo mapping started",
                    actor="workflow-worker",
                )
            mapped = fixture.mapped_candidate(obligation_result.output)
            if run.state is RunState.MAPPING:
                run = states.transition(
                    run.run_id,
                    RunState.MAPPED,
                    reason="Exact-hash synthetic demo mapping completed",
                    actor="workflow-worker",
                )
            if run.state is not RunState.MAPPED:
                raise StaleRecordError("worker cannot hand off from current run state")
            finding_result = FindingVerifier().verify(
                source=parsed,
                accepted=accepted,
                obligations=obligation_result.output,
                corpus=fixture.corpus,
                candidates=InvestigatorDraftOutput(findings=(mapped,)),
            )
            if finding_result.output is None or len(finding_result.output.findings) != 1:
                raise WorkerExecutionError("FINDING_VERIFICATION_REJECTED")
            commit = self._handoff_commit(
                run=run,
                source=source,
                output=finding_result.output,
            )
            duplicate = self._repositories.commit_verified_worker_handoff(commit)
            return self._result(commit.handoff, duplicate=duplicate)
        except (DuplicateRecordError, StaleRecordError):
            raise
        except WorkerExecutionError as error:
            self._mark_recoverable(states, envelope.run_id, error.code)
            raise
        except AnalystError as error:
            self._mark_recoverable(states, envelope.run_id, error.code.value)
            raise WorkerExecutionError(error.code.value) from None
        except (RecordNotFoundError, ValueError):
            self._mark_recoverable(states, envelope.run_id, "WORKER_INPUT_REJECTED")
            raise WorkerExecutionError("WORKER_INPUT_REJECTED") from None
        except Exception:
            self._mark_recoverable(states, envelope.run_id, "WORKER_DEPENDENCY_UNAVAILABLE")
            raise WorkerExecutionError("WORKER_DEPENDENCY_UNAVAILABLE") from None

    def ready(self) -> bool:
        return self._max_source_bytes >= 1024 and self._analyst_settings.model == (
            "gemini-3.5-flash"
        )

    def _bind_envelope(self, envelope: WorkflowLaunchRequest) -> SourceDocumentRecord:
        envelope = WorkflowLaunchRequest.model_validate(envelope)
        source = self._repositories.get_source_document(envelope.run_id)
        run = self._repositories.get_run(envelope.run_id)
        if (
            source.run_id != run.run_id
            or source.regulation_id != run.regulation.reg_id
            or source.gcs_uri != envelope.source_gcs_uri
            or not compare_digest(source.source_sha256, envelope.source_sha256)
            or source.synthetic is not True
            or envelope.synthetic is not True
        ):
            raise StaleRecordError("workflow envelope is not authoritatively bound")
        return source

    def _resume_if_needed(self, run: Run, states: RunStateCoordinator) -> Run:
        if run.state is not RunState.FAILED_RECOVERABLE:
            return run
        latest = self._repositories.latest_checkpoint(run.run_id)
        if latest is None or latest.resume_state is None:
            raise StaleRecordError("recoverable run has no resume checkpoint")
        return states.transition(
            run.run_id,
            latest.resume_state,
            reason="Workflow retry resumed from durable checkpoint",
            actor="workflow-worker",
        )

    def _mark_recoverable(self, states: RunStateCoordinator, run_id: str, code: str) -> None:
        try:
            run = self._repositories.get_run(run_id)
            if run.state not in {
                RunState.FAILED_RECOVERABLE,
                RunState.COMPLETED,
                RunState.FAILED,
                RunState.AWAITING_APPROVAL,
            }:
                states.transition(
                    run.run_id,
                    RunState.FAILED_RECOVERABLE,
                    failure_code=code,
                    reason="Worker stage failed and may be retried",
                    actor="workflow-worker",
                )
        except Exception:
            return

    def _handoff_commit(
        self,
        *,
        run: Run,
        source: SourceDocumentRecord,
        output: VerifiedWorkerOutput,
    ) -> VerifiedWorkerHandoffCommit:
        fixture = load_minimum_live_fixture(source.source_sha256)
        obligations = [_obligation(item) for item in output.obligations]
        obligation_by_id = {item.obligation_id: item for item in obligations}
        verified_finding = output.findings[0]
        finding = _finding(
            verified_finding,
            obligation_by_id[verified_finding.obligation.obligation_id],
        )
        proposal = ActionPolicy().propose(finding, ActionType.DRAFT_AMENDMENT)
        amendment = ProposedAmendment(
            action_id=proposal.action_id,
            finding_id=finding.finding_id,
            contract_id=finding.target_id,
            clause_updates=fixture.amendment_clause_updates,
        )
        action = ActionRecord(run_id=run.run_id, action=proposal, amendment=amendment)
        approval = Approval(
            approval_id=str(uuid5(NAMESPACE_URL, f"regops:approval:{proposal.action_id}")),
            action_id=proposal.action_id,
            run_id=run.run_id,
            finding_id=finding.finding_id,
            status=ApprovalStatus.PENDING,
        )
        awaiting_finding = finding.model_copy(
            update={
                "status": FindingStatus.AWAITING_APPROVAL,
                "proposed_action": proposal,
            }
        )
        latest = self._repositories.latest_checkpoint(run.run_id)
        if latest is None or latest.state is not RunState.MAPPED:
            raise StaleRecordError("worker handoff has no mapped checkpoint")
        base_time = max(self._clock(), latest.recorded_at + timedelta(microseconds=1))
        current_run, current_checkpoint = run, latest
        checkpoints = []
        state_events = []
        for offset, target in enumerate(
            (RunState.VERIFYING, RunState.VERIFIED, RunState.AWAITING_APPROVAL)
        ):
            planned = plan_run_transition(
                run=current_run,
                checkpoint=current_checkpoint,
                target=target,
                now=base_time + timedelta(microseconds=offset),
                reason="Deterministic verified worker handoff",
                actor="workflow-worker",
            )
            checkpoints.append(planned.checkpoint)
            state_events.append(planned.audit_event)
            current_run, current_checkpoint = planned.run, planned.checkpoint
        final_run = Run.model_validate(
            current_run.model_dump()
            | {
                "progress": RunProgress(
                    documents_total=1,
                    documents_processed=1,
                    partitions_total=0,
                    partitions_complete=0,
                    percent=100,
                ),
                "findings_by_severity": FindingsBySeverity(
                    low=int(verified_finding.severity.value == "low"),
                    medium=int(verified_finding.severity.value == "medium"),
                    high=int(verified_finding.severity.value == "high"),
                ),
                "pending_approvals": [approval],
            }
        )
        handoff = WorkerHandoffRecord(
            run_id=run.run_id,
            source_sha256=source.source_sha256,
            output_sha256=sha256(canonical_bytes(output)).hexdigest(),
            corpus_sha256=output.corpus_sha256,
            obligation_ids=sorted(item.obligation_id for item in obligations),
            finding_id=finding.finding_id,
            action_id=proposal.action_id,
            approval_id=approval.approval_id,
            synthetic=True,
        )
        event_time = base_time + timedelta(microseconds=3)
        return VerifiedWorkerHandoffCommit(
            expected_source=source,
            output=output,
            obligations=obligations,
            contract=fixture.target_contract,
            finding=awaiting_finding,
            action=action,
            approval=approval,
            pending_slot=PendingApprovalSlot(
                run_id=run.run_id,
                approval_id=approval.approval_id,
                action_id=proposal.action_id,
                finding_id=finding.finding_id,
            ),
            run=final_run,
            checkpoints=checkpoints,
            audit_events=[
                *state_events,
                AuditEvent(
                    event_id=str(uuid4()),
                    run_id=run.run_id,
                    event_type=AuditEventType.ACTION_ATTEMPTED,
                    occurred_at=event_time,
                    action_id=proposal.action_id,
                ),
                AuditEvent(
                    event_id=str(uuid4()),
                    run_id=run.run_id,
                    event_type=AuditEventType.IDEMPOTENCY_RESULT,
                    occurred_at=event_time,
                    action_id=proposal.action_id,
                    idempotency_result=IdempotencyResult.FIRST_EXECUTION,
                ),
            ],
            handoff=handoff,
        )

    def _existing_result(self, source: SourceDocumentRecord) -> WorkflowRunResult:
        handoff = self._repositories.get_worker_handoff(source.run_id)
        if (
            not compare_digest(handoff.source_sha256, source.source_sha256)
            or self._repositories.get_action(handoff.action_id).run_id != source.run_id
            or self._repositories.get_finding(handoff.finding_id).run_id != source.run_id
        ):
            raise StaleRecordError("existing worker handoff is corrupt")
        approval = self._repositories.get_approval(handoff.approval_id)
        run = self._repositories.get_run(source.run_id)
        action = self._repositories.get_action(handoff.action_id)
        obligations = sorted(
            item.obligation_id
            for item in self._repositories.list_obligations(run.run_id)
        )
        awaiting = (
            run.state is RunState.AWAITING_APPROVAL
            and approval.status is ApprovalStatus.PENDING
            and action.action.status is ActionStatus.AWAITING_APPROVAL
            and run.pending_approvals == [approval]
        )
        completed = (
            run.state is RunState.COMPLETED
            and approval.status in {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}
            and action.action.status
            in {ActionStatus.APPROVED_DRAFT, ActionStatus.REJECTED}
            and not run.pending_approvals
        )
        if (
            approval.action_id != handoff.action_id
            or action.action.finding_id != handoff.finding_id
            or obligations != handoff.obligation_ids
            or not (awaiting or completed)
        ):
            raise StaleRecordError("existing worker handoff is corrupt")
        return self._result(
            handoff,
            duplicate=True,
            state="COMPLETED" if completed else "AWAITING_APPROVAL",
        )

    @staticmethod
    def _result(
        handoff: WorkerHandoffRecord,
        *,
        duplicate: bool,
        state: Literal["AWAITING_APPROVAL", "COMPLETED"] = "AWAITING_APPROVAL",
    ) -> WorkflowRunResult:
        return WorkflowRunResult(
            run_id=handoff.run_id,
            obligation_count=len(handoff.obligation_ids),
            finding_id=handoff.finding_id,
            action_id=handoff.action_id,
            approval_id=handoff.approval_id,
            duplicate_delivery=duplicate,
            state=state,
        )
