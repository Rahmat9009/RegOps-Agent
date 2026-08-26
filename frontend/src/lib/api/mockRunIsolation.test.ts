// Two concurrent mock runs must stay completely separate.
//
// The contract's finding, action and approval routes carry no run id, so every
// run-owned identifier has to be globally unique on its own. When the mock shared
// `FND-0001` / `ACT-0001` / `APR-0001` across runs, a link saved from an earlier
// run silently resolved against the newest one. These tests pin the repair: two
// runs alive at the same time, and nothing crossing between them.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MockRegOpsApi } from "./mockAdapter";
import { mockAmendmentActionId, mockAmendmentFindingId, mockShadowRunId } from "./mockData";
import type { Run } from "./types";

/** Enough fake time to walk a whole phase of the pipeline script. */
const PHASE_MS = 60_000;

function syntheticPdf(name: string): File {
  return new File(["%PDF-1.4\n%%EOF"], name, { type: "application/pdf" });
}

async function settle<T>(promise: Promise<T>): Promise<T> {
  promise.catch(() => undefined);
  await vi.advanceTimersByTimeAsync(500);
  return promise;
}

interface PendingRun {
  run: Run;
  approvalId: string;
  actionId: string;
  findingId: string;
}

/** Read a run back and assert it is waiting on a human decision. */
async function awaitingApproval(api: MockRegOpsApi, runId: string): Promise<PendingRun> {
  const run = await settle(api.getRun(runId));
  expect(run.state).toBe("AWAITING_APPROVAL");

  const approval = run.pending_approvals?.[0];
  expect(approval, runId).toBeDefined();

  return {
    run,
    approvalId: approval?.approval_id as string,
    actionId: approval?.action_id as string,
    findingId: approval?.finding_id as string,
  };
}

