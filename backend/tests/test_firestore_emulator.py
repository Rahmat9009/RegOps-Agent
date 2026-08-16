from __future__ import annotations

import os
from typing import Any, cast
from uuid import uuid4

import pytest
from google.cloud import firestore

from regops_api.domain_models import (
    RegulationRecord,
    RunCheckpoint,
    RunIntakeCommit,
    SourceDocumentRecord,
)
from regops_api.firestore import FirestoreRepositories, checkpoint_document_id
from regops_api.schemas import Regulation, RunState
from tests.factories import NOW, make_run


@pytest.mark.firestore_emulator
@pytest.mark.skipif(
    not os.getenv("FIRESTORE_EMULATOR_HOST"),
    reason="FIRESTORE_EMULATOR_HOST is not configured",
)
def test_emulator_atomic_intake_commit_round_trip() -> None:
    """Optional integration coverage; default verification uses transaction fakes."""
    suffix = uuid4().hex
    run_id = f"emulator-run-{suffix}"
    regulation_id = f"emulator-regulation-{suffix}"
    regulation = Regulation(
        reg_id=regulation_id,
        title="Synthetic emulator regulation",
        source_filename="emulator.pdf",
        synthetic=True,
    )
    run = make_run().model_copy(
        update={"run_id": run_id, "regulation": regulation}
    )
    checkpoint = RunCheckpoint(
        run_id=run_id,
        sequence=0,
        state=RunState.INGESTED,
        recorded_at=NOW,
    )
    commit = RunIntakeCommit(
        run=run,
        checkpoint=checkpoint,
        regulation=RegulationRecord(
            regulation=regulation,
            content_sha256="e" * 64,
            version=1,
            created_at=NOW,
        ),
        source_document=SourceDocumentRecord(
            run_id=run_id,
            regulation_id=regulation_id,
            object_name=f"runs/{run_id}/source/regulation.pdf",
            gcs_uri=f"gs://emulator-private/runs/{run_id}/source/regulation.pdf",
            source_sha256="e" * 64,
            size_bytes=10,
            content_type="application/pdf",
            sanitized_filename="emulator.pdf",
            synthetic=True,
            created_at=NOW,
        ),
    )
    client = firestore.Client(project="regops-phase1b-emulator")
    repositories = FirestoreRepositories(client)
    references = (
        client.collection("runs").document(run_id),
        client.collection("checkpoints").document(
            checkpoint_document_id(run_id, 0)
        ),
        client.collection("regulations").document(regulation_id),
        client.collection("source_documents").document(run_id),
    )
    try:
        repositories.commit_run_intake(commit)
        assert repositories.get_run(run_id) == run
        assert repositories.get_source_document(run_id) == commit.source_document
        assert repositories.get_regulation(regulation_id) == commit.regulation
        assert repositories.latest_checkpoint(run_id) == checkpoint
    finally:
        for reference in references:
            reference.delete()
        cast(Any, client).close()
