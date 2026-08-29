from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from regops_api.analyst_errors import AnalystCode, AnalystError
from regops_api.analyst_settings import AnalystSettings
from regops_api.domain_models import (
    RegulationRecord,
    RunCheckpoint,
    RunIntakeCommit,
    SourceDocumentRecord,
    StoredSourceObject,
    WorkflowLaunchRequest,
)
from regops_api.firestore import FirestoreRepositories
from regops_api.internal_auth import WorkerAuthenticationError
from regops_api.live_fixture import (
    KNOWN_SOURCE_SHA256,
    load_minimum_live_fixture,
    minimum_live_counterfactual,
)
from regops_api.main import create_app
from regops_api.runtime import (
    RunIntakeService,
    RuntimeActionService,
    RuntimeApprovalService,
    RuntimeAuditService,
    RuntimeContainer,
)
from regops_api.schemas import (
    ActionStatus,
    ApprovalDecision,
    ApprovalDecisionValue,
    FindingStatus,
    Run,
    RunState,
)
from regops_api.worker_models import AnalystDraftOutput, CandidateObligation, SourceDocument
from regops_api.worker_runtime import MinimumLiveWorker
from tests.factories import NOW, make_obligation, make_run
from tests.runtime_helpers import RecordingWorkflow, make_runtime
from tests.test_atomic_persistence import FakeFirestoreClient

SAMPLE = Path(__file__).parents[2] / "samples" / "regops-synthetic-regulation-2026.pdf"


class BoundMemoryStorage:
    def __init__(self) -> None:
        self.sources: dict[str, bytes] = {}
        self.audit_packages: list[tuple[str, bytes]] = []

    def store_source(self, *, run_id: str, content: bytes, content_type: str) -> StoredSourceObject:
        assert content_type == "application/pdf"
        self.sources[run_id] = content
        name = f"runs/{run_id}/source/regulation.pdf"
        return StoredSourceObject(object_name=name, gcs_uri=f"gs://test-private/{name}")

    def delete_source(self, *, run_id: str, object_name: str) -> None:
        assert object_name == f"runs/{run_id}/source/regulation.pdf"
        self.sources.pop(run_id, None)

    def read_bound_source(self, *, record: SourceDocumentRecord, max_bytes: int) -> bytes:
        content = self.sources[record.run_id]
        assert record.object_name == f"runs/{record.run_id}/source/regulation.pdf"
        assert record.gcs_uri == f"gs://test-private/{record.object_name}"
        assert len(content) <= max_bytes == 10 * 1024 * 1024
        assert sha256(content).hexdigest() == record.source_sha256
        return content

    def store_audit_package_and_sign(self, *, run_id: str, content: bytes) -> str:
        self.audit_packages.append((run_id, content))
        return (
            f"https://storage.googleapis.com/test-private/runs/{run_id}/audit/"
            "audit-package.json?X-Goog-Signature=test"
        )


class FixtureAnalyst:
    def analyze(self, *, source: SourceDocument) -> AnalystDraftOutput:
        fixture = load_minimum_live_fixture(source.identity.source_sha256)
        return AnalystDraftOutput(
            obligations=tuple(
                CandidateObligation(**item.model_dump()) for item in fixture.accepted_obligations
            )
        )


class UnsupportedAnalyst(FixtureAnalyst):
    def analyze(self, *, source: SourceDocument) -> AnalystDraftOutput:
        output = super().analyze(source=source)
        unsupported = output.obligations[0].model_copy(
            update={"statement": "Unsupported synthetic candidate."}
        )
        return AnalystDraftOutput(obligations=(unsupported,))


class RejectOnceAnalyst(FixtureAnalyst):
    def __init__(self, code: AnalystCode = AnalystCode.GEMINI_REQUEST_REJECTED) -> None:
        self.calls = 0
        self.code = code

    def analyze(self, *, source: SourceDocument) -> AnalystDraftOutput:
        self.calls += 1
        if self.calls == 1:
            raise AnalystError(self.code)
        return super().analyze(source=source)


class Identity:
    def __init__(self, accepted: bool = True) -> None:
        self.accepted = accepted

    def verify(self, authorization: str | None) -> None:
        if not self.accepted or authorization != "Bearer valid-token":
            raise WorkerAuthenticationError


class WrongIdentity:
    def verify(self, _authorization: str | None) -> None:
        raise WorkerAuthenticationError(wrong_caller=True)


