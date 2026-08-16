// mockAdapter.ts — In-memory RegOpsApi implementation. Drives a realistic workflow:
// upload -> extracting -> mapping -> verifying -> awaiting approval ->
// (approve) -> executing -> revalidating -> completed.
//
// State advances on a wall-clock timer so the dashboard's 2s polling shows motion.
// Approval is required to move past AWAITING_APPROVAL, mirroring the real backend.

import type { RegOpsApi, ListFindingsParams } from "./client";
import type {
  Run,
  RunState,
  CreateRunRequest,
  FindingsListResponse,
  Finding,
  CounterfactualPreview,
  Approval,
  ApprovalDecision,
  AuditReport,
  HealthStatus,
} from "./types";
import {
  baseRun,
  MOCK_RUN_SEQUENCE,
  MOCK_FINDING_SUMMARIES,
  MOCK_FINDING_DETAIL,
  MOCK_COUNTERFACTUAL,
  mockAudit,
} from "./mockData";

interface RunClock {
  run: Run;
  startedAt: number;
  approved: boolean;
  approvals: Record<string, Approval>;
}

const STEP_MS = 1500; // time spent in each pre-approval state

function nowIso() {
  return new Date().toISOString();
}

export class MockRegOpsApi implements RegOpsApi {
  private runs = new Map<string, RunClock>();
  private seq = 0;

  async getHealth(): Promise<HealthStatus> {
    return { status: "ok", version: "1.0.0-mock" };
  }

  async createRun(body: CreateRunRequest): Promise<Run> {
    if (!body.synthetic_ack) {
      throw { error: "synthetic_ack_required", detail: "Confirm demo data is synthetic." };
    }
    const runId = `RUN-${(++this.seq).toString().padStart(3, "0")}`;
    const run = baseRun(runId);
    run.regulation.title = body.regulation_filename.replace(/\.pdf$/i, "");
    this.runs.set(runId, { run, startedAt: Date.now(), approved: false, approvals: {} });
    return structuredClone(run);
  }

  async getRun(runId: string): Promise<Run> {
    const rc = this.mustGet(runId);
    this.advance(rc);
    return structuredClone(rc.run);
  }

  async listRunFindings(runId: string, params?: ListFindingsParams): Promise<FindingsListResponse> {
    this.mustGet(runId);
    let items = MOCK_FINDING_SUMMARIES.map((f) => ({ ...f, run_id: runId }));
    if (params?.severity) items = items.filter((f) => f.severity === params.severity);
    if (params?.q) {
      const q = params.q.toLowerCase();
      items = items.filter((f) => f.target_id.toLowerCase().includes(q));
    }
    return { items, total: items.length };
  }

  async getFinding(findingId: string): Promise<Finding> {
    const f = MOCK_FINDING_DETAIL[findingId];
    if (!f) throw { error: "not_found", detail: `finding ${findingId}` };
    return structuredClone(f);
  }

  async previewAction(actionId: string): Promise<CounterfactualPreview> {
    return structuredClone({ ...MOCK_COUNTERFACTUAL, action_id: actionId });
  }

  async decideApproval(approvalId: string, body: ApprovalDecision): Promise<Approval> {
    // Find the run holding this approval.
    for (const rc of this.runs.values()) {
      const existing = rc.approvals[approvalId];
      if (existing && existing.status !== "PENDING") {
        throw { error: "already_decided", detail: approvalId };
      }
    }
    const rc = [...this.runs.values()].find((r) =>
      r.run.pending_approvals?.some((a) => a.approval_id === approvalId),
    );
    if (!rc) throw { error: "not_found", detail: `approval ${approvalId}` };

    const decision: Approval = {
      approval_id: approvalId,
      action_id: rc.run.pending_approvals![0].action_id,
      run_id: rc.run.run_id,
      status: body.decision === "approve" ? "APPROVED" : "REJECTED",
      decided_at: nowIso(),
      decided_by: "demo-user",
      note: body.note ?? null,
    };
    rc.approvals[approvalId] = decision;

    if (body.decision === "approve") {
      rc.approved = true;
      rc.startedAt = Date.now(); // restart clock for the post-approval states
      rc.run.pending_approvals = [];
    } else {
      rc.run.state = "FAILED";
    }
    return structuredClone(decision);
  }

