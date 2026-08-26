// types.ts — Hand-mirrored from contracts/openapi.yaml (OpenAPI 3.1, frozen).
//
// Every type here corresponds 1:1 to a `components.schemas` entry. Required
// properties are non-optional; `anyOf [..., null]` properties are `T | null` and
// optional (the contract gives them a default). Do NOT add fields the contract
// does not define — record gaps in frontend/CONTRACT_REQUESTS.md instead.

/* ------------------------------------------------------------------ enums */

export type RunState =
  | "INGESTED"
  | "EXTRACTING"
  | "EXTRACTED"
  | "MAPPING"
  | "MAPPED"
  | "VERIFYING"
  | "VERIFIED"
  | "AWAITING_APPROVAL"
  | "EXECUTING"
  | "REVALIDATING"
  | "COMPLETED"
  | "FAILED_RECOVERABLE"
  | "FAILED";

export type Severity = "low" | "medium" | "high";

export type SourceAuthority = "primary_government" | "secondary" | "internal";

export type Relationship = "conflicts_with" | "requires_update" | "no_impact";

export type FindingVerdict = "survived" | "refuted" | "uncertain";

export type FindingStatus = "OPEN" | "AWAITING_APPROVAL" | "RESOLVED";

export type ActionType = "tag_case" | "create_review_task" | "draft_amendment";

export type ActionAutonomy = "auto" | "approval_required";

export type ActionStatus =
  | "PENDING"
  | "EXECUTED"
  | "AWAITING_APPROVAL"
  | "APPROVED_DRAFT"
  | "REJECTED";

export type ApprovalStatus = "PENDING" | "APPROVED" | "REJECTED";

export type ApprovalDecisionValue = "approve" | "reject";

export type ObligationType = "prohibition" | "requirement" | "limit" | "exception";

export type DocumentKind = "regulation" | "contract" | "policy" | "case";

/* ------------------------------------------------------- health and errors */

/** HealthStatus — `status` is `const: ok`. */
export interface HealthStatus {
  status: "ok";
  version: string;
}

/** ErrorDetail — one FastAPI-style validation detail. */
export interface ErrorDetail {
  location?: (string | number)[];
  message: string;
  type: string;
}

/** APIError — the response body shape for 404 / 409 / 422 / 501. */
export interface APIErrorBody {
  code: string;
  message: string;
  details?: ErrorDetail[] | null;
}

/* --------------------------------------------------------------- run model */

export interface RunProgress {
  documents_total: number;
  documents_processed: number;
  /** Reserved for Phase 2 Cloud Run Job progress. Contract default: 0. */
  partitions_total?: number;
  /** Reserved for Phase 2 Cloud Run Job progress. Contract default: 0. */
  partitions_complete?: number;
  percent: number;
}

/** Regulation — `synthetic` is `const: true`; the demo corpus is never real. */
export interface Regulation {
  reg_id: string;
  title: string;
  jurisdiction?: string | null;
  source_filename: string;
  synthetic: true;
}

export interface FindingsBySeverity {
  low: number;
  medium: number;
  high: number;
}

/**
 * RunTransition — one authoritative, server-recorded state change.
 *
 * `from_state` is `null` only for the first transition of a run. `reason` and
 * `actor` are safe backend-assigned labels: never prompts, stack traces,
 * credentials, tokens, or infrastructure detail.
 */
export interface RunTransition {
  from_state: RunState | null;
  to_state: RunState;
  occurred_at: string;
  reason: string | null;
  actor: string;
}

/**
 * RecoveryInfo — safe recovery metadata for a recoverable failure.
 *
 * The contract guarantees that `recovery_available === true` implies a non-null
 * `checkpoint_state`. Error fields are sanitized by the backend.
 */
export interface RecoveryInfo {
  recovery_available: boolean;
  checkpoint_state: RunState | null;
  attempt_count: number;
  last_error_code: string | null;
  last_error_message: string | null;
}

/** ChangeDetection — lowercase SHA-256 digests plus the detection outcome. */
export interface ChangeDetection {
  /** 64 lowercase hex characters. */
  source_sha256: string;
  /** 64 lowercase hex characters, or null when nothing preceded this document. */
  previous_source_sha256: string | null;
  changed: boolean;
  detected_at: string;
}

export interface Run {
  run_id: string;
  state: RunState;
  created_at: string;
  updated_at: string;
  regulation: Regulation;
  progress: RunProgress;
  /** Authoritative server-recorded history, ordered oldest to newest. */
  transitions: RunTransition[];
  recovery?: RecoveryInfo | null;
  change_detection?: ChangeDetection | null;
  findings_by_severity?: FindingsBySeverity;
  pending_approvals?: Approval[];
  completed_actions?: ProposedAction[];
}

