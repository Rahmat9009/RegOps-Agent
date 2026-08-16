// types.ts — Frozen API types, hand-mirrored from contracts/openapi.yaml.
// Do NOT add fields the contract does not define. If you need more, note it in
// docs/frontend-notes.md for Codex — do not change the contract from the frontend.

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

export interface HealthStatus {
  status: string;
  version?: string;
}

export interface ApiError {
  error: string;
  detail?: string;
}

export interface CreateRunRequest {
  regulation_filename: string;
  gcs_uri?: string;
  synthetic_ack: boolean;
}

export interface ChangeDetection {
  result: "new" | "new_version" | "duplicate";
  content_hash: string;
  supersedes?: string | null;
  version: number;
}

export interface RunProgress {
  documents_total: number;
  documents_processed: number;
  partitions_total?: number;
  partitions_complete?: number;
  percent: number;
}

export interface FindingsBySeverity {
  low: number;
  medium: number;
  high: number;
}

export type TimelineAgent =
  | "change_detector"
  | "regulation_analyst"
  | "impact_investigator"
  | "action_controller"
  | "orchestrator";

export interface TimelineEvent {
  ts: string;
  agent?: TimelineAgent;
  state: RunState;
  message: string;
}

export interface RegulationRef {
  reg_id: string;
  title: string;
  jurisdiction?: string;
  synthetic: boolean;
}

export interface Recovery {
  failed_partition: number;
  retry_count: number;
  resumed_from_checkpoint: boolean;
}

export interface Run {
  run_id: string;
  state: RunState;
  created_at: string;
  updated_at?: string;
  regulation: RegulationRef;
  change_detection?: ChangeDetection;
  progress?: RunProgress;
  findings_by_severity?: FindingsBySeverity;
  pending_approvals?: ApprovalSummary[];
  completed_actions?: ActionSummary[];
  recovery?: Recovery | null;
  timeline?: TimelineEvent[];
}

export interface Evidence {
  doc_id: string;
  doc_kind: "regulation" | "contract" | "policy" | "case";
  page?: number;
  quote: string;
}

export interface Scores {
  evidence_strength: number;
  source_authority: SourceAuthority;
  interpretation_confidence: number;
  operational_severity: Severity;
  human_review_required: boolean;
}

export type FindingRelationship = "conflicts_with" | "requires_update" | "no_impact";
export type FindingVerdict = "survived" | "refuted" | "uncertain";
export type FindingStatus = "OPEN" | "AWAITING_APPROVAL" | "RESOLVED";

export interface FindingSummary {
  finding_id: string;
  run_id: string;
  target_id: string;
  relationship: FindingRelationship;
  severity: Severity;
  verdict: FindingVerdict;
  status: FindingStatus;
  human_review_required?: boolean;
}

export interface Obligation {
  obligation_id: string;
  statement: string;
  type: "prohibition" | "requirement" | "limit" | "exception";
  exceptions?: string[];
  effective_date?: string | null;
  evidence: Evidence;
}

export interface AffectedCase {
  case_id: string;
  summary: string;
  signed_date?: string | null;
}

export type ActionType = "tag_case" | "create_review_task" | "draft_amendment";
export type ActionAutonomy = "auto" | "approval_required";
export type ActionStatus =
  | "PENDING"
  | "EXECUTED"
  | "AWAITING_APPROVAL"
  | "APPROVED_DRAFT"
  | "REJECTED";

export interface ActionSummary {
  action_id: string;
  finding_id: string;
  type: ActionType;
  autonomy: ActionAutonomy;
  status: ActionStatus;
  idempotency_key?: string;
}

export interface Finding extends FindingSummary {
  obligation: Obligation;
  affected_case?: AffectedCase | null;
  evidence_path: Evidence[];
  scores: Scores;
  proposed_action?: ActionSummary;
}

export interface FindingsListResponse {
  items: FindingSummary[];
  total: number;
}

export interface CounterfactualPreview {
  action_id: string;
  simulation: "shadow_state";
  findings_before: number;
  resolved: string[];
  unchanged: string[];
  new_conflicts: string[];
  remaining_high_risk?: string[];
  detected_finding_picture_improves?: boolean;
  narrative?: string;
}

export interface ApprovalSummary {
  approval_id: string;
  action_id: string;
  run_id: string;
  status: "PENDING" | "APPROVED" | "REJECTED";
}

export interface Approval extends ApprovalSummary {
  decided_at?: string | null;
  decided_by?: string | null;
  note?: string | null;
}

export interface ApprovalDecision {
  decision: "approve" | "reject";
  note?: string;
}

export interface AuditReport {
  run_id: string;
  generated_at: string;
  executed_actions: ActionSummary[];
  idempotency?: {
    duplicate_actions_prevented: number;
    duplicate_action_rate?: number;
  };
  revalidation: {
    findings_resolved: number;
    findings_remaining: number;
  };
  processing: {
    total_seconds: number;
    documents_processed: number;
  };
  evaluation?: {
    obligation_precision?: number;
    impact_precision?: number;
    impact_recall?: number;
    citation_correctness?: number;
    false_escalation_rate?: number;
    resume_success_rate?: number;
  } | null;
  audit_package_url?: string;
}
