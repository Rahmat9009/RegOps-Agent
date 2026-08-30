# RegOps — From Rule Change to Resolved Action

**All Things Agentic Hackathon · Taskmaster track**

RegOps is an evidence-first synthetic demonstration that turns one bounded regulation fixture into a potential-conflict finding, a human-approved draft amendment against a shadow copy, deterministic revalidation, and a private audit package.

RegOps identifies potential conflicts and supports review. It does **not** determine legal compliance or process real contracts, cases, people, or regulations. Approval produces an `APPROVED_DRAFT` against a synthetic contract's shadow copy; it never silently replaces a source contract.

## Live submission deployment

Deployment evidence was verified on **2026-08-30**.

- Frontend: <https://regops-agent.vercel.app>
- Cloud Run API: <https://regops-api-vx2qltpxca-ey.a.run.app>
- API base: <https://regops-api-vx2qltpxca-ey.a.run.app/api/v1>
- Health: <https://regops-api-vx2qltpxca-ey.a.run.app/api/v1/health>
- Google Cloud project: `claude-workspace-free` (`791800137620`)
- Primary region: `europe-west3`

The production Vercel frontend uses the real HTTP adapter. Vercel hosts the frontend; the required API, orchestration, persistence, model call, content inspection, deterministic verification, approval handling, and audit generation run on Google Cloud.

See [live deployment evidence](docs/live-deployment-evidence.md) for resource topology, safe run proofs, judge inspection commands, audit-package behavior, and exact hosted limitations. See [infrastructure reproduction](infrastructure/README.md) for placeholder-based deployment instructions.

## Current implementation

| Area | Current status |
| --- | --- |
| Public contract | FastAPI implements exactly the eight operations and thirteen run states frozen in [contracts/openapi.yaml](contracts/openapi.yaml). Clients poll run state; there is no server push. |
| Hosted frontend | React/Vite UI deployed on Vercel in HTTP mode against the Cloud Run API. The mock adapter remains available for an offline UI demonstration, but the hosted submission is not mock-only. |
| Hosted backend | One Python 3.12 Cloud Run service provides the public API and OIDC-protected minimum worker route. Firestore is authoritative; source and audit objects use private Cloud Storage. |
| Orchestration | Google Workflow `regops-run-worker` invokes the protected Cloud Run worker route. Its deployed definition is checked in at [infrastructure/workflows/regops-run-worker.yaml](infrastructure/workflows/regops-run-worker.yaml). |
| Model boundary | Gemini 3.5 Flash in `eu`, with Model Armor input/output templates, performs only three bounded boolean detections for the exact synthetic fixture. |
| Evidence authority | Immutable backend fixture records supply canonical wording and evidence. The deterministic verifier independently checks document binding, digest, page, and exact quotation before persistence. |
| Action boundary | Only the Action Controller can use the three allowlisted actions: tag case, create review task, and approval-required draft amendment. Gemini and ADK do not control IDs, evidence, actions, approvals, or state. |
| ADK | The Impact Investigator and its read-only tool boundary are implemented and tested, but the hosted exact-hash minimum slice does not invoke it. |
| Production | Production mode remains fail-closed without trusted production identity, authentication, configuration, and governed production data. |

## Hosted architecture

```text
Vercel React UI
      |
      | HTTPS /api/v1, exact CORS origin
      v
Cloud Run: regops-api
      |-- Firestore (authoritative run/checkpoint/finding/action/approval/audit state)
      |-- private Cloud Storage (source PDF and audit package)
      |-- Workflows execution launcher
      |-- Model Armor input -> Gemini 3.5 Flash -> Model Armor output
      |-- deterministic evidence verifier and Action Controller
      |
      +<-- OIDC POST from Workflow regops-run-worker
```

The Workflow posts the four-field `WorkflowLaunchRequest` to `/internal/v1/workflow/run` with the `regops-workflow` identity and the Cloud Run origin as audience. It waits for the worker response and returns the body. It does not remain suspended for human approval: approval is recorded through the frozen API after the run reaches `AWAITING_APPROVAL`.

Firestore is authoritative if observations disagree. ADK session history and model output are never authoritative state.

## Verified live outcomes

