// mockData.ts — Synthetic fixtures for the overseas-recruitment fee-rule scenario.
//
// ALL records are synthetic and labeled as such. Every object here conforms to a
// schema in contracts/openapi.yaml (Phase 1B freeze); there are no extra fields.
//
// The corpus is deliberately large enough to exercise pagination: the run detects
// MOCK_BASELINE_FINDING_COUNT findings, which is also the baseline the audit and
// the counterfactual preview report.
//
// Identity rule: every record a run OWNS — its findings, actions, approvals and
// shadow snapshot — carries a globally unique, run-scoped id of the form
// `RUN-001-FND-0001`. The API's resource ids are global (`GET /findings/{id}`,
// `POST /actions/{id}/preview` take no run), so two concurrent demo runs must not
// share them, or a link into the older run would resolve against the newer one.
// Evidence documents (regulation, contract, policy, case ids) are deliberately
// NOT scoped: they are the same synthetic corpus records for every run.

import type {
  AffectedCase,
  Approval,
  AuditReport,
  ChangeDetection,
  CounterfactualPreview,
  EvidenceReference,
  Finding,
  FindingScores,
  FindingsBySeverity,
  FindingSummary,
  Obligation,
  ProposedAction,
  RecoveryInfo,
  Run,
  RunState,
  RunTransition,
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

/* ------------------------------------------------------------ obligations */

const feeProhibition: Obligation = {
  obligation_id: "OBL-2026-0417-02",
  statement: "Placement fees charged to migrant workers are prohibited (limit: BDT 0).",
  type: "prohibition",
  exceptions: ["Employer-paid administrative costs as defined in §4(b)."],
  effective_date: "2026-10-01",
  evidence: [regulationEvidence],
};

const scheduleRequirement: Obligation = {
  obligation_id: "OBL-2026-0417-05",
  statement: "Published fee schedules must be reissued within 30 days of a fee-rule amendment.",
  type: "requirement",
  exceptions: [],
  effective_date: "2026-10-01",
  evidence: [regulationEvidence],
};

const medicalException: Obligation = {
  obligation_id: "OBL-2026-0417-09",
  statement: "Employer-paid medical examination costs remain permissible under the amended rule.",
  type: "exception",
  exceptions: [],
  effective_date: "2026-10-01",
  evidence: [regulationEvidence],
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

/** States after a human approves: the amendment is executed and revalidated. */
export const MOCK_POST_APPROVAL_STATES: RunState[] = ["EXECUTING", "REVALIDATING", "COMPLETED"];

/**
 * States after a human rejects. Rejection executes nothing, so the run moves
 * straight from AWAITING_APPROVAL to COMPLETED: never through EXECUTING or
 * REVALIDATING, and never to FAILED.
 */
export const MOCK_POST_REJECTION_STATES: RunState[] = ["COMPLETED"];

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

/* ------------------------------------------------------------- identity */

/**
 * Compose a run-scoped resource id. `localId` identifies the record within its
 * run (`FND-0001`); the returned id is globally unique (`RUN-001-FND-0001`).
 */
export function scopeToRun(runId: string, localId: string): string {
  return `${runId}-${localId}`;
}

/**
 * The exact inverse of `scopeToRun`: the run-local id when `id` is owned by
 * `runId`, and `null` otherwise. This is a whole-prefix match, never a substring
 * search, so one run's id can never resolve inside another run.
 */
export function localIdForRun(runId: string, id: string): string | null {
  const prefix = `${runId}-`;
  return id.startsWith(prefix) ? id.slice(prefix.length) : null;
}

/** Run-local ids. These are only ever read through the helpers below. */
const LOCAL_APPROVAL_ID = "APR-0001";
const LOCAL_AMENDMENT_ACTION_ID = "ACT-AMENDMENT";
const LOCAL_REVIEW_TASK_ACTION_ID = "ACT-REVIEW";
/** The finding the proposed amendment targets. */
const LOCAL_AMENDMENT_FINDING_ID = "FND-0001";
/** The finding the automatic review task targets. */
const LOCAL_REVIEW_TASK_FINDING_ID = "FND-0002";

export function mockApprovalId(runId: string): string {
  return scopeToRun(runId, LOCAL_APPROVAL_ID);
}

export function mockAmendmentActionId(runId: string): string {
  return scopeToRun(runId, LOCAL_AMENDMENT_ACTION_ID);
}

export function mockReviewTaskActionId(runId: string): string {
  return scopeToRun(runId, LOCAL_REVIEW_TASK_ACTION_ID);
}

/** Every action id this run owns, in the order the run produces them. */
export function mockActionIds(runId: string): string[] {
  return [mockAmendmentActionId(runId), mockReviewTaskActionId(runId)];
}

export function mockAmendmentFindingId(runId: string): string {
  return scopeToRun(runId, LOCAL_AMENDMENT_FINDING_ID);
}

export function mockReviewTaskFindingId(runId: string): string {
  return scopeToRun(runId, LOCAL_REVIEW_TASK_FINDING_ID);
}

/** The discarded shadow snapshot a counterfactual preview runs against. */
export function mockShadowRunId(runId: string): string {
  return scopeToRun(runId, "SHADOW");
}

/* ------------------------------------------------------------ transitions */

/**
 * Safe transition labels. These describe recorded state changes only — never
 * prompts, model reasoning, stack traces, credentials, or infrastructure detail.
 */
export const MOCK_TRANSITION_REASONS: Record<RunState, string> = {
  INGESTED: "Synthetic regulation accepted; run created.",
  EXTRACTING: "Obligation extraction started.",
  EXTRACTED: "Obligations and their citations were recorded.",
  MAPPING: "Corpus matching started.",
  MAPPED: "Candidate findings were produced.",
  VERIFYING: "Refutation pass started.",
  VERIFIED: "Verdicts were assigned to the candidate findings.",
  AWAITING_APPROVAL: "A consequential action paused for a human decision.",
  EXECUTING: "Approved and automatic actions queued for idempotent execution.",
  REVALIDATING: "Rerunning the pipeline to confirm which findings were resolved.",
  COMPLETED: "Run finished; the audit report is available.",
  FAILED_RECOVERABLE: "A partition failed; a checkpoint retry was scheduled.",
  FAILED: "The run stopped and cannot continue.",
};

/** Backend-assigned actor labels used by the mock. */
export const MOCK_PIPELINE_ACTOR = "regops-orchestrator";
export const MOCK_REVIEWER_ACTOR = "demo-reviewer";

export function mockTransition(
  from: RunState | null,
  to: RunState,
  occurredAt: string,
  options: { actor?: string; reason?: string } = {},
): RunTransition {
  return {
    from_state: from,
    to_state: to,
    occurred_at: occurredAt,
    reason: options.reason ?? MOCK_TRANSITION_REASONS[to],
    actor: options.actor ?? MOCK_PIPELINE_ACTOR,
  };
}

/* -------------------------------------------------------------- recovery */

/** The recoverable failure the mock injects once during mapping. */
export function mockRecovery(available: boolean): RecoveryInfo {
  return {
    recovery_available: available,
    // recovery_available=true requires a non-null checkpoint; the mock keeps the
    // checkpoint after the resume so the console can report what it resumed from.
    checkpoint_state: "MAPPING",
    attempt_count: 1,
    last_error_code: "partition_timeout",
    last_error_message:
      "A corpus partition exceeded its processing window and was retried from the last checkpoint.",
  };
}

/* ------------------------------------------------------- change detection */

/**
 * A deterministic 64-character lowercase hex value derived from `seed`.
 *
 * It is a synthetic stand-in that satisfies the contract's SHA-256 pattern — it
 * is NOT a cryptographic digest and never identifies a real document.
 */
export function syntheticSha256(seed: string): string {
  let digest = "";
  for (let block = 0; block < 8; block += 1) {
    // `>>> 0` keeps the accumulator unsigned; a signed int32 would render as a
    // negative value rather than hex.
    let hash = (0x811c9dc5 ^ block) >>> 0;
    for (let index = 0; index < seed.length; index += 1) {
      hash ^= seed.charCodeAt(index);
      hash = Math.imul(hash, 0x01000193) >>> 0;
    }
    digest += hash.toString(16).padStart(8, "0");
  }
  return digest;
}

export function mockChangeDetection(sourceFilename: string, detectedAt: string): ChangeDetection {
  return {
    source_sha256: syntheticSha256(`source:${sourceFilename}`),
    previous_source_sha256: syntheticSha256("source:overseas-worker-fee-rules-2025.pdf"),
    changed: true,
    detected_at: detectedAt,
  };
}

/* --------------------------------------------------------------- findings */

/** Findings detected before any remediation. */
export const MOCK_BASELINE_FINDING_COUNT = 37;
/** Findings the approved amendment resolves. Rejection resolves none. */
export const MOCK_RESOLVED_ON_APPROVAL = 31;

/** The run-local finding id for a 1-based corpus position. */
function localFindingId(index: number): string {
  return `FND-${String(index).padStart(4, "0")}`;
}

/** Run-local ids of the findings the shadow rerun no longer detects. */
const LOCAL_RESOLVED_FINDING_IDS: string[] = Array.from(
  { length: MOCK_RESOLVED_ON_APPROVAL },
  (_, index) => localFindingId(index + 1),
);

/** Run-local ids of the findings still detected after the simulated change. */
const LOCAL_UNCHANGED_FINDING_IDS: string[] = Array.from(
  { length: MOCK_BASELINE_FINDING_COUNT - MOCK_RESOLVED_ON_APPROVAL },
  (_, index) => localFindingId(MOCK_RESOLVED_ON_APPROVAL + index + 1),
);

/**
 * Run-local ids of conflicts that would appear only because of the amendment.
 * They are outside the detected corpus — that is what makes them new.
 */
const LOCAL_NEW_CONFLICT_IDS = ["FND-1001", "FND-1002"];

/** Findings the shadow rerun no longer detects once the amendment is applied. */
export function mockResolvedFindingIds(runId: string): string[] {
  return LOCAL_RESOLVED_FINDING_IDS.map((id) => scopeToRun(runId, id));
}

/** Findings still detected after the simulated change. */
export function mockUnchangedFindingIds(runId: string): string[] {
  return LOCAL_UNCHANGED_FINDING_IDS.map((id) => scopeToRun(runId, id));
}

/** Conflicts that would appear only because of the amendment. */
export function mockNewConflictIds(runId: string): string[] {
  return LOCAL_NEW_CONFLICT_IDS.map((id) => scopeToRun(runId, id));
}

/**
 * One finding's full record. The blueprint set is shared by every mock run: the
 * run id and the run-scoped `finding_id` are stamped on when the record is read,
 * which is what keeps two concurrent runs from sharing an identifier.
 */
interface FindingBlueprint {
  /** Position within the run's corpus, e.g. `FND-0001`. Never global. */
  local_id: string;
  summary: Omit<FindingSummary, "run_id" | "finding_id">;
  obligation: Obligation;
  affected_case: AffectedCase | null;
  evidence_path: EvidenceReference[];
  action: "amendment" | "review_task" | null;
  /** Free-text corpus so `q` can search obligation text as the contract describes. */
  searchText: string;
}

const HAND_WRITTEN_BLUEPRINTS: FindingBlueprint[] = [
  {
    local_id: "FND-0001",
    summary: {
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
    },
    obligation: feeProhibition,
    affected_case: {
      case_id: "CASE-0142",
      summary:
        "Active deployment file referencing contract CNT-0001; worker fee collected under the prior rule.",
      signed_date: "2026-06-12",
      synthetic: true,
    },
    evidence_path: [regulationEvidence, contractEvidence, caseEvidence],
    action: "amendment",
    searchText:
      "placement fee prohibition migrant worker recruitment agency clause 7.2 contract",
  },
  {
    local_id: "FND-0002",
    summary: {
      target_id: "CASE-0142",
      relationship: "requires_update",
      severity: "medium",
      verdict: "survived",
      status: "OPEN",
      human_review_required: false,
      scores: {
        evidence_strength: 0.78,
        source_authority: "primary_government",
        interpretation_confidence: 0.71,
        operational_severity: "medium",
        human_review_required: false,
      },
    },
    obligation: feeProhibition,
    affected_case: {
      case_id: "CASE-0142",
      summary: "Deployment file requires a fee-reconciliation review before the rule takes effect.",
      signed_date: "2026-06-12",
      synthetic: true,
    },
    evidence_path: [regulationEvidence, caseEvidence],
    action: "review_task",
    searchText: "deployment case worker fee collected prior rule review task",
  },
  {
    local_id: "FND-0003",
    summary: {
      target_id: "POL-0007#section-3",
      relationship: "requires_update",
      severity: "low",
      verdict: "uncertain",
      status: "OPEN",
      human_review_required: true,
      scores: {
        evidence_strength: 0.54,
        source_authority: "internal",
        interpretation_confidence: 0.41,
        operational_severity: "low",
        human_review_required: true,
      },
    },
    obligation: scheduleRequirement,
    affected_case: null,
    evidence_path: [regulationEvidence, policyEvidence],
    action: null,
    searchText: "policy fee schedule appendix annual review section 3",
  },
  {
    local_id: "FND-0004",
    summary: {
      target_id: "CNT-0044#clause-2.1",
      relationship: "no_impact",
      severity: "low",
      verdict: "refuted",
      status: "RESOLVED",
      human_review_required: false,
      scores: {
        evidence_strength: 0.88,
        source_authority: "primary_government",
        interpretation_confidence: 0.86,
        operational_severity: "low",
        human_review_required: false,
      },
    },
    obligation: medicalException,
    affected_case: null,
    evidence_path: [regulationEvidence],
    action: null,
    searchText: "medical examination cost employer paid no impact",
  },
];

/** Synthetic clause quotes reused across the generated part of the corpus. */
const GENERATED_QUOTES = [
  "Recruitment service charges are recovered from the Worker's first three salary payments.",
  "The Agency may retain a documentation handling charge payable by the Worker on signature.",
  "Fee schedules annexed to this agreement remain in force until the Agency issues a revision.",
];

function generatedScores(index: number, severity: FindingSummary["severity"]): FindingScores {
  const authorities: FindingScores["source_authority"][] = [
    "primary_government",
    "secondary",
    "internal",
  ];
  return {
    evidence_strength: round2(0.6 + ((index * 7) % 30) / 100),
    source_authority: authorities[index % authorities.length] ?? "primary_government",
    interpretation_confidence: round2(0.45 + ((index * 13) % 45) / 100),
    operational_severity: severity,
    human_review_required: severity === "high",
  };
}

/**
 * The remainder of the detected corpus. Values are derived deterministically from
 * the index so every mock run reports the same synthetic picture.
 */
function generatedBlueprint(index: number): FindingBlueprint {
  const severity: FindingSummary["severity"] =
    index % 7 === 0 ? "high" : index % 3 === 0 ? "medium" : "low";
  const verdict: FindingSummary["verdict"] = index % 11 === 0 ? "uncertain" : "survived";
  const relationship: FindingSummary["relationship"] =
    severity === "high" ? "conflicts_with" : index % 5 === 0 ? "no_impact" : "requires_update";
  const humanReview = severity === "high" || verdict === "uncertain";
  const contractId = `CNT-${String(1000 + index).padStart(4, "0")}`;
  const clause = `${(index % 9) + 1}.${(index % 4) + 1}`;
  const quote = GENERATED_QUOTES[index % GENERATED_QUOTES.length] as string;
  const obligation = index % 4 === 0 ? scheduleRequirement : feeProhibition;

  const clauseEvidence: EvidenceReference = {
    doc_id: contractId,
    doc_kind: "contract",
    page: (index % 8) + 1,
    quote,
  };

  const affectedCase: AffectedCase | null =
    index % 4 === 1
      ? {
          case_id: `CASE-${String(200 + index).padStart(4, "0")}`,
          summary: `Synthetic deployment file referencing contract ${contractId} under the prior fee rule.`,
          signed_date: "2026-05-04",
          synthetic: true,
        }
      : null;

  return {
    local_id: localFindingId(index),
    summary: {
      target_id: `${contractId}#clause-${clause}`,
      relationship,
      severity,
      verdict,
      status: "OPEN",
      human_review_required: humanReview,
      scores: generatedScores(index, severity),
    },
    obligation,
    affected_case: affectedCase,
    evidence_path: affectedCase
      ? [
          regulationEvidence,
          clauseEvidence,
          {
            doc_id: affectedCase.case_id,
            doc_kind: "case",
            page: 1,
            quote: `Deployment file records a recruitment charge collected under contract ${contractId}.`,
          },
        ]
      : [regulationEvidence, clauseEvidence],
    action: null,
    searchText: `${contractId.toLowerCase()} clause ${clause} ${quote.toLowerCase()} ${obligation.statement.toLowerCase()}`,
  };
}

const BLUEPRINTS: FindingBlueprint[] = [
  ...HAND_WRITTEN_BLUEPRINTS,
  ...Array.from({ length: MOCK_BASELINE_FINDING_COUNT - HAND_WRITTEN_BLUEPRINTS.length }, (_, i) =>
    generatedBlueprint(i + HAND_WRITTEN_BLUEPRINTS.length + 1),
  ),
];

/** Exact run-local id -> blueprint index. No substring matching anywhere. */
const BLUEPRINTS_BY_LOCAL_ID = new Map(BLUEPRINTS.map((entry) => [entry.local_id, entry]));

/** Run-local ids of the high-severity findings the amendment does not resolve. */
const LOCAL_REMAINING_HIGH_RISK_IDS: string[] = LOCAL_UNCHANGED_FINDING_IDS.filter(
  (id) => BLUEPRINTS_BY_LOCAL_ID.get(id)?.summary.severity === "high",
);

/** High-severity findings the amendment does not resolve. */
export function mockRemainingHighRiskIds(runId: string): string[] {
  return LOCAL_REMAINING_HIGH_RISK_IDS.map((id) => scopeToRun(runId, id));
}

export function mockFindingSummaries(runId: string): FindingSummary[] {
  return BLUEPRINTS.map((entry) => ({
    ...entry.summary,
    finding_id: scopeToRun(runId, entry.local_id),
    run_id: runId,
  }));
}

/** Every finding id this run owns, for building an exact ownership index. */
export function mockFindingIds(runId: string): string[] {
  return BLUEPRINTS.map((entry) => scopeToRun(runId, entry.local_id));
}

/**
 * The searchable text behind one of `runId`'s findings. An id belonging to any
 * other run has no text here, so a cross-run id can never match a filter.
 */
export function findingSearchText(runId: string, findingId: string): string {
  const localId = localIdForRun(runId, findingId);
  if (localId === null) return "";
  return BLUEPRINTS_BY_LOCAL_ID.get(localId)?.searchText ?? "";
}

/** Severity counts across every detected finding, computed from the fixtures. */
export function mockFindingsBySeverity(): FindingsBySeverity {
  return countBySeverity(BLUEPRINTS.map((entry) => entry.summary.severity));
}

export function countBySeverity(
  severities: FindingSummary["severity"][],
): FindingsBySeverity {
  const counts: FindingsBySeverity = { low: 0, medium: 0, high: 0 };
  for (const severity of severities) counts[severity] += 1;
  return counts;
}

/**
 * The full record for one of `runId`'s findings. `findingId` must be run-scoped:
 * an id owned by another run resolves to `undefined` rather than to this run's
 * record at the same corpus position.
 */
export function mockFindingDetail(runId: string, findingId: string): Finding | undefined {
  const localId = localIdForRun(runId, findingId);
  if (localId === null) return undefined;
  const blueprint = BLUEPRINTS_BY_LOCAL_ID.get(localId);
  if (!blueprint) return undefined;

  return {
    ...blueprint.summary,
    finding_id: findingId,
    run_id: runId,
    obligation: blueprint.obligation,
    affected_case: blueprint.affected_case,
    evidence_path: blueprint.evidence_path,
    proposed_action:
      blueprint.action === "amendment"
        ? amendmentAction(runId, "AWAITING_APPROVAL")
        : blueprint.action === "review_task"
          ? reviewTaskAction(runId, "PENDING")
          : null,
  };
}

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
    // The contract requires at least one transition, and the first one always has
    // a null from_state.
    transitions: [mockTransition(null, "INGESTED", createdAt)],
    recovery: null,
    change_detection: mockChangeDetection(sourceFilename, createdAt),
    findings_by_severity: { low: 0, medium: 0, high: 0 },
    pending_approvals: [],
    completed_actions: [],
  };
}

