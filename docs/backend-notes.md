# Backend contract notes

## 2026-08-16 — deliberate Phase 0 contract repair

`contracts/openapi.yaml` was upgraded from OpenAPI 3.0.3 to 3.1.0 while retaining
exactly eight paths and all 13 run states.

Contract-breaking integration changes for the frontend adapter:

- `POST /runs` now accepts only `multipart/form-data` with required binary PDF field
  `regulation_file` and required boolean field `synthetic_ack`; it returns `202` and a
  `Run`. The former JSON body and `201` response were removed. No upload endpoint exists.
- `Error` is replaced by structured `APIError` (`code`, `message`, optional `details`).
- `Evidence`, `Scores`, and `ActionSummary` are renamed `EvidenceReference`,
  `FindingScores`, and `ProposedAction`.
- `Regulation` and `Obligation` are now explicit reusable schemas. `Run.regulation`
  references `Regulation`; `Finding.obligation` references `Obligation`.
- `CounterfactualPreview` now uses `action_id`, `shadow_run_id`,
  `baseline_finding_count`, `resolved_finding_ids`, `unchanged_finding_ids`,
  `new_conflict_ids`, `remaining_high_risk_ids`,
  `detected_finding_picture_improves`, and optional `narrative`.
- `ApprovalDecision` contains only `decision` and optional `note`. It rejects
  `decided_by` and every other unknown field. Reviewer identity is backend-controlled:
  the unauthenticated synthetic demo assigns `Approval.decided_by` to
  `"demo-reviewer"`. The frontend must never submit or select reviewer identity.
  `Approval` remains the reusable response representation and retains `decided_by`.
- `Run` now requires `updated_at`, `progress`, and `regulation.source_filename`.

The six business-workflow operations are declared but return structured `501` errors
during Phase 0. Claude remains responsible for applying these changes only within
`frontend/`.
