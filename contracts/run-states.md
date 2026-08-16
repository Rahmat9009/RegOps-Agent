# Run states (frozen)

Polling model: the frontend calls `GET /api/v1/runs/{run_id}` every 2 seconds. No WebSockets.

| State | Meaning | Frontend treatment |
|---|---|---|
| `INGESTED` | Regulation received; run created | Info (blue) |
| `EXTRACTING` | Regulation Analyst extracting obligations | In-progress |
| `EXTRACTED` | Obligations + citations ready | In-progress |
| `MAPPING` | Impact Investigator matching corpus | In-progress + partition progress |
| `MAPPED` | Candidate findings produced | In-progress |
| `VERIFYING` | Internal refutation pass running | In-progress |
| `VERIFIED` | Findings carry survived/refuted/uncertain | In-progress |
| `AWAITING_APPROVAL` | A consequential action is paused for human decision | Review (amber); show approval + counterfactual |
| `EXECUTING` | Approved/auto actions executing | In-progress |
| `REVALIDATING` | Rerunning pipeline to confirm resolution | In-progress |
| `COMPLETED` | Run finished; audit available | Verified complete (green) |
| `FAILED_RECOVERABLE` | A partition failed; retry/resume in progress | Recovery (amber/red) with retry state |
| `FAILED` | Unrecoverable failure | Error (red) |

Terminal states: `COMPLETED`, `FAILED`. `FAILED_RECOVERABLE` is transient and should resolve to a later state after retry.

Color + text + icon are all required for each state — never color alone.

## Approval rejection

Reviewer rejection is an expected business decision, not a system failure. A rejected
proposed amendment becomes `REJECTED`, is never executed, and is excluded from both
`Run.completed_actions` and `AuditReport.executed_actions`. The affected finding stays
`OPEN` unless another action independently resolves it.

When no other work remains, rejection may take the run directly from
`AWAITING_APPROVAL` to `COMPLETED`. It must not be forced through `EXECUTING` or
`REVALIDATING`, and rejection alone must never transition the run to `FAILED`.

`Run.transitions` is the authoritative server-recorded history, ordered oldest to
newest. Its reason and actor fields contain safe labels only—never prompts, stack
traces, credentials, tokens, or sensitive infrastructure detail.