  async getRunAudit(runId: string): Promise<AuditReport> {
    this.mustGet(runId);
    return structuredClone(mockAudit(runId));
  }

  // --- internal ---

  private mustGet(runId: string): RunClock {
    const rc = this.runs.get(runId);
    if (!rc) throw { error: "not_found", detail: `run ${runId}` };
    return rc;
  }

  /** Advance run state based on elapsed time; pause at AWAITING_APPROVAL until approved. */
  private advance(rc: RunClock) {
    const seq = MOCK_RUN_SEQUENCE;
    const approvalIdx = seq.indexOf("AWAITING_APPROVAL");
    const elapsedSteps = Math.floor((Date.now() - rc.startedAt) / STEP_MS);

    let idx = seq.indexOf(rc.run.state);
    if (idx < 0) idx = 0;

    if (!rc.approved) {
      const target = Math.min(approvalIdx, elapsedSteps);
      idx = Math.max(idx, target);
    } else {
      // After approval, walk from EXECUTING to COMPLETED.
      const postStart = approvalIdx + 1;
      const target = Math.min(seq.length - 1, postStart + elapsedSteps);
      idx = Math.max(idx, target);
    }

    const newState = seq[idx] as RunState;
    if (newState !== rc.run.state) this.applyState(rc, newState);
  }

  private applyState(rc: RunClock, state: RunState) {
    rc.run.state = state;
    rc.run.updated_at = nowIso();
    const p = rc.run.progress!;

    switch (state) {
      case "MAPPING":
        p.documents_processed = 120;
        p.partitions_complete = 2;
        p.percent = 40;
        break;
      case "MAPPED":
      case "VERIFYING":
        p.documents_processed = 300;
        p.partitions_complete = 6;
        p.percent = 100;
        rc.run.findings_by_severity = { low: 1, medium: 1, high: 1 };
        break;
      case "AWAITING_APPROVAL":
        rc.run.pending_approvals = [
          { approval_id: "APR-0001", action_id: "ACT-0001", run_id: rc.run.run_id, status: "PENDING" },
        ];
        break;
      case "EXECUTING":
        rc.run.completed_actions = [
          {
            action_id: "ACT-0002",
            finding_id: "FND-0002",
            type: "create_review_task",
            autonomy: "auto",
            status: "EXECUTED",
            idempotency_key: "FND-0002:create_review_task:" + rc.run.run_id,
          },
        ];
        break;
      case "COMPLETED":
        rc.run.completed_actions = mockAudit(rc.run.run_id).executed_actions;
        break;
    }

    rc.run.timeline = [
      ...(rc.run.timeline ?? []),
      { ts: nowIso(), state, message: timelineMessage(state) },
    ];
  }
}

function timelineMessage(state: RunState): string {
  const m: Partial<Record<RunState, string>> = {
    EXTRACTING: "Regulation Analyst extracting obligations with citations.",
    EXTRACTED: "Obligations extracted; evidence attached.",
    MAPPING: "Impact Investigator matching corpus (partitioned).",
    MAPPED: "Candidate findings produced.",
    VERIFYING: "Internal refutation pass running.",
    VERIFIED: "Findings verified (survived/refuted/uncertain).",
    AWAITING_APPROVAL: "Consequential amendment paused for human approval.",
    EXECUTING: "Executing approved and auto actions (idempotent).",
    REVALIDATING: "Re-running pipeline to confirm resolution.",
    COMPLETED: "Run complete; audit package generated.",
    FAILED: "Action rejected; run halted.",
  };
  return m[state] ?? `State: ${state}`;
}
