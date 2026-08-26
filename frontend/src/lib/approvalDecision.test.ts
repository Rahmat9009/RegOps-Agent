// Human-approval safety: a decision may only be recorded against evidence that
// actually loaded. These tests pin the rule itself, not the markup that renders
// it — the screen's buttons and its submit guard both read this helper.

import { describe, expect, it } from "vitest";

import {
  canSubmitDecision,
  DECISION_BLOCKER_MESSAGE,
  evaluateDecisionEligibility,
  type ApprovalBinding,
} from "./approvalDecision";
import type { Approval, CounterfactualPreview, Finding, ProposedAction } from "./api";

const RUN_ID = "RUN-001";
const FINDING_ID = `${RUN_ID}-FND-0001`;
const ACTION_ID = `${RUN_ID}-ACT-AMENDMENT`;
const APPROVAL_ID = `${RUN_ID}-APR-0001`;

function approval(overrides: Partial<Approval> = {}): Approval {
  return {
    approval_id: APPROVAL_ID,
    action_id: ACTION_ID,
    run_id: RUN_ID,
    finding_id: FINDING_ID,
    status: "PENDING",
    decided_at: null,
    decided_by: null,
    note: null,
    ...overrides,
  };
}

function action(overrides: Partial<ProposedAction> = {}): ProposedAction {
  return {
    action_id: ACTION_ID,
    finding_id: FINDING_ID,
    type: "draft_amendment",
    autonomy: "approval_required",
    status: "AWAITING_APPROVAL",
    idempotency_key: `${FINDING_ID}:draft_amendment`,
    ...overrides,
  };
}

function finding(overrides: Partial<Finding> = {}): Finding {
  return {
    finding_id: FINDING_ID,
    run_id: RUN_ID,
    target_id: "CNT-0001#clause-7.2",
    relationship: "conflicts_with",
    severity: "high",
    verdict: "survived",
    status: "AWAITING_APPROVAL",
    human_review_required: true,
    scores: {
      evidence_strength: 0.91,
      source_authority: "primary_government",
      interpretation_confidence: 0.63,
      operational_severity: "high",
      human_review_required: true,
    },
    obligation: {
      obligation_id: "OBL-1",
      statement: "Placement fees are prohibited.",
      type: "prohibition",
      exceptions: [],
      effective_date: "2026-10-01",
      evidence: [{ doc_id: "REG-1", doc_kind: "regulation", page: 3, quote: "…" }],
    },
    affected_case: null,
    evidence_path: [{ doc_id: "REG-1", doc_kind: "regulation", page: 3, quote: "…" }],
    proposed_action: action(),
    ...overrides,
  };
}

function preview(overrides: Partial<CounterfactualPreview> = {}): CounterfactualPreview {
  return {
    action_id: ACTION_ID,
    shadow_run_id: `${RUN_ID}-SHADOW`,
    baseline_finding_count: 37,
    resolved_finding_ids: [FINDING_ID],
    unchanged_finding_ids: [],
    new_conflict_ids: [],
    remaining_high_risk_ids: [],
    detected_finding_picture_improves: true,
    narrative: null,
    ...overrides,
  };
}

/** Everything loaded and consistent. */
function loaded(overrides: Partial<ApprovalBinding> = {}): ApprovalBinding {
  return {
    approval: approval(),
    finding: finding(),
    action: action(),
    preview: preview(),
    ...overrides,
  };
}

