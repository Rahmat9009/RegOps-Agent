# AGENTS.md — Backend Agent Brief (Codex)

You are responsible for the **backend, contracts, and infrastructure** of **RegOps**.

RegOps targets **Python 3.12** and the **Taskmaster** hackathon track.

## Hard boundaries
- You edit **`backend/`, `contracts/`, `infrastructure/`**. Do **not** modify `frontend/`.
- You **own and maintain `contracts/openapi.yaml`** — it is the integration boundary. It is currently **frozen** for parallel work. Any change must be deliberate and announced (note it in `docs/backend-notes.md`) so the frontend can rebuild its mock adapter to match.
- Claude edits **`frontend/` only**. Frontend contract requests belong in
  `frontend/CONTRACT_REQUESTS.md`, never `docs/frontend-notes.md`.

## Build order (frozen)
1. FastAPI project and typed schemas (mirror `contracts/openapi.yaml`).
2. Complete one-document vertical workflow (the 12-step acceptance test in `docs/`).
3. Gemini structured extraction (JSON-schema-constrained; evidence required on every claim).
4. Finding and evidence-chain generation.
5. Three-action policy engine (tag case · create review task · draft amendment against shadow copy → approval).
6. Approval callback (Google Workflows; a FastAPI stub is acceptable first, real callback second).
7. Shadow-state counterfactual validation (**deterministic** — rerun the same matching+validation pipeline on a shadow copy; Gemini only narrates the diff).
8. Phase 2: Cloud Run Jobs and checkpoints (partitioning, retries, idempotency).
9. Injection-containment and evaluation tests (containment = document content cannot cause a consequential action).
10. Google Cloud deployment configuration.

## Contract compliance
- Implement exactly the 8 endpoints and the run-state enum in `contracts/openapi.yaml`.
- Run states: `INGESTED, EXTRACTING, EXTRACTED, MAPPING, MAPPED, VERIFYING, VERIFIED, AWAITING_APPROVAL, EXECUTING, REVALIDATING, COMPLETED, FAILED_RECOVERABLE, FAILED`.
- Progress is via polling; no server push required.

## Language & safety discipline
- Never claim the system "determines legal compliance." It "identifies potential conflicts," "supports review," and "verifies approved remediation was applied to the detected finding."
- "Modify contract" = generate & store a proposed amendment against a synthetic contract's **shadow copy**; on approval, status becomes `APPROVED_DRAFT`. Never silently replace a contract.
- Analyst/Investigator agents have **no action tools**. Only the Action Controller acts, and only on schema-valid `Finding` records. Actions are allowlisted; amendments always require approval.
- All contracts/cases are **synthetic** and labeled.

## Phase boundaries
- **Phase 0:** Python 3.12 FastAPI contract, schemas, validation, tests, and a Cloud Run-ready container only. Do not begin the business workflow.
- **Phase 1:** one-document workflow in a single Cloud Run service process. No Cloud Run Jobs and no Pub/Sub.
- **Phase 2:** Cloud Run Jobs, partition checkpoints, and Pub/Sub begin here.

## Core services (Phase 1)
Gemini 3.5 (Vertex AI) · Google ADK · Cloud Run service · Firestore · Cloud Storage · Google Workflows. Defer Cloud Run Jobs, Pub/Sub, BigQuery, Memory Bank, and advanced monitoring to Phase 2 or later.
