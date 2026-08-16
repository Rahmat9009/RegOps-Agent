// mockData.ts — Synthetic fixtures for the overseas-recruitment fee-rule scenario.
//
// ALL records are synthetic and labeled as such. Every object here conforms to a
// schema in contracts/openapi.yaml; there are no extra fields.

import type {
  Approval,
  AuditReport,
  CounterfactualPreview,
  EvidenceReference,
  Finding,
  FindingSummary,
  ProposedAction,
  Run,
  RunState,
} from "./types";

export const SYNTHETIC_NOTICE =
  "Synthetic demonstration data — not real contracts, cases, or persons.";

export const SHADOW_COPY_NOTICE =
  "Approval records an APPROVED_DRAFT amendment against a synthetic contract's shadow copy. It does not modify any real contract and does not determine legal compliance.";

/* --------------------------------------------------------------- evidence */

const regulationEvidence: EvidenceReference = {
  doc_id: "REG-2026-0417",
  doc_kind: "regulation",
  page: 3,
  quote:
    "No licensed recruitment agency shall charge a migrant worker any placement fee; permissible costs are limited to those defined in §4(b).",
};

const contractEvidence: EvidenceReference = {
  doc_id: "CNT-0001",
  doc_kind: "contract",
  page: 2,
  quote:
    "The Worker agrees to pay a placement fee of BDT 45,000 to the Agency prior to deployment.",
};

const caseEvidence: EvidenceReference = {
  doc_id: "CASE-0142",
  doc_kind: "case",
  page: 1,
  quote:
    "Deployment file records a collected placement fee of BDT 45,000 under contract CNT-0001, receipt dated 2026-06-14.",
};

const policyEvidence: EvidenceReference = {
  doc_id: "POL-0007",
  doc_kind: "policy",
  page: 5,
  quote:
    "Agency fee schedules are reviewed annually and published in Appendix C of the recruitment operations manual.",
};

/* -------------------------------------------------------- pipeline script */

/**
 * The ordered states the mock walks through before approval. FAILED_RECOVERABLE
 * appears once mid-mapping and resolves on retry, which is exactly how the
 * contract describes it: transient, followed by a later state.
 */
export const MOCK_PRE_APPROVAL_STATES: RunState[] = [
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
];

/** States after a human approves. A rejection ends the run at FAILED instead. */
export const MOCK_POST_APPROVAL_STATES: RunState[] = ["EXECUTING", "REVALIDATING", "COMPLETED"];

/** Documents and partitions processed by the time each state is reached. */
export const MOCK_PROGRESS_BY_STATE: Partial<
  Record<RunState, { documents_processed: number; partitions_complete: number; percent: number }>
> = {
  INGESTED: { documents_processed: 0, partitions_complete: 0, percent: 0 },
  EXTRACTING: { documents_processed: 1, partitions_complete: 0, percent: 5 },
  EXTRACTED: { documents_processed: 1, partitions_complete: 0, percent: 10 },
  MAPPING: { documents_processed: 148, partitions_complete: 3, percent: 49 },
  FAILED_RECOVERABLE: { documents_processed: 148, partitions_complete: 3, percent: 49 },
  MAPPED: { documents_processed: 300, partitions_complete: 6, percent: 100 },
  VERIFYING: { documents_processed: 300, partitions_complete: 6, percent: 100 },
  VERIFIED: { documents_processed: 300, partitions_complete: 6, percent: 100 },
  AWAITING_APPROVAL: { documents_processed: 300, partitions_complete: 6, percent: 100 },
  EXECUTING: { documents_processed: 300, partitions_complete: 6, percent: 100 },
  REVALIDATING: { documents_processed: 300, partitions_complete: 6, percent: 100 },
  COMPLETED: { documents_processed: 300, partitions_complete: 6, percent: 100 },
};

export const MOCK_APPROVAL_ID = "APR-0001";
export const MOCK_AMENDMENT_ACTION_ID = "ACT-0001";
export const MOCK_REVIEW_TASK_ACTION_ID = "ACT-0002";

/** Findings detected before any remediation. Shared by the audit and the preview. */
export const MOCK_BASELINE_FINDING_COUNT = 37;
/** Findings the approved amendment resolves. Rejection resolves none. */
export const MOCK_RESOLVED_ON_APPROVAL = 31;

/* ------------------------------------------------------------ constructors */

