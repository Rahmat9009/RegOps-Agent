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
Phase 1 remains a single-process service. The Gemini/ADK analysis worker and cloud
resource provisioning are deferred. Cloud Run Jobs and Pub/Sub begin in Phase 2.
