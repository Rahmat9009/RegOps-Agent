# infrastructure/ — owned by Codex

Deployment and Google Cloud configuration. See `AGENTS.md` (root).

Expected contents (added after Phase 0; no cloud resources are provisioned yet):
- `setup_gcp.sh` — enable APIs, create Firestore, bucket, service account + IAM roles.
- `cloudrun.service.yaml` — Cloud Run service definition.
- `cloudrun.job.yaml` — Cloud Run Job for partitioned corpus processing (Phase 2).
- `workflows/approval.yaml` — Google Workflows approval callback definition.
- Notes on required env vars: `PROJECT_ID`, `REGION`, `BUCKET`.

Phase 1 uses one Cloud Run service process and does not use Cloud Run Jobs or Pub/Sub.
Cloud Run Jobs and Pub/Sub begin in Phase 2.

Potential APIs for Phase 1, when provisioning is authorized: Run, Firestore, Storage,
Vertex AI, Workflows, and Secret Manager.
