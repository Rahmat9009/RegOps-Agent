from datetime import UTC, datetime, timedelta

import pytest

from regops_api.domain_models import AuditEventType
from regops_api.in_memory import InMemoryRepositories
from regops_api.schemas import RunState
from regops_api.state_machine import (
    ALLOWED_TRANSITIONS,
    InvalidRunTransitionError,
    RunStateCoordinator,
)
from tests.factories import NOW, make_run


class AdvancingClock:
    def __init__(self) -> None:
        self._now = NOW

    def __call__(self) -> datetime:
        self._now += timedelta(seconds=1)
        return self._now


def test_happy_path_transitions_are_explicit_and_checkpointed() -> None:
    repositories = InMemoryRepositories.for_tests()
    coordinator = RunStateCoordinator(
        repositories, repositories, repositories, clock=AdvancingClock()
    )
    coordinator.initialize(make_run())
    path = [
        RunState.EXTRACTING,
        RunState.EXTRACTED,
        RunState.MAPPING,
        RunState.MAPPED,
        RunState.VERIFYING,
        RunState.VERIFIED,
        RunState.AWAITING_APPROVAL,
        RunState.EXECUTING,
        RunState.REVALIDATING,
        RunState.COMPLETED,
    ]

    for state in path:
        coordinator.transition("run-1", state)

    checkpoints = repositories.list_checkpoints("run-1")
    assert [checkpoint.state for checkpoint in checkpoints] == [RunState.INGESTED, *path]
    assert [checkpoint.sequence for checkpoint in checkpoints] == list(range(11))
    assert len(repositories.list_audit_events("run-1")) == 10
    assert all(
        event.event_type is AuditEventType.STATE_TRANSITION
        for event in repositories.list_audit_events("run-1")
    )


def test_invalid_transition_is_rejected_without_mutating_run() -> None:
    repositories = InMemoryRepositories.for_tests()
    coordinator = RunStateCoordinator(repositories, repositories, repositories)
    coordinator.initialize(make_run())

    with pytest.raises(InvalidRunTransitionError):
        coordinator.transition("run-1", RunState.MAPPED)

    assert repositories.get_run("run-1").state is RunState.INGESTED
    assert len(repositories.list_checkpoints("run-1")) == 1


def test_failed_recoverable_resumes_only_from_recorded_checkpoint_state() -> None:
    repositories = InMemoryRepositories.for_tests()
    coordinator = RunStateCoordinator(repositories, repositories, repositories)
    coordinator.initialize(make_run())
    coordinator.transition("run-1", RunState.EXTRACTING)
    coordinator.transition(
        "run-1", RunState.FAILED_RECOVERABLE, failure_code="VERTEX_TIMEOUT"
    )
    checkpoint = repositories.latest_checkpoint("run-1")

    assert checkpoint is not None
    assert checkpoint.resume_state is RunState.EXTRACTING
    assert checkpoint.failure_code == "VERTEX_TIMEOUT"
    with pytest.raises(InvalidRunTransitionError):
        coordinator.transition("run-1", RunState.MAPPING)

    resumed = coordinator.transition("run-1", RunState.EXTRACTING)
    assert resumed.state is RunState.EXTRACTING


def test_terminal_states_have_no_outgoing_transitions() -> None:
    assert ALLOWED_TRANSITIONS[RunState.COMPLETED] == frozenset()
    assert ALLOWED_TRANSITIONS[RunState.FAILED] == frozenset()
    assert datetime.now(UTC).tzinfo is UTC
