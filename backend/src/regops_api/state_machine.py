"""Explicit run-state transitions and durable checkpoint coordination."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from uuid import uuid4

from regops_api.domain_models import AuditEvent, AuditEventType, RunCheckpoint
from regops_api.repositories import (
    AuditRepository,
    CheckpointRepository,
    RunRepository,
    RunStateAtomicRepository,
)
from regops_api.schemas import RecoveryInfo, Run, RunState, RunTransition

Clock = Callable[[], datetime]


@dataclass(frozen=True)
class PlannedRunTransition:
    run: Run
    checkpoint: RunCheckpoint
    audit_event: AuditEvent


class InvalidRunTransitionError(ValueError):
    """Raised before persistence when a run transition is not allowlisted."""


def validate_initial_run(run: Run, checkpoint: RunCheckpoint) -> None:
    transition = run.transitions[0]
    if (
        len(run.transitions) != 1
        or checkpoint.run_id != run.run_id
        or checkpoint.sequence != 0
        or checkpoint.state is not run.state
        or checkpoint.recorded_at != transition.occurred_at
        or transition.from_state is not None
        or transition.to_state is not run.state
    ):
        raise InvalidRunTransitionError("initial run and checkpoint binding disagree")


def validate_authoritative_run_update(
    *,
    current: Run,
    updated: Run,
    previous_checkpoint: RunCheckpoint,
    checkpoints: list[RunCheckpoint],
    audit_events: list[AuditEvent],
) -> None:
    """Validate an exact append-only transition/checkpoint/audit suffix."""

    if not checkpoints or current.run_id != updated.run_id:
        raise InvalidRunTransitionError("run update requires bound checkpoints")
    if previous_checkpoint.run_id != current.run_id:
        raise InvalidRunTransitionError("previous checkpoint is bound to another run")
    if previous_checkpoint.state is not current.state:
        raise InvalidRunTransitionError("previous checkpoint disagrees with run state")
    existing_count = len(current.transitions)
    if updated.transitions[:existing_count] != current.transitions:
        raise InvalidRunTransitionError("run transition history is not append-only")
    appended = updated.transitions[existing_count:]
    if len(appended) != len(checkpoints):
        raise InvalidRunTransitionError("transition and checkpoint counts disagree")
    state_events = [
        event
        for event in audit_events
        if event.event_type is AuditEventType.STATE_TRANSITION
    ]
    if len(state_events) != len(checkpoints):
        raise InvalidRunTransitionError("transition audit event count disagrees")
    state = current.state
    previous = previous_checkpoint
    machine = RunStateMachine()
    for offset, (transition, checkpoint, event) in enumerate(
        zip(appended, checkpoints, state_events, strict=True), start=1
    ):
        machine.validate(state, checkpoint.state, checkpoint=previous)
        if (
            checkpoint.run_id != current.run_id
            or checkpoint.sequence != previous_checkpoint.sequence + offset
            or transition.from_state is not state
            or transition.to_state is not checkpoint.state
            or transition.occurred_at != checkpoint.recorded_at
            or event.run_id != current.run_id
            or event.from_state is not state
            or event.to_state is not checkpoint.state
            or event.occurred_at != transition.occurred_at
        ):
            raise InvalidRunTransitionError(
                "transition, checkpoint, and audit bindings disagree"
            )
        state = checkpoint.state
        previous = checkpoint
    if updated.state is not state or updated.updated_at != appended[-1].occurred_at:
        raise InvalidRunTransitionError("final run state disagrees with transition suffix")


_FAILURE_TARGETS = frozenset({RunState.FAILED_RECOVERABLE, RunState.FAILED})
_RESUMABLE_STATES = frozenset(
    {
        RunState.INGESTED,
        RunState.EXTRACTING,
        RunState.EXTRACTED,
        RunState.MAPPING,
        RunState.MAPPED,
        RunState.VERIFYING,
        RunState.VERIFIED,
        RunState.AWAITING_APPROVAL,
        RunState.EXECUTING,
        RunState.REVALIDATING,
    }
)

ALLOWED_TRANSITIONS = MappingProxyType(
    {
        RunState.INGESTED: frozenset({RunState.EXTRACTING}) | _FAILURE_TARGETS,
        RunState.EXTRACTING: frozenset({RunState.EXTRACTED}) | _FAILURE_TARGETS,
        RunState.EXTRACTED: frozenset({RunState.MAPPING}) | _FAILURE_TARGETS,
        RunState.MAPPING: frozenset({RunState.MAPPED}) | _FAILURE_TARGETS,
        RunState.MAPPED: frozenset({RunState.VERIFYING}) | _FAILURE_TARGETS,
        RunState.VERIFYING: frozenset({RunState.VERIFIED}) | _FAILURE_TARGETS,
        RunState.VERIFIED: frozenset(
            {RunState.AWAITING_APPROVAL, RunState.EXECUTING, RunState.COMPLETED}
        )
        | _FAILURE_TARGETS,
        RunState.AWAITING_APPROVAL: frozenset(
            {RunState.EXECUTING, RunState.COMPLETED}
        )
        | _FAILURE_TARGETS,
        RunState.EXECUTING: frozenset({RunState.REVALIDATING}) | _FAILURE_TARGETS,
        RunState.REVALIDATING: frozenset({RunState.COMPLETED}) | _FAILURE_TARGETS,
        RunState.FAILED_RECOVERABLE: _RESUMABLE_STATES | frozenset({RunState.FAILED}),
        RunState.COMPLETED: frozenset(),
        RunState.FAILED: frozenset(),
    }
)


class RunStateMachine:
    def validate(
        self,
        current: RunState,
        target: RunState,
        *,
        checkpoint: RunCheckpoint | None = None,
    ) -> None:
        if target not in ALLOWED_TRANSITIONS[current]:
            raise InvalidRunTransitionError(
                f"transition from {current.value} to {target.value} is not allowed"
            )
        if current is RunState.FAILED_RECOVERABLE:
            if target is RunState.FAILED:
                return
            if checkpoint is None or checkpoint.resume_state is not target:
                expected = (
                    checkpoint.resume_state.value
                    if checkpoint and checkpoint.resume_state
                    else None
                )
                raise InvalidRunTransitionError(
                    f"recoverable run must resume at checkpoint state {expected!r}"
                )


def plan_run_transition(
    *,
    run: Run,
    checkpoint: RunCheckpoint | None,
    target: RunState,
    now: datetime,
    failure_code: str | None = None,
    reason: str | None = None,
    actor: str = "system",
) -> PlannedRunTransition:
    RunStateMachine().validate(run.state, target, checkpoint=checkpoint)
    recovery = run.recovery
    if target is RunState.FAILED_RECOVERABLE:
        prior_attempts = sum(
            transition.to_state is RunState.FAILED_RECOVERABLE
            for transition in run.transitions
        )
        recovery = RecoveryInfo(
            recovery_available=True,
            checkpoint_state=run.state,
            attempt_count=prior_attempts + 1,
            last_error_code=failure_code,
            last_error_message=reason,
        )
    elif run.state is RunState.FAILED_RECOVERABLE:
        recovery = None
    updated = Run.model_validate(
        {
            **run.model_dump(),
            "state": target,
            "updated_at": now,
            "recovery": recovery,
            "transitions": [
                *run.transitions,
                RunTransition(
                    from_state=run.state,
                    to_state=target,
                    occurred_at=now,
                    reason=reason,
                    actor=actor,
                ),
            ],
        }
    )
    sequence = 0 if checkpoint is None else checkpoint.sequence + 1
    next_checkpoint = RunCheckpoint(
        run_id=run.run_id,
        sequence=sequence,
        state=target,
        recorded_at=now,
        resume_state=(run.state if target is RunState.FAILED_RECOVERABLE else None),
        failure_code=failure_code,
    )
    event = AuditEvent(
        event_id=str(uuid4()),
        run_id=run.run_id,
        event_type=AuditEventType.STATE_TRANSITION,
        occurred_at=now,
        from_state=run.state,
        to_state=target,
    )
    return PlannedRunTransition(
        run=updated,
        checkpoint=next_checkpoint,
        audit_event=event,
    )


class RunStateCoordinator:
    """Persists each valid transition together with its checkpoint and audit event."""

    def __init__(
        self,
        runs: RunRepository,
        checkpoints: CheckpointRepository,
        audits: AuditRepository,
        *,
        atomic: RunStateAtomicRepository | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._runs = runs
        self._checkpoints = checkpoints
        self._audits = audits
        self._atomic = (
            atomic
            if atomic is not None
            else runs
            if isinstance(runs, RunStateAtomicRepository)
            else None
        )
        self._clock = clock

    def initialize(self, run: Run) -> RunCheckpoint:
        checkpoint = RunCheckpoint(
            run_id=run.run_id,
            sequence=0,
            state=run.state,
            recorded_at=run.created_at,
        )
        validate_initial_run(run, checkpoint)
        if self._atomic is not None:
            self._atomic.initialize_run_state(run, checkpoint)
        else:
            self._runs.add_run(run)
            self._checkpoints.append_checkpoint(checkpoint)
        return checkpoint

    def transition(
        self,
        run_id: str,
        target: RunState,
        *,
        failure_code: str | None = None,
        reason: str | None = None,
        actor: str = "system",
    ) -> Run:
        run = self._runs.get_run(run_id)
        latest = self._checkpoints.latest_checkpoint(run_id)
        now = self._clock()
        planned = plan_run_transition(
            run=run,
            checkpoint=latest,
            target=target,
            now=now,
            failure_code=failure_code,
            reason=reason,
            actor=actor,
        )
        if self._atomic is not None:
            self._atomic.commit_run_transition(
                expected_state=run.state,
                run=planned.run,
                checkpoint=planned.checkpoint,
                audit_event=planned.audit_event,
            )
        else:
            self._runs.update_run(planned.run)
            self._checkpoints.append_checkpoint(planned.checkpoint)
            self._audits.append_audit_event(planned.audit_event)
        return planned.run
