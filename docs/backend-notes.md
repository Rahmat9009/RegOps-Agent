# Backend contract notes

## 2026-08-29 — bounded synthetic live obligation detection (no contract change)

The frozen contract and frontend remain unchanged. The hosted minimum-live
demonstration no longer asks Gemini to construct interdependent obligation fields.
For `REGOPS_MODE=demo`, `minimum-live-slice-v1`, source SHA-256
`6571084f3ff2215fcf48d467c7d9e8afd808f5f4b644c00ddca7a9ca66e4c5d9`,
the fixture document identity and the explicit minimum-live worker composition,
Gemini 3.5 Flash receives inspected PDF page text and returns only these required
booleans: `placement_fee_prohibition`, `fee_schedule_reissue`, and
`employer_paid_medical_exception`. Extra, missing, non-boolean, malformed, blocked
or false output fails closed. Detection is preselected before generation, makes one
Gemini call per delivery and has no general-extraction fallback or retry-until-true
behavior.

After all three detections are true, trusted backend code resolves the fixed keys to
immutable synthetic ground-truth `AcceptedObligation` records. The unchanged
`verify_obligations` gate then independently checks exact document identity, source
digest, page and quotation presence against the parsed PDF. Only its canonical
verified output can persist. The booleans are not authoritative evidence and are not
persisted. Gemini does not author stored IDs, canonical statements, evidence,
actions or approvals. The general candidate-producing analyst remains implemented
and tested for non-fixture sources, but the exact-hash hosted demonstration does not
use it and must not be described as unrestricted regulatory extraction.

The content-free compatibility test is opt-in through
`REGOPS_LIVE_DETECTION_DIAGNOSTIC=1`; default tests cannot reach ADC or the network.
It may report only request status, a fixed Armor category, schema status, three
booleans, verifier acceptance and bounded counts. No live result is claimed here
unless the diagnostic is actually run during this change. It was run once with
ADC/Vertex Enterprise, Gemini 3.5 Flash and the existing Model Armor templates:
the request succeeded, Armor returned `allowed`, the strict schema parsed all three
booleans as true, and the unchanged verifier accepted three of three resolved
candidates. No source text, quotation, provider payload, thought signature,
credential or token was emitted. The worker run was not retried and nothing was
deployed.

## 2026-08-29 — superseded free-form obligation reconciliation (no contract change)

The frozen contract and frontend remain unchanged. One opt-in ADC/Vertex Enterprise
diagnostic ran the exact tracked synthetic PDF through the current input Armor gate,
Gemini 3.5 analyst, output Armor gate, strict Pydantic parser and unchanged
`verify_obligations`. It emitted no candidate text, quotation, signature, provider
payload, credential or token. The safe result was three candidates and three
accepted records, one `UNSUPPORTED_OBLIGATION` issue, matching obligation types,
and mismatches in statement, effective date and every complete evidence-set
dimension (document, page, quotation and cardinality). Zero candidate evidence sets
uniquely identified an accepted obligation. This proves the deployed failure was
unsupported candidate/evidence output, not malformed transport or verifier drift.

The evidence branch remains fail closed. For the exact
`minimum-live-slice-v1`/SHA-256
`6571084f3ff2215fcf48d467c7d9e8afd808f5f4b644c00ddca7a9ca66e4c5d9`
only, the provider projection now restricts source binding fields and evidence
choices to the fixture's already verified anchors, requires exactly the complete
two-anchor set per candidate, and requires explicit date and exception fields. The
v3 prompt requires verbatim source binding and exact, non-shortened,
non-paraphrased quotations. Wrong, partial, ambiguous, duplicate or unknown
evidence remains rejected; no fuzzy quotation matching was added.

A second, independent deterministic synthetic-demo gate reconciles only statement
wording. It activates only in demo composition after strict model parsing and only
when a candidate's complete evidence set uniquely identifies one accepted fixture
obligation using existing layout-whitespace normalization, every unchanged anchor
passes the exact evidence verifier, and type, effective date and exceptions match.
It replaces only the statement with the catalog's canonical statement. All
candidates must form a complete one-to-one mapping; otherwise the original
candidates go unchanged to the general verifier and fail. The general verifier was
not modified. Unknown hashes receive the base projection and no reconciliation;
production composition rejects the minimum-live worker.

The content-free diagnostic is opt-in through
`REGOPS_LIVE_OBLIGATION_DIAGNOSTIC=1` and excluded from default tests. It was run
once to establish the mismatch. The changed projection was not repeatedly sampled
until an output passed and has not been deployed.

The recovery count defect was separate: resume intentionally cleared `Run.recovery`,
but the next failure derived its count only from that cleared object, resetting the
displayed count to one. Counts now derive from append-only transitions into
`FAILED_RECOVERABLE`; each actual failed recovery appends one transition and
increments once. A duplicate failure handler that observes the already-failed state
does neither. Checkpoint resume, deterministic IDs and atomic handoff behavior are
unchanged.