describe("evaluateDecisionEligibility", () => {
  it("allows both decisions when the binding, evidence and preview all loaded", () => {
    const result = evaluateDecisionEligibility(loaded());

    expect(result.canApprove).toBe(true);
    expect(result.canReject).toBe(true);
    expect(result.blockers).toEqual([]);
  });

  it("blocks both decisions when nothing is pending", () => {
    const result = evaluateDecisionEligibility({
      approval: null,
      finding: finding(),
      action: action(),
      preview: preview(),
    });

    expect(result.canApprove).toBe(false);
    expect(result.canReject).toBe(false);
    expect(result.blockers).toEqual(["no_pending_approval"]);
  });

  it("blocks both decisions when the bound finding failed to load", () => {
    const result = evaluateDecisionEligibility(loaded({ finding: null }));

    expect(result.canApprove).toBe(false);
    expect(result.canReject).toBe(false);
    expect(result.blockers).toContain("finding_missing");
  });

  it("blocks both decisions when a different finding loaded", () => {
    const result = evaluateDecisionEligibility(
      loaded({ finding: finding({ finding_id: "RUN-002-FND-0001" }) }),
    );

    expect(result.canApprove).toBe(false);
    expect(result.canReject).toBe(false);
    expect(result.blockers).toContain("finding_mismatch");
  });

  it("blocks both decisions when the proposed action failed to load", () => {
    const result = evaluateDecisionEligibility(
      loaded({ finding: finding({ proposed_action: null }), action: null }),
    );

    expect(result.canApprove).toBe(false);
    expect(result.canReject).toBe(false);
    expect(result.blockers).toContain("action_missing");
  });

  it("blocks both decisions when the action is not the one the approval names", () => {
    const result = evaluateDecisionEligibility(
      loaded({ action: action({ action_id: "RUN-002-ACT-AMENDMENT" }) }),
    );

    expect(result.canApprove).toBe(false);
    expect(result.canReject).toBe(false);
    expect(result.blockers).toContain("action_mismatch");
  });

  it("blocks both decisions when the action belongs to a different finding", () => {
    const result = evaluateDecisionEligibility(
      loaded({ action: action({ finding_id: "RUN-001-FND-0009" }) }),
    );

    expect(result.canApprove).toBe(false);
    expect(result.canReject).toBe(false);
    expect(result.blockers).toContain("action_mismatch");
  });

  it("blocks approval but still allows rejection when the preview failed to load", () => {
    const result = evaluateDecisionEligibility(loaded({ preview: null }));

    expect(result.canApprove).toBe(false);
    // Rejection executes nothing, so a failed preview must not force a reviewer's
    // hand towards approving.
    expect(result.canReject).toBe(true);
    expect(result.blockers).toEqual(["preview_missing"]);
  });

  it("blocks approval when the preview describes a different action", () => {
    const result = evaluateDecisionEligibility(
      loaded({ preview: preview({ action_id: "RUN-002-ACT-AMENDMENT" }) }),
    );

    expect(result.canApprove).toBe(false);
    expect(result.canReject).toBe(true);
    expect(result.blockers).toEqual(["preview_mismatch"]);
  });

  it("reports every blocker it found", () => {
    const result = evaluateDecisionEligibility({
      approval: approval(),
      finding: null,
      action: null,
      preview: null,
    });

    expect(result.blockers).toEqual(["finding_missing", "action_missing", "preview_missing"]);
  });

  it("has an explanation for every blocker it can report", () => {
    const bindings: ApprovalBinding[] = [
      { approval: null, finding: null, action: null, preview: null },
      loaded({ finding: null }),
      loaded({ finding: finding({ finding_id: "RUN-002-FND-0001" }) }),
      loaded({ action: null }),
      loaded({ action: action({ action_id: "RUN-002-ACT-AMENDMENT" }) }),
      loaded({ preview: null }),
      loaded({ preview: preview({ action_id: "RUN-002-ACT-AMENDMENT" }) }),
    ];

    const reported = new Set(bindings.flatMap((b) => evaluateDecisionEligibility(b).blockers));
    expect(reported.size).toBe(Object.keys(DECISION_BLOCKER_MESSAGE).length);
    for (const blocker of reported) {
      expect(DECISION_BLOCKER_MESSAGE[blocker].length).toBeGreaterThan(0);
    }
  });
});

describe("canSubmitDecision", () => {
  it("mirrors the eligibility for each decision", () => {
    const ready = evaluateDecisionEligibility(loaded());
    expect(canSubmitDecision(ready, "approve")).toBe(true);
    expect(canSubmitDecision(ready, "reject")).toBe(true);

    const previewFailed = evaluateDecisionEligibility(loaded({ preview: null }));
    expect(canSubmitDecision(previewFailed, "approve")).toBe(false);
    expect(canSubmitDecision(previewFailed, "reject")).toBe(true);

    const nothingLoaded = evaluateDecisionEligibility({
      approval: null,
      finding: null,
      action: null,
      preview: null,
    });
    expect(canSubmitDecision(nothingLoaded, "approve")).toBe(false);
    expect(canSubmitDecision(nothingLoaded, "reject")).toBe(false);
  });
});