- Clean run `011188a0-08c3-4bdc-864f-f90f415ca959` started at `INGESTED` without recovery, reached `AWAITING_APPROVAL` with one high-severity finding, recorded human approval, traversed `EXECUTING → REVALIDATING → COMPLETED`, resolved the finding, stored an `APPROVED_DRAFT`, and produced a downloadable private audit package reporting one executed action, one resolved finding, and zero remaining.
- Hosted-frontend run `e76f7556-4899-41bc-bc8d-d87a2859db46` completed through the Vercel UI with one approved draft amendment, one resolved finding, zero remaining, one document processed, and `43.151677` seconds total backend processing time. Its downloaded audit package matched the run.
- Recovery run `7f0074d1-9463-4983-9417-a6ce58d87413` demonstrated a durable `FAILED_RECOVERABLE` checkpoint/resume before approval and final completion.

No signed URL, provider payload, generated amendment text, credential, token, or private document content is recorded in repository evidence.

## Quick judge path

Open <https://regops-agent.vercel.app> and use the visibly synthetic sample path. The hosted UI talks to the real backend and is constrained to the checked-in synthetic regulation fixture.

1. Start the synthetic intake and follow the polled run stages.
2. Inspect the one high-severity potential-conflict finding and its evidence chain.
3. Open the counterfactual preview. It is a deterministic shadow-state simulation, not a legal conclusion or source-contract modification.
4. Approve the proposed synthetic amendment.
5. Confirm the transition history includes `EXECUTING` and `REVALIDATING`, the run is `COMPLETED`, the finding is `RESOLVED`, and the action is `APPROVED_DRAFT`.
6. Open the audit report. If the private audit download is offered, treat its short-lived URL as bearer access and do not copy or publish it.

The public health check is safe to run without credentials:

```sh
curl --fail --silent --show-error \
  https://regops-api-vx2qltpxca-ey.a.run.app/api/v1/health
```

Expected shape: `{"status":"ok","version":"0.1.0"}`. Health proves liveness only, not access to every private dependency.

## Exact hosted limits

- The hosted slice supports the exact synthetic regulation fixture at [samples/regops-synthetic-regulation-2026.pdf](samples/regops-synthetic-regulation-2026.pdf), bound by its known SHA-256 and `minimum-live-slice-v1` runtime fixture.
- Gemini returns only three required booleans for fixed synthetic obligations. It does not produce the persisted canonical claims or citations.
- Immutable backend fixture records supply canonical wording and evidence; the deterministic verifier independently validates exact source binding and evidence.
- The live mapping is fixed backend policy over one synthetic contract conflict. The implemented ADK Impact Investigator is not invoked by this hosted slice.
- Demo approval uses a backend-controlled synthetic reviewer identity. There is no production authentication or trusted production reviewer integration.
- The checked-in Workflow is one OIDC worker invocation, not a durable human-approval callback implementation.
- Phase 1 uses one Cloud Run service. Cloud Run Jobs, Pub/Sub, multi-document partitions, Agent Runtime/Registry, Agent Gateway, Memory Bank, and bonus models are not part of the hosted minimum slice.
- This is not a legal determination service. All visible records are synthetic and labelled.

## Local backend setup

