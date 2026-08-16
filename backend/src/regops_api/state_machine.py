"""Explicit run-state transitions and durable checkpoint coordination."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from types import MappingProxyType
from uuid import uuid4

from regops_api.domain_models import AuditEvent, AuditEventType, RunCheckpoint
from regops_api.repositories import AuditRepository, CheckpointRepository, RunRepository
from regops_api.schemas import Run, RunState, RunTransition

Clock = Callable[[], datetime]


class InvalidRunTransitionError(ValueError):
    """Raised before persistence when a run transition is not allowlisted."""


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


class RunStateCoordinator:
    """Persists each valid transition together with its checkpoint and audit event."""

    def __init__(
        self,
        runs: RunRepository,
        checkpoints: CheckpointRepository,
        audits: AuditRepository,
        *,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._runs = runs
        self._checkpoints = checkpoints
        self._audits = audits
        self._clock = clock
        self._machine = RunStateMachine()

    def initialize(self, run: Run) -> RunCheckpoint:
        self._runs.add_run(run)
        checkpoint = RunCheckpoint(
            run_id=run.run_id,
            sequence=0,
            state=run.state,
            recorded_at=run.created_at,
        )
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
        self._machine.validate(run.state, target, checkpoint=latest)
        now = self._clock()
        updated = Run.model_validate(
            {
                **run.model_dump(),
                "state": target,
                "updated_at": now,
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
        sequence = 0 if latest is None else latest.sequence + 1
        checkpoint = RunCheckpoint(
            run_id=run_id,
            sequence=sequence,
            state=target,
            recorded_at=now,
            resume_state=(run.state if target is RunState.FAILED_RECOVERABLE else None),
            failure_code=failure_code,
        )
        self._runs.update_run(updated)
        self._checkpoints.append_checkpoint(checkpoint)
        self._audits.append_audit_event(
            AuditEvent(
                event_id=str(uuid4()),
                run_id=run_id,
                event_type=AuditEventType.STATE_TRANSITION,
                occurred_at=now,
                from_state=run.state,
                to_state=target,
            )
        )
        return updated
