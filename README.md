# RegOps — From Rule Change to Resolved Action

**All Things Agentic Hackathon · Taskmaster track**

RegOps is an event-driven compliance-operations agent. It detects an official rule change, finds the recruitment contracts and worker cases it potentially conflicts with, drafts evidence-backed remediation, pauses consequential changes for human approval, and verifies that approved remediation was applied to the records it detected — with a clickable evidence chain behind every decision.

> **Scope note.** RegOps *identifies potential conflicts* and *supports compliance review*. It does **not** determine legality or guarantee legal compliance. It verifies that an approved amendment resolved *its own detected finding*. All contracts and cases in this project are **synthetic** and labeled as such.

---

## This is one monorepo (by design)

Judges should see a single reproducible system, not scattered repos. Two AI agents build in parallel under strict ownership boundaries, and they may only work in parallel **after the API contract in `contracts/` is frozen** (it is — see below).

```
regops/
├── frontend/          # Claude Code owns  — React interface, mock adapter, all views
├── backend/           # Codex owns        — Python 3.12 FastAPI service
├── contracts/         # Codex maintains   — FROZEN API contract (source of truth)
├── infrastructure/    # Codex owns        — Cloud Run, Jobs, Workflows, IaC
├── docs/              # Shared            — architecture & submission material
├── README.md
├── CLAUDE.md          # Frontend agent brief + boundary rules
└── AGENTS.md          # Backend agent brief + boundary rules
```

### Ownership boundaries (hard rules)
- **Claude Code** edits `frontend/` only. Must not touch `backend/`, `contracts/`, or `infrastructure/`.
- **Codex** edits `backend/`, `contracts/`, `infrastructure/`. Must not touch `frontend/`.
- The API contract (`contracts/openapi.yaml`) is the **integration boundary**. It is frozen. Changes are made by Codex and announced; the frontend rebuilds its mock adapter to match.

---

## Getting started

**Frontend (Claude Code):**
```bash
cd frontend
# Claude Code scaffolds the Vite app around src/lib/api/ (the frozen adapter)
npm install && npm run dev
```
The frontend runs entirely against a **typed mock adapter** (`frontend/src/lib/api/`) until the backend is live. Swapping to the real backend changes one factory call, not the components.

**Backend (Codex, Python 3.12):**
```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m mypy
```

Phase 1 runs the one-document workflow in one Cloud Run service process. Cloud Run
Jobs and Pub/Sub begin in Phase 2.

---

## Reproducibility for judges
- One `git clone` yields the whole system.
- `docs/` contains the architecture diagram, frozen spec, and the integrity disclosure.
- Synthetic data only, visibly labeled.