def seeded_runtime() -> tuple[RuntimeContainer, Run, WorkflowLaunchRequest]:
    storage = BoundMemoryStorage()
    workflow = RecordingWorkflow()
    runtime = make_runtime(
        storage=cast(Any, storage),
        workflows=workflow,
        counterfactual=minimum_live_counterfactual(),
    )
    run = RunIntakeService(runtime).create(
        filename="synthetic.pdf",
        content=SAMPLE.read_bytes(),
    )
    worker = MinimumLiveWorker(
        repositories=runtime.repositories,
        storage=storage,
        analyst_factory=lambda _content: FixtureAnalyst(),
        analyst_settings=AnalystSettings(),
        max_source_bytes=10 * 1024 * 1024,
    )
    runtime = replace(runtime, worker=worker, workflow_identity=Identity())
    return runtime, run, workflow.requests[0]


def test_known_fixture_and_real_worker_reach_atomic_awaiting_approval() -> None:
    runtime, run, envelope = seeded_runtime()

    assert runtime.worker is not None
    result = runtime.worker.run(envelope)

    assert result.run_id == run.run_id
    assert result.obligation_count == 3 and result.finding_count == 1
    stored = runtime.repositories.get_run(run.run_id)
    assert stored.state is RunState.AWAITING_APPROVAL
    assert [item.to_state for item in stored.transitions] == [
        RunState.INGESTED,
        RunState.EXTRACTING,
        RunState.EXTRACTED,
        RunState.MAPPING,
        RunState.MAPPED,
        RunState.VERIFYING,
        RunState.VERIFIED,
        RunState.AWAITING_APPROVAL,
    ]
    assert len(runtime.repositories.list_findings(run.run_id)) == 1
    assert len(runtime.repositories.list_actions(run.run_id)) == 1
    assert len(runtime.repositories.list_approvals(run.run_id)) == 1

    duplicate = runtime.worker.run(envelope)
    assert duplicate.duplicate_delivery
    assert runtime.repositories.get_run(run.run_id) == stored


def test_internal_endpoint_is_private_authenticated_and_bounded() -> None:
    runtime, _run, envelope = seeded_runtime()
    app = create_app(settings=runtime.settings, runtime=runtime)
    client = TestClient(app)

    assert "/internal/v1/workflow/run" not in app.openapi()["paths"]
    assert "/internal/v1/readiness" not in app.openapi()["paths"]
    assert client.get("/internal/v1/readiness").status_code == 401
    assert client.get(
        "/internal/v1/readiness",
        headers={"Authorization": "Bearer valid-token"},
    ).json() == {"status": "ready"}
    assert (
        client.post("/internal/v1/workflow/run", json=envelope.model_dump(mode="json")).status_code
        == 401
    )
    response = client.post(
        "/internal/v1/workflow/run",
        headers={"Authorization": "Bearer valid-token"},
        json=envelope.model_dump(mode="json"),
    )
    assert response.status_code == 200
    assert set(response.json()) == {
        "run_id",
        "state",
        "obligation_count",
        "finding_count",
        "finding_id",
        "action_id",
        "approval_id",
        "duplicate_delivery",
        "synthetic",
    }
    extra = envelope.model_dump(mode="json") | {"bucket": "attacker"}
    assert (
        client.post(
            "/internal/v1/workflow/run",
            headers={"Authorization": "Bearer valid-token"},
            json=extra,
        ).status_code
        == 422
    )
    wrong_client = TestClient(
        create_app(
            settings=runtime.settings,
            runtime=replace(runtime, workflow_identity=WrongIdentity()),
        )
    )
    assert (
        wrong_client.post(
            "/internal/v1/workflow/run",
            headers={"Authorization": "Bearer valid-token"},
            json=envelope.model_dump(mode="json"),
        ).status_code
        == 403
    )


def test_wrong_source_binding_and_unknown_hash_fail_closed() -> None:
    runtime, run, envelope = seeded_runtime()
    wrong_uri = envelope.model_copy(update={"source_gcs_uri": "gs://other/source.pdf"})
    with pytest.raises(Exception, match="authoritatively bound"):
        assert runtime.worker is not None
        runtime.worker.run(wrong_uri)
    assert runtime.repositories.get_run(run.run_id).state is RunState.INGESTED
    client = TestClient(create_app(settings=runtime.settings, runtime=runtime))
    for rejected in (
        wrong_uri,
        envelope.model_copy(update={"source_sha256": "f" * 64}),
    ):
        assert client.post(
            "/internal/v1/workflow/run",
            headers={"Authorization": "Bearer valid-token"},
            json=rejected.model_dump(mode="json"),
        ).status_code == 409
    with pytest.raises(ValueError, match="UNKNOWN_LIVE_SOURCE"):
        load_minimum_live_fixture("f" * 64)
    assert sha256(SAMPLE.read_bytes()).hexdigest() == KNOWN_SOURCE_SHA256


