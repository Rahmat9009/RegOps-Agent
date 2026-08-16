// mockAdapter.ts — In-memory RegOpsApi implementation used when VITE_API_MODE=mock.
//
// It drives the full demonstration workflow:
//   upload -> extracting -> mapping (with one recoverable partition failure)
//   -> verifying -> awaiting approval -> counterfactual preview
//   -> approve -> executing -> revalidating -> completed
//
// State advances on a wall clock so 2-second polling shows real movement, and the
// run registry is mirrored into sessionStorage so a page reload does not lose the
// demo. Every response conforms to contracts/openapi.yaml; every failure is a
// RegOpsApiError with the status the contract declares.

import type { ListFindingsParams, RegOpsApi } from "./client";
import { RegOpsApiError } from "./errors";
import type {
  ActionStatus,
  Approval,
  ApprovalDecision,
  AuditReport,
  CounterfactualPreview,
  CreateRunInput,
  Finding,
  FindingList,
  FindingSummary,
  HealthStatus,
  Run,
  RunState,
} from "./types";
import {
  amendmentAction,
  baseRun,
  findingSearchText,
  MOCK_AMENDMENT_ACTION_ID,
  MOCK_POST_APPROVAL_STATES,
  MOCK_PRE_APPROVAL_STATES,
  MOCK_PROGRESS_BY_STATE,
  mockAudit,
  mockCounterfactual,
  mockFindingDetail,
  mockFindingSummaries,
  pendingApproval,
  reviewTaskAction,
  type RunOutcome,
} from "./mockData";

/** Wall-clock time spent in each pipeline state. */
const STEP_MS = 2200;
/** Artificial latency, so loading states are real rather than theoretical. */
const LATENCY_MS = 140;

const STORAGE_KEY = "regops.mock.runs.v2";

type Phase = "pre_approval" | "post_approval";

interface RunRecord {
  run: Run;
  phase: Phase;
  /**
   * The recorded business outcome, or null while no decision has been made.
   * A rejection is a valid terminal outcome — the run still completes.
   */
  decision: RunOutcome | null;
  /** Epoch ms at which the current phase began. */
  phaseStartedAt: number;
  approvals: Record<string, Approval>;
}

export class MockRegOpsApi implements RegOpsApi {
  private records = new Map<string, RunRecord>();
  private sequence = 0;

  constructor() {
    this.restore();
  }

  async getHealth(): Promise<HealthStatus> {
    await delay();
    return { status: "ok", version: "0.1.0-mock" };
  }

  async createRun(input: CreateRunInput): Promise<Run> {
    await delay();

    if (!input.synthetic_ack) {
      throw new RegOpsApiError({
        code: "validation_error",
        message: "Confirm that the uploaded demonstration document is synthetic.",
        status: 422,
        details: [
          {
            location: ["body", "synthetic_ack"],
            message: "Input should be true",
            type: "value_error",
          },
        ],
      });
    }

    const file = input.regulation_file;
    const looksLikePdf =
      file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
    if (!looksLikePdf) {
      throw new RegOpsApiError({
        code: "validation_error",
        message: "regulation_file must be a PDF.",
        status: 422,
        details: [
          {
            location: ["body", "regulation_file"],
            message: "Expected content type application/pdf",
            type: "value_error",
          },
        ],
      });
    }

    const runId = `RUN-${String(++this.sequence).padStart(3, "0")}`;
    const createdAt = new Date().toISOString();
    const run = baseRun(runId, file.name, createdAt);

    this.records.set(runId, {
      run,
      phase: "pre_approval",
      decision: null,
      phaseStartedAt: Date.now(),
      approvals: {},
    });
    this.persist();
    return clone(run);
  }

  async getRun(runId: string): Promise<Run> {
    await delay();
    const record = this.mustGetRun(runId);
    this.advance(record);
    this.persist();
    return clone(record.run);
  }

  async listRunFindings(runId: string, params?: ListFindingsParams): Promise<FindingList> {
    await delay();
    const record = this.mustGetRun(runId);
    this.advance(record);

    // Findings only exist once mapping has produced candidates.
    if (!hasFindings(record.run.state)) {
      return { items: [], total: 0 };
    }

    let items: FindingSummary[] = mockFindingSummaries(runId).map((summary) =>
      this.applyOutcome(record, summary),
    );

    if (params?.severity) {
      items = items.filter((item) => item.severity === params.severity);
    }
    if (params?.q) {
      const needle = params.q.trim().toLowerCase();
      items = items.filter(
        (item) =>
          item.target_id.toLowerCase().includes(needle) ||
          findingSearchText(item.finding_id).includes(needle),
      );
    }

    return { items, total: items.length };
  }

