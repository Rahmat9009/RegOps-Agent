// Guards against the Phase 1A workarounds creeping back in.
//
// The suite runs without a DOM, so these screens cannot be rendered here. What
// can be checked cheaply is the data access they declare: the findings list must
// not hydrate a row with `getFinding`, and the approval screen must not walk the
// finding list to discover which finding an action came from. Both workarounds
// were removed once the contract froze `FindingSummary.scores` and
// `Approval.finding_id`.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

function source(file: string): string {
  return readFileSync(fileURLToPath(new URL(file, import.meta.url)), "utf8");
}

describe("FindingsPage data access", () => {
  const code = source("./FindingsPage.tsx");

  it("does not hydrate scores with a per-row detail request", () => {
    expect(code).not.toContain("api.getFinding");
  });

  it("reads the score set straight off the summary", () => {
    expect(code).toContain("item.scores.evidence_strength");
    expect(code).toContain("item.scores.interpretation_confidence");
    expect(code).toContain("item.scores.source_authority");
  });

  it("requests a page rather than the whole result", () => {
    expect(code).toContain("limit: FINDINGS_PAGE_SIZE");
    expect(code).toContain("offset");
  });
});

describe("ApprovalPage data access", () => {
  const code = source("./ApprovalPage.tsx");

  it("reaches the finding through Approval.finding_id", () => {
    expect(code).toContain("api.getFinding(approval.finding_id)");
  });

  it("does not scan the run's findings for a matching action", () => {
    expect(code).not.toContain("api.listRunFindings");
    expect(code).not.toContain("findFindingForAction");
  });

  it("never constructs reviewer identity", () => {
    expect(code).not.toContain("decided_by:");
  });

  // The eligibility rule itself is tested in lib/approvalDecision.test.ts. What is
  // checked here is that this screen is actually wired to it — on both the submit
  // path and the controls — and invents nothing when a record is missing.
  it("guards the submit path, not only the buttons", () => {
    expect(code).toContain("canSubmitDecision(eligibility, value)");
    expect(code).toContain("evaluateDecisionEligibility");
  });

  it("disables each control according to its own eligibility", () => {
    expect(code).toContain("disabled={submitting !== null || !eligibility.canApprove}");
    expect(code).toContain("disabled={submitting !== null || !eligibility.canReject}");
  });

  it("explains what is missing instead of substituting a fallback", () => {
    expect(code).toContain("DECISION_BLOCKER_MESSAGE");
    // No invented action, finding, approval or reviewer identity.
    expect(code).not.toMatch(/\?\?\s*MOCK_/);
  });
});
