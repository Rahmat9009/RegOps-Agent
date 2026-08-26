// mockAdapter.ts — In-memory RegOpsApi implementation used when VITE_API_MODE=mock.
//
// It drives the full demonstration workflow:
//   upload -> extracting -> mapping (with one recoverable partition failure)
//   -> verifying -> awaiting approval -> counterfactual preview
//   -> approve -> executing -> revalidating -> completed
//   -> or reject -> completed (nothing executed, nothing revalidated)
//
// State advances on a wall clock so 2-second polling shows real movement, and the
// run registry is mirrored into sessionStorage so a page reload does not lose the
// demo. Every state change is appended to the run's authoritative `transitions`
// history. Every response conforms to contracts/openapi.yaml; every failure is a
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
  countBySeverity,
  findingSearchText,
  MOCK_POST_APPROVAL_STATES,
  MOCK_POST_REJECTION_STATES,
  MOCK_PRE_APPROVAL_STATES,
  MOCK_PROGRESS_BY_STATE,
  MOCK_REVIEWER_ACTOR,
  mockActionIds,
  mockAmendmentActionId,
  mockAmendmentFindingId,
  mockApprovalId,
  mockAudit,
  mockCounterfactual,
  mockFindingDetail,
  mockFindingIds,
  mockFindingsBySeverity,
  mockFindingSummaries,
  mockRecovery,
  mockResolvedFindingIds,
  mockTransition,
  pendingApproval,
  reviewTaskAction,
  type RunOutcome,
} from "./mockData";

/** Wall-clock time spent in each pipeline state. */
const STEP_MS = 2200;
/** Artificial latency, so loading states are real rather than theoretical. */
const LATENCY_MS = 140;

// v4: run-owned identifiers (findings, actions, approvals, shadow snapshots) are
// now globally unique and run-scoped. Snapshots written by an earlier version
// hold the old shared ids, are incompatible, and are discarded.
const STORAGE_KEY = "regops.mock.runs.v4";

/** Contract defaults and bounds for `GET /runs/{run_id}/findings`. */
const DEFAULT_LIMIT = 50;
const MAX_LIMIT = 100;

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
  /** How far the run has walked into the current phase's script. */
  scriptIndex: number;
  approvals: Record<string, Approval>;
}

export class MockRegOpsApi implements RegOpsApi {
  private records = new Map<string, RunRecord>();
  private sequence = 0;