describe("MockRegOpsApi cross-run identity", () => {
  let api: MockRegOpsApi;
  let first: PendingRun;
  let second: PendingRun;

  beforeEach(async () => {
    vi.useFakeTimers();
    api = new MockRegOpsApi();

    // Two runs created back to back, both alive at the same time.
    const older = await settle(
      api.createRun({ regulation_file: syntheticPdf("first.pdf"), synthetic_ack: true }),
    );
    const newer = await settle(
      api.createRun({ regulation_file: syntheticPdf("second.pdf"), synthetic_ack: true }),
    );
    expect(older.run_id).not.toBe(newer.run_id);

    await vi.advanceTimersByTimeAsync(PHASE_MS);
    first = await awaitingApproval(api, older.run_id);
    second = await awaitingApproval(api, newer.run_id);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("gives the two runs disjoint finding ids", async () => {
    const mine = await settle(api.listRunFindings(first.run.run_id, { limit: 100 }));
    const theirs = await settle(api.listRunFindings(second.run.run_id, { limit: 100 }));

    expect(mine.items.length).toBe(theirs.items.length);
    expect(mine.items.length).toBeGreaterThan(0);

    const theirIds = new Set(theirs.items.map((item) => item.finding_id));
    for (const item of mine.items) {
      expect(item.run_id).toBe(first.run.run_id);
      expect(theirIds.has(item.finding_id), item.finding_id).toBe(false);
    }
  });

  it("gives the two runs different action ids", () => {
    expect(first.actionId).toBe(mockAmendmentActionId(first.run.run_id));
    expect(second.actionId).toBe(mockAmendmentActionId(second.run.run_id));
    expect(first.actionId).not.toBe(second.actionId);
  });

  it("gives the two runs different approval ids", () => {
    expect(first.approvalId).not.toBe(second.approvalId);
    expect(first.findingId).not.toBe(second.findingId);
  });

  it("resolves each finding detail to the run that owns it", async () => {
    const mine = await settle(api.getFinding(first.findingId));
    const theirs = await settle(api.getFinding(second.findingId));

    expect(mine.run_id).toBe(first.run.run_id);
    expect(mine.finding_id).toBe(mockAmendmentFindingId(first.run.run_id));
    expect(theirs.run_id).toBe(second.run.run_id);
    expect(mine.proposed_action?.action_id).toBe(first.actionId);
    expect(theirs.proposed_action?.action_id).toBe(second.actionId);
  });

  it("never resolves a finding id that belongs to no run", async () => {
    // The pre-v4 shared identifier: it must not resolve to anything now.
    await expect(settle(api.getFinding("FND-0001"))).rejects.toThrow(/no finding found/i);
  });

  it("previews each action against its own run, not the most recent one", async () => {
    const older = await settle(api.previewAction(first.actionId));
    const newer = await settle(api.previewAction(second.actionId));

    expect(older.action_id).toBe(first.actionId);
    expect(older.shadow_run_id).toBe(mockShadowRunId(first.run.run_id));
    expect(newer.shadow_run_id).toBe(mockShadowRunId(second.run.run_id));

    const newerIds = new Set([
      ...newer.resolved_finding_ids,
      ...newer.unchanged_finding_ids,
      ...newer.new_conflict_ids,
      ...newer.remaining_high_risk_ids,
    ]);
    for (const id of [
      ...older.resolved_finding_ids,
      ...older.unchanged_finding_ids,
      ...older.new_conflict_ids,
      ...older.remaining_high_risk_ids,
    ]) {
      expect(id.startsWith(`${first.run.run_id}-`), id).toBe(true);
      expect(newerIds.has(id), id).toBe(false);
    }
  });

  it("keeps an older run's action link working after a newer run is created", async () => {
    const third = await settle(
      api.createRun({ regulation_file: syntheticPdf("third.pdf"), synthetic_ack: true }),
    );
    expect(third.run_id).not.toBe(first.run.run_id);

    // The link a reviewer saved from the first run still points at the first run.
    const preview = await settle(api.previewAction(first.actionId));
    expect(preview.shadow_run_id).toBe(mockShadowRunId(first.run.run_id));
    expect(preview.resolved_finding_ids[0]?.startsWith(`${first.run.run_id}-`)).toBe(true);

    const finding = await settle(api.getFinding(first.findingId));
    expect(finding.run_id).toBe(first.run.run_id);
  });

  it("does not let a decision on one run touch the other", async () => {
    const decision = await settle(api.decideApproval(first.approvalId, { decision: "reject" }));
    expect(decision.run_id).toBe(first.run.run_id);
    expect(decision.action_id).toBe(first.actionId);
    expect(decision.finding_id).toBe(first.findingId);

    await vi.advanceTimersByTimeAsync(PHASE_MS);

    const decided = await settle(api.getRun(first.run.run_id));
    expect(decided.state).toBe("COMPLETED");
    expect(decided.pending_approvals ?? []).toHaveLength(0);

    // The second run is untouched: still waiting, still holding its own approval.
    const untouched = await awaitingApproval(api, second.run.run_id);
    expect(untouched.approvalId).toBe(second.approvalId);

    const theirFinding = await settle(api.getFinding(second.findingId));
    expect(theirFinding.status).toBe("AWAITING_APPROVAL");
    expect(theirFinding.proposed_action?.status).toBe("AWAITING_APPROVAL");
  });

  it("decides each run's approval independently", async () => {
    await settle(api.decideApproval(first.approvalId, { decision: "reject" }));
    const approvedSecond = await settle(
      api.decideApproval(second.approvalId, { decision: "approve" }),
    );

    expect(approvedSecond.status).toBe("APPROVED");
    expect(approvedSecond.run_id).toBe(second.run.run_id);

    await vi.advanceTimersByTimeAsync(PHASE_MS);

    const rejected = await settle(api.getRunAudit(first.run.run_id));
    const approved = await settle(api.getRunAudit(second.run.run_id));

    expect(rejected.revalidation.findings_resolved).toBe(0);
    expect(approved.revalidation.findings_resolved).toBeGreaterThan(0);

    // Audit actions carry their own run's ids and nothing else.
    for (const action of rejected.executed_actions) {
      expect(action.action_id.startsWith(`${first.run.run_id}-`), action.action_id).toBe(true);
    }
    for (const action of approved.executed_actions) {
      expect(action.action_id.startsWith(`${second.run.run_id}-`), action.action_id).toBe(true);
    }
  });

  it("rejects an approval id that belongs to no run", async () => {
    await expect(
      settle(api.decideApproval("APR-0001", { decision: "approve" })),
    ).rejects.toThrow(/no approval found/i);
  });
});
