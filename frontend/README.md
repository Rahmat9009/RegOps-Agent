# frontend/ — RegOps console (owned by Claude Code)

React + Vite + TypeScript UI for RegOps. See root `CLAUDE.md` for the brief, the eight
required views, and the design direction.

## Getting started

```bash
npm install
npm run dev
```

The app runs against the **mock adapter** by default — no backend required.

| Script              | What it does                                        |
| ------------------- | --------------------------------------------------- |
| `npm run dev`       | Vite dev server on http://localhost:5173             |
| `npm run build`     | Typecheck, then production build into `dist/`        |
| `npm run typecheck` | `tsc --noEmit` over `src/` and the Node-side configs |
| `npm run lint`      | ESLint (flat config, typescript-eslint)              |
| `npm test`          | Vitest, single run (`test:watch` for watch mode)     |
| `npm run preview`   | Serve the built `dist/`                              |

Tests cover the API layer and pure helpers (`src/**/*.test.ts`) and run in a `node`
environment — no DOM, no component rendering.

TypeScript runs in `strict` mode with `noUnusedLocals`, `noUnusedParameters`,
`noFallthroughCasesInSwitch`, `noImplicitOverride` and `verbatimModuleSyntax`.

## Choosing an adapter

`src/lib/api/index.ts` picks the adapter from an environment variable. Copy
`.env.example` to `.env.local` to change it.

```
VITE_API_MODE=mock          # in-memory workflow (default)
VITE_API_MODE=http          # real HTTP client
VITE_API_BASE_URL=/api/v1   # base path for http mode
```

In dev, `/api` is proxied to `http://localhost:8080` (override with the
`REGOPS_API_PROXY` environment variable). Switching adapters requires **no component
changes** — both implement the same `RegOpsApi` interface.

## Layout

```
src/
  lib/api/          the only place data comes from
    types.ts        hand-mirrored from contracts/openapi.yaml (frozen)
    client.ts       RegOpsApi — one method per operationId
    errors.ts       RegOpsApiError; every adapter throws this
    httpAdapter.ts  real fetch client (multipart POST /runs)
    mockAdapter.ts  in-memory workflow driver
    mockData.ts     synthetic fixtures
    index.ts        adapter factory + the `api` singleton
  lib/presentation.ts  enum -> { label, icon, tone } for every status
  lib/format.ts        display formatting
  lib/activeRun.ts     which run this browser is looking at (browser state)
  hooks/               useAsync, useRunPolling (2 s polling)
  components/          shell, panels, badges, meters, loading/empty/error states
  routes/              one file per view
  styles/              tokens.css, base.css, app.css
```

## Screens

| Route                      | View                             |
| -------------------------- | -------------------------------- |
| `/`                        | Operations dashboard             |
| `/intake`                  | Regulation intake                |
| `/runs/:runId`             | Run detail                       |
| `/runs/:runId/findings`    | Findings list                    |
| `/findings/:findingId`     | Evidence detail (evidence chain) |
| `/actions/:actionId/preview` | Counterfactual shadow-state preview |
| `/approvals/:approvalId?run=` | Approval decision             |
| `/runs/:runId/audit`       | Audit report                     |

## Rules

- Do not modify `backend/`, `contracts/`, `infrastructure/`, `docs/`, or root files.
- Do not invent endpoints beyond `contracts/openapi.yaml`. Gaps go in
  `frontend/CONTRACT_REQUESTS.md` for Codex.
- No `fetch` in components — all data access goes through `src/lib/api/`.
- Every status is **icon + text + colour**; colour never carries meaning alone.
- The frontend never submits `decided_by`. Reviewer identity is backend-assigned.
- Approval produces an `APPROVED_DRAFT` against a synthetic contract's **shadow copy**.
  Nothing in this UI may imply a real contract was modified or that legal compliance
  was determined.
