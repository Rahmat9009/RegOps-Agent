// mockData.ts — Realistic synthetic fixtures for the Bangladesh overseas-recruitment
// fee-rule scenario. ALL synthetic and labeled. Timestamps are fixed strings so the
// UI is deterministic; the mock adapter advances run state on a timer.

import type {
  Run,
  Finding,
  FindingSummary,
  CounterfactualPreview,
  AuditReport,
  Evidence,
} from "./types";

export const SYNTHETIC_NOTICE =
  "Synthetic demonstration data — not real contracts, cases, or persons.";

const regEvidence: Evidence = {
  doc_id: "REG-2026-0417",
  doc_kind: "regulation",
  page: 3,
  quote:
    "No licensed recruitment agency shall charge a migrant worker any placement fee; permissible costs are limited to those defined in §4(b).",
};

const contractEvidence: Evidence = {
  doc_id: "CNT-0001",
  doc_kind: "contract",
  page: 2,
  quote:
    "The Worker agrees to pay a placement fee of BDT 45,000 to the Agency prior to deployment.",
};

// The ordered pipeline states the mock adapter walks through.
export const MOCK_RUN_SEQUENCE: Run["state"][] = [
  "INGESTED",
  "EXTRACTING",
  "EXTRACTED",
  "MAPPING",
  "MAPPED",
  "VERIFYING",
  "VERIFIED",
  "AWAITING_APPROVAL",
  // -> approval decision moves it to EXECUTING (handled by the adapter)
  "EXECUTING",
  "REVALIDATING",
  "COMPLETED",
];

export function baseRun(runId: string): Run {
  return {
    run_id: runId,
    state: "INGESTED",
    created_at: "2026-08-16T09:00:00Z",
    updated_at: "2026-08-16T09:00:00Z",
    regulation: {
      reg_id: "REG-2026-0417",
      title: "Amendment to Overseas Worker Recruitment Fee Rules",
      jurisdiction: "BD",
      synthetic: true,
    },
    change_detection: {
      result: "new_version",
      content_hash: "sha256:9f2c…a41",
      supersedes: "REG-2024-0031",
      version: 3,
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
    recovery: null,
    timeline: [
      {
        ts: "2026-08-16T09:00:00Z",
        agent: "change_detector",
        state: "INGESTED",
        message: "New regulation version detected (supersedes REG-2024-0031).",
      },
    ],
  };
}

export const MOCK_FINDING_SUMMARIES: FindingSummary[] = [
  {
    finding_id: "FND-0001",
    run_id: "RUN-demo",
    target_id: "CNT-0001#clause-7.2",
    relationship: "conflicts_with",
    severity: "high",
    verdict: "survived",
    status: "AWAITING_APPROVAL",
    human_review_required: true,
  },
  {
    finding_id: "FND-0002",
    run_id: "RUN-demo",
    target_id: "CASE-0142",
    relationship: "requires_update",
    severity: "medium",
    verdict: "survived",
    status: "OPEN",
    human_review_required: false,
  },
  {
    finding_id: "FND-0003",
    run_id: "RUN-demo",
    target_id: "POL-0007#section-3",
    relationship: "requires_update",
    severity: "low",
    verdict: "uncertain",
    status: "OPEN",
    human_review_required: true,
  },
];

export const MOCK_FINDING_DETAIL: Record<string, Finding> = {
  "FND-0001": {
    ...MOCK_FINDING_SUMMARIES[0],
    obligation: {
      obligation_id: "OBL-2026-0417-02",
      statement:
        "Placement fees charged to migrant workers are prohibited (limit: BDT 0).",
      type: "prohibition",
      exceptions: ["Employer-paid administrative costs as defined in §4(b)."],
      effective_date: "2026-10-01",
      evidence: regEvidence,
    },
    affected_case: {
      case_id: "CASE-0142",
      summary:
        "Active deployment file referencing contract CNT-0001; worker fee collected under prior rule.",
      signed_date: "2026-06-12",
    },
    evidence_path: [regEvidence, contractEvidence],
    scores: {
      evidence_strength: 0.91,
      source_authority: "primary_government",
      interpretation_confidence: 0.63,
      operational_severity: "high",
      human_review_required: true,
    },
    proposed_action: {
      action_id: "ACT-0001",
      finding_id: "FND-0001",
      type: "draft_amendment",
      autonomy: "approval_required",
      status: "AWAITING_APPROVAL",
      idempotency_key: "FND-0001:draft_amendment:RUN-demo",
    },
  },
};

export const MOCK_COUNTERFACTUAL: CounterfactualPreview = {
  action_id: "ACT-0001",
  simulation: "shadow_state",
  findings_before: 37,
  // Illustrative IDs; in the real backend these are computed by rerunning the pipeline.
  resolved: Array.from({ length: 31 }, (_, i) => `FND-${String(i + 1).padStart(4, "0")}`),
  unchanged: ["FND-0020", "FND-0021", "FND-0033", "FND-0034"],
  new_conflicts: ["FND-1001", "FND-1002"],
  remaining_high_risk: ["FND-0033"],
  detected_finding_picture_improves: true,
  narrative:
    "Applying the fee-prohibition amendment to the shadow copy resolves 31 of 37 detected findings. Four remain unchanged (non-fee clauses) and two new conflicts appear where the amendment references a superseded cost schedule. Shadow-state simulation only.",
};

export function mockAudit(runId: string): AuditReport {
  return {
    run_id: runId,
    generated_at: "2026-08-16T09:04:30Z",
    executed_actions: [
      {
        action_id: "ACT-0001",
        finding_id: "FND-0001",
        type: "draft_amendment",
        autonomy: "approval_required",
        status: "APPROVED_DRAFT",
        idempotency_key: "FND-0001:draft_amendment:RUN-demo",
      },
      {
        action_id: "ACT-0002",
        finding_id: "FND-0002",
        type: "create_review_task",
        autonomy: "auto",
        status: "EXECUTED",
        idempotency_key: "FND-0002:create_review_task:RUN-demo",
      },
    ],
    idempotency: { duplicate_actions_prevented: 1, duplicate_action_rate: 0 },
    revalidation: { findings_resolved: 31, findings_remaining: 6 },
    processing: { total_seconds: 268.4, documents_processed: 300 },
    evaluation: {
      obligation_precision: 0.94,
      impact_precision: 0.9,
      impact_recall: 0.86,
      citation_correctness: 1.0,
      false_escalation_rate: 0.05,
      resume_success_rate: 1.0,
    },
    audit_package_url: "#mock-audit-package",
  };
}
