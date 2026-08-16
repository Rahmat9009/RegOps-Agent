# frontend/ — owned by Claude Code

React + Vite + TypeScript UI for RegOps. See root `CLAUDE.md` for the full brief, the 8 required views, and the design direction.

## What's already here (do not fight it — build on it)
- **`src/lib/api/`** — the frozen, typed API layer. All data access goes through it.
  - `types.ts` — types mirrored from `contracts/openapi.yaml` (frozen).
  - `client.ts` — the `RegOpsApi` interface every component depends on.
  - `mockAdapter.ts` — in-memory implementation that drives the full demo workflow.
  - `mockData.ts` — synthetic Bangladesh fee-rule fixtures (labeled synthetic).
  - `index.ts` — exports `api` (the singleton) and everything components need.

Usage in a component:
```ts
import { api, type Run } from "@/lib/api";
const run = await api.getRun(runId); // poll every 2s for progress
```

## Your job
1. Scaffold the Vite app around `src/lib/api/` (add `package.json`, `vite.config.ts`, `tsconfig.json`, `index.html`, `src/main.tsx`, routing, components).
2. Build the 8 views (root `CLAUDE.md`) against `api`.
3. Keep **all** data access behind `src/lib/api/`. No `fetch` in components.
4. Framer Motion only where motion aids comprehension; Lucide icons; accessible semantic HTML; status = text + icon + color (never color alone).

## Rules
- Do not modify `backend/`, `contracts/`, or `infrastructure/`.
- Do not invent endpoints beyond `contracts/openapi.yaml`. Need something more? Add a line to `docs/frontend-notes.md` for Codex.
- Switching to the real backend later = implement `HttpRegOpsApi` and flip `USE_REAL_API` in `index.ts`. Components must not change.
