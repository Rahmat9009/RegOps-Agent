# Backend contract notes

## 2026-08-28 — minimum live worker slice (no contract change)

The frozen public contract remains unchanged: exactly eight `/api/v1` paths and 13
run states. `POST /internal/v1/workflow/run` and `GET /internal/v1/readiness` are
private routes excluded from generated OpenAPI.

The slice connects persistent synthetic PDF intake to Workflow OIDC, exact-object
Cloud Storage reading, bounded parsing, Model Armor-guarded Gemini extraction,
unchanged deterministic obligation/finding verification, and an atomic handoff to
`AWAITING_APPROVAL`. A package runtime fixture is bound only to SHA-256
`6571084f3ff2215fcf48d467c7d9e8afd808f5f4b644c00ddca7a9ca66e4c5d9`. It maps one
verified prohibition to one synthetic placement-fee contract conflict. The mapping
is backend-owned synthetic policy, not Gemini or ADK output. The ADK investigator
remains implemented/tested but is not invoked. The 37-finding evaluation fixtures
are unchanged.

The handoff transaction stores verified obligations, one finding, the immutable
synthetic source contract, deterministic draft amendment/action claim, pending
Approval and run guard, audit events, worker claim, checkpoints, and final transition
suffix together. Coherent duplicate delivery returns the stored result; partial or
conflicting state returns a sanitized conflict. Preview and approval touch only a
shadow copy. Approval remains an `APPROVED_DRAFT`; rejection executes nothing.

Required demo variables are `REGOPS_MODE=demo`, `GOOGLE_CLOUD_PROJECT`,
`REGOPS_BUCKET`, `REGOPS_WORKFLOW`, `REGOPS_WORKFLOW_REGION`,
`REGOPS_ARMOR_LOCATION`, `REGOPS_GEMINI_LOCATION`, `REGOPS_GEMINI_MODEL`
(`gemini-3.5-flash`), `REGOPS_ARMOR_INPUT_TEMPLATE`,
`REGOPS_ARMOR_OUTPUT_TEMPLATE`, `REGOPS_WORKFLOW_SERVICE_ACCOUNT`,
`REGOPS_WORKER_AUDIENCE`, `REGOPS_AUDIT_SIGNER_SERVICE_ACCOUNT`, and exact HTTPS
`REGOPS_CORS_ORIGINS`. `REGOPS_REGION` is only a temporary location fallback. CORS
is not authentication.

IAM/deployment remain external blockers: the Workflow caller needs Cloud Run invoke;
the service identity needs exact-object Storage, Firestore, Vertex AI, Model Armor,
Workflow execution, and IAM Credentials `signBlob` permissions. Resources and model
regional availability must already exist. No cloud resources were changed and no
live-cloud verification is claimed.

