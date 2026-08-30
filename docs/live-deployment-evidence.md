# RegOps live deployment evidence

Deployment evidence date: **2026-08-30**. This is the date the submission deployment and the evidence below were verified; it is not asserted to be the creation timestamp of every underlying resource.

RegOps is a synthetic hackathon demonstration. It identifies potential conflicts, supports human review, and verifies that an approved remediation was applied to the detected finding. It does **not** determine legal compliance. No real regulation, contract, case, or person is processed by the hosted slice.

## Public entry points

| Surface | Deployed URL |
| --- | --- |
| Vercel frontend | <https://regops-agent.vercel.app> |
| Cloud Run API origin | <https://regops-api-vx2qltpxca-ey.a.run.app> |
| Public API base | <https://regops-api-vx2qltpxca-ey.a.run.app/api/v1> |
| Health | <https://regops-api-vx2qltpxca-ey.a.run.app/api/v1/health> |

The hosted Vercel build uses the real HTTP adapter. It is not the browser-only mock demonstration. Vercel hosts only the frontend; the required API, persistence, protected worker entry point, model call, content inspection, and orchestration run on Google Cloud.

The deployed browser configuration is `VITE_API_MODE=http` and
`VITE_API_BASE_URL=https://regops-api-vx2qltpxca-ey.a.run.app/api/v1`. The backend
allows the exact CORS origin `https://regops-agent.vercel.app` with no wildcard or
trailing slash; `REGOPS_API_PROXY` is not a production Vercel setting.

## Deployed Google Cloud topology

| Resource | Deployed value and role |
| --- | --- |
| Project | `claude-workspace-free` (`791800137620`) |
| Primary region | `europe-west3` |
| Cloud Run | The `regops-api` service serves the frozen public FastAPI operations and the OIDC-protected `/internal/v1/workflow/run` worker route at the API origin above. Phase 1 remains one service process. |
| Workflows | `regops-run-worker` in `europe-west3`; it posts the four-field run envelope to the internal Cloud Run route with an OIDC token and a 300-second timeout. The exact deployed source is checked in at [`infrastructure/workflows/regops-run-worker.yaml`](../infrastructure/workflows/regops-run-worker.yaml). |
| Firestore | Native mode, `(default)` database, `europe-west3`; authoritative run state, transitions, checkpoints, findings, actions, approvals, and audit records. |
| Cloud Storage | Private bucket `claude-workspace-free-regops-private`; immutable run-scoped synthetic PDF sources and generated audit packages. |
| Artifact Registry | Docker repository `regops` in `europe-west3`; stores the Cloud Run image. |
| Vertex AI / Gemini | `gemini-3.5-flash` with Gemini location `eu`; used only for bounded detection in the hosted minimum slice. |
| Model Armor | Templates `regops-input` and `regops-output`; inspect bounded page text before Gemini and decoded model-authored output before strict parsing. |
| Vercel | Hosts the compiled React/Vite frontend and points its public HTTP adapter at the Cloud Run API base. |

The deployed Workflow is deliberately small. Intake creates the durable Firestore run and asynchronously starts a Workflow execution. The Workflow authenticates to the internal Cloud Run endpoint as `regops-workflow`, waits for the worker response, and returns its body. The minimum worker advances the run to `AWAITING_APPROVAL`; the Workflow does not remain suspended on a callback. The human decision is recorded through the frozen approval endpoint, and the Cloud Run service applies the shadow-copy draft and deterministic revalidation.

### Runtime identity topology

