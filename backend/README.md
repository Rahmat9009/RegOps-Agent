# RegOps backend

Python 3.12 FastAPI implementation of the frozen `contracts/openapi.yaml` plus the
Phase 1B persistent API and orchestration data plane. All eight contract paths are
wired. The API persists typed records in Firestore, stores private source and audit
objects in Cloud Storage, and starts the one-document process asynchronously with
Google Workflows. It never fabricates obligations or findings.

## Runtime modes

- `test` requires an explicitly injected runtime and may use the labelled in-memory
  repository and test fakes. It never discovers Google credentials.
- `demo` is the currently deployable synthetic hackathon mode. It requires Firestore,
  Cloud Storage, and Workflows configuration and assigns the backend-controlled
  `demo-reviewer` identity because all records are synthetic.
- `production` requires those persistent services plus a trusted reviewer identity
  adapter. Authentication is not implemented by this phase. The default global app
  intentionally cannot start in production mode because it has no trusted identity
  adapter injection; startup fails closed rather than using the demo identity.

`REGOPS_MODE` selects the mode (`production` by default). Persistent modes require
`GOOGLE_CLOUD_PROJECT`, `REGOPS_REGION`, `REGOPS_BUCKET`, and `REGOPS_WORKFLOW`.
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

Firestore transactions provide five concurrency boundaries:

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
Phase 1 remains a single-process service. The Gemini analyst adapter below is not
wired into API orchestration. ADK and cloud resource provisioning are deferred.
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
ADC, API version `v1`, temperature zero, one candidate, no tools, no automatic
function calls, no cached corpus and no thought output. `REGOPS_GEMINI_MODEL`
defaults to `gemini-3.5-flash`. The generation config uses JSON MIME and
`AnalystDraftOutput.model_json_schema()` with strict additional-field rejection.
The versioned prompt is packaged in the wheel.

`should_return_http_response=True` prevents the SDK from parsing model JSON before
inspection. The bounded raw response is inspected first, then its decoded text is
inspected again before strict JSON/Pydantic parsing. Missing/empty/truncated,
non-object, duplicate-key, non-finite, schema-invalid, refusal and tool-call outputs
fail without partial candidates. Default bounds are 8,192 generated tokens,
32,000 output characters and 128,000 raw response bytes.

`build_demo_analyst` requires `REGOPS_MODE=demo`, `GOOGLE_CLOUD_PROJECT`,
`REGOPS_REGION`, `REGOPS_ARMOR_INPUT_TEMPLATE` and `REGOPS_ARMOR_OUTPUT_TEMPLATE`.
Template names must belong to the configured project and region. Call `close()`
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

API references used for the adapter: [Google Gen AI SDK](https://googleapis.github.io/python-genai/)
and [Model Armor sanitization result](https://docs.cloud.google.com/model-armor/reference/rest/v1/SanitizationResult).

Phase 1B.2C remains the single ADK application, analyst/investigator capability
separation, impact investigator, fixed read-only corpus tools, session boundaries,
and their tests. Persistence/orchestration remains Phase 1B.2D.
