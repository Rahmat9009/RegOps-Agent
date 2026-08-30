# RegOps infrastructure

This directory records the deployed Phase 1 synthetic demonstration and provides a placeholder-based reproduction guide. It does not contain Terraform or a resource-creation script, and none of the commands below were run by the documentation task that added this record.

## Deployed submission topology

Verified for submission on **2026-08-30**:

- Google Cloud project: `claude-workspace-free` (`791800137620`)
- Primary region: `europe-west3`
- Cloud Run API: <https://regops-api-vx2qltpxca-ey.a.run.app>
- Workflow: `regops-run-worker` in `europe-west3`
- Firestore: Native mode, `(default)` database, `europe-west3`
- Private bucket: `claude-workspace-free-regops-private`
- Artifact Registry Docker repository: `regops`
- Gemini: `gemini-3.5-flash` in `eu`
- Model Armor: `regops-input` and `regops-output`
- Vercel frontend: <https://regops-agent.vercel.app>

The exact deployed Workflow source is [workflows/regops-run-worker.yaml](workflows/regops-run-worker.yaml). Full resource/run evidence and safe inspection commands are in [docs/live-deployment-evidence.md](../docs/live-deployment-evidence.md).

The deployed public browser configuration is:

```text
Cloud Run REGOPS_CORS_ORIGINS=https://regops-agent.vercel.app
Vercel VITE_API_MODE=http
Vercel VITE_API_BASE_URL=https://regops-api-vx2qltpxca-ey.a.run.app/api/v1
Vercel REGOPS_API_PROXY=<unset>
```

These values are public routing configuration, not credentials. Vercel embeds the
`VITE_*` values at build time.

Phase 1 uses one Cloud Run service process and no Cloud Run Jobs or Pub/Sub. The Workflow sends the existing four-field run envelope to the OIDC-protected worker route and returns the worker response. It does not remain suspended on a human-approval callback; approval and deterministic revalidation are handled through the Cloud Run API after the worker reaches `AWAITING_APPROVAL`.

## Runtime identities and least privilege

| Principal | Required responsibility | Minimum useful access |
| --- | --- | --- |
| API service account, for example `regops-api@<project-id>.iam.gserviceaccount.com` | Cloud Run runtime, API persistence, Workflow launch, bounded model/Armor calls, audit upload, and delegated signing | Firestore data user on the RegOps database; object access on the private bucket; execute only the named Workflow; Vertex AI inference; use the two Model Armor templates; call IAM Credentials `signBlob` only as the audit signer; write ordinary service logs. |
| Worker service account, for example `regops-worker@<project-id>.iam.gserviceaccount.com` | Reserved dedicated worker identity | Grant only if a separate worker compute resource is introduced. The hosted minimum slice executes the worker route inside the API Cloud Run service and does not require this identity as a separate compute hop. |
| Workflow service account, for example `regops-workflow@<project-id>.iam.gserviceaccount.com` | OIDC caller for the internal worker route | Invoke only the named Cloud Run service. No Firestore, Storage, reviewer, action, amendment, or deployment administration. The backend validates its exact email and audience. |
| Audit signer, for example `regops-audit-signer@<project-id>.iam.gserviceaccount.com` | Keyless V4 signing identity | Read the private audit objects needed for a signed `GET`. It receives no private key and no broad write or runtime authority. |
| Deployment operator | One-time provisioning/deployment | Resource creation and `iam.serviceAccounts.actAs` only where required. Do not reuse this identity as a runtime principal. |

The public API must be reachable by Vercel, so the Cloud Run service permits unauthenticated invocation. That does not make private storage public and does not authorize the internal worker route: `/internal/v1/workflow/run` separately requires a valid Google OIDC token for the exact Workflow service account and audience.

Prefer resource-level IAM bindings and conditional bindings over project-wide grants. In particular:

- grant `roles/run.invoker` to the Workflow identity on the named Cloud Run service;
- grant Workflow execution permission to the API identity on the named Workflow;
- grant bucket object access only on the RegOps bucket;
- grant `roles/iam.serviceAccountTokenCreator` to the API identity on the audit-signer service account, not on every service account;
- grant the signer read access to the private audit objects, not public access;
- do not grant reviewer identity, approval authority, Owner, Editor, service-account-key administration, or IAM administration to any runtime identity.

Firestore server IAM is not a per-document security boundary. Isolate the deployment and retain the repository's fixed collection/object-path allowlists and transaction validation.

## Persistent object layout

- Source PDF: `runs/{run_id}/source/regulation.pdf`
- Audit package: `runs/{run_id}/audit/audit-package.json`
- Firestore collections: documented in [backend/README.md](../backend/README.md)

The bucket uses uniform bucket-level access and public-access prevention. Source uploads use create-only generation preconditions. Signed audit URLs are short-lived response values, never durable Firestore state or repository content.

## Reproduction example

Everything in this section is an **example** for an authorized operator creating an equivalent deployment in another project. Replace every angle-bracket placeholder. Review current Google Cloud documentation and organization policy before running it. Never put credentials, access tokens, service-account keys, signed URLs, or private object content in a command, environment file, build argument, or repository commit.

