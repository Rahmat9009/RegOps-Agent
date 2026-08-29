# RegOps backend

Python 3.12 FastAPI implementation of the frozen `contracts/openapi.yaml` plus the
Phase 1B persistent API and orchestration data plane. All eight contract paths are
wired. The API persists typed records in Firestore, stores private source and audit
objects in Cloud Storage, and starts the one-document process asynchronously with
Google Workflows. It never fabricates obligations or findings.

## Runtime modes

- `test` requires an explicitly injected runtime and may use the labelled in-memory
  repository and test fakes. It never discovers Google credentials.
- `demo` is the minimum live synthetic hackathon mode. It requires Firestore,
  private Cloud Storage, Workflows, Model Armor, Vertex AI Gemini, Workflow OIDC,
  and IAM `signBlob` configuration and assigns the backend-controlled
  `demo-reviewer` identity because all records are synthetic.
- `production` requires those persistent services plus a trusted reviewer identity
  adapter. Authentication is not implemented by this phase. The default global app
  intentionally cannot start in production mode because it has no trusted identity
  adapter injection; startup fails closed rather than using the demo identity.

`REGOPS_MODE` selects the mode (`production` by default). The live demo requires
`GOOGLE_CLOUD_PROJECT`, `REGOPS_BUCKET`, `REGOPS_WORKFLOW`,
`REGOPS_WORKFLOW_REGION`, `REGOPS_ARMOR_LOCATION`, `REGOPS_GEMINI_LOCATION`,
`REGOPS_WORKFLOW_SERVICE_ACCOUNT`, `REGOPS_WORKER_AUDIENCE`,
`REGOPS_AUDIT_SIGNER_SERVICE_ACCOUNT`, exact `REGOPS_CORS_ORIGINS`, and both
Model Armor template variables. `REGOPS_REGION` is a temporary fallback for the
three explicit locations; new configuration should not use it.
`REGOPS_MAX_UPLOAD_BYTES` defaults to 10 MiB. `REGOPS_SIGNED_URL_TTL_SECONDS`
defaults to 300 seconds and is constrained to 60–900 seconds. Demo and production
never fall back to memory or fake integrations.

## Persistent layout and atomicity

Firestore uses stable top-level collections: `runs`, `regulations`,
`source_documents`, `obligations`, `synthetic_contracts`, `synthetic_cases`,
`shadow_snapshots`, `findings`, `review_tasks`, `approvals`, `audit_events`,
`audit_reports`, `proposed_actions`, `checkpoints`, `case_tags`, and
`action_idempotency`, and `pending_approval_slots`. Pydantic JSON serialization is
validated again on every read.

Firestore transactions provide six concurrency boundaries:

- intake commits the initial Run, sequence-zero checkpoint, RegulationRecord, and
  SourceDocumentRecord together after the private source upload;

- run state compare-and-set writes the authoritative Run transition chain, next
  checkpoint, and audit event together, and refuses completion while a pending
  approval exists;
- approval-required draft creation atomically claims its deterministic action and
  idempotency identifiers, creates the Approval, updates the Finding, appends the
  attempt/idempotency audit records, and claims the run-scoped pending slot;
- approval decision compare-and-set validates the sole pending Approval, run-scoped
  slot, and exact run/action/finding/source binding, then clears the slot and commits
  status, shadow snapshot, lifecycle checkpoints, and audit events together;
- an action write atomically claims its deterministic SHA-256 idempotency document,
  preserving automatic tag/review-task idempotency.
- verified worker handoff atomically stores verified obligations, one finding, its
  synthetic target, draft action/idempotency claim, Approval/pending guard, audit
  events, checkpoints, and `VERIFYING → VERIFIED → AWAITING_APPROVAL`.

Source contracts are immutable. Approved amendments are stored as separately bound
shadow snapshots. Source PDFs use `runs/{run_id}/source/regulation.pdf`; generated
audit packages use `runs/{run_id}/audit/audit-package.json`. Objects remain private,
and audit downloads are backend-generated short-lived HTTPS signed URLs.