export function baseRun(runId: string, sourceFilename: string, createdAt: string): Run {
  return {
    run_id: runId,
    state: "INGESTED",
    created_at: createdAt,
    updated_at: createdAt,
    regulation: {
      reg_id: "REG-2026-0417",
      title: "Amendment to Overseas Worker Recruitment Fee Rules",
      jurisdiction: "BD",
      source_filename: sourceFilename,
      synthetic: true,
    },
    progress: {
      documents_total: 300,
      documents_processed: 0,
      partitions_total: 6,
      partitions_complete: 0,
      percent: 0,
    },
    findings_by_severity: { low: 0, medium: 0, high: 0 },
    pending_approvals: [],
    completed_actions: [],
  };
}

export function amendmentAction(runId: string, status: ProposedAction["status"]): ProposedAction {
  return {
    action_id: MOCK_AMENDMENT_ACTION_ID,
    finding_id: "FND-0001",
    type: "draft_amendment",
    autonomy: "approval_required",
    status,
    idempotency_key: `FND-0001:draft_amendment:${runId}`,
  };
}

export function reviewTaskAction(runId: string, status: ProposedAction["status"]): ProposedAction {
  return {
    action_id: MOCK_REVIEW_TASK_ACTION_ID,
    finding_id: "FND-0002",
    type: "create_review_task",
    autonomy: "auto",
    status,
    idempotency_key: `FND-0002:create_review_task:${runId}`,
  };
}

export function pendingApproval(runId: string): Approval {
  return {
    approval_id: MOCK_APPROVAL_ID,
    action_id: MOCK_AMENDMENT_ACTION_ID,
    run_id: runId,
    status: "PENDING",
    decided_at: null,
    decided_by: null,
    note: null,
  };
}

/* --------------------------------------------------------------- findings */

export function mockFindingSummaries(runId: string): FindingSummary[] {
  return [
    {
      finding_id: "FND-0001",
      run_id: runId,
      target_id: "CNT-0001#clause-7.2",
      relationship: "conflicts_with",
      severity: "high",
      verdict: "survived",
      status: "AWAITING_APPROVAL",
      human_review_required: true,
    },
    {
      finding_id: "FND-0002",
      run_id: runId,
      target_id: "CASE-0142",
      relationship: "requires_update",
      severity: "medium",
      verdict: "survived",
      status: "OPEN",
      human_review_required: false,
    },
    {
      finding_id: "FND-0003",
      run_id: runId,
      target_id: "POL-0007#section-3",
      relationship: "requires_update",
      severity: "low",
      verdict: "uncertain",
      status: "OPEN",
      human_review_required: true,
    },
    {
      finding_id: "FND-0004",
      run_id: runId,
      target_id: "CNT-0044#clause-2.1",
      relationship: "no_impact",
      severity: "low",
      verdict: "refuted",
      status: "RESOLVED",
      human_review_required: false,
    },
  ];
}

/** Free-text corpus per finding, so `q` can search obligation text as the contract describes. */
const FINDING_SEARCH_TEXT: Record<string, string> = {
  "FND-0001": "placement fee prohibition migrant worker recruitment agency clause 7.2 contract",
  "FND-0002": "deployment case worker fee collected prior rule review task",
  "FND-0003": "policy fee schedule appendix annual review section 3",
  "FND-0004": "medical examination cost employer paid no impact",
};

export function findingSearchText(findingId: string): string {
  return FINDING_SEARCH_TEXT[findingId] ?? "";
}

