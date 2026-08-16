// client.ts — The API surface every component uses. Components import ONLY from
// `src/lib/api` (this interface + the factory in index.ts), never fetch directly.
// The mock adapter and the future real HTTP client both implement RegOpsApi, so
// swapping backends changes one line in index.ts and no component code.

import type {
  Run,
  CreateRunRequest,
  FindingsListResponse,
  Finding,
  Severity,
  CounterfactualPreview,
  Approval,
  ApprovalDecision,
  AuditReport,
  HealthStatus,
} from "./types";

export interface ListFindingsParams {
  severity?: Severity;
  q?: string;
}

export interface RegOpsApi {
  getHealth(): Promise<HealthStatus>;

  createRun(body: CreateRunRequest): Promise<Run>;
  getRun(runId: string): Promise<Run>;

  listRunFindings(runId: string, params?: ListFindingsParams): Promise<FindingsListResponse>;
  getFinding(findingId: string): Promise<Finding>;

  previewAction(actionId: string): Promise<CounterfactualPreview>;
  decideApproval(approvalId: string, body: ApprovalDecision): Promise<Approval>;

  getRunAudit(runId: string): Promise<AuditReport>;
}