### 1. Set non-secret deployment values

Example shell variables:

```sh
PROJECT_ID='<project-id>'
PROJECT_NUMBER='<project-number>'
REGION='<region>'
GEMINI_LOCATION='<gemini-location>'
RUN_SERVICE='regops-api'
WORKFLOW_NAME='regops-run-worker'
BUCKET_NAME='<globally-unique-private-bucket>'
AR_REPOSITORY='regops'
IMAGE_TAG='<immutable-git-commit-or-release-tag>'
FRONTEND_ORIGIN='https://<production-frontend-host>'
API_SA="regops-api@${PROJECT_ID}.iam.gserviceaccount.com"
WORKER_SA="regops-worker@${PROJECT_ID}.iam.gserviceaccount.com"
WORKFLOW_SA="regops-workflow@${PROJECT_ID}.iam.gserviceaccount.com"
AUDIT_SIGNER_SA="regops-audit-signer@${PROJECT_ID}.iam.gserviceaccount.com"
```

For the recorded deployment, the exact CORS origin is `https://regops-agent.vercel.app` with no trailing slash. The Gemini location (`eu`) is intentionally distinct from the primary resource region (`europe-west3`).

### 2. Enable required APIs

Example:

```sh
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  workflows.googleapis.com \
  workflowexecutions.googleapis.com \
  aiplatform.googleapis.com \
  modelarmor.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  --project="$PROJECT_ID"
```

Organization policy may require additional service-agent setup. Secret Manager is not required by the checked-in runtime because it uses attached service identities/ADC and contains no application secret.

### 3. Create the four service accounts

Examples:

```sh
gcloud iam service-accounts create regops-api \
  --project="$PROJECT_ID" \
  --display-name='RegOps API runtime'
gcloud iam service-accounts create regops-worker \
  --project="$PROJECT_ID" \
  --display-name='RegOps dedicated worker'
gcloud iam service-accounts create regops-workflow \
  --project="$PROJECT_ID" \
  --display-name='RegOps Workflow caller'
gcloud iam service-accounts create regops-audit-signer \
  --project="$PROJECT_ID" \
  --display-name='RegOps keyless audit signer'
```

Do not create or download service-account keys. Bind only the IAM edges in the table above. Example role names commonly used by this topology include `roles/datastore.user`, `roles/storage.objectUser`, `roles/storage.objectViewer`, `roles/workflows.invoker`, `roles/run.invoker`, `roles/aiplatform.user`, `roles/modelarmor.user`, and `roles/iam.serviceAccountTokenCreator`; availability and resource-level support must be verified in the target project before applying them.

Example signer delegation on the signer resource:

```sh
gcloud iam service-accounts add-iam-policy-binding "$AUDIT_SIGNER_SA" \
  --project="$PROJECT_ID" \
  --member="serviceAccount:$API_SA" \
  --role='roles/iam.serviceAccountTokenCreator'
```

### 4. Create Firestore Native mode and private Storage

These are creation examples. Firestore database location is effectively permanent; choose it deliberately.

```sh
gcloud firestore databases create \
  --project="$PROJECT_ID" \
  --database='(default)' \
  --location="$REGION" \
  --type=firestore-native

gcloud storage buckets create "gs://$BUCKET_NAME" \
  --project="$PROJECT_ID" \
  --location="$REGION" \
  --uniform-bucket-level-access \
  --public-access-prevention
```

Grant the API identity only the object operations required for run-scoped sources/audits and grant the audit signer only read access needed for the audit download. Confirm that neither `allUsers` nor `allAuthenticatedUsers` appears in the bucket IAM policy.

### 5. Create Model Armor templates

Create two templates in the selected Armor location:

- `<input-template>`: prompt-injection, sensitive-data, and responsible-AI filters for bounded page-derived input text;
- `<output-template>`: the same required filter families for complete decoded model-authored output.

Use the Google Cloud Console or current official Model Armor API/CLI for the target project. Google Cloud CLI command availability and flags for Model Armor vary by release, so this repository does not claim a portable create command. Record the resulting full resource names as:

```text
projects/<project-number>/locations/<region>/templates/<input-template>
projects/<project-number>/locations/<region>/templates/<output-template>
```

The application fails closed if either template is missing, belongs to another project/location, reports incomplete filter coverage, or cannot be reached. Never use an allow-all fallback.

### 6. Build and store the container image

Examples from the repository root:

```sh
gcloud artifacts repositories create "$AR_REPOSITORY" \
  --project="$PROJECT_ID" \
  --location="$REGION" \
  --repository-format=docker \
  --description='RegOps backend images'

gcloud builds submit backend \
  --project="$PROJECT_ID" \
  --tag="$REGION-docker.pkg.dev/$PROJECT_ID/$AR_REPOSITORY/regops-api:$IMAGE_TAG"
```

Use an immutable Git commit or release identifier for `IMAGE_TAG`; do not use credentials or mutable private data as build arguments.

### 7. Deploy Cloud Run

Example after the private resources, IAM bindings, and Model Armor templates exist:

```sh
gcloud run deploy "$RUN_SERVICE" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --platform=managed \
  --image="$REGION-docker.pkg.dev/$PROJECT_ID/$AR_REPOSITORY/regops-api:$IMAGE_TAG" \
  --service-account="$API_SA" \
  --allow-unauthenticated \
  --timeout=300 \
  --set-env-vars="REGOPS_MODE=demo,GOOGLE_CLOUD_PROJECT=$PROJECT_ID,REGOPS_BUCKET=$BUCKET_NAME,REGOPS_WORKFLOW=$WORKFLOW_NAME,REGOPS_WORKFLOW_REGION=$REGION,REGOPS_ARMOR_LOCATION=$REGION,REGOPS_GEMINI_LOCATION=$GEMINI_LOCATION,REGOPS_GEMINI_MODEL=gemini-3.5-flash,REGOPS_ARMOR_INPUT_TEMPLATE=projects/$PROJECT_NUMBER/locations/$REGION/templates/<input-template>,REGOPS_ARMOR_OUTPUT_TEMPLATE=projects/$PROJECT_NUMBER/locations/$REGION/templates/<output-template>,REGOPS_WORKFLOW_SERVICE_ACCOUNT=$WORKFLOW_SA,REGOPS_WORKER_AUDIENCE=https://<cloud-run-service-origin>,REGOPS_AUDIT_SIGNER_SERVICE_ACCOUNT=$AUDIT_SIGNER_SA,REGOPS_CORS_ORIGINS=$FRONTEND_ORIGIN"
```

Obtain the stable Cloud Run service URL first and ensure `REGOPS_WORKER_AUDIENCE` equals its exact HTTPS origin with no trailing slash. `REGOPS_CORS_ORIGINS` must equal the production frontend origin exactly; no wildcard and no trailing slash are accepted. If the first deploy is used to discover the service URL, perform the final configuration update only after confirming the URL and IAM review.

### 8. Deploy the Workflow

The checked-in [workflows/regops-run-worker.yaml](workflows/regops-run-worker.yaml) is the exact source for the recorded deployment and therefore contains its Cloud Run origin twice: worker URL and OIDC audience. For another project, make a deployment copy and replace both occurrences with that project's exact Cloud Run origin before deploying.

Example:

```sh
gcloud workflows deploy "$WORKFLOW_NAME" \
  --project="$PROJECT_ID" \
  --location="$REGION" \
  --service-account="$WORKFLOW_SA" \
  --source='<project-specific-workflow.yaml>'
```

Grant the Workflow service account `roles/run.invoker` on the named service even though the public API permits unauthenticated requests; application-level OIDC validation is the authorization boundary for the internal route. Grant the API service account permission to execute only this named Workflow.

### 9. Configure Vercel production

Build the existing `frontend/` project on Vercel with these **public, non-secret** production variables:

```text
VITE_API_MODE=http
VITE_API_BASE_URL=https://<cloud-run-service-origin>/api/v1
```

Do not set `REGOPS_API_PROXY` in Vercel production; it is only the local Vite development proxy. After changing `VITE_*` variables, create a new Vercel production build because Vite embeds them at build time. Set backend `REGOPS_CORS_ORIGINS` to the final Vercel production origin exactly.

### 10. Verify health and metadata

Safe public examples:

```sh
curl --fail --silent --show-error \
  "https://<cloud-run-service-origin>/api/v1/health"
curl --fail --silent --show-error --head \
  "$FRONTEND_ORIGIN"
```

Expected health shape: `{"status":"ok","version":"0.1.0"}`. Then use the read-only, narrowly formatted `gcloud` commands in [docs/live-deployment-evidence.md](../docs/live-deployment-evidence.md) to inspect service identities, Workflow state, Firestore location, bucket privacy, Artifact Registry, and service accounts.

Do not verify by printing Cloud Run environment variables, access tokens, Workflow execution arguments/results, provider/model payloads, private documents, object contents, or signed audit URLs.

## Runtime variables

The Cloud Run demo requires:

- `REGOPS_MODE`
- `GOOGLE_CLOUD_PROJECT`
- `REGOPS_BUCKET`
- `REGOPS_WORKFLOW`
- `REGOPS_WORKFLOW_REGION`
- `REGOPS_ARMOR_LOCATION`
- `REGOPS_GEMINI_LOCATION`
- `REGOPS_GEMINI_MODEL`
- `REGOPS_ARMOR_INPUT_TEMPLATE`
- `REGOPS_ARMOR_OUTPUT_TEMPLATE`
- `REGOPS_WORKFLOW_SERVICE_ACCOUNT`
- `REGOPS_WORKER_AUDIENCE`
- `REGOPS_AUDIT_SIGNER_SERVICE_ACCOUNT`
- `REGOPS_CORS_ORIGINS`

Optional bounds are `REGOPS_MAX_UPLOAD_BYTES` and `REGOPS_SIGNED_URL_TTL_SECONDS`. `REGOPS_REGION` is only a legacy location fallback. Production mode additionally requires a trusted reviewer identity provider and remains fail-closed in the current application composition.
