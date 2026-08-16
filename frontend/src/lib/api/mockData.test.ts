// Phase 1B fixture integrity. The mock adapter is the only backend the demo has,
// so its fixtures must satisfy the same contract invariants the real API does.

import { describe, expect, it } from "vitest";

import { isSafeAuditPackageUrl } from "@/lib/url";
import {
  amendmentAction,
  baseRun,
  MOCK_ACTION_ATTEMPTS,
  MOCK_BASELINE_FINDING_COUNT,
  MOCK_DUPLICATE_ACTIONS_PREVENTED,
  MOCK_RESOLVED_ON_APPROVAL,
  mockAmendmentActionId,
  mockAmendmentFindingId,
  mockAudit,
  mockChangeDetection,
  mockCounterfactual,
  mockFindingDetail,
  mockFindingsBySeverity,
  mockFindingSummaries,
  mockNewConflictIds,
  mockRecovery,
  mockRemainingHighRiskIds,
  mockResolvedFindingIds,
  mockShadowRunId,
  mockUnchangedFindingIds,
  localIdForRun,
  pendingApproval,
  reviewTaskAction,
  scopeToRun,
  syntheticSha256,
} from "./mockData";

const RUN_ID = "RUN-001";
/** A second concurrent run, used to prove ids never collide. */
const OTHER_RUN_ID = "RUN-002";

describe("mock run fixture", () => {
  const run = baseRun(RUN_ID, "synthetic-fee-rule-amendment.pdf", "2026-08-16T09:00:00.000Z");

  it("carries a contract-valid initial transition", () => {
    expect(run.transitions).toHaveLength(1);
    expect(run.transitions[0]?.from_state).toBeNull();
    expect(run.transitions[0]?.to_state).toBe("INGESTED");
    expect(run.transitions[0]?.actor).toBeTruthy();
    expect(run.transitions[0]?.reason).toBeTruthy();
  });

  it("starts with no recovery and a change-detection result", () => {
    expect(run.recovery).toBeNull();
    expect(run.change_detection?.source_sha256).toMatch(/^[0-9a-f]{64}$/);
  });

  it("labels the regulation as synthetic", () => {
    expect(run.regulation.synthetic).toBe(true);
  });
});

describe("run-scoped identity", () => {
  it("round-trips a run-local id through the run scope", () => {
    const scoped = scopeToRun(RUN_ID, "FND-0007");
    expect(scoped).toBe("RUN-001-FND-0007");
    expect(localIdForRun(RUN_ID, scoped)).toBe("FND-0007");
  });

  it("refuses to read an id that belongs to another run", () => {
    const scoped = scopeToRun(OTHER_RUN_ID, "FND-0007");
    expect(localIdForRun(RUN_ID, scoped)).toBeNull();
    // A run id that is a prefix of another run's id must not match either.
    expect(localIdForRun("RUN-1", scopeToRun("RUN-10", "FND-0001"))).toBeNull();
  });
});

describe("synthetic hashes", () => {
  it("produces 64 lowercase hex characters", () => {
    expect(syntheticSha256("anything")).toMatch(/^[0-9a-f]{64}$/);
    expect(syntheticSha256("")).toMatch(/^[0-9a-f]{64}$/);
  });

  it("is deterministic and input-sensitive", () => {
    expect(syntheticSha256("a")).toBe(syntheticSha256("a"));
    expect(syntheticSha256("a")).not.toBe(syntheticSha256("b"));
  });

  it("yields change detection that satisfies the contract's patterns", () => {
    const detection = mockChangeDetection("reg.pdf", "2026-08-16T09:00:00.000Z");
    expect(detection.source_sha256).toMatch(/^[0-9a-f]{64}$/);
    expect(detection.previous_source_sha256).toMatch(/^[0-9a-f]{64}$/);
    expect(detection.source_sha256).not.toBe(detection.previous_source_sha256);
    expect(detection.changed).toBe(true);
  });
});

describe("mock recovery fixture", () => {
  it("never claims availability without a checkpoint", () => {
    const available = mockRecovery(true);
    expect(available.recovery_available).toBe(true);
    expect(available.checkpoint_state).not.toBeNull();
  });

  it("keeps the checkpoint visible after the retry succeeded", () => {
    const resolved = mockRecovery(false);
    expect(resolved.recovery_available).toBe(false);
    expect(resolved.attempt_count).toBeGreaterThan(0);
  });
});

