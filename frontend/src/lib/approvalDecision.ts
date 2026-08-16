// approvalDecision.ts — Whether a human decision may be recorded at all.
//
// A decision is a consequential act, so it must never be submitted against
// evidence the console could not load. This module is the single place that
// decides, so the buttons' `disabled` state and the submit guard cannot drift
// apart: `evaluateDecisionEligibility` is pure, takes only what the screen
// actually loaded, and never invents a substitute for a missing record.
//
// The two decisions are deliberately not symmetrical:
//   - Approving executes something. It needs the exact bound finding, the exact
//     proposed action AND the deterministic counterfactual preview.
//   - Rejecting executes nothing. It needs the binding and its evidence, but a
//     failed preview must not trap a reviewer into approving by default.

import type { Approval, CounterfactualPreview, Finding, ProposedAction } from "@/lib/api";

/** Exactly what the approval screen managed to load. Nulls are real failures. */
export interface ApprovalBinding {
  /** The pending approval being decided, or null when none is pending. */
  approval: Approval | null;
  /** The finding named by `Approval.finding_id`, or null when it failed to load. */
  finding: Finding | null;
  /** The proposed action carried by that finding, or null when absent. */
  action: ProposedAction | null;
  /** The counterfactual preview for that action, or null when it failed to load. */
  preview: CounterfactualPreview | null;
}

/** Why a decision is unavailable. Each maps to one message on screen. */
export type DecisionBlocker =
  | "no_pending_approval"
  | "finding_missing"
  | "finding_mismatch"
  | "action_missing"
  | "action_mismatch"
  | "preview_missing"
  | "preview_mismatch";

export interface DecisionEligibility {
  /** True only when the binding, its evidence and the preview all loaded. */
  canApprove: boolean;
  /** True when the binding and its evidence loaded; the preview is not required. */
  canReject: boolean;
  /** Everything missing or inconsistent, in the order it is checked. */
  blockers: DecisionBlocker[];
}

/** Human-readable, colour-independent explanation for each blocker. */
export const DECISION_BLOCKER_MESSAGE: Record<DecisionBlocker, string> = {
  no_pending_approval:
    "This run has no approval pending under this id, so there is nothing to decide.",
  finding_missing:
    "The finding this approval is bound to could not be loaded, so neither decision can be recorded.",
  finding_mismatch:
    "The finding that loaded is not the one this approval names, so neither decision can be recorded.",
  action_missing:
    "The proposed action for this finding could not be loaded, so neither decision can be recorded.",
  action_mismatch:
    "The action on this finding is not the one this approval names, so neither decision can be recorded.",
  preview_missing:
    "The deterministic counterfactual preview could not be loaded, so this action cannot be approved. Rejecting stays available: it executes nothing.",
  preview_mismatch:
    "The counterfactual preview describes a different action, so this action cannot be approved. Rejecting stays available: it executes nothing.",
};

/**
 * Decide what this reviewer may do, from what actually loaded.
 *
 * Every check is an exact identifier match against the approval the API
 * returned — nothing is inferred from position, recency or substrings.
 */
export function evaluateDecisionEligibility(binding: ApprovalBinding): DecisionEligibility {
  const { approval, finding, action, preview } = binding;
  const blockers: DecisionBlocker[] = [];

  if (!approval) {
    return { canApprove: false, canReject: false, blockers: ["no_pending_approval"] };
  }

  if (!finding) {
    blockers.push("finding_missing");
  } else if (finding.finding_id !== approval.finding_id) {
    blockers.push("finding_mismatch");
  }

  if (!action) {
    blockers.push("action_missing");
  } else if (action.action_id !== approval.action_id) {
    blockers.push("action_mismatch");
  } else if (finding && action.finding_id !== finding.finding_id) {
    blockers.push("action_mismatch");
  }

  // Rejection executes nothing, so it only needs the binding and its evidence.
  const canReject = blockers.length === 0;

  if (!preview) {
    blockers.push("preview_missing");
  } else if (preview.action_id !== approval.action_id) {
    blockers.push("preview_mismatch");
  }

  return { canApprove: blockers.length === 0, canReject, blockers };
}

/** Whether one specific decision may be submitted. Used by the submit guard. */
export function canSubmitDecision(
  eligibility: DecisionEligibility,
  decision: "approve" | "reject",
): boolean {
  return decision === "approve" ? eligibility.canApprove : eligibility.canReject;
}
