# RegOps backend

Python 3.12 FastAPI implementation of `contracts/openapi.yaml` plus the Phase 1A
domain and orchestration foundation for the one-document path. Phase 1A includes
strict role outputs, explicit run transitions and checkpoints, repository ports, an
opt-in non-production in-memory adapter, allowlisted idempotent actions, backend-owned
approval identity, deterministic shadow-state revalidation, and auditable events.

The six later-workflow HTTP operations remain contract-visible structured `501`
boundaries until real Phase 1 integrations are wired. Gemini/Vertex, Google ADK,
Firestore, Cloud Storage, and Google Workflows are represented by interfaces only.
Runtime placeholders fail clearly and never fabricate obligations or findings.

## Clean setup and checks (PowerShell)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements-dev.lock
.venv\Scripts\python -m pip install --no-deps -e .
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m mypy
.venv\Scripts\openapi-spec-validator ..\contracts\openapi.yaml
.venv\Scripts\python scripts\compare_openapi.py
```

Run locally with `.venv\Scripts\regops-api` or build `Dockerfile` for Cloud Run.
Phase 1 remains a single-process service. Cloud Run Jobs and Pub/Sub begin in Phase 2.