describe("mock finding fixtures", () => {
  const summaries = mockFindingSummaries(RUN_ID);

  it("produces the baseline the audit and counterfactual report", () => {
    expect(summaries).toHaveLength(MOCK_BASELINE_FINDING_COUNT);
  });

  it("gives every summary a complete score set", () => {
    for (const summary of summaries) {
      expect(summary.run_id).toBe(RUN_ID);
      expect(summary.scores.operational_severity).toBe(summary.severity);
      expect(summary.scores.evidence_strength).toBeGreaterThanOrEqual(0);
      expect(summary.scores.evidence_strength).toBeLessThanOrEqual(1);
      expect(summary.scores.interpretation_confidence).toBeGreaterThanOrEqual(0);
      expect(summary.scores.interpretation_confidence).toBeLessThanOrEqual(1);
    }
  });

  it("uses unique ids", () => {
    const ids = new Set(summaries.map((summary) => summary.finding_id));
    expect(ids.size).toBe(summaries.length);
  });

  it("scopes every finding id to its run", () => {
    for (const summary of summaries) {
      expect(summary.finding_id.startsWith(`${RUN_ID}-`), summary.finding_id).toBe(true);
    }
  });

  it("shares no finding id with another run", () => {
    const others = new Set(
      mockFindingSummaries(OTHER_RUN_ID).map((summary) => summary.finding_id),
    );
    for (const summary of summaries) {
      expect(others.has(summary.finding_id), summary.finding_id).toBe(false);
    }
  });

  it("refuses to resolve another run's finding id", () => {
    const foreign = mockFindingSummaries(OTHER_RUN_ID)[0]?.finding_id as string;
    expect(mockFindingDetail(RUN_ID, foreign)).toBeUndefined();
    expect(mockFindingDetail(OTHER_RUN_ID, foreign)?.run_id).toBe(OTHER_RUN_ID);
  });

  it("exposes a detail record with at least one evidence reference for every summary", () => {
    for (const summary of summaries) {
      const detail = mockFindingDetail(RUN_ID, summary.finding_id);
      expect(detail, summary.finding_id).toBeDefined();
      expect(detail?.evidence_path.length).toBeGreaterThan(0);
      expect(detail?.obligation.evidence.length).toBeGreaterThan(0);
      expect(detail?.scores).toEqual(summary.scores);
    }
  });

  it("counts severities across the whole fixture set", () => {
    const counts = mockFindingsBySeverity();
    expect(counts.low + counts.medium + counts.high).toBe(MOCK_BASELINE_FINDING_COUNT);
  });
});

describe("mock approval fixture", () => {
  it("names the finding its action came from", () => {
    const approval = pendingApproval(RUN_ID);
    expect(approval.finding_id).toBe(mockAmendmentFindingId(RUN_ID));
    expect(mockFindingDetail(RUN_ID, approval.finding_id)?.proposed_action?.action_id).toBe(
      approval.action_id,
    );
  });

  it("scopes the approval and its action to the run", () => {
    const approval = pendingApproval(RUN_ID);
    const other = pendingApproval(OTHER_RUN_ID);

    expect(approval.approval_id).not.toBe(other.approval_id);
    expect(approval.action_id).not.toBe(other.action_id);
    expect(approval.finding_id).not.toBe(other.finding_id);
    expect(approval.run_id).toBe(RUN_ID);
  });

  it("gives each run's actions distinct ids and idempotency keys", () => {
    const mine = amendmentAction(RUN_ID, "AWAITING_APPROVAL");
    const theirs = amendmentAction(OTHER_RUN_ID, "AWAITING_APPROVAL");
    const review = reviewTaskAction(RUN_ID, "PENDING");

    expect(mine.action_id).not.toBe(theirs.action_id);
    expect(mine.idempotency_key).not.toBe(theirs.idempotency_key);
    expect(mine.action_id).not.toBe(review.action_id);
    expect(mine.finding_id).toBe(mockAmendmentFindingId(RUN_ID));
  });

  it("never pre-fills reviewer identity", () => {
    expect(pendingApproval(RUN_ID).decided_by).toBeNull();
  });
});