def test_corrupt_partial_handoff_fails_with_conflict_and_is_not_repaired() -> None:
    runtime, run, envelope = seeded_runtime()
    runtime.repositories.add_obligations(run.run_id, [make_obligation("orphan")])
    assert runtime.worker is not None

    with pytest.raises(Exception, match="partial worker handoff"):
        runtime.worker.run(envelope)

    response = TestClient(create_app(settings=runtime.settings, runtime=runtime)).post(
        "/internal/v1/workflow/run",
        headers={"Authorization": "Bearer valid-token"},
        json=envelope.model_dump(mode="json"),
    )

    assert response.status_code == 409
    assert [item.obligation_id for item in runtime.repositories.list_obligations(run.run_id)] == [
        "orphan"
    ]
    assert runtime.repositories.list_actions(run.run_id) == []
    assert runtime.repositories.list_approvals(run.run_id) == []


def test_unsupported_candidate_persists_sanitized_recoverable_checkpoint() -> None:
    runtime, run, envelope = seeded_runtime()
    worker = MinimumLiveWorker(
        repositories=runtime.repositories,
        storage=runtime.storage,
        analyst_factory=lambda _content: UnsupportedAnalyst(),
        analyst_settings=AnalystSettings(),
        max_source_bytes=10 * 1024 * 1024,
    )

    with pytest.raises(Exception, match="OBLIGATION_VERIFICATION_REJECTED"):
        worker.run(envelope)

    failed = runtime.repositories.get_run(run.run_id)
    checkpoint = runtime.repositories.latest_checkpoint(run.run_id)
    assert failed.state is RunState.FAILED_RECOVERABLE
    assert failed.recovery is not None
    assert failed.recovery.last_error_code == "OBLIGATION_VERIFICATION_REJECTED"
    assert checkpoint is not None
    assert checkpoint.state is RunState.FAILED_RECOVERABLE
    assert checkpoint.resume_state is RunState.EXTRACTING
    assert runtime.repositories.list_obligations(run.run_id) == []
    assert runtime.worker is not None
    recovered = runtime.worker.run(envelope)
    assert recovered.state == "AWAITING_APPROVAL"
    assert len(runtime.repositories.list_obligations(run.run_id)) == 3


@pytest.mark.parametrize(
    "failure_code",
    [
        AnalystCode.GEMINI_REQUEST_REJECTED,
        AnalystCode.MODEL_ARMOR_OUTPUT_PROMPT_INJECTION_BLOCKED,
    ],
)
def test_original_envelope_resumes_analyst_failure_without_duplicate_records(
    failure_code: AnalystCode,
) -> None:
    runtime, run, envelope = seeded_runtime()
    analyst = RejectOnceAnalyst(failure_code)
    worker = MinimumLiveWorker(
        repositories=runtime.repositories,
        storage=runtime.storage,
        analyst_factory=lambda _content: analyst,
        analyst_settings=AnalystSettings(),
        max_source_bytes=10 * 1024 * 1024,
    )
    source_before = runtime.repositories.get_source_document(run.run_id)
    regulation_before = runtime.repositories.get_regulation(run.regulation.reg_id)

    with pytest.raises(Exception, match=failure_code.value):
        worker.run(envelope)

    failed = runtime.repositories.get_run(run.run_id)
    checkpoint = runtime.repositories.latest_checkpoint(run.run_id)
    assert failed.run_id == run.run_id
    assert failed.state is RunState.FAILED_RECOVERABLE
    assert failed.recovery is not None
    assert failed.recovery.checkpoint_state is RunState.EXTRACTING
    assert failed.recovery.attempt_count == 1
    assert failed.recovery.last_error_code == failure_code.value
    assert checkpoint is not None and checkpoint.resume_state is RunState.EXTRACTING
    assert runtime.repositories.list_obligations(run.run_id) == []
    assert runtime.repositories.list_findings(run.run_id) == []
    assert runtime.repositories.list_actions(run.run_id) == []
    assert runtime.repositories.list_approvals(run.run_id) == []

    recovered = worker.run(envelope)

    assert recovered.run_id == run.run_id and recovered.state == "AWAITING_APPROVAL"
    assert analyst.calls == 2
    assert runtime.repositories.get_source_document(run.run_id) == source_before
    assert runtime.repositories.get_regulation(run.regulation.reg_id) == regulation_before
    assert len(runtime.repositories.list_regulations_by_source("synthetic.pdf")) == 1
    assert len(runtime.repositories.list_obligations(run.run_id)) == 3
    assert len(runtime.repositories.list_findings(run.run_id)) == 1
    assert len(runtime.repositories.list_actions(run.run_id)) == 1
    assert len(runtime.repositories.list_approvals(run.run_id)) == 1
    events = runtime.repositories.list_audit_events(run.run_id)
    assert len({event.event_id for event in events}) == len(events)