| Identity | Hosted responsibility and boundary |
| --- | --- |
| `regops-api@claude-workspace-free.iam.gserviceaccount.com` | Cloud Run service identity. Uses the deployed Firestore, private bucket, Workflow execution, Vertex AI/Gemini, Model Armor, and keyless audit-signing integrations required by demo composition. It does not supply reviewer identity. |
| `regops-worker@claude-workspace-free.iam.gserviceaccount.com` | Dedicated worker identity provisioned for separation. The checked-in hosted Workflow currently invokes the worker route on the `regops-api` Cloud Run service, so this identity is not a separate hosted compute hop in the minimum slice. |
| `regops-workflow@claude-workspace-free.iam.gserviceaccount.com` | Workflow execution identity and the only accepted OIDC caller for the internal worker route. It is not a reviewer and has no action or approval authority. |
| `regops-audit-signer@claude-workspace-free.iam.gserviceaccount.com` | Dedicated keyless V4 URL signing identity with read access to the private audit object. The API identity may call IAM Credentials `signBlob` for this signer; no service-account key file is used. |

The logical Analyst and Investigator have no action tools. Only deterministic backend code validates and persists records, and only the Action Controller can apply the three allowlisted actions. Amendments always require a human decision and affect only a synthetic shadow copy.

## Live run evidence

The following records are safe identifiers and outcome summaries. No document body, model/provider payload, generated amendment text, token, credential, or signed URL is included.

### Clean API run

- Run ID: `011188a0-08c3-4bdc-864f-f90f415ca959`.
- Began at `INGESTED` with no recovery object.
- Reached `AWAITING_APPROVAL` with one high-severity finding.
- A human approval was recorded.
- Traversed `EXECUTING` and `REVALIDATING`, then finished `COMPLETED`.
- The finding became `RESOLVED`; the amendment action became `APPROVED_DRAFT`.
- The audit reported one executed action, one resolved finding, and zero remaining findings.
- A short-lived signed URL for the private audit package was generated, and the package downloaded successfully.

This proves the hosted approved one-document path from ingestion through private
audit delivery for the exact fixture. It does not prove general
regulatory-document support.

### Hosted frontend run

- Run ID: `e76f7556-4899-41bc-bc8d-d87a2859db46`.
- Completed through the production Vercel UI using the live Cloud Run API.
- Produced one approved draft amendment against the synthetic shadow copy.
- Resolved one finding, left zero findings remaining, and processed one document.
- Reported total backend processing time of `43.151677` seconds.
- The downloaded audit package matched the run.

This establishes a real hosted frontend-to-Google-Cloud path; the submitted frontend is not mock-only.

### Durable recovery run

- Run ID: `7f0074d1-9463-4983-9417-a6ce58d87413`.
- Demonstrated a durable `FAILED_RECOVERABLE` checkpoint and resume before reaching approval.
- Subsequently completed the approval, execution, and revalidation path.

The recovery proof is limited to safe state/checkpoint behavior. Provider payloads, generated content, authorization material, and signed URLs are intentionally excluded.

## Private audit-package behavior

Source PDFs and audit packages remain private under run-scoped object names. Audit report generation uploads the exact package, then uses Application Default Credentials and IAM Credentials `signBlob` against the dedicated signer identity to produce a short-lived HTTPS V4 `GET` URL for that object. The URL is response-only, behaves as bearer access while valid, and is never authoritative durable state. It must not be logged, committed, pasted into issues, or shown in submission material.

If upload succeeds but signing is temporarily unavailable, the API still returns the audit metrics with `audit_package_url: null` and may retry signing on a later audit GET. No private key or downloaded service-account credential is required.

## Exact hosted-demonstration limits