// The idempotency key already carries the run: the finding id it is built from is
// run-scoped, so the same action in two runs cannot collide on it.
export function amendmentAction(runId: string, status: ProposedAction["status"]): ProposedAction {
  const findingId = mockAmendmentFindingId(runId);
  return {
    action_id: mockAmendmentActionId(runId),
    finding_id: findingId,
    type: "draft_amendment",
    autonomy: "approval_required",
    status,
    idempotency_key: `${findingId}:draft_amendment`,
  };
}

export function reviewTaskAction(runId: string, status: ProposedAction["status"]): ProposedAction {
  const findingId = mockReviewTaskFindingId(runId);
  return {
    action_id: mockReviewTaskActionId(runId),
    finding_id: findingId,
    type: "create_review_task",
    autonomy: "auto",
    status,
    idempotency_key: `${findingId}:create_review_task`,
  };
}

export function pendingApproval(runId: string): Approval {
  return {
    approval_id: mockApprovalId(runId),
    action_id: mockAmendmentActionId(runId),
    run_id: runId,
    // Required by the contract: the approval screen reaches its finding directly.
    finding_id: mockAmendmentFindingId(runId),
    status: "PENDING",
    decided_at: null,
    decided_by: null,
    note: null,
  };
}

/* --------------------------------------------------------- counterfactual */