export function mockFindingDetail(runId: string, findingId: string): Finding | undefined {
  const summary = mockFindingSummaries(runId).find((f) => f.finding_id === findingId);
  if (!summary) return undefined;

  switch (findingId) {
    case "FND-0001":
      return {
        ...summary,
        obligation: {
          obligation_id: "OBL-2026-0417-02",
          statement: "Placement fees charged to migrant workers are prohibited (limit: BDT 0).",
          type: "prohibition",
          exceptions: ["Employer-paid administrative costs as defined in §4(b)."],
          effective_date: "2026-10-01",
          evidence: [regulationEvidence],
        },
        affected_case: {
          case_id: "CASE-0142",
          summary:
            "Active deployment file referencing contract CNT-0001; worker fee collected under the prior rule.",
          signed_date: "2026-06-12",
          synthetic: true,
        },
        evidence_path: [regulationEvidence, contractEvidence, caseEvidence],
        scores: {
          evidence_strength: 0.91,
          source_authority: "primary_government",
          interpretation_confidence: 0.63,
          operational_severity: "high",
          human_review_required: true,
        },
        proposed_action: amendmentAction(runId, "AWAITING_APPROVAL"),
      };

    case "FND-0002":
      return {
        ...summary,
        obligation: {
          obligation_id: "OBL-2026-0417-02",
          statement: "Placement fees charged to migrant workers are prohibited (limit: BDT 0).",
          type: "prohibition",
          exceptions: ["Employer-paid administrative costs as defined in §4(b)."],
          effective_date: "2026-10-01",
          evidence: [regulationEvidence],
        },
        affected_case: {
          case_id: "CASE-0142",
          summary:
            "Deployment file requires a fee-reconciliation review before the rule takes effect.",
          signed_date: "2026-06-12",
          synthetic: true,
        },
        evidence_path: [regulationEvidence, caseEvidence],
        scores: {
          evidence_strength: 0.78,
          source_authority: "primary_government",
          interpretation_confidence: 0.71,
          operational_severity: "medium",
          human_review_required: false,
        },
        proposed_action: reviewTaskAction(runId, "PENDING"),
      };

    case "FND-0003":
      return {
        ...summary,
        obligation: {
          obligation_id: "OBL-2026-0417-05",
          statement:
            "Published fee schedules must be reissued within 30 days of a fee-rule amendment.",
          type: "requirement",
          exceptions: [],
          effective_date: "2026-10-01",
          evidence: [regulationEvidence],
        },
        affected_case: null,
        evidence_path: [regulationEvidence, policyEvidence],
        scores: {
          evidence_strength: 0.54,
          source_authority: "internal",
          interpretation_confidence: 0.41,
          operational_severity: "low",
          human_review_required: true,
        },
        proposed_action: null,
      };

    case "FND-0004":
      return {
        ...summary,
        obligation: {
          obligation_id: "OBL-2026-0417-09",
          statement:
            "Employer-paid medical examination costs remain permissible under the amended rule.",
          type: "exception",
          exceptions: [],
          effective_date: "2026-10-01",
          evidence: [regulationEvidence],
        },
        affected_case: null,
        evidence_path: [regulationEvidence],
        scores: {
          evidence_strength: 0.88,
          source_authority: "primary_government",
          interpretation_confidence: 0.86,
          operational_severity: "low",
          human_review_required: false,
        },
        proposed_action: null,
      };

    default:
      return undefined;
  }
}

/* --------------------------------------------------------- counterfactual */

export function mockCounterfactual(actionId: string, runId: string): CounterfactualPreview {
  return {
    action_id: actionId,
    shadow_run_id: `SHADOW-${runId}`,
    baseline_finding_count: MOCK_BASELINE_FINDING_COUNT,
    // Illustrative IDs. In the real backend these come from rerunning the same
    // matching and validation pipeline against the shadow copy.
    resolved_finding_ids: Array.from(
      { length: MOCK_RESOLVED_ON_APPROVAL },
      (_, i) => `FND-${String(i + 1).padStart(4, "0")}`,
    ),
    unchanged_finding_ids: ["FND-0032", "FND-0033", "FND-0034", "FND-0035"],
    new_conflict_ids: ["FND-1001", "FND-1002"],
    remaining_high_risk_ids: ["FND-0033"],
    detected_finding_picture_improves: true,
    narrative:
      "Applying the fee-prohibition amendment to the shadow copy resolves 31 of 37 detected findings. Four are unchanged (non-fee clauses) and two new conflicts appear where the amendment references a superseded cost schedule.",
  };
}

/* ----------------------------------------------------------------- audit */

/** The business outcome of the run's approval decision. */
export type RunOutcome = "approved" | "rejected";

/**
 * A rejection is a valid terminal business outcome, not a failure: the run still
 * completes, the automatic review task still executed, and the rejected amendment
 * is absent from `executed_actions` because it was never executed. Nothing is
 * resolved, so every baseline finding remains.
 */
export function mockAudit(
  runId: string,
  generatedAt: string,
  outcome: RunOutcome = "approved",
): AuditReport {
  const approved = outcome === "approved";
  const resolved = approved ? MOCK_RESOLVED_ON_APPROVAL : 0;

  return {
    run_id: runId,
    generated_at: generatedAt,
    executed_actions: approved
      ? [amendmentAction(runId, "APPROVED_DRAFT"), reviewTaskAction(runId, "EXECUTED")]
      : [reviewTaskAction(runId, "EXECUTED")],
    idempotency: { duplicate_actions_prevented: 1, duplicate_action_rate: 0 },
    revalidation: {
      findings_resolved: resolved,
      findings_remaining: MOCK_BASELINE_FINDING_COUNT - resolved,
    },
    processing: { total_seconds: 268.4, documents_processed: 300 },
    evaluation: {
      obligation_precision: 0.94,
      impact_precision: 0.9,
      impact_recall: 0.86,
      citation_correctness: 1.0,
      false_escalation_rate: 0.05,
      resume_success_rate: 1.0,
    },
    audit_package_url: null,
  };
}