  /**
   * Exact resource id -> owning run id. The contract's finding, action and
   * approval routes take no run id, so ownership is resolved through these
   * indexes: never by scanning runs, never by substring matching, and never by
   * assuming the most recent run.
   */
  private findingOwners = new Map<string, string>();
  private actionOwners = new Map<string, string>();
  private approvalOwners = new Map<string, string>();

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
      scriptIndex: 0,
      approvals: {},
    });
    this.indexRun(runId);
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

    const limit = clampLimit(params?.limit);
    const offset = clampOffset(params?.offset);

    // Findings only exist once mapping has produced candidates.
    if (!hasFindings(record.run.state)) {
      return { items: [], total: 0, limit, offset, by_severity: { low: 0, medium: 0, high: 0 } };
    }

    const resolvedIds = this.resolvedFindingIds(record);
    let matching: FindingSummary[] = mockFindingSummaries(runId).map((summary) =>
      this.applyOutcome(record, summary, resolvedIds),
    );

    if (params?.severity) {
      matching = matching.filter((item) => item.severity === params.severity);
    }
    if (params?.q) {
      const needle = params.q.trim().toLowerCase();
      matching = matching.filter(
        (item) =>
          item.target_id.toLowerCase().includes(needle) ||
          findingSearchText(runId, item.finding_id).includes(needle),
      );
    }

    // `total` and `by_severity` describe the complete filtered result; `items` is
    // only the requested page of it.
    return {
      items: clone(matching.slice(offset, offset + limit)),
      total: matching.length,
      limit,
      offset,
      by_severity: countBySeverity(matching.map((item) => item.severity)),
    };
  }

  async getFinding(findingId: string): Promise<Finding> {
    await delay();

    // The finding id names exactly one run. A finding belonging to another run is
    // a 404 here, never this run's record at the same corpus position.
    const record = this.ownerOf(this.findingOwners, findingId);
    const detail = record ? mockFindingDetail(record.run.run_id, findingId) : undefined;
    if (!record || !detail) throw notFound("finding", findingId);

    this.advance(record);
    const withOutcome: Finding = {
      ...detail,
      ...this.applyOutcome(record, detail, this.resolvedFindingIds(record)),
    };
    if (withOutcome.proposed_action && detail.proposed_action) {
      withOutcome.proposed_action = {
        ...detail.proposed_action,
        status: this.actionStatus(record, detail.proposed_action.action_id),
      };
    }
    return clone(withOutcome);
  }

  async previewAction(actionId: string): Promise<CounterfactualPreview> {
    await delay();
    // The owning run is resolved exactly, so an older run's action keeps
    // previewing that run even after a newer run exists.
    const record = this.ownerOf(this.actionOwners, actionId);
    // Only the approval-required amendment has a counterfactual preview.
    if (!record || actionId !== mockAmendmentActionId(record.run.run_id)) {
      throw notFound("action", actionId);
    }
    return clone(mockCounterfactual(actionId, record.run.run_id));
  }

  async decideApproval(approvalId: string, body: ApprovalDecision): Promise<Approval> {
    await delay();

    // Exactly one run owns this approval id; deciding it can never touch another.
    const record = this.ownerOf(this.approvalOwners, approvalId);
    if (!record) throw notFound("approval", approvalId);
    // Bring the run up to the state its wall clock implies, so the pending list
    // this decision is checked against is current.
    this.advance(record);

    const existing = record.approvals[approvalId];
    if (existing && existing.status !== "PENDING") {
      throw new RegOpsApiError({
        code: "approval_already_decided",
        message: `Approval ${approvalId} was already ${existing.status.toLowerCase()}.`,
        status: 409,
      });
    }

    // The action and the finding come from the pending record itself. If the run
    // is not actually waiting on this decision there is no relationship to
    // record, and the mock fails closed rather than inventing one.
    const pending = record.run.pending_approvals?.find((a) => a.approval_id === approvalId);
    if (!pending) throw notFound("approval", approvalId);

    const approved = body.decision === "approve";
    const decidedAt = new Date().toISOString();

    const decision: Approval = {
      approval_id: approvalId,
      action_id: pending.action_id,
      run_id: record.run.run_id,
      finding_id: pending.finding_id,
      status: approved ? "APPROVED" : "REJECTED",
      decided_at: decidedAt,
      // Backend-assigned reviewer identity. The frontend never submits this.
      decided_by: MOCK_REVIEWER_ACTOR,
      note: body.note ?? null,
    };
    record.approvals[approvalId] = decision;
    record.run.pending_approvals = [];

    // Both outcomes let the run finish. Approval executes the amendment and then
    // revalidates; rejection executes nothing, so the run goes straight to
    // COMPLETED without passing through EXECUTING or REVALIDATING. Neither
    // outcome is a failure.
    record.decision = approved ? "approved" : "rejected";
    record.phase = "post_approval";
    record.phaseStartedAt = Date.now();
    record.scriptIndex = 0;

    const script = this.scriptFor(record);
    const firstState = script[0] as RunState;
    this.applyState(record, firstState, decidedAt, {
      actor: MOCK_REVIEWER_ACTOR,
      reason: approved
        ? "Reviewer approved the proposed amendment."
        : "Reviewer rejected the proposed amendment; nothing was executed.",
    });

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

  /** The run that owns `id` according to an exact index, or undefined. */
  private ownerOf(index: Map<string, string>, id: string): RunRecord | undefined {
    const runId = index.get(id);
    return runId === undefined ? undefined : this.records.get(runId);
  }

  /** Record every id this run owns, so a lookup never has to guess. */
  private indexRun(runId: string): void {
    for (const findingId of mockFindingIds(runId)) this.findingOwners.set(findingId, runId);
    for (const actionId of mockActionIds(runId)) this.actionOwners.set(actionId, runId);
    this.approvalOwners.set(mockApprovalId(runId), runId);
  }

  /** The run-scoped findings this run's approved amendment resolves. */
  private resolvedFindingIds(record: RunRecord): Set<string> {
    return new Set(mockResolvedFindingIds(record.run.run_id));
  }

  private scriptFor(record: RunRecord): RunState[] {
    if (record.phase === "pre_approval") return MOCK_PRE_APPROVAL_STATES;
    return record.decision === "rejected" ? MOCK_POST_REJECTION_STATES : MOCK_POST_APPROVAL_STATES;
  }

  /**
   * Advance the run to the state its elapsed wall-clock time implies, applying
   * every intermediate state on the way. Steps are never skipped: the transition
   * history is the authoritative record and must stay complete even if no browser
   * tab was open while the run moved.
   */
  private advance(record: RunRecord): void {
    const script = this.scriptFor(record);
    const elapsedSteps = Math.floor((Date.now() - record.phaseStartedAt) / STEP_MS);
    const target = Math.min(script.length - 1, Math.max(0, elapsedSteps));

    while (record.scriptIndex < target) {
      record.scriptIndex += 1;
      const state = script[record.scriptIndex] as RunState;
      const occurredAt = new Date(record.phaseStartedAt + record.scriptIndex * STEP_MS).toISOString();
      const resumed = script[record.scriptIndex - 1] === "FAILED_RECOVERABLE";
      this.applyState(
        record,
        state,
        occurredAt,
        resumed ? { reason: "Resumed from the last checkpoint." } : {},
      );
    }
  }

  private applyState(
    record: RunRecord,
    state: RunState,
    occurredAt: string,
    transition: { actor?: string; reason?: string } = {},
  ): void {
    const previous = record.run.state;
    record.run.state = state;
    record.run.updated_at = occurredAt;
    record.run.transitions = [
      ...record.run.transitions,
      mockTransition(previous, state, occurredAt, transition),
    ];

    const progress = MOCK_PROGRESS_BY_STATE[state];
    if (progress) {
      record.run.progress = { ...record.run.progress, ...progress };
    }

    if (state === "FAILED_RECOVERABLE") {
      record.run.recovery = mockRecovery(true);
    } else if (previous === "FAILED_RECOVERABLE") {
      // The retry succeeded: the checkpoint and attempt count stay visible, but
      // no recovery is outstanding any more.
      record.run.recovery = mockRecovery(false);
    }

    if (hasFindings(state)) {
      record.run.findings_by_severity = mockFindingsBySeverity();
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

  /** Reflect the approval outcome in the findings the amendment covers. */
  private applyOutcome(
    record: RunRecord,
    summary: FindingSummary,
    resolvedIds: Set<string>,
  ): FindingSummary {
    const isAmendmentTarget = summary.finding_id === mockAmendmentFindingId(record.run.run_id);

    if (
      record.decision === "approved" &&
      record.run.state === "COMPLETED" &&
      resolvedIds.has(summary.finding_id)
    ) {
      // Revalidation confirmed these are no longer detected.
      return { ...summary, status: "RESOLVED" };
    }

    if (!isAmendmentTarget) return { ...summary };
    // Rejection leaves the conflict unaddressed: the finding stays OPEN.
    if (record.decision === "rejected") return { ...summary, status: "OPEN" };
    if (record.run.state === "AWAITING_APPROVAL") return { ...summary, status: "AWAITING_APPROVAL" };
    return { ...summary, status: "OPEN" };
  }

  private actionStatus(record: RunRecord, actionId: string): ActionStatus {
    if (actionId !== mockAmendmentActionId(record.run.run_id)) {
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
        // Ownership follows from the run id, so the index is rebuilt rather than
        // persisted.
        this.indexRun(id);
      }
    } catch {
      // A malformed snapshot just means the demo starts fresh.
    }
  }
}

/* ------------------------------------------------------------------ helpers */

function clampLimit(value: number | null | undefined): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return DEFAULT_LIMIT;
  return Math.min(MAX_LIMIT, Math.max(1, Math.trunc(value)));
}

function clampOffset(value: number | null | undefined): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return 0;
  return Math.max(0, Math.trunc(value));
}

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
