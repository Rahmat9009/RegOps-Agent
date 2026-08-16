# Contract requests — frontend → Codex

Gaps found while building the frontend against `contracts/openapi.yaml`. The frontend
has **not** changed the contract and does **not** call anything not declared there. Each
item below records what the UI needs, why, and the workaround shipped in the meantime.

Status legend: `OPEN` = awaiting Codex decision · `WORKED-AROUND` = UI ships without it.

---

## CR-001 — Run listing / "most recent run" lookup — `WORKED-AROUND`

**Need.** The operations dashboard opens on "the current run". The contract has no
`GET /runs` (list) and no "latest run" lookup, so there is no way to find a run
without already holding its `run_id`.

**Workaround.** The frontend stores the most recently created `run_id` in
`localStorage` and calls `GET /runs/{run_id}`. A browser with cleared storage sees an
empty state that routes to regulation intake.

**Requested.** `GET /api/v1/runs` returning `{ items: Run[], total: int }`, ideally with
`limit` and `state` query parameters.

---

## CR-002 — Run state-transition history (timeline) — `WORKED-AROUND`

**Need.** Run detail must show "visible processing stages" and a timeline of state
transitions with timestamps. `Run` exposes only the *current* `state` plus
`created_at` / `updated_at`, so history is not retrievable.

**Workaround.** The run detail screen records transitions it observes **itself** while
polling, and labels the list explicitly as client-observed. Transitions that happen
while no browser tab is open are therefore missing, and a page reload starts the
observed history over. No reasoning or chain-of-thought is fabricated — only observed
state values and the wall-clock time they were first seen.

**Requested.** Either a `transitions: [{ state, occurred_at }]` array on `Run`, or
`GET /api/v1/runs/{run_id}/transitions`. Server-recorded state values only — the UI
does not want, and will not display, agent reasoning text.

---

## CR-003 — Recoverable-failure detail — `WORKED-AROUND`

**Need.** `run-states.md` says `FAILED_RECOVERABLE` should be shown "with retry
state". The contract has the enum value but no accompanying detail: which partition
failed, retry count, and whether a checkpoint resume occurred are not exposed.

**Workaround.** The UI renders a recovery panel keyed off `state === "FAILED_RECOVERABLE"`
alone, showing the generic recovery message plus the partition counters already present
in `RunProgress`. Retry count and failed-partition index are not shown, because the
frontend does not have them and will not invent them.

**Requested.** An optional `recovery: { failed_partition, retry_count, resumed_from_checkpoint } | null`
on `Run`.

---

## CR-004 — Change / version detection result — `WORKED-AROUND`

**Need.** The regulation intake screen is specified to show the "detected
version/change result" (new document vs. new version vs. duplicate, and what it
supersedes). `Regulation` carries `reg_id`, `title`, `jurisdiction`,
`source_filename`, `synthetic` — no change-detection outcome.

**Workaround.** Intake confirms the accepted run using only contract fields
(`run_id`, `state`, `regulation`). The change-detection section states plainly that the
result is not yet reported by the API rather than showing a placeholder value.

**Requested.** An optional `change_detection: { result: "new" | "new_version" | "duplicate",
content_hash, supersedes: string | null, version: int } | null` on `Regulation` or `Run`.

---

## CR-005 — Approval lookup by id — `WORKED-AROUND`

**Need.** The approval screen is reachable by URL (`/approvals/{approval_id}`). There
is no `GET /approvals/{approval_id}`; the only way to read an approval is to find it
inside `Run.pending_approvals`, and decided approvals disappear from that array.

**Workaround.** The approval screen requires a `run` query parameter and locates the
approval inside `GET /runs/{run_id}`. After a decision it renders the `Approval`
returned by `POST /approvals/{approval_id}/decision`; a hard reload after deciding
shows a "no longer pending" state rather than the decision record.

**Requested.** `GET /api/v1/approvals/{approval_id}` returning `Approval`.

---

## CR-006 — Audit package download — `WORKED-AROUND`

**Need.** The audit view specifies a "download audit package" control.
`AuditReport.audit_package_url` exists but is nullable and undocumented as to
whether it is a signed URL, a relative API path, or a GCS URI.

**Workaround.** The download control is rendered enabled only when
`audit_package_url` is a non-null string, and disabled with an explanatory message
otherwise. The frontend treats the value as an opaque URL and does not construct one.

**Requested.** Documentation of the value's form (signed HTTPS URL preferred), or a
dedicated `GET /api/v1/runs/{run_id}/audit/package` endpoint.

---

## CR-007 — Scores on `FindingSummary` — `WORKED-AROUND`

**Need.** The findings list is specified to show evidence strength, source authority,
interpretation confidence, operational severity and the human-review requirement.
`FindingSummary` carries `severity` and `human_review_required`; the other three live
on `FindingScores`, which only `Finding` exposes.

**Workaround.** The list calls `GET /findings/{finding_id}` once per listed row to
hydrate the score set. That is an N+1 request pattern and will not survive a realistic
finding count.

**Requested.** Add `scores: FindingScores` to `FindingSummary`, or a
`?include=scores` query parameter on `GET /runs/{run_id}/findings`.

---

## CR-008 — Action → finding lookup — `WORKED-AROUND`

**Need.** The approval screen receives an `action_id` from `Run.pending_approvals`
and must show the finding that action came from (its obligation, evidence and target).
There is no `GET /actions/{action_id}`, and `ProposedAction` is only reachable by
first fetching the finding that owns it.

**Workaround.** The approval screen lists the run's findings and fetches each one until
it finds the matching `proposed_action.action_id`. This is O(findings) requests per
approval screen load.

**Requested.** `GET /api/v1/actions/{action_id}` returning `ProposedAction`, ideally
with the owning `finding_id` resolvable in one call.

---

## CR-009 — Findings pagination — `OPEN`

**Need.** `GET /runs/{run_id}/findings` returns `{ items, total }` with no `limit` /
`offset`. A run over a 300-document corpus can produce far more findings than one
response should carry, and the UI has no way to page.

**Workaround.** None needed yet at demo scale; the list renders `items` in full.

**Requested.** `limit` and `offset` query parameters, with `total` continuing to mean
the unpaged count.
