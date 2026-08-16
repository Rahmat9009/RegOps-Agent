// Rejection is a valid terminal business outcome, not a failure. These tests pin
// that behaviour so the demo cannot regress into treating "reject" as FAILED.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MockRegOpsApi } from "./mockAdapter";
import { MOCK_AMENDMENT_ACTION_ID, MOCK_BASELINE_FINDING_COUNT } from "./mockData";
import type { Run } from "./types";

/** Enough fake time to walk a whole phase of the pipeline script. */
const PHASE_MS = 60_000;

function syntheticPdf(): File {
  return new File(["%PDF-1.4\n%%EOF"], "synthetic-regulation.pdf", { type: "application/pdf" });
}

/** Flush the adapter's artificial latency so the pending call resolves. */
async function settle<T>(promise: Promise<T>): Promise<T> {
  // Advancing timers can settle the promise before the caller attaches a handler,
  // so mark it handled here. The original promise is still what gets returned, so
  // rejections continue to reach the caller.
  promise.catch(() => undefined);
  await vi.advanceTimersByTimeAsync(500);
  return promise;
}

/** Move the clock so the adapter's wall-clock state machine advances. */
async function jumpAhead(ms = PHASE_MS): Promise<void> {
  await vi.advanceTimersByTimeAsync(ms);
}

/** Drive a fresh run to the point where it is waiting on a human decision. */
async function runAwaitingApproval(api: MockRegOpsApi): Promise<{ run: Run; approvalId: string }> {
  const created = await settle(
    api.createRun({ regulation_file: syntheticPdf(), synthetic_ack: true }),
  );
  await jumpAhead();
  const run = await settle(api.getRun(created.run_id));

  expect(run.state).toBe("AWAITING_APPROVAL");
  const approvalId = run.pending_approvals?.[0]?.approval_id;
  expect(approvalId).toBeDefined();

  return { run, approvalId: approvalId as string };
}

describe("MockRegOpsApi approval rejection", () => {
  let api: MockRegOpsApi;

  beforeEach(() => {
    vi.useFakeTimers();
    api = new MockRegOpsApi();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("completes the run rather than failing it", async () => {
    const { run, approvalId } = await runAwaitingApproval(api);

    const decision = await settle(api.decideApproval(approvalId, { decision: "reject" }));
    expect(decision.status).toBe("REJECTED");

    await jumpAhead();
    const finished = await settle(api.getRun(run.run_id));

    expect(finished.state).toBe("COMPLETED");
    expect(finished.state).not.toBe("FAILED");
  });

  it("leaves the target finding OPEN and marks the amendment REJECTED", async () => {
    const { run, approvalId } = await runAwaitingApproval(api);
    await settle(api.decideApproval(approvalId, { decision: "reject" }));
    await jumpAhead();
    await settle(api.getRun(run.run_id));

    const finding = await settle(api.getFinding("FND-0001"));

    expect(finding.status).toBe("OPEN");
    expect(finding.proposed_action?.action_id).toBe(MOCK_AMENDMENT_ACTION_ID);
    expect(finding.proposed_action?.status).toBe("REJECTED");
  });

  it("keeps the automatic review task EXECUTED and the rejected amendment out of completed actions", async () => {
    const { run, approvalId } = await runAwaitingApproval(api);
    await settle(api.decideApproval(approvalId, { decision: "reject" }));
    await jumpAhead();

    const finished = await settle(api.getRun(run.run_id));
    const actions = finished.completed_actions ?? [];

    const reviewTask = actions.find((action) => action.type === "create_review_task");
    expect(reviewTask?.status).toBe("EXECUTED");

    expect(actions.some((action) => action.action_id === MOCK_AMENDMENT_ACTION_ID)).toBe(false);
  });

  it("omits the rejected amendment from the audit's executed actions", async () => {
    const { run, approvalId } = await runAwaitingApproval(api);
    await settle(api.decideApproval(approvalId, { decision: "reject" }));
    await jumpAhead();
    await settle(api.getRun(run.run_id));

    const audit = await settle(api.getRunAudit(run.run_id));

    expect(audit.executed_actions.map((action) => action.action_id)).not.toContain(
      MOCK_AMENDMENT_ACTION_ID,
    );
    expect(audit.executed_actions).toHaveLength(1);
    expect(audit.executed_actions[0]?.type).toBe("create_review_task");
    expect(audit.executed_actions[0]?.status).toBe("EXECUTED");
  });

  it("reports nothing resolved and every baseline finding remaining", async () => {
    const { run, approvalId } = await runAwaitingApproval(api);
    await settle(api.decideApproval(approvalId, { decision: "reject" }));
    await jumpAhead();
    await settle(api.getRun(run.run_id));

    const audit = await settle(api.getRunAudit(run.run_id));

    expect(audit.revalidation.findings_resolved).toBe(0);
    expect(audit.revalidation.findings_remaining).toBe(MOCK_BASELINE_FINDING_COUNT);
  });

  it("rejects a second decision on the same approval with a 409", async () => {
    const { approvalId } = await runAwaitingApproval(api);
    await settle(api.decideApproval(approvalId, { decision: "reject" }));

    await expect(settle(api.decideApproval(approvalId, { decision: "approve" }))).rejects.toThrow(
      /already rejected/i,
    );
  });
});

describe("MockRegOpsApi approval acceptance", () => {
  let api: MockRegOpsApi;

  beforeEach(() => {
    vi.useFakeTimers();
    api = new MockRegOpsApi();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("resolves the finding and records the amendment as an approved draft", async () => {
    const { run, approvalId } = await runAwaitingApproval(api);
    await settle(api.decideApproval(approvalId, { decision: "approve" }));
    await jumpAhead();

    const finished = await settle(api.getRun(run.run_id));
    expect(finished.state).toBe("COMPLETED");

    const finding = await settle(api.getFinding("FND-0001"));
    expect(finding.status).toBe("RESOLVED");
    expect(finding.proposed_action?.status).toBe("APPROVED_DRAFT");

    const audit = await settle(api.getRunAudit(run.run_id));
    expect(audit.executed_actions.map((action) => action.action_id)).toContain(
      MOCK_AMENDMENT_ACTION_ID,
    );
    expect(audit.revalidation.findings_resolved).toBeGreaterThan(0);
  });
});