  async getFinding(findingId: string): Promise<Finding> {
    await delay();

    for (const record of this.records.values()) {
      const detail = mockFindingDetail(record.run.run_id, findingId);
      if (!detail) continue;
      this.advance(record);
      const withOutcome: Finding = { ...detail, ...this.applyOutcome(record, detail) };
      if (withOutcome.proposed_action && detail.proposed_action) {
        withOutcome.proposed_action = {
          ...detail.proposed_action,
          status: this.actionStatus(record, detail.proposed_action.action_id),
        };
      }
      return clone(withOutcome);
    }

    throw notFound("finding", findingId);
  }

  async previewAction(actionId: string): Promise<CounterfactualPreview> {
    await delay();
    const record = this.findRecordForAction(actionId);
    if (!record || actionId !== MOCK_AMENDMENT_ACTION_ID) {
      throw notFound("action", actionId);
    }
    return clone(mockCounterfactual(actionId, record.run.run_id));
  }

  async decideApproval(approvalId: string, body: ApprovalDecision): Promise<Approval> {
    await delay();

    const record = [...this.records.values()].find(
      (candidate) =>
        candidate.approvals[approvalId] !== undefined ||
        candidate.run.pending_approvals?.some((a) => a.approval_id === approvalId),
    );
    if (!record) throw notFound("approval", approvalId);

    const existing = record.approvals[approvalId];
    if (existing && existing.status !== "PENDING") {
      throw new RegOpsApiError({
        code: "approval_already_decided",
        message: `Approval ${approvalId} was already ${existing.status.toLowerCase()}.`,
        status: 409,
      });
    }

    const pending = record.run.pending_approvals?.find((a) => a.approval_id === approvalId);
    const actionId = pending?.action_id ?? MOCK_AMENDMENT_ACTION_ID;

    const decision: Approval = {
      approval_id: approvalId,
      action_id: actionId,
      run_id: record.run.run_id,
      status: body.decision === "approve" ? "APPROVED" : "REJECTED",
      decided_at: new Date().toISOString(),
      // Backend-assigned reviewer identity. The frontend never submits this.
      decided_by: "demo-reviewer",
      note: body.note ?? null,
    };
    record.approvals[approvalId] = decision;
    record.run.pending_approvals = [];
    record.phaseStartedAt = Date.now();

    // Both outcomes let the run finish. A rejection is a decision, not a failure:
    // the automatic review task still executes and the run still reaches COMPLETED.
    // Only the amendment differs — rejected, and never executed.
    record.decision = body.decision === "approve" ? "approved" : "rejected";
    record.phase = "post_approval";
    this.applyState(record, "EXECUTING");

    this.persist();
    return clone(decision);
  }

  async getRunAudit(runId: string): Promise<AuditReport> {
    await delay();
    const record = this.mustGetRun(runId);
    this.advance(record);

    if (record.run.state !== "COMPLETED") {
      throw new RegOpsApiError({
        code: "audit_not_available",
        message: `Run ${runId} has no audit report yet (current state: ${record.run.state}).`,
        status: 404,
      });
    }
    return clone(mockAudit(runId, record.run.updated_at, record.decision ?? "approved"));
  }

  /* ---------------------------------------------------------------- internal */

  private mustGetRun(runId: string): RunRecord {
    const record = this.records.get(runId);
    if (!record) throw notFound("run", runId);
    return record;
  }

  private findRecordForAction(actionId: string): RunRecord | undefined {
    return [...this.records.values()].find((record) =>
      mockFindingSummaries(record.run.run_id).some(
        (summary) =>
          mockFindingDetail(record.run.run_id, summary.finding_id)?.proposed_action?.action_id ===
          actionId,
      ),
    );
  }