The Workflows execution argument contains only `run_id`, the private source GCS URI,
the exact lowercase source SHA-256, and `synthetic: true`. Intake does not pass PDF
bytes or signed URLs and does not wait for analysis. A launch failure records
`FAILED_RECOVERABLE` before returning a sanitized `503`.
If intake metadata persistence fails after upload, cleanup targets only that exact
`runs/{run_id}/source/regulation.pdf` object. Cleanup is best-effort and never masks
the original sanitized persistence failure. A workflow launch failure occurs later,
so it preserves both metadata and source object.

All Firestore, Storage, and Workflows adapters are synchronous. FastAPI runs wholly
synchronous routes in its worker thread pool, while multipart intake delegates the
synchronous service call through Starlette's managed thread-pool helper after the
asynchronous upload read.

## Minimum live worker slice

`POST /internal/v1/workflow/run` accepts exactly the four-field Workflow envelope,
is excluded from public OpenAPI, rebinds all fields to Firestore, and validates a
Google OIDC token for the exact configured Workflow service account and audience.
`GET /internal/v1/readiness` uses the same private boundary. The frozen health route
remains liveness. CORS is an exact-origin browser policy and is not authentication.

The worker reads only the persisted run object, enforces the PDF byte limit and exact
lowercase SHA-256, and invokes the bounded parser and Model Armor-guarded Gemini
detector. A package fixture accepts only source hash
`6571084f3ff2215fcf48d467c7d9e8afd808f5f4b644c00ddca7a9ca66e4c5d9` and maps one
verified placement-fee prohibition to one synthetic contract conflict. This mapping
is deterministic backend policy, not Gemini or ADK output. Unknown hashes fail
closed; the 37-finding evaluation fixtures are unchanged.

For `minimum-live-slice-v1` only, explicit demo composition preselects a constrained
Gemini 3.5 Flash request with exactly three required boolean fixture keys. It asks
only whether the exact synthetic regulation contains the fixed placement-fee,
fee-schedule and employer-paid-medical concepts. The model cannot return statements,
quotations, dates or identifiers through this schema. All three detections must be
true; missing, false, non-boolean, malformed, blocked or extra output fails closed
without another Gemini call. The backend then resolves the keys to immutable
synthetic ground-truth records and runs the unchanged `verify_obligations` gate,
which independently confirms every document binding, digest, page and exact
quotation against the parsed PDF. Only canonical verified output may persist.
Gemini is not authoritative for IDs, canonical wording, evidence, actions or
approvals. Unknown hashes and production mode cannot enter this path; there is no
fallback from general extraction to fixture detection.

Recovery attempt counts are derived from the run's append-only transitions into
`FAILED_RECOVERABLE`, so each real failed recovery cycle increments once even though
the public recovery object is cleared while a checkpoint is actively resumed. A
duplicate failure handler observing an already-failed run does not add a transition
or increment the count.

Preview and revalidation run the same deterministic matcher on a shadow copy. The
source contract remains immutable. Approval stores `APPROVED_DRAFT` and traverses
`EXECUTING → REVALIDATING → COMPLETED`; rejection traverses directly to `COMPLETED`
and is excluded from executed/completed actions. Audit signing refreshes ADC and uses
IAM Credentials `signBlob` for the exact audit object; no JSON service-account key is
used or expected.

