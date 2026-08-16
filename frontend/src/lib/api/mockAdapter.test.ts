// Rejection is a valid terminal business outcome, not a failure. These tests pin
// that behaviour so the demo cannot regress into treating "reject" as FAILED.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MockRegOpsApi } from "./mockAdapter";
import {
  MOCK_BASELINE_FINDING_COUNT,
  mockAmendmentActionId,
  mockAmendmentFindingId,
} from "./mockData";
import type { Run, RunState } from "./types";

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

/** Every state the run recorded, oldest first. */
function visitedStates(run: Run): RunState[] {
  return run.transitions.map((transition) => transition.to_state);
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

    const finding = await settle(api.getFinding(mockAmendmentFindingId(run.run_id)));

    expect(finding.status).toBe("OPEN");
    expect(finding.proposed_action?.action_id).toBe(mockAmendmentActionId(run.run_id));
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

    expect(
      actions.some((action) => action.action_id === mockAmendmentActionId(run.run_id)),
    ).toBe(false);
  });

  it("omits the rejected amendment from the audit's executed actions", async () => {
    const { run, approvalId } = await runAwaitingApproval(api);
    await settle(api.decideApproval(approvalId, { decision: "reject" }));
    await jumpAhead();
    await settle(api.getRun(run.run_id));

    const audit = await settle(api.getRunAudit(run.run_id));

    expect(audit.executed_actions.map((action) => action.action_id)).not.toContain(
      mockAmendmentActionId(run.run_id),
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

  it("goes straight from AWAITING_APPROVAL to COMPLETED, skipping execution and revalidation", async () => {
    const { run, approvalId } = await runAwaitingApproval(api);
    await settle(api.decideApproval(approvalId, { decision: "reject" }));
    await jumpAhead();

    const finished = await settle(api.getRun(run.run_id));
    const states = visitedStates(finished);

    expect(states).not.toContain("EXECUTING");
    expect(states).not.toContain("REVALIDATING");
    expect(states).not.toContain("FAILED");
    expect(states.at(-1)).toBe("COMPLETED");

    const completing = finished.transitions.at(-1);
    expect(completing?.from_state).toBe("AWAITING_APPROVAL");
    expect(completing?.to_state).toBe("COMPLETED");
    expect(completing?.actor).toBe("demo-reviewer");
  });

  it("retains every baseline finding in the list", async () => {
    const { run, approvalId } = await runAwaitingApproval(api);
    await settle(api.decideApproval(approvalId, { decision: "reject" }));
    await jumpAhead();
    await settle(api.getRun(run.run_id));

    const list = await settle(api.listRunFindings(run.run_id, { limit: 100 }));

    expect(list.total).toBe(MOCK_BASELINE_FINDING_COUNT);
    expect(
      list.items.some(
        (item) =>
          item.status === "RESOLVED" && item.finding_id === mockAmendmentFindingId(run.run_id),
      ),
    ).toBe(false);
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

    const finding = await settle(api.getFinding(mockAmendmentFindingId(run.run_id)));
    expect(finding.status).toBe("RESOLVED");
    expect(finding.proposed_action?.status).toBe("APPROVED_DRAFT");

    const audit = await settle(api.getRunAudit(run.run_id));
    expect(audit.executed_actions.map((action) => action.action_id)).toContain(
      mockAmendmentActionId(run.run_id),
    );
    expect(audit.revalidation.findings_resolved).toBeGreaterThan(0);
  });

  it("passes through both EXECUTING and REVALIDATING before completing", async () => {
    const { run, approvalId } = await runAwaitingApproval(api);
    await settle(api.decideApproval(approvalId, { decision: "approve" }));
    await jumpAhead();

    const finished = await settle(api.getRun(run.run_id));
    const states = visitedStates(finished);

    expect(states).toContain("EXECUTING");
    expect(states).toContain("REVALIDATING");
    expect(states.indexOf("EXECUTING")).toBeLessThan(states.indexOf("REVALIDATING"));
    expect(states.at(-1)).toBe("COMPLETED");
    expect(states).not.toContain("FAILED");
  });
});

describe("MockRegOpsApi authoritative transitions", () => {
  let api: MockRegOpsApi;

  beforeEach(() => {
    vi.useFakeTimers();
    api = new MockRegOpsApi();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("starts with a single INGESTED transition whose from_state is null", async () => {
    const created = await settle(
      api.createRun({ regulation_file: syntheticPdf(), synthetic_ack: true }),
    );

    expect(created.transitions).toHaveLength(1);
    expect(created.transitions[0]?.from_state).toBeNull();
    expect(created.transitions[0]?.to_state).toBe("INGESTED");
    expect(created.transitions[0]?.actor.length).toBeGreaterThan(0);
    expect(created.transitions[0]?.occurred_at).toBe(created.created_at);
  });

  it("records a complete, chained, oldest-to-newest history without skipping states", async () => {
    const { run } = await runAwaitingApproval(api);

    const states = visitedStates(run);
    // The whole scripted pipeline is present even though the test jumped the
    // clock past several steps in one go.
    expect(states).toEqual([
      "INGESTED",
      "EXTRACTING",
      "EXTRACTED",
      "MAPPING",
      "FAILED_RECOVERABLE",
      "MAPPING",
      "MAPPED",
      "VERIFYING",
      "VERIFIED",
      "AWAITING_APPROVAL",
    ]);

    for (let index = 1; index < run.transitions.length; index += 1) {
      const previous = run.transitions[index - 1];
      const current = run.transitions[index];
      expect(current?.from_state).toBe(previous?.to_state);
      expect(Date.parse(current?.occurred_at ?? "")).toBeGreaterThanOrEqual(
        Date.parse(previous?.occurred_at ?? ""),
      );
    }
  });

  it("labels the checkpoint resume with a safe reason", async () => {
    const { run } = await runAwaitingApproval(api);

    const resume = run.transitions.find(
      (transition) => transition.from_state === "FAILED_RECOVERABLE",
    );
    expect(resume?.to_state).toBe("MAPPING");
    expect(resume?.reason).toMatch(/checkpoint/i);
  });
});

describe("MockRegOpsApi recovery and change detection", () => {
  let api: MockRegOpsApi;

  beforeEach(() => {
    vi.useFakeTimers();
    api = new MockRegOpsApi();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("reports change detection on the accepted run", async () => {
    const created = await settle(
      api.createRun({ regulation_file: syntheticPdf(), synthetic_ack: true }),
    );

    const detection = created.change_detection;
    expect(detection).not.toBeNull();
    expect(detection?.source_sha256).toMatch(/^[0-9a-f]{64}$/);
    expect(detection?.previous_source_sha256).toMatch(/^[0-9a-f]{64}$/);
    expect(typeof detection?.changed).toBe("boolean");
    expect(Number.isNaN(Date.parse(detection?.detected_at ?? ""))).toBe(false);
  });

  it("has no recovery record before anything fails", async () => {
    const created = await settle(
      api.createRun({ regulation_file: syntheticPdf(), synthetic_ack: true }),
    );

    expect(created.recovery).toBeNull();
  });

  it("keeps a sanitized recovery record after the retry succeeds", async () => {
    const { run } = await runAwaitingApproval(api);

    const recovery = run.recovery;
    expect(recovery).not.toBeNull();
    expect(recovery?.recovery_available).toBe(false);
    expect(recovery?.checkpoint_state).toBe("MAPPING");
    expect(recovery?.attempt_count).toBeGreaterThan(0);
    expect(recovery?.last_error_code).toBeTruthy();
    // Sanitized: a message, never a stack trace or provider payload.
    expect(recovery?.last_error_message).not.toMatch(/\bat\s+\w+\s*\(/);
  });
});

describe("MockRegOpsApi findings pagination", () => {
  let api: MockRegOpsApi;

  beforeEach(() => {
    vi.useFakeTimers();
    api = new MockRegOpsApi();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns every summary with its complete score set", async () => {
    const { run } = await runAwaitingApproval(api);
    const list = await settle(api.listRunFindings(run.run_id, { limit: 100 }));

    expect(list.items.length).toBeGreaterThan(0);
    for (const item of list.items) {
      expect(item.scores.evidence_strength).toBeGreaterThanOrEqual(0);
      expect(item.scores.evidence_strength).toBeLessThanOrEqual(1);
      expect(item.scores.interpretation_confidence).toBeGreaterThanOrEqual(0);
      expect(item.scores.interpretation_confidence).toBeLessThanOrEqual(1);
      expect(item.scores.operational_severity).toBe(item.severity);
      expect(typeof item.scores.source_authority).toBe("string");
      expect(typeof item.scores.human_review_required).toBe("boolean");
    }
  });

  it("pages items while total and by_severity describe the whole filtered result", async () => {
    const { run } = await runAwaitingApproval(api);

    const firstPage = await settle(api.listRunFindings(run.run_id, { limit: 25, offset: 0 }));
    expect(firstPage.limit).toBe(25);
    expect(firstPage.offset).toBe(0);
    expect(firstPage.items).toHaveLength(25);
    expect(firstPage.total).toBe(MOCK_BASELINE_FINDING_COUNT);
    const counted =
      firstPage.by_severity.low + firstPage.by_severity.medium + firstPage.by_severity.high;
    expect(counted).toBe(MOCK_BASELINE_FINDING_COUNT);

    const secondPage = await settle(api.listRunFindings(run.run_id, { limit: 25, offset: 25 }));
    expect(secondPage.offset).toBe(25);
    expect(secondPage.items).toHaveLength(MOCK_BASELINE_FINDING_COUNT - 25);
    expect(secondPage.total).toBe(MOCK_BASELINE_FINDING_COUNT);

    const firstIds = firstPage.items.map((item) => item.finding_id);
    const secondIds = secondPage.items.map((item) => item.finding_id);
    expect(firstIds.filter((id) => secondIds.includes(id))).toEqual([]);
  });

  it("counts the filtered result, not the page, when a severity filter is applied", async () => {
    const { run } = await runAwaitingApproval(api);

    const high = await settle(api.listRunFindings(run.run_id, { severity: "high", limit: 1 }));

    expect(high.items).toHaveLength(1);
    expect(high.total).toBeGreaterThan(1);
    expect(high.by_severity.high).toBe(high.total);
    expect(high.by_severity.low).toBe(0);
    expect(high.by_severity.medium).toBe(0);
  });

  it("applies the contract's defaults and bounds", async () => {
    const { run } = await runAwaitingApproval(api);

    const defaults = await settle(api.listRunFindings(run.run_id));
    expect(defaults.limit).toBe(50);
    expect(defaults.offset).toBe(0);

    const clamped = await settle(api.listRunFindings(run.run_id, { limit: 5000, offset: -10 }));
    expect(clamped.limit).toBe(100);
    expect(clamped.offset).toBe(0);
  });

  it("returns an empty page with pagination metadata before findings exist", async () => {
    const created = await settle(
      api.createRun({ regulation_file: syntheticPdf(), synthetic_ack: true }),
    );

    const list = await settle(api.listRunFindings(created.run_id, { limit: 25, offset: 0 }));

    expect(list.items).toEqual([]);
    expect(list.total).toBe(0);
    expect(list.limit).toBe(25);
    expect(list.offset).toBe(0);
    expect(list.by_severity).toEqual({ low: 0, medium: 0, high: 0 });
  });
});

describe("MockRegOpsApi approval relationship", () => {
  let api: MockRegOpsApi;

  beforeEach(() => {
    vi.useFakeTimers();
    api = new MockRegOpsApi();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("names the finding on the pending approval, so no action scan is needed", async () => {
    const { run } = await runAwaitingApproval(api);
    const approval = run.pending_approvals?.[0];

    expect(approval?.finding_id).toBe(mockAmendmentFindingId(run.run_id));

    const finding = await settle(api.getFinding(approval?.finding_id as string));
    expect(finding.proposed_action?.action_id).toBe(approval?.action_id);
  });

  it("returns the finding id on the decision record too", async () => {
    const { run, approvalId } = await runAwaitingApproval(api);

    const decision = await settle(api.decideApproval(approvalId, { decision: "approve" }));

    expect(decision.finding_id).toBe(mockAmendmentFindingId(run.run_id));
    // Reviewer identity stays backend-assigned.
    expect(decision.decided_by).toBe("demo-reviewer");
  });
});
