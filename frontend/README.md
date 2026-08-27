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

## Design system

`styles/tokens.css` is the single source for colour, type, space, elevation and
motion. Nothing else defines a raw colour or duration.

**Brand.** A deep navy console chrome (`--chrome*`) over a cool slate canvas. The
mark in `components/Logo.tsx` is an R whose leg is an evidence chain ending in one
solid node — the decision. It is the only solid element, it is drawn from
`currentColor` so it works on navy, light and dark, and `public/favicon.svg` is the
same geometry on a tile.

**Colour.** Blue = information / active workflow, teal = verified completion only,
amber = awaiting review and recovery, coral = rejected / failed / high severity,
violet = the model boundary. Violet is *not* a status: it marks shadow-state
simulation and model-written narrative, and always sits next to a label saying so.
Colour never carries meaning alone — every status is icon + text + colour.

**Type.** Inter Tight for display, Inter for body, JetBrains Mono for identifiers,
timestamps, counters and eyebrows. All three fall back to full system stacks, so
the console renders correctly with no network. The mono uppercase eyebrow is the
structural voice: it labels sections, table headings and definition-list terms.

**Motion.** `--dur-fast` 160 ms for interaction, `--dur` 200 ms, `--dur-slow` 280 ms
for panels, `--dur-page` 320 ms for the route entrance, all on `--ease`. Motion is
only ever used to show that something changed: progress moving between polls, a
newly recorded transition arriving, a stage activating. There are no decorative
loops. Every animation stops under `prefers-reduced-motion`, and `PageTransition`
renders a plain element rather than a fast one.

**The rail.** The signature device is a hairline track with nodes on it, used for
the run lifecycle (`components/PipelineMap.tsx`), the recorded transition history
and the evidence chain. It turns from horizontal to vertical below 1280px.

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
  lib/approvalDecision.ts  when a human decision may be recorded (pure)
  lib/presentation.ts  enum -> { label, icon, tone } for every status
  lib/pagination.ts    findings filter + page state (pure, testable)
  lib/format.ts        display formatting
  lib/url.ts           audit-package URL safety check
  lib/activeRun.ts     which run this browser is looking at (browser state)
  hooks/               useAsync, useRunPolling (2 s polling), useRunPresence
  components/          shell, logo, panels, badges, meters, rail, states
  routes/              one file per view
  styles/              tokens.css (design system), base.css (reset + a11y), app.css
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
- Rejection is a business decision, not a failure: the amendment becomes `REJECTED` and
  is never executed, the finding stays `OPEN`, and the run completes directly from
  `AWAITING_APPROVAL` without `EXECUTING` or `REVALIDATING`.
- Run history comes from `Run.transitions`, the authoritative server-recorded array.
  The client records no history of its own and displays no agent reasoning.
- Every mock identifier a run owns — findings, actions, approvals, shadow snapshots —
  is globally unique and run-scoped (`RUN-001-FND-0001`). The contract's finding,
  action and approval routes carry no run id, so a link saved from one run must never
  resolve against another. Evidence document ids (regulation, contract, policy, case)
  stay shared: they are the same synthetic corpus records for every run.
- A decision is never recorded against evidence that failed to load. Approve requires
  the exact bound finding, its proposed action and the counterfactual preview; reject
  requires the binding and its evidence only, because it executes nothing. The rule
  lives in `lib/approvalDecision.ts` and gates the submit path, not just the buttons.