/**
 * The deterministic shadow-state preview for `runId`'s amendment. Every id it
 * reports is scoped to `runId`, so a preview opened from an older run keeps
 * naming that run's findings even after a newer run exists.
 */
export function mockCounterfactual(actionId: string, runId: string): CounterfactualPreview {
  const unchanged = mockUnchangedFindingIds(runId);
  const newConflicts = mockNewConflictIds(runId);
  return {
    action_id: actionId,
    shadow_run_id: mockShadowRunId(runId),
    baseline_finding_count: MOCK_BASELINE_FINDING_COUNT,
    // These identifiers are the same synthetic findings the run reports. In the
    // real backend they come from rerunning the matching and validation pipeline
    // against the shadow copy.
    resolved_finding_ids: mockResolvedFindingIds(runId),
    unchanged_finding_ids: unchanged,
    new_conflict_ids: newConflicts,
    remaining_high_risk_ids: mockRemainingHighRiskIds(runId),
    detected_finding_picture_improves: true,
    narrative: `Applying the fee-prohibition amendment to the shadow copy resolves ${MOCK_RESOLVED_ON_APPROVAL} of ${MOCK_BASELINE_FINDING_COUNT} detected findings. ${unchanged.length} are unchanged (non-fee clauses) and ${newConflicts.length} new conflicts appear where the amendment references a superseded cost schedule.`,
  };
}

