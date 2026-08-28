"""Worker-only ports. No SDK, client, generic tool registry or write capability
is passed to either candidate-producing role. The persistence port belongs to
trusted backend code only and accepts verified records, never draft output.
"""

from typing import Protocol

from regops_api.worker_models import (
    AcceptedEvidenceCatalog,
    AnalystDraftOutput,
    CorpusRecord,
    CorpusSnapshot,
    InvestigatorDraftOutput,
    SourceDocument,
    VerifiedObligationSet,
    VerifiedWorkerOutput,
)


class ImmutableSourcePages(Protocol):
    def read_bound_source(self) -> SourceDocument: ...


class AcceptedEvidenceLookup(Protocol):
    """Trusted verifier input; implementations must use the bound snapshot."""

    def read_accepted_evidence(self) -> AcceptedEvidenceCatalog: ...

    def read_accepted_corpus(self) -> CorpusSnapshot: ...


class ReadOnlyCorpus(Protocol):
    """A preloaded corpus view with exact-ID lookup, not arbitrary querying."""

    def list_records(self) -> tuple[CorpusRecord, ...]: ...

    def get_record(self, target_id: str) -> CorpusRecord | None: ...


class CandidateAnalyst(Protocol):
    def analyze(self, *, source: SourceDocument) -> AnalystDraftOutput: ...


class CandidateInvestigator(Protocol):
    def investigate(
        self,
        *,
        obligations: VerifiedObligationSet,
        corpus: ReadOnlyCorpus,
    ) -> InvestigatorDraftOutput: ...


class VerifiedOutputPersistence(Protocol):
    """Backend-only handoff; later adapter must revalidate and atomically commit.

    This port must never be supplied to an analyst, investigator or model tool.
    It supplies no approval, action or reviewer capability.
    """

    def handoff_verified(self, *, output: VerifiedWorkerOutput) -> None: ...