describe("mock counterfactual fixture", () => {
  const preview = mockCounterfactual(mockAmendmentActionId(RUN_ID), RUN_ID);

  it("partitions the baseline into resolved and unchanged", () => {
    expect(preview.baseline_finding_count).toBe(MOCK_BASELINE_FINDING_COUNT);
    expect(preview.resolved_finding_ids).toHaveLength(MOCK_RESOLVED_ON_APPROVAL);
    expect(
      preview.resolved_finding_ids.length + preview.unchanged_finding_ids.length,
    ).toBe(MOCK_BASELINE_FINDING_COUNT);
  });

  it("draws its identifiers from findings the run actually reports", () => {
    const known = new Set(mockFindingSummaries(RUN_ID).map((summary) => summary.finding_id));
    for (const id of [...mockResolvedFindingIds(RUN_ID), ...mockUnchangedFindingIds(RUN_ID)]) {
      expect(known.has(id), id).toBe(true);
    }
    // New conflicts do not exist today — that is what makes them new.
    for (const id of mockNewConflictIds(RUN_ID)) {
      expect(known.has(id)).toBe(false);
    }
  });

  it("only lists remaining high-risk findings that are also unchanged", () => {
    expect(mockRemainingHighRiskIds(RUN_ID).length).toBeGreaterThan(0);
    for (const id of mockRemainingHighRiskIds(RUN_ID)) {
      expect(mockUnchangedFindingIds(RUN_ID)).toContain(id);
    }
  });

  it("scopes every identifier, including the shadow snapshot, to its own run", () => {
    const other = mockCounterfactual(mockAmendmentActionId(OTHER_RUN_ID), OTHER_RUN_ID);

    expect(preview.shadow_run_id).toBe(mockShadowRunId(RUN_ID));
    expect(preview.shadow_run_id).not.toBe(other.shadow_run_id);

    const mine = [
      ...preview.resolved_finding_ids,
      ...preview.unchanged_finding_ids,
      ...preview.new_conflict_ids,
      ...preview.remaining_high_risk_ids,
    ];
    const theirs = new Set([
      ...other.resolved_finding_ids,
      ...other.unchanged_finding_ids,
      ...other.new_conflict_ids,
      ...other.remaining_high_risk_ids,
    ]);
    for (const id of mine) {
      expect(id.startsWith(`${RUN_ID}-`), id).toBe(true);
      expect(theirs.has(id), id).toBe(false);
    }
  });
});

describe("mock audit fixture", () => {
  it("excludes the rejected amendment and resolves nothing", () => {
    const audit = mockAudit(RUN_ID, "2026-08-16T09:20:00.000Z", "rejected");
    expect(audit.executed_actions.map((action) => action.type)).toEqual(["create_review_task"]);
    expect(audit.revalidation.findings_resolved).toBe(0);
    expect(audit.revalidation.findings_remaining).toBe(MOCK_BASELINE_FINDING_COUNT);
  });

  it("balances resolved and remaining against the baseline when approved", () => {
    const audit = mockAudit(RUN_ID, "2026-08-16T09:20:00.000Z", "approved");
    expect(audit.revalidation.findings_resolved + audit.revalidation.findings_remaining).toBe(
      MOCK_BASELINE_FINDING_COUNT,
    );
  });

  it("scopes its executed action ids to the run", () => {
    const mine = mockAudit(RUN_ID, "2026-08-16T09:20:00.000Z", "approved");
    const theirs = mockAudit(OTHER_RUN_ID, "2026-08-16T09:20:00.000Z", "approved");
    const theirIds = new Set(theirs.executed_actions.map((action) => action.action_id));

    expect(mine.executed_actions.length).toBeGreaterThan(0);
    for (const action of mine.executed_actions) {
      expect(action.action_id.startsWith(`${RUN_ID}-`), action.action_id).toBe(true);
      expect(action.finding_id.startsWith(`${RUN_ID}-`), action.finding_id).toBe(true);
      expect(theirIds.has(action.action_id), action.action_id).toBe(false);
    }
  });

  it("reports a positive duplicate rate whenever duplicates were prevented", () => {
    for (const outcome of ["approved", "rejected"] as const) {
      const { idempotency } = mockAudit(RUN_ID, "2026-08-16T09:20:00.000Z", outcome);

      expect(idempotency.duplicate_actions_prevented).toBe(MOCK_DUPLICATE_ACTIONS_PREVENTED);
      expect(idempotency.duplicate_actions_prevented).toBeGreaterThan(0);
      expect(idempotency.duplicate_action_rate).toBeGreaterThan(0);
      // The documented synthetic scenario: one duplicate out of three attempts.
      expect(idempotency.duplicate_action_rate).toBeCloseTo(
        MOCK_DUPLICATE_ACTIONS_PREVENTED / MOCK_ACTION_ATTEMPTS,
        10,
      );
    }
  });

  it("keeps the duplicate rate inside the contract's 0..1 bounds", () => {
    for (const outcome of ["approved", "rejected"] as const) {
      const { duplicate_action_rate: rate } = mockAudit(
        RUN_ID,
        "2026-08-16T09:20:00.000Z",
        outcome,
      ).idempotency;

      expect(rate).toBeGreaterThanOrEqual(0);
      expect(rate).toBeLessThanOrEqual(1);
    }
    expect(MOCK_DUPLICATE_ACTIONS_PREVENTED).toBeLessThanOrEqual(MOCK_ACTION_ATTEMPTS);
  });

  it("never offers an audit package URL that would be refused as unsafe", () => {
    for (const outcome of ["approved", "rejected"] as const) {
      const url = mockAudit(RUN_ID, "2026-08-16T09:20:00.000Z", outcome).audit_package_url;
      // Either absent, or a value the console is willing to put in an href.
      expect(url === null || isSafeAuditPackageUrl(url)).toBe(true);
    }
  });
});