  /** Advance the run's state based on how long it has been in the current phase. */
  private advance(record: RunRecord): void {
    const script =
      record.phase === "pre_approval" ? MOCK_PRE_APPROVAL_STATES : MOCK_POST_APPROVAL_STATES;
    const elapsedSteps = Math.floor((Date.now() - record.phaseStartedAt) / STEP_MS);
    const index = Math.min(script.length - 1, Math.max(0, elapsedSteps));
    const nextState = script[index];

    if (nextState && nextState !== record.run.state) {
      this.applyState(record, nextState);
    }
  }

  private applyState(record: RunRecord, state: RunState): void {
    record.run.state = state;
    record.run.updated_at = new Date().toISOString();

    const progress = MOCK_PROGRESS_BY_STATE[state];
    if (progress) {
      record.run.progress = { ...record.run.progress, ...progress };
    }

    if (hasFindings(state)) {
      record.run.findings_by_severity = { low: 2, medium: 1, high: 1 };
    }

    if (state === "AWAITING_APPROVAL") {
      record.run.pending_approvals = [pendingApproval(record.run.run_id)];
    }

    if (state === "EXECUTING") {
      record.run.completed_actions = [reviewTaskAction(record.run.run_id, "EXECUTED")];
    }

    if (state === "COMPLETED") {
      // A rejected amendment was never executed, so it must not appear here.
      record.run.completed_actions =
        record.decision === "rejected"
          ? [reviewTaskAction(record.run.run_id, "EXECUTED")]
          : [
              amendmentAction(record.run.run_id, "APPROVED_DRAFT"),
              reviewTaskAction(record.run.run_id, "EXECUTED"),
            ];
    }
  }

  /** Reflect the approval outcome in the finding the amendment targets. */
  private applyOutcome(record: RunRecord, summary: FindingSummary): FindingSummary {
    if (summary.finding_id !== "FND-0001") return { ...summary };
    // Rejection leaves the conflict unaddressed: the finding stays OPEN.
    if (record.decision === "rejected") return { ...summary, status: "OPEN" };
    if (record.decision === "approved" && record.run.state === "COMPLETED") {
      return { ...summary, status: "RESOLVED" };
    }
    if (record.run.state === "AWAITING_APPROVAL") return { ...summary, status: "AWAITING_APPROVAL" };
    return { ...summary, status: "OPEN" };
  }

  private actionStatus(record: RunRecord, actionId: string): ActionStatus {
    if (actionId !== MOCK_AMENDMENT_ACTION_ID) {
      return record.run.state === "COMPLETED" || record.run.state === "EXECUTING"
        ? "EXECUTED"
        : "PENDING";
    }
    if (record.decision === "rejected") return "REJECTED";
    if (record.decision === "approved") {
      return record.run.state === "COMPLETED" ? "APPROVED_DRAFT" : "PENDING";
    }
    if (record.run.state === "AWAITING_APPROVAL") return "AWAITING_APPROVAL";
    return "PENDING";
  }

  /* ------------------------------------------------------------ persistence */

  private persist(): void {
    try {
      const payload = JSON.stringify({
        sequence: this.sequence,
        records: [...this.records.entries()].map(([id, record]) => [id, record]),
      });
      globalThis.sessionStorage?.setItem(STORAGE_KEY, payload);
    } catch {
      // Storage is a convenience for page reloads, never a correctness requirement.
    }
  }

  private restore(): void {
    try {
      const raw = globalThis.sessionStorage?.getItem(STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as {
        sequence?: number;
        records?: [string, RunRecord][];
      };
      this.sequence = parsed.sequence ?? 0;
      for (const [id, record] of parsed.records ?? []) {
        this.records.set(id, record);
      }
    } catch {
      // A malformed snapshot just means the demo starts fresh.
    }
  }
}

/* ------------------------------------------------------------------ helpers */

function hasFindings(state: RunState): boolean {
  const withFindings: RunState[] = [
    "MAPPED",
    "VERIFYING",
    "VERIFIED",
    "AWAITING_APPROVAL",
    "EXECUTING",
    "REVALIDATING",
    "COMPLETED",
    "FAILED",
  ];
  return withFindings.includes(state);
}

function notFound(resource: string, id: string): RegOpsApiError {
  return new RegOpsApiError({
    code: `${resource}_not_found`,
    message: `No ${resource} found with id ${id}.`,
    status: 404,
  });
}

function delay(ms = LATENCY_MS): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function clone<T>(value: T): T {
  return structuredClone(value);
}