RegOps requires Python **3.12.x** (`>=3.12,<3.13`). From `backend/`:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements-dev.lock
.venv\Scripts\python -m pip install --no-deps -e .
```

On macOS/Linux, use `python3.12 -m venv .venv` and `.venv/bin/python`.

The backend reads process environment directly and does not automatically load `.env` files. Never commit credentials, access tokens, service-account JSON, signed URLs, or private object contents.

### Runtime modes

| Mode | Behavior |
| --- | --- |
| `test` | Requires an explicitly injected `RuntimeContainer`; tests use in-memory/fake boundaries and block network/ADC by default. |
| `demo` | Persistent synthetic mode. Requires the configured Google Cloud resources, identities, Model Armor, Gemini, Workflow OIDC, exact CORS origin, and keyless audit signer. It never falls back to memory. |
| `production` | Default mode. Intentionally fails closed because no trusted reviewer identity provider is wired. |

### Backend configuration

Use project-specific values; these are placeholders, not credentials:

| Variable | Purpose | Example |
| --- | --- | --- |
| `REGOPS_MODE` | Runtime selection | `demo` |
| `GOOGLE_CLOUD_PROJECT` | Google Cloud project ID | `<project-id>` |
| `REGOPS_BUCKET` | Existing private bucket | `<private-bucket>` |
| `REGOPS_WORKFLOW` | Existing Workflow name | `<workflow-name>` |
| `REGOPS_WORKFLOW_REGION` | Workflow region | `<region>` |
| `REGOPS_ARMOR_LOCATION` | Model Armor location | `<region>` |
| `REGOPS_GEMINI_LOCATION` | Vertex AI/Gemini location | `<gemini-location>` |
| `REGOPS_GEMINI_MODEL` | Required hosted model | `gemini-3.5-flash` |
| `REGOPS_ARMOR_INPUT_TEMPLATE` | Input template resource name | `projects/<project-number>/locations/<region>/templates/<input-template>` |
| `REGOPS_ARMOR_OUTPUT_TEMPLATE` | Output template resource name | `projects/<project-number>/locations/<region>/templates/<output-template>` |
| `REGOPS_WORKFLOW_SERVICE_ACCOUNT` | Exact accepted Workflow OIDC email | `<workflow-sa>@<project-id>.iam.gserviceaccount.com` |
| `REGOPS_WORKER_AUDIENCE` | Exact Cloud Run audience | `https://<service-url>` |
| `REGOPS_AUDIT_SIGNER_SERVICE_ACCOUNT` | Dedicated keyless signer email | `<signer-sa>@<project-id>.iam.gserviceaccount.com` |
| `REGOPS_CORS_ORIGINS` | Comma-separated exact HTTPS browser origins, no trailing slash | `https://<frontend-host>` |
| `REGOPS_MAX_UPLOAD_BYTES` | Optional upload cap; defaults to 10 MiB | `10485760` |
| `REGOPS_SIGNED_URL_TTL_SECONDS` | Optional audit URL lifetime; 60–900 seconds | `300` |

`REGOPS_REGION` remains a temporary fallback for the three explicit locations; new deployments should set the explicit variables.

## Reproducible checks

From `backend/` with the Python 3.12 environment installed:

```sh
python -m pytest -q
python -m ruff check .
python -m mypy --no-incremental
python -m openapi_spec_validator ../contracts/openapi.yaml
python scripts/compare_openapi.py
python scripts/lock_dependencies.py --check
python -m pip check
```

The default test suite uses no Google credentials. The Firestore Emulator and live diagnostics are opt-in. Live diagnostics must never print provider payloads, source text, quotations, thought signatures, credentials, tokens, or signed URLs.

From `frontend/`, the existing offline checks remain:

```sh
npm ci
npm run typecheck
npm run lint
npm test
npm run build
```

The frozen integration boundary is [contracts/openapi.yaml](contracts/openapi.yaml): exactly eight operations and the thirteen states documented in [contracts/run-states.md](contracts/run-states.md). This documentation change does not modify either contract or frontend source.

## Security boundary

- Model Armor inspects bounded input text and decoded model-authored output. Blocked or unavailable inspection fails closed.
- Gemini has no tools and cannot control persisted IDs, canonical wording, evidence, actions, approval, reviewer identity, state transitions, or audit signing.
- Analyst/Investigator interfaces have no action tools. Only the deterministic Action Controller acts on schema-valid `Finding` records.
- Source contracts and source PDFs remain immutable. Approved amendments create separate `APPROVED_DRAFT` shadow snapshots.
- Firestore transactions protect run state, checkpoint, evidence/action handoff, pending approval, decisions, and idempotency boundaries.
- Private source and audit objects are never made public. Audit downloads use short-lived keyless signed URLs that are not persisted.
- CORS is an exact browser-origin policy, not authentication. The hosted demo is synthetic and does not provide production identity.

## Deployment reproduction

[infrastructure/README.md](infrastructure/README.md) documents the required APIs, four service-account responsibilities, least-privilege IAM edges, Firestore Native database, private bucket, Model Armor templates, Artifact Registry build, Cloud Run deployment, Workflow deployment, exact CORS origin, Vercel production variables, and health verification. Commands there are examples with placeholders and were not executed by this documentation task.

Cloud Run Jobs and Pub/Sub begin in Phase 2. Do not add them to the Phase 1 hosted slice.