/* ----------------------------------------------------------------- audit */

/** The business outcome of the run's approval decision. */
export type RunOutcome = "approved" | "rejected";

/**
 * The synthetic idempotency scenario, identical for both outcomes.
 *
 * The run makes MOCK_ACTION_ATTEMPTS action attempts in total: the amendment, the
 * automatic review task, and one retried attempt that repeats an idempotency key
 * already seen. That repeat is detected and stopped before execution, so
 * MOCK_DUPLICATE_ACTIONS_PREVENTED of MOCK_ACTION_ATTEMPTS attempts were
 * duplicates and the rate is their quotient — a positive prevented count can
 * never sit beside a zero rate.
 *
 * The contract's AuditIdempotency carries no attempt count, so the denominator is
 * documented here rather than reported; the audit screen explains it in words.
 */
export const MOCK_ACTION_ATTEMPTS = 3;
export const MOCK_DUPLICATE_ACTIONS_PREVENTED = 1;
export const MOCK_DUPLICATE_ACTION_RATE =
  MOCK_DUPLICATE_ACTIONS_PREVENTED / MOCK_ACTION_ATTEMPTS;

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
    idempotency: {
      duplicate_actions_prevented: MOCK_DUPLICATE_ACTIONS_PREVENTED,
      duplicate_action_rate: MOCK_DUPLICATE_ACTION_RATE,
    },
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
    // The contract defines a non-null value as a short-lived signed HTTPS URL
    // generated by the backend. The offline demo issues no signed URL, so this
    // stays null rather than pointing the download control at an invented target.
    audit_package_url: null,
  };
}

/* ---------------------------------------------------------------- helpers */

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}