## Clean setup and checks (PowerShell)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements-dev.lock
.venv\Scripts\python -m pip install --no-deps -e .
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m mypy
.venv\Scripts\openapi-spec-validator ..\contracts\openapi.yaml
.venv\Scripts\python scripts\compare_openapi.py
```

The default suite includes deterministic Firestore transaction-callback unit tests
and requires no Google credentials. An optional test marked `firestore_emulator`
runs only when `FIRESTORE_EMULATOR_HOST` is configured.

Run locally with `.venv\Scripts\regops-api` or build `Dockerfile` for Cloud Run.
Phase 1 remains a single-process service. The hosted exact-hash minimum slice uses
Gemini only for fixed obligation detection. The general candidate-producing analyst
and ADK path remain implemented and tested but are not invoked by this hosted demo
composition. Cloud resource provisioning is deferred.
Cloud Run Jobs and Pub/Sub begin in Phase 2.

## Phase 1B.2B: guarded candidate extraction

This phase adds only local PDF extraction, explicit Model Armor text inspection,
and a Gemini candidate analyst. It does not implement the investigator, ADK,
orchestration, persistence, actions, callbacks, Agent Runtime or deployment.
`CandidateAnalyst.analyze(source=...)` and the frozen HTTP contract are unchanged.
The analyst returns `AnalystDraftOutput`; only `verify_obligations` creates
authoritative identifiers and verified obligations. A schema-valid candidate with
a wrong quotation/page is returned to that verifier and rejected there.

### PDF and model input

`parse_pdf` checks the signature, upload limit and exact SHA-256 before starting
`pypdf` in a disposable local subprocess. Bytes use stdin, not files, URLs or
command arguments. The manifest uses one-based pages and is compared in full
against independent re-extraction before any Model Armor/Gemini call.

| Limit | Default | Configuration |
| --- | --- | --- |
| PDF bytes | 10 MiB, or smaller intake limit | `REGOPS_MAX_UPLOAD_BYTES` |
| Pages | 100 | `REGOPS_PDF_MAX_PAGES`, at most 100 |
| Extracted characters per page | 20,000 | `REGOPS_PDF_MAX_PAGE_CHARS`, at most 20,000 |
| Total extracted characters | 200,000 | `REGOPS_PDF_MAX_TOTAL_CHARS`, at most 2,000,000 |
| Parser lifetime | 10 seconds | `PdfLimits.timeout_seconds`, at most 30 |
| Decoded streams | 8 MiB each / 32 MiB total | fixed application safety bounds |
| Object graph visits | 50,000 | fixed application safety bound |

Encrypted, damaged, zero-page, blank/unextractable-page, active-content, image,
unsupported-filter and ordinary embedded-file PDFs fail closed. No OCR or
semantic text repair is performed. Only CRLF/CR line endings are normalized;
case, punctuation, word boundaries and quotation semantics are unchanged.
The parser is time bounded and has stream/graph/output limits, but is not an
OS-level memory sandbox. Only synthetic documents are supported.

**Sample compatibility decision:** the checked-in four-page PDF contains a C2PA
`Content Credentials` associated file. Its explicit provenance FileSpec shape is
ignored during local extraction; it is never evidence and is not authenticated by
this adapter. Ordinary attachments remain rejected. To prevent uninspected PDF
metadata or attachment content from reaching the model, Gemini receives only the
inspected, page-labelled text, not native PDF bytes or a GCS URI. This deliberately
narrows the older specification's native-PDF input design and preserves the
unchanged candidate port. No source bytes, fixture hashes or verification rules
were changed to accommodate the model.

### Model Armor and Gemini

Two injected `TextInspection` ports guard input and output. The real adapter uses
the official `google-cloud-modelarmor` client, with separate input and output
templates. Every page must pass before generation. Each template must report
successful prompt-injection, sensitive-data and responsible-AI filters; missing,
unknown, inconsistent, suspicious, skipped or failed results cannot authorize use.
Only fixed `ArmorOutcome` values leave the adapter; matched text and vendor
diagnostics are discarded. No sanitized replacement text is substituted.

`google-genai` is configured with `enterprise=True`, explicit project/location,
ADC, API version `v1`, one candidate, no tools, no automatic function calls, no
cached corpus and no thought output. Gemini 3.5 sampling parameters (`temperature`,
`top_p`, and `top_k`) are intentionally omitted. Bounded extraction uses
`thinking_level=MINIMAL` with `include_thoughts=False`; deterministic behavior comes
from the system instruction, structured output and the verifier. `REGOPS_GEMINI_MODEL`
defaults to `gemini-3.5-flash`.

The general analyst generation config uses JSON MIME and a small inline provider schema. A live
incremental probe showed that the complete nested Pydantic schema is rejected for
schema complexity: restoring the outer obligation array's `minItems: 1` and
`maxItems: 50` to the otherwise accepted projection reproduces HTTP 400. The request
therefore omits that provider-side outer cardinality pair and redundant schema
detail. The response remains bounded by
token/byte/character limits and must still pass the unchanged, strict
`AnalystDraftOutput` model (including the 1..50 obligation
bound, extra-field rejection, identifiers, lengths and patterns) and deterministic
verifier. Its versioned prompt is packaged in the wheel.

The hosted minimum-live detector has a separate packaged instruction and a strict
three-boolean schema with no free-form fields. It preserves one candidate, JSON MIME,
`thinking_level=MINIMAL`, `include_thoughts=False`, disabled tools/function calls,
raw-envelope decoding, both Armor gates and the existing byte/token/time limits.
Unlike transient retries retained by the general analyst, detection makes exactly
one Gemini generation call per worker delivery and never retries until a key is true.

`should_return_http_response=True` prevents the SDK from parsing model JSON before
the application-controlled boundary. The adapter structurally decodes that bounded
raw envelope with duplicate-key and non-finite-number rejection; validates the
candidate count, finish reason, role, safety ratings and exact allowed part keys;
then discards provider wrapper metadata. Model Armor inspects the complete decoded
model-authored text before strict JSON/Pydantic parsing and deterministic
verification. Inspecting opaque transport/provider metadata is not a content-security
boundary: one live response was blocked only in its raw wrapper while its decoded
text was allowed. A separate live generation produced decoded text that was itself
prompt-injection-blocked; that block remains authoritative. The v2 system prompt
was advanced to v3 to require neutral declarative candidate fields, complete source
bindings, explicit date/exception fields and exact, non-paraphrased quotations,
and the provider projection now bounds generated strings and obligation/document
types to reduce unsupported prompt-like material. Missing/empty/truncated, non-object,
schema-invalid, refusal and tool-call outputs fail without partial candidates.
Default bounds are 8,192 generated tokens,
32,000 output characters and 128,000 raw response bytes. A Gemini 3.5 text part may
also contain a string `thoughtSignature`; it is accepted only alongside string
`text`, type-checked while decoding, then discarded before Armor inspection. It is
never returned, persisted or logged. Any malformed signature or any other part
field fails closed. Confirmed output blocks use fixed category-specific internal
codes for prompt injection, sensitive data or unsafe content; no matched content or
provider diagnostic enters recovery records.

`build_demo_analyst` and `build_demo_detector` require `REGOPS_MODE=demo`, `GOOGLE_CLOUD_PROJECT`,
`REGOPS_ARMOR_LOCATION`, `REGOPS_GEMINI_LOCATION`,
`REGOPS_ARMOR_INPUT_TEMPLATE` and `REGOPS_ARMOR_OUTPUT_TEMPLATE`.
The detector factory additionally requires the exact known PDF hash and fixture
version. Template names must belong to the configured project and Armor location. Call `close()`
to release factory-owned clients. Tests inject fakes directly. Production remains
unavailable; missing Armor configuration, raw API keys, alternate SDK endpoints
and enabled message capture are rejected. Nothing silently falls back to the
Gemini Developer API or an allow-all inspector.

Failures expose fixed `AnalystCode` strings only. Only timeout, rate-limit and
transient service/inspection failures retry: at most three attempts per call,
bounded jitter backoff and `Retry-After` delays capped at four seconds, up to
90 seconds per Gemini call, 10 seconds per Armor
inspection, and a shared 210-second stage budget. SDK retries are disabled.
Blocked content, invalid PDFs, malformed output, rejected requests and verifier
failures do not retry. This follows the explicit 1B.2B request rather than the
older specification's malformed-output retry suggestion. Dependency logs are
suppressed only inside the sensitive call context, including structured fields;
parser diagnostics never reach application logs.

### Offline and optional live verification

Default tests block network connections, DNS lookup and ADC discovery, permitting
only the standard library's internal socketpair loopback IPC on Windows. Recordings
are explicitly authored synthetic fixtures, not claimed live model outputs. They
check the exact three candidates, page-three citations and byte-identical verified
results. A real SDK test uses an in-memory HTTP transport and verifies that output
inspection precedes the SDK's candidate parser.

The `live_gemini` test is skipped unless `REGOPS_LIVE_GEMINI=1` and the project,
region and both template environment variables are present. ADC must also be
available. It uses the real input/output Armor adapters and the synthetic PDF,
and checks structured output and citations, not exact live prose. A skipped test
does not establish regional model availability, live extraction quality or cloud
security configuration.

The request-only diagnostic is separately skipped unless
`REGOPS_LIVE_GEMINI_DIAGNOSTIC=1`; it requires `GOOGLE_CLOUD_PROJECT` and
`REGOPS_GEMINI_LOCATION` (or `REGOPS_REGION`) and uses ADC/Vertex Enterprise only.
It sends a fixed synthetic prompt, adds the generation config incrementally, and
prints only fixed labels and status codes. It never reads or logs response bodies,
authorization material or thought signatures. It distinguishes model/IAM access
from schema/config rejection and does not run in the default suite.

The content-free output diagnostic is separately opt-in through
`REGOPS_LIVE_GEMINI_ARMOR_DIAGNOSTIC=1`. It uses the tracked synthetic PDF, the
production Gemini request configuration, ADC/Vertex Enterprise and the existing
`regops-output` template. Raw response data remains only inside the sensitive-I/O
scope and is discarded after inspection. The test emits only fixed raw/decoded
`ArmorOutcome` categories and bounded candidate/text-part counts; it never emits or
retains provider payloads, model text or thought signatures. A blocked decoded-text
outcome is a successful security diagnosis, not an accepted candidate.

The minimum-live compatibility diagnostic is separately opt-in through
`REGOPS_LIVE_DETECTION_DIAGNOSTIC=1`. It uses the tracked PDF, Gemini 3.5 Flash,
ADC/Vertex Enterprise and the existing input/output Armor templates. It emits only
request success, a fixed Armor category, schema-parse status, the three booleans,
verifier acceptance and candidate/verified counts. Source text, quotations,
provider payloads, thought signatures and authorization material remain inside the
sensitive-I/O scope and are discarded. It is excluded from the default suite.

### Reproducing dependency locks (Python 3.12, PowerShell)

Existing pins are retained as resolver constraints. Reports stay in ignored
`.venv/`; the renderer emits only package names and versions. Both shared and
direct pins are checked by the default integrity test.

```powershell
.venv\Scripts\python -m pip install --dry-run --ignore-installed --report .venv/runtime-resolution.json -c requirements-runtime.lock .
.venv\Scripts\python -m pip install --dry-run --ignore-installed --report .venv/dev-resolution.json -c requirements-dev.lock '.[dev]'
.venv\Scripts\python scripts\lock_dependencies.py
.venv\Scripts\python scripts\lock_dependencies.py --check
.venv\Scripts\python -m pip install -r requirements-dev.lock
.venv\Scripts\python -m pip install --no-deps -e .
.venv\Scripts\python -m pip check
```

API references used for the adapter: [Gemini 3.5 Flash guide](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/guides/gemini-3-5-flash),
[structured output](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/capabilities/control-generated-output),
[Google Gen AI SDK](https://googleapis.github.io/python-genai/), and
[Model Armor sanitization result](https://docs.cloud.google.com/model-armor/reference/rest/v1/SanitizationResult).

## Phase 1B.2C: ADK Impact Investigator

This phase adds one ADK application topology with a deterministic sequential root
and exactly two single-turn components. The Analyst has no model-callable tools;
the Investigator has exactly five package-bound, read-only functions over the
immutable synthetic corpus. Neither component receives persistence, approval,
action, amendment, generic query, network, search, or code-execution capability.

The checked-in five-record corpus is strict, frozen, visibly synthetic, and bound
to canonical manifest and per-record SHA-256 digests. Tool calls accept only exact
contract/clause/case/policy IDs and return bounded JSON copies with exact evidence
anchors. Unknown IDs fail closed without echoing the input.

Investigation is one-shot. Its session ID is derived from the run ID, canonical
obligation-set digest, corpus digest, model, instruction version, and tool-schema
version. A fresh `InMemorySessionService` is used per call; session state contains
only digests, backend obligation IDs, and `synthetic: true`. Candidate output is
independently parsed into strict `InvestigatorDraftOutput`; it cannot carry action,
approval, amendment, status, authoritative run, or finding fields.

The application is not wired into API intake or lifecycle state. Persistent stage
commits, orchestration, recovery, and action handoff remain Phase 1B.2D.