## 2026-08-29 — Model Armor output wrapper correction (no contract change)

The frozen contract and frontend remain unchanged. An opt-in, content-free live
diagnostic used the tracked synthetic PDF, the production Gemini 3.5 request,
ADC/Vertex Enterprise and the existing `regops-output` template. It proved
`prompt_injection_blocked` for the complete raw provider response and `allowed` for
the complete decoded model text in one generation, then proved
`prompt_injection_blocked` for both raw and decoded text in a separate generation
(each one candidate and one text part). Earlier probes had separately allowed both
the known-safe candidate fixture and an opaque synthetic signature. This establishes
the fixed detector category and also proves model-output variability: provider
wrapper material can false-positive independently, while some generated decoded
text is validly blocked. No response body, model text, quote, signature, credential
or provider payload was printed, logged, persisted or returned by the diagnostic.

The adapter handles both cases without weakening Armor. It retains
`should_return_http_response=True`, structurally decodes the bounded raw JSON with
duplicate-key and NaN rejection, validates candidate count, finish reason, role,
safety state and exact allowed text-part keys, and discards opaque non-content
metadata. Model Armor then inspects the complete decoded text before strict
Pydantic candidate parsing and the unchanged deterministic verifier. Provider
metadata is not a meaningful content-security boundary; accepting it cannot
authorize a candidate, while inspecting it can make non-content transport fields
look like model instructions. If decoded text is blocked, the category-specific
failure is preserved and no candidate parsing or persistence occurs.

To reduce the observed model-authored variant, the system prompt was versioned to
`regulation-analyst-v2` and required neutral third-person declarative candidate
fields, forbade prompt/meta/instructional material in candidate prose, and required
the shortest exact supporting quotation without adjacent unrelated material. The
provider projection additionally applies existing Pydantic string bounds and fixed
obligation/document-kind enums. Strict Pydantic parsing and deterministic
verification remain unchanged and authoritative.

One post-correction live diagnostic was run after those v2 constraints were applied.
The Gemini request returned one candidate/one text part and the existing output
template reported `allowed` for both the raw envelope and decoded text. This was a
verification of the changed request, not a retry that accepted or persisted either
earlier blocked response; both blocked responses had already been discarded.

A `thoughtSignature` is accepted only as a string attached to a string text part,
then discarded before Armor inspection. It is never persisted, exposed or logged.
Unknown part fields, thought-only parts, functions, executable code, non-text output,
malformed envelopes and blocked decoded text all fail closed. The input Armor gate
is unchanged. Decoded output blocks now use fixed sanitized category-specific
internal codes for prompt injection, sensitive data and unsafe content, without
changing the public contract shape or recording matched content.

The output diagnostic is opt-in through
`REGOPS_LIVE_GEMINI_ARMOR_DIAGNOSTIC=1` and remains excluded from the default suite.
It performs read-only inference/template inspection and makes no cloud resource or
deployment changes.

## 2026-08-29 — Gemini 3.5 live compatibility correction (no contract change)

The frozen public contract and frontend are unchanged. The live request rejection
was reproduced with `google-genai==2.20.0` through an ADC/Vertex Enterprise-only,
payload-blind diagnostic in `global`. Model access, `thinking_level=MINIMAL`, and
JSON mode returned HTTP 200. The authored `AnalystDraftOutput.model_json_schema()`
returned HTTP 400. A smaller inline projection returned HTTP 200; adding the outer
obligation array's `minItems: 1` and `maxItems: 50` back to that nested projection
returned HTTP 400. This identifies the endpoint's structured-schema complexity
limit, specifically the outer 1..50 cardinality over the nested obligation/evidence
shape, as the live request failure. `temperature=0` returned HTTP 200 in the reduced
probe but is still intentionally omitted, together with `top_p` and `top_k`, under
current Gemini 3.5 guidance.

The provider schema remains structurally bounded and keeps the accepted 1..5 evidence
cardinality; generation also remains bounded by output-token, raw-byte and decoded-
character limits. The returned text must still pass the unchanged strict Pydantic
model, its 1..50 obligation cardinality and all extra-field/identifier/text rules,
then the unchanged deterministic verifier. No model-owned identifiers are accepted.

Gemini 3.5 text parts may carry a string `thoughtSignature`. The adapter validates
the signature type while structurally decoding the provider response, discards the
opaque value before decoded-text Armor inspection, and never persists, returns or
logs it. Missing text, malformed signatures, thought-only parts, tool calls,
executable code and every other part field fail closed.

The safe request diagnostic is opt-in through
`REGOPS_LIVE_GEMINI_DIAGNOSTIC=1`; default tests cannot use the network or ADC. It
uses only a fixed synthetic prompt and emits only fixed diagnostic labels/status
codes. No cloud resources, deployment, workflow, source, action, approval or audit
records were changed by this correction.

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
