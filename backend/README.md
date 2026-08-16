# RegOps backend

Minimal Python 3.12 FastAPI implementation of `contracts/openapi.yaml`. Phase 0
implements health and multipart PDF intake. The six later-workflow endpoints are
contract-visible structured `501` stubs; no Gemini, ADK, Firestore, or business
workflow is implemented here.

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
