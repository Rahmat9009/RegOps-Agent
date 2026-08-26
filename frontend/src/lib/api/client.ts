// client.ts — The API surface every component uses. Components import ONLY from
// `src/lib/api` (this interface + the factory in index.ts), never fetch directly.
// The mock adapter and the real HTTP client both implement RegOpsApi, so swapping
// backends is an environment variable, not a component change.
//
// One method per operationId in contracts/openapi.yaml. Nothing else.

import type {
  Approval,
  ApprovalDecision,
  AuditReport,
  CounterfactualPreview,
  CreateRunInput,
  Finding,
  FindingList,
  HealthStatus,
  Run,
  Severity,
} from "./types";

/** Query parameters for `GET /runs/{run_id}/findings`. */
export interface ListFindingsParams {
  severity?: Severity | null;
  /** Free-text search over target and obligation text. */
  q?: string | null;
  /** Page size. Contract default 50, range 1–100. */
  limit?: number | null;
  /** Zero-based offset into the filtered result. Contract default 0. */
  offset?: number | null;
}

export interface RegOpsApi {
  /** getHealth — GET /health */
  getHealth(): Promise<HealthStatus>;

  /** createRun — POST /runs (multipart/form-data) */
  createRun(input: CreateRunInput): Promise<Run>;

  /** getRun — GET /runs/{run_id} */
  getRun(runId: string): Promise<Run>;

  /** listRunFindings — GET /runs/{run_id}/findings */
  listRunFindings(runId: string, params?: ListFindingsParams): Promise<FindingList>;

  /** getFinding — GET /findings/{finding_id} */
  getFinding(findingId: string): Promise<Finding>;

  /** previewAction — POST /actions/{action_id}/preview */
  previewAction(actionId: string): Promise<CounterfactualPreview>;

  /**
   * decideApproval — POST /approvals/{approval_id}/decision
   *
   * `body` carries the decision and an optional note only. Reviewer identity
   * (`decided_by`) is assigned by the backend and is never sent from here.
   */
  decideApproval(approvalId: string, body: ApprovalDecision): Promise<Approval>;

  /** getRunAudit — GET /runs/{run_id}/audit */
  getRunAudit(runId: string): Promise<AuditReport>;
}
