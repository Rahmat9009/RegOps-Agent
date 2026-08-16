# infrastructure/ — owned by Codex

Deployment and Google Cloud configuration. See `AGENTS.md` (root).

Expected contents when provisioning is separately authorized (no cloud resources are
provisioned by Phase 1B.1):
- `setup_gcp.sh` — enable APIs, create Firestore, bucket, service account + IAM roles.
- `cloudrun.service.yaml` — Cloud Run service definition.
- `cloudrun.job.yaml` — Cloud Run Job for partitioned corpus processing (Phase 2).
- `workflows/approval.yaml` — Google Workflows approval callback definition.
- Runtime variables: `REGOPS_MODE`, `GOOGLE_CLOUD_PROJECT`, `REGOPS_REGION`,
  `REGOPS_BUCKET`, `REGOPS_WORKFLOW`, optional `REGOPS_MAX_UPLOAD_BYTES`, and optional
  `REGOPS_SIGNED_URL_TTL_SECONDS`.

`REGOPS_MODE=demo` is the currently deployable synthetic hackathon configuration.
The default global app intentionally fails closed in `production` because Phase 1B.1
does not provide a trusted reviewer identity adapter or completed authentication.

Persistent object layout:

- Cloud Storage source: `runs/{run_id}/source/regulation.pdf`
- Cloud Storage audit package: `runs/{run_id}/audit/audit-package.json`
- Firestore: stable top-level collections documented in `backend/README.md`

The Workflows execution payload is limited to the run identifier, private source GCS
URI, exact source SHA-256, and synthetic marker. It contains no document bytes,
credentials, reviewer identity, or signed URL.

Phase 1 uses one Cloud Run service process and does not use Cloud Run Jobs or Pub/Sub.
Cloud Run Jobs and Pub/Sub begin in Phase 2.

Potential APIs for Phase 1, when provisioning is authorized: Run, Firestore, Storage,
Vertex AI, Workflows, and Secret Manager. Gemini/ADK worker implementation and all
provisioning remain deferred.