Exact local verification from `backend/`:

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy --no-incremental
.venv\Scripts\openapi-spec-validator.exe ..\contracts\openapi.yaml
.venv\Scripts\python.exe scripts\compare_openapi.py
.venv\Scripts\python.exe scripts\lock_dependencies.py --check
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe -m pip wheel --no-deps --no-build-isolation --wheel-dir .venv\wheel-check .
docker build -t regops-api:minimum-live .
git diff --check
```

## 2026-08-16 — deliberate Phase 0 contract repair

`contracts/openapi.yaml` was upgraded from OpenAPI 3.0.3 to 3.1.0 while retaining
exactly eight paths and all 13 run states.

Contract-breaking integration changes for the frontend adapter:

- `POST /runs` now accepts only `multipart/form-data` with required binary PDF field
  `regulation_file` and required boolean field `synthetic_ack`; it returns `202` and a
  `Run`. The former JSON body and `201` response were removed. No upload endpoint exists.
- `Error` is replaced by structured `APIError` (`code`, `message`, optional `details`).
- `Evidence`, `Scores`, and `ActionSummary` are renamed `EvidenceReference`,
  `FindingScores`, and `ProposedAction`.
- `Regulation` and `Obligation` are now explicit reusable schemas. `Run.regulation`
  references `Regulation`; `Finding.obligation` references `Obligation`.
- `CounterfactualPreview` now uses `action_id`, `shadow_run_id`,
  `baseline_finding_count`, `resolved_finding_ids`, `unchanged_finding_ids`,
  `new_conflict_ids`, `remaining_high_risk_ids`,
  `detected_finding_picture_improves`, and optional `narrative`.
- `ApprovalDecision` contains only `decision` and optional `note`. It rejects
  `decided_by` and every other unknown field. Reviewer identity is backend-controlled:
  the unauthenticated synthetic demo assigns `Approval.decided_by` to
  `"demo-reviewer"`. The frontend must never submit or select reviewer identity.
  `Approval` remains the reusable response representation and retains `decided_by`.
- `Run` now requires `updated_at`, `progress`, and `regulation.source_filename`.

The six business-workflow operations are declared but return structured `501` errors
during Phase 0. Claude remains responsible for applying these changes only within
`frontend/`.

## 2026-08-16 — deliberate Phase 1B contract freeze

The contract still contains exactly eight paths and the same 13 `RunState` values.
The six unfinished workflow operations remain structured `501` boundaries; this
change does not wire Gemini, Google ADK, persistence, workflow callbacks, or the real
business workflow.

Accepted frontend contract requests:

- **CR-002:** `Run.transitions` is now a required, authoritative, oldest-to-newest
  array of reusable `RunTransition` records. No internal reasoning or sensitive
  operational detail is exposed.
- **CR-003:** nullable `Run.recovery` exposes safe checkpoint, attempt, and sanitized
  error metadata. Pydantic rejects `recovery_available=true` without a checkpoint.
- **CR-004:** nullable `Run.change_detection` exposes current and previous lowercase
  SHA-256 values, whether content changed, and detection time.
- **CR-006:** a non-null `AuditReport.audit_package_url` is defined as a short-lived,
  absolute HTTPS signed download URL generated by the backend. It is response-only;
  runtime validation requires parsed HTTPS scheme and a non-empty host.
- **CR-007:** `FindingSummary.scores` is required, removing the score-hydration N+1.
- **CR-009:** findings accept `limit` (default 50, range 1–100) and `offset` (default
  0, minimum 0). `items` is the selected page, while `total` and `by_severity` count
  the complete result matching the active filters before pagination.

Additional accepted integration decisions:

- `Approval.finding_id` is required, allowing the approval UI to reach its finding
  without an action lookup.
- Rejection is authoritative: the amendment becomes `REJECTED`, is never executed,
  the finding remains `OPEN` unless independently resolved, and the run may move
  directly from `AWAITING_APPROVAL` to `COMPLETED`. A reviewer rejection alone is not
  a failure and rejected amendments are absent from completed/executed action lists.

Deferred requests, preserving the eight-path boundary:

- **CR-001:** no run-listing or latest-run endpoint.
- **CR-005:** no approval lookup endpoint.
- **CR-008:** no action lookup endpoint; required `Approval.finding_id` addresses the
  approval screen's immediate relationship need without adding a ninth path.

Security invariants remain unchanged: `ApprovalDecision` accepts only `decision` and
optional `note`; reviewer identity is backend-controlled; analyst and investigator
roles have no action tools; actions remain allowlisted; and the in-memory adapter
cannot be selected as production persistence.

## 2026-08-16 — Phase 1B.1 persistent API plane

The frozen contract and run-state document were not changed. The six former runtime
`501` boundaries now use typed repositories and existing deterministic services.
Demo and production composition is fail-closed around Firestore, private Cloud
Storage, Google Workflows executions, and backend-controlled reviewer identity.

Run transitions, approval decisions, shadow snapshots, and deterministic action
idempotency claims have explicit Firestore transaction boundaries. Intake stores the
exact PDF bytes under a run-scoped private object name, persists reproducibility
metadata, and passes only safe references to Workflows. The Gemini/ADK analysis
worker and Google Cloud provisioning remain deferred.

## 2026-08-26 — Phase 1B.1 final runtime-safety correction

The frozen contract and frontend were not changed. Firestore now has atomic
boundaries for all intake metadata and approval-required draft creation. A
run-scoped `pending_approval_slots` guard enforces the focused one-amendment
scenario; approval decisions verify and clear it transactionally, and ordinary run
transitions cannot commit `COMPLETED` while any pending Approval remains. Corrupted
multiple-pending data fails closed.

If metadata persistence fails after a private source upload, cleanup is restricted
to the exact run-scoped source object and cannot hide the original persistence
failure. Workflow-launch failure remains later in the sequence and preserves both
metadata and source while recording `FAILED_RECOVERABLE`.

Synchronous Firestore, Storage, and Workflows calls no longer execute directly on
FastAPI's event loop. Demo mode is the currently deployable synthetic hackathon
mode. Production authentication is not implemented; the default global app
intentionally fails closed in production until a trusted reviewer identity adapter
is injected.

## 2026-08-27 — Phase 1B.2C ADK Investigator boundary

The frozen OpenAPI contract, its eight paths, and its 13 run states were not
changed. Phase 1B.2C adds only the internal single-application ADK topology, the
candidate-only Impact Investigator, a canonical immutable five-record synthetic
corpus, five exact-ID read-only tools, and an ephemeral deterministic session
boundary. API wiring, Firestore stage commits, workflow recovery, action policy,
approval handling, and deployment infrastructure remain unchanged and deferred to
the later scoped phases.

The Analyst tool registry is empty. The Investigator registry contains only
`list_contract_summaries`, `get_contract_clause`, `list_case_summaries`,
`get_case_evidence`, and `get_internal_fee_policy`. Neither registry can reach
Firestore, repositories, approvals, reviewer identity, ActionPolicy, the Action
Controller, amendment writing, Workflows, arbitrary network access, web search, or
code execution. Sessions are invocation-local and hold only digests, backend-owned
obligation IDs, and the synthetic marker; ADK history is not authoritative.
