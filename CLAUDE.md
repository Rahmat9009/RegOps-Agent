# CLAUDE.md — Frontend Agent Brief (Claude Code)

You are responsible **only for the frontend** of a hackathon project named **RegOps**.

## Hard boundaries
- You edit **`frontend/` only**. Do **not** modify `backend/`, `contracts/`, or `infrastructure/`.
- The API contract in `contracts/openapi.yaml` is **frozen**. Do **not** invent additional backend endpoints. If you need something the contract lacks, record it in `frontend/CONTRACT_REQUESTS.md` for Codex — do not add it yourself.
- Before starting, **inspect the existing repository and preserve any user changes.** Then produce a concise implementation plan and implement in **small, verified phases**.

## Stack & conventions
- **React + Vite + TypeScript.**
- **Framer Motion** only where motion improves comprehension.
- **Lucide** icons.
- **Accessible semantic HTML.** Every status carries **text + icon**, never color alone.
- All API access stays behind **`frontend/src/lib/api/`**. Build against the **typed mock adapter** already present there; it can later be replaced by the real backend **without changing components**. (Swap the adapter via the factory in `src/lib/api/index.ts`.)

## Required views
1. **Operations dashboard** — current run, pipeline state & progress, documents processed, findings by severity, pending approvals, completed actions, recovery/failure status.
2. **Regulation intake** — upload PDF, synthetic-demo disclosure, detected version/change result, start-analysis confirmation.
3. **Run detail** — visible processing stages, partition progress, timeline of agent decisions, recoverable-failure/retry state. **No fabricated reasoning or chain-of-thought** — show only real state transitions returned by the API.
4. **Findings** — search & filters; show evidence strength, source authority, interpretation confidence, operational severity, human-review requirement.
5. **Evidence detail** — regulation citation → extracted obligation → conflicting synthetic contract clause → affected worker case → proposed action → verifier verdict; full **clickable evidence chain**.
6. **Counterfactual preview** — findings before remediation, predicted-to-resolve, unchanged, new conflicts introduced, remaining high-risk cases. **Clearly label as a shadow-state simulation.**
7. **Approval screen** — proposed amendment, evidence, before/after comparison, approve & reject. **Never imply approval legally modifies a real contract** (it produces an `APPROVED_DRAFT` against a synthetic shadow copy).
8. **Audit report** — executed actions, idempotency results, revalidation outcome, processing time, evaluation metrics, download-audit-package control.

## Design direction
- A **serious operational-intelligence product**: evidence-first, calm, trustworthy.
- Avoid generic AI gradients, excessive glassmorphism, chatbot layouts.
- Desktop dashboard that stays **excellent on mobile**.
- Restrained color: neutral surfaces, **blue = information**, **amber = review**, **red = high severity**, **green only for verified completion**.
- Strong typography, clear hierarchy, polished **loading / empty / error / recovery** states.
- **Synthetic data only**, labeled visibly.

## Mock workflow to demonstrate
`upload → extracting → mapping → verifying → awaiting approval → counterfactual preview → approve → executing → revalidating → completed`
Use simple **polling** for progress: `GET /api/v1/runs/{run_id}` every 2s. No WebSockets.

## Definition of done (frontend)
- All 8 views implemented against the mock adapter, responsive, accessible.
- No component imports anything outside `src/lib/api/` for data.
- Swapping the adapter to the real client requires **no component changes**.