/* ---------------------------------------------------- evidence and finding */

export interface EvidenceReference {
  doc_id: string;
  doc_kind: DocumentKind;
  /** Required by the contract, minimum 1. */
  page: number;
  quote: string;
}

export interface Obligation {
  obligation_id: string;
  statement: string;
  type: ObligationType;
  exceptions?: string[];
  effective_date?: string | null;
  /** Contract requires at least one evidence reference. */
  evidence: EvidenceReference[];
}

export interface FindingScores {
  /** 0..1 */
  evidence_strength: number;
  source_authority: SourceAuthority;
  /** 0..1 */
  interpretation_confidence: number;
  operational_severity: Severity;
  human_review_required: boolean;
}

export interface ProposedAction {
  action_id: string;
  finding_id: string;
  type: ActionType;
  autonomy: ActionAutonomy;
  status: ActionStatus;
  idempotency_key: string;
}

export interface FindingSummary {
  finding_id: string;
  run_id: string;
  target_id: string;
  relationship: Relationship;
  severity: Severity;
  verdict: FindingVerdict;
  status: FindingStatus;
  human_review_required: boolean;
  /** Required by the contract — the findings list never hydrates scores per row. */
  scores: FindingScores;
}

/** AffectedCase — `synthetic` is `const: true`. */
export interface AffectedCase {
  case_id: string;
  summary: string;
  signed_date?: string | null;
  synthetic: true;
}

export interface Finding extends FindingSummary {
  obligation: Obligation;
  affected_case?: AffectedCase | null;
  /** Contract requires at least one evidence reference. */
  evidence_path: EvidenceReference[];
  scores: FindingScores;
  proposed_action?: ProposedAction | null;
}

export interface FindingList {
  /** The selected page of matching findings. */
  items: FindingSummary[];
  /** Findings matching the active filters, before pagination. */
  total: number;
  limit: number;
  offset: number;
  /** Severity counts across the complete filtered result, before pagination. */
  by_severity: FindingsBySeverity;
}

/* -------------------------------------------------------- counterfactual */

/**
 * CounterfactualPreview — deterministic shadow-state output. Counts and IDs come
 * from rerunning the same matching and validation pipeline against a shadow copy.
 * `narrative` is explicitly non-authoritative.
 */
export interface CounterfactualPreview {
  action_id: string;
  shadow_run_id: string;
  baseline_finding_count: number;
  resolved_finding_ids: string[];
  unchanged_finding_ids: string[];
  new_conflict_ids: string[];
  remaining_high_risk_ids: string[];
  detected_finding_picture_improves: boolean;
  narrative?: string | null;
}

/* -------------------------------------------------------------- approvals */

export interface Approval {
  approval_id: string;
  action_id: string;
  run_id: string;
  /** The finding this approval's action came from — no action lookup needed. */
  finding_id: string;
  status: ApprovalStatus;
  decided_at?: string | null;
  /**
   * Backend-assigned reviewer identity. The unauthenticated synthetic demo uses
   * the controlled value `demo-reviewer`. The frontend must NEVER submit or
   * select this value — it is read-only here.
   */
  decided_by?: string | null;
  note?: string | null;
}

/**
 * ApprovalDecision — the only request body the frontend sends for a decision.
 * Deliberately has no reviewer identity field: `decided_by` is backend-assigned.
 */
export interface ApprovalDecision {
  decision: ApprovalDecisionValue;
  note?: string | null;
}

/* ------------------------------------------------------------------ audit */

export interface AuditIdempotency {
  duplicate_actions_prevented: number;
  /** 0..1 */
  duplicate_action_rate: number;
}

export interface AuditRevalidation {
  findings_resolved: number;
  findings_remaining: number;
}

export interface AuditProcessing {
  total_seconds: number;
  documents_processed: number;
}

/** AuditEvaluation — the contract requires all six metrics when present. */
export interface AuditEvaluation {
  obligation_precision: number;
  impact_precision: number;
  impact_recall: number;
  citation_correctness: number;
  false_escalation_rate: number;
  resume_success_rate: number;
}

export interface AuditReport {
  run_id: string;
  generated_at: string;
  executed_actions: ProposedAction[];
  idempotency: AuditIdempotency;
  revalidation: AuditRevalidation;
  processing: AuditProcessing;
  evaluation?: AuditEvaluation | null;
  audit_package_url?: string | null;
}

/* --------------------------------------------------------- request inputs */

/**
 * Body of `POST /api/v1/runs`, sent as `multipart/form-data`.
 * `regulation_file` is the raw PDF binary; `synthetic_ack` confirms the uploaded
 * demo document is synthetic.
 */
export interface CreateRunInput {
  regulation_file: File;
  synthetic_ack: boolean;
}