def test_firestore_worker_handoff_and_duplicate_delivery_are_atomic() -> None:
    content = SAMPLE.read_bytes()
    run = make_run()
    source = SourceDocumentRecord(
        run_id=run.run_id,
        regulation_id=run.regulation.reg_id,
        object_name=f"runs/{run.run_id}/source/regulation.pdf",
        gcs_uri=f"gs://test-private/runs/{run.run_id}/source/regulation.pdf",
        source_sha256=KNOWN_SOURCE_SHA256,
        size_bytes=len(content),
        content_type="application/pdf",
        sanitized_filename=run.regulation.source_filename,
        synthetic=True,
        created_at=NOW,
    )
    repositories = FirestoreRepositories(cast(Any, FakeFirestoreClient()))
    repositories.commit_run_intake(
        RunIntakeCommit(
            run=run,
            checkpoint=RunCheckpoint(
                run_id=run.run_id,
                sequence=0,
                state=RunState.INGESTED,
                recorded_at=NOW,
            ),
            regulation=RegulationRecord(
                regulation=run.regulation,
                content_sha256=KNOWN_SOURCE_SHA256,
                version=1,
                created_at=NOW,
            ),
            source_document=source,
        )
    )
    storage = BoundMemoryStorage()
    storage.sources[run.run_id] = content
    worker = MinimumLiveWorker(
        repositories=repositories,
        storage=storage,
        analyst_factory=lambda _content: FixtureAnalyst(),
        analyst_settings=AnalystSettings(),
        max_source_bytes=10 * 1024 * 1024,
    )
    envelope = WorkflowLaunchRequest(
        run_id=run.run_id,
        source_gcs_uri=source.gcs_uri,
        source_sha256=source.source_sha256,
        synthetic=True,
    )

    first = worker.run(envelope)
    duplicate = worker.run(envelope)

    assert not first.duplicate_delivery and duplicate.duplicate_delivery
    assert repositories.get_run(run.run_id).state is RunState.AWAITING_APPROVAL
    assert len(repositories.list_obligations(run.run_id)) == 3
    assert len(repositories.list_findings(run.run_id)) == 1
    assert len(repositories.list_actions(run.run_id)) == 1
    assert len(repositories.list_approvals(run.run_id)) == 1


def test_approve_preview_revalidation_and_audit_are_coherent() -> None:
    runtime, run, envelope = seeded_runtime()
    assert runtime.worker is not None
    result = runtime.worker.run(envelope)
    preview = RuntimeActionService(runtime).preview(result.action_id)
    assert preview.baseline_finding_count == 1
    assert preview.resolved_finding_ids == [result.finding_id]
    assert preview.new_conflict_ids == [] and preview.detected_finding_picture_improves

    decided = RuntimeApprovalService(runtime).decide(
        result.approval_id,
        ApprovalDecision(decision=ApprovalDecisionValue.APPROVE),
    )
    assert decided.decided_by == "test-reviewer"
    completed = runtime.repositories.get_run(run.run_id)
    assert completed.state is RunState.COMPLETED
    assert [item.to_state for item in completed.transitions[-3:]] == [
        RunState.EXECUTING,
        RunState.REVALIDATING,
        RunState.COMPLETED,
    ]
    assert completed.completed_actions[0].status is ActionStatus.APPROVED_DRAFT
    finding = runtime.repositories.get_finding(result.finding_id)
    assert finding.status is FindingStatus.RESOLVED
    contract = runtime.repositories.get_synthetic_contract(finding.target_id)
    assert "must pay" in contract.clauses["placement-fee"]
    report = RuntimeAuditService(runtime).get(run.run_id)
    assert report.executed_actions[0].status is ActionStatus.APPROVED_DRAFT
    duplicate = runtime.worker.run(envelope)
    assert duplicate.duplicate_delivery and duplicate.state == "COMPLETED"


def test_reject_completes_without_execute_or_revalidate() -> None:
    runtime, run, envelope = seeded_runtime()
    assert runtime.worker is not None
    result = runtime.worker.run(envelope)

    RuntimeApprovalService(runtime).decide(
        result.approval_id,
        ApprovalDecision(decision=ApprovalDecisionValue.REJECT),
    )

    completed = runtime.repositories.get_run(run.run_id)
    assert completed.state is RunState.COMPLETED
    states = [item.to_state for item in completed.transitions]
    assert RunState.EXECUTING not in states and RunState.REVALIDATING not in states
    assert completed.completed_actions == []
    action = runtime.repositories.get_action(result.action_id)
    assert action.action.status is ActionStatus.REJECTED
    assert RuntimeAuditService(runtime).get(run.run_id).executed_actions == []
    duplicate = runtime.worker.run(envelope)
    assert duplicate.duplicate_delivery and duplicate.state == "COMPLETED"