- The hosted worker accepts only the exact checked-in synthetic regulation fixture bound to `minimum-live-slice-v1` and its known SHA-256. Unknown source hashes fail closed.
- Gemini 3.5 Flash performs bounded boolean detection for exactly three fixed synthetic obligations: placement-fee prohibition, fee-schedule reissue, and employer-paid medical exception.
- Immutable backend fixture records supply canonical obligation wording, document bindings, dates, and evidence. Gemini cannot author those persisted fields.
- The deterministic verifier independently re-extracts and validates the exact document binding, digest, page, and quotation before any claim can persist.
- Gemini does not control IDs, persisted evidence, findings, action selection, amendments, approvals, reviewer identity, run state, or revalidation.
- The Google ADK Impact Investigator is implemented and tested, but the hosted exact-hash minimum slice does not invoke it. The live mapping is fixed backend policy over one synthetic contract conflict.
- The live Workflow is a one-call OIDC orchestration step; it does not implement a long-lived approval callback or Cloud Run Job fan-out.
- Demo approval uses the backend-controlled synthetic identity `demo-reviewer`. Production authentication and trusted reviewer identity are not implemented.
- Production mode remains fail-closed without trusted production identity and configuration.
- Only synthetic data is supported. The service identifies potential conflicts and supports review; it is not a legal determination service.
- Cloud Run Jobs, Pub/Sub, multi-document partitioning, Agent Runtime/Registry, Memory Bank, and Agent Gateway are not part of the hosted minimum slice.

## Safe judge verification

These read-only commands expose no credentials, provider payloads, private document content, or signed URLs. They assume a judge already has permission to inspect the project.

Public health and frontend checks:

```sh
curl --fail --silent --show-error \
  https://regops-api-vx2qltpxca-ey.a.run.app/api/v1/health
curl --fail --silent --show-error --head \
  https://regops-agent.vercel.app
```

Expected results are HTTP 200 for both endpoints and a health JSON object with `status: "ok"` and a version. Health is a liveness probe; it is not by itself proof that private dependencies are accessible.

Safe Google Cloud metadata inspection examples (they require an installed and
authorized Google Cloud CLI):

```sh
gcloud projects describe claude-workspace-free \
  --format='table(projectId,projectNumber)'

gcloud run services describe regops-api \
  --project=claude-workspace-free \
  --region=europe-west3 \
  --format='table(metadata.name,status.url,spec.template.spec.serviceAccountName,status.conditions[0].status)'

gcloud workflows describe regops-run-worker \
  --project=claude-workspace-free \
  --location=europe-west3 \
  --format='table(name.basename(),state,serviceAccount,revisionId)'

gcloud firestore databases describe \
  --project=claude-workspace-free \
  --database='(default)' \
  --format='table(name,type,locationId)'

gcloud storage buckets describe gs://claude-workspace-free-regops-private \
  --project=claude-workspace-free \
  --format='table(name,location,iamConfiguration.publicAccessPrevention,iamConfiguration.uniformBucketLevelAccess.enabled)'

gcloud artifacts repositories describe regops \
  --project=claude-workspace-free \
  --location=europe-west3 \
  --format='table(name,format)'

gcloud iam service-accounts list \
  --project=claude-workspace-free \
  --filter='email~"^regops-(api|worker|workflow|audit-signer)@"' \
  --format='table(email,disabled)'
```

Model Armor command availability varies with the installed Google Cloud CLI release. When supported, this is a read-only example:

```sh
gcloud model-armor templates list \
  --project=claude-workspace-free \
  --location=europe-west3 \
  --filter='name:(regops-input OR regops-output)' \
  --format='table(name.basename())'
```

Do not use `--format=json` on executions, inspect Cloud Run environment variables, print access tokens, retrieve private objects directly, or copy an `audit_package_url` into verification output.

## Reproducing the deployment

The complete placeholder-based deployment sequence, API list, IAM edges, private data resources, image build, Cloud Run and Workflow deploy commands, CORS setting, Vercel variables, and health checks are maintained in [`infrastructure/README.md`](../infrastructure/README.md). Those commands are deployment examples, not actions run by this documentation change.

## Verification performed for this record

On 2026-08-30, read-only HTTP checks returned HTTP 200 for the Vercel frontend and the Cloud Run health endpoint; the health body matched the expected `status` and `version` shape. The local shell did not have `gcloud` on `PATH`, so this documentation task did not independently query cloud metadata. Resource facts above are the confirmed live deployment facts supplied for the submission, corroborated by the checked-in runtime configuration and Workflow source. No cloud resource was created, updated, deleted, or redeployed while producing this record.
