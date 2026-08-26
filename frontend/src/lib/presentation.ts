// presentation.ts — Maps contract enum values to the label, icon and tone the UI
// shows. Every status is rendered as icon + text + colour, so a reader who cannot
// distinguish the colours still gets the full meaning.
//
// Tone vocabulary (from CLAUDE.md):
//   info     blue   — informational / in progress
//   review   amber  — needs human attention
//   critical red    — high severity or failure
//   verified green  — verified completion ONLY
//   neutral  grey   — everything else

import {
  AlertTriangle,
  Ban,
  BadgeCheck,
  Building2,
  CheckCircle2,
  CircleDashed,
  CircleSlash,
  ClipboardList,
  FileDiff,
  FileSearch,
  FileSignature,
  FileText,
  Gavel,
  GitCompare,
  Hourglass,
  Landmark,
  Layers,
  ListChecks,
  Loader2,
  OctagonAlert,
  RefreshCw,
  ScrollText,
  ShieldQuestion,
  Tag,
  UserCheck,
  XCircle,
  type LucideIcon,
} from "lucide-react";

import type {
  ActionAutonomy,
  ActionStatus,
  ActionType,
  ApprovalStatus,
  ChangeDetection,
  DocumentKind,
  FindingStatus,
  FindingVerdict,
  ObligationType,
  RecoveryInfo,
  Relationship,
  RunState,
  Severity,
  SourceAuthority,
} from "@/lib/api";

export type Tone = "neutral" | "info" | "review" | "critical" | "verified";

export interface Descriptor {
  label: string;
  tone: Tone;
  icon: LucideIcon;
  /** Plain-language explanation shown as help text or a tooltip-free caption. */
  description: string;
  /** True while the pipeline is actively working, used to drive polling. */
  active?: boolean;
}

/* ------------------------------------------------------------- run state */

export const RUN_STATE: Record<RunState, Descriptor> = {
  INGESTED: {
    label: "Ingested",
    tone: "info",
    icon: FileText,
    description: "Regulation received; the run has been created.",
    active: true,
  },
  EXTRACTING: {
    label: "Extracting",
    tone: "info",
    icon: Loader2,
    description: "Extracting obligations and their citations from the regulation.",
    active: true,
  },
  EXTRACTED: {
    label: "Extracted",
    tone: "info",
    icon: ScrollText,
    description: "Obligations and citations are ready.",
    active: true,
  },
  MAPPING: {
    label: "Mapping",
    tone: "info",
    icon: Loader2,
    description: "Matching obligations against the synthetic document corpus.",
    active: true,
  },
  MAPPED: {
    label: "Mapped",
    tone: "info",
    icon: Layers,
    description: "Candidate findings have been produced.",
    active: true,
  },
  VERIFYING: {
    label: "Verifying",
    tone: "info",
    icon: Loader2,
    description: "Running the internal refutation pass over candidate findings.",
    active: true,
  },
  VERIFIED: {
    label: "Verified",
    tone: "info",
    icon: ListChecks,
    description: "Findings now carry a survived, refuted or uncertain verdict.",
    active: true,
  },
  AWAITING_APPROVAL: {
    label: "Awaiting approval",
    tone: "review",
    icon: UserCheck,
    description: "A consequential action is paused for a human decision.",
    active: false,
  },
  EXECUTING: {
    label: "Executing",
    tone: "info",
    icon: Loader2,
    description: "Executing approved and automatic actions idempotently.",
    active: true,
  },
  REVALIDATING: {
    label: "Revalidating",
    tone: "info",
    icon: RefreshCw,
    description: "Rerunning the pipeline to confirm the finding was resolved.",
    active: true,
  },
  COMPLETED: {
    label: "Completed",
    tone: "verified",
    icon: CheckCircle2,
    description: "Run finished and the audit report is available.",
    active: false,
  },
  FAILED_RECOVERABLE: {
    label: "Recoverable failure",
    tone: "review",
    icon: RefreshCw,
    description: "A partition failed. Retry and checkpoint resume are in progress.",
    active: true,
  },
  FAILED: {
    label: "Failed",
    tone: "critical",
    icon: OctagonAlert,
    description: "The run stopped and cannot continue.",
    active: false,
  },
};

/** Canonical order of the happy path, used by the pipeline map. */
export const PIPELINE_STEPS: RunState[] = [
  "INGESTED",
  "EXTRACTING",
  "EXTRACTED",
  "MAPPING",
  "MAPPED",
  "VERIFYING",
  "VERIFIED",
  "AWAITING_APPROVAL",
  "EXECUTING",
  "REVALIDATING",
  "COMPLETED",
];

export function isTerminalState(state: RunState): boolean {
  return state === "COMPLETED" || state === "FAILED";
}

/** Should the UI keep polling `GET /runs/{run_id}`? */
export function shouldPoll(state: RunState): boolean {
  return RUN_STATE[state].active === true;
}

/* --------------------------------------------------------------- severity */

export const SEVERITY: Record<Severity, Descriptor> = {
  high: {
    label: "High severity",
    tone: "critical",
    icon: AlertTriangle,
    description: "Operationally significant; treat as a priority for review.",
  },
  medium: {
    label: "Medium severity",
    tone: "review",
    icon: ShieldQuestion,
    description: "Warrants review but is not immediately operationally critical.",
  },
  low: {
    label: "Low severity",
    tone: "neutral",
    icon: CircleDashed,
    description: "Minor operational impact.",
  },
};

export const SEVERITY_ORDER: Severity[] = ["high", "medium", "low"];

/* ----------------------------------------------------------- finding meta */

export const VERDICT: Record<FindingVerdict, Descriptor> = {
  survived: {
    label: "Survived refutation",
    tone: "info",
    icon: BadgeCheck,
    description: "The finding held up against the internal refutation pass.",
  },
  refuted: {
    label: "Refuted",
    tone: "neutral",
    icon: CircleSlash,
    description: "The refutation pass found the conflict does not hold.",
  },
  uncertain: {
    label: "Uncertain",
    tone: "review",
    icon: ShieldQuestion,
    description: "The refutation pass was inconclusive; a human should read it.",
  },
};

export const FINDING_STATUS: Record<FindingStatus, Descriptor> = {
  OPEN: {
    label: "Open",
    tone: "info",
    icon: CircleDashed,
    description: "No remediation has been recorded yet.",
  },
  AWAITING_APPROVAL: {
    label: "Awaiting approval",
    tone: "review",
    icon: Hourglass,
    description: "A proposed action for this finding is paused for a human decision.",
  },
  RESOLVED: {
    label: "Resolved",
    tone: "verified",
    icon: CheckCircle2,
    description: "Revalidation confirmed the finding was addressed.",
  },
};

export const RELATIONSHIP: Record<Relationship, Descriptor> = {
  conflicts_with: {
    label: "Conflicts with",
    tone: "critical",
    icon: AlertTriangle,
    description: "The target appears to contradict the extracted obligation.",
  },
  requires_update: {
    label: "Requires update",
    tone: "review",
    icon: FileSignature,
    description: "The target is consistent but needs to be updated.",
  },
  no_impact: {
    label: "No impact",
    tone: "neutral",
    icon: CircleSlash,
    description: "The obligation does not change this target.",
  },
};

export const SOURCE_AUTHORITY: Record<SourceAuthority, Descriptor> = {
  primary_government: {
    label: "Primary government source",
    tone: "info",
    icon: Landmark,
    description: "Evidence comes from the issuing authority's own document.",
  },
  secondary: {
    label: "Secondary source",
    tone: "neutral",
    icon: FileSearch,
    description: "Evidence comes from a restatement or commentary, not the issuer.",
  },
  internal: {
    label: "Internal source",
    tone: "neutral",
    icon: Building2,
    description: "Evidence comes from an internal document rather than a regulator.",
  },
};

export const OBLIGATION_TYPE: Record<ObligationType, Descriptor> = {
  prohibition: {
    label: "Prohibition",
    tone: "critical",
    icon: Ban,
    description: "The regulation forbids the described conduct.",
  },
  requirement: {
    label: "Requirement",
    tone: "info",
    icon: ListChecks,
    description: "The regulation mandates the described conduct.",
  },
  limit: {
    label: "Limit",
    tone: "review",
    icon: GitCompare,
    description: "The regulation caps or bounds the described conduct.",
  },
  exception: {
    label: "Exception",
    tone: "neutral",
    icon: CircleSlash,
    description: "The regulation carves this case out of a broader rule.",
  },
};

export const DOCUMENT_KIND: Record<DocumentKind, Descriptor> = {
  regulation: {
    label: "Regulation",
    tone: "info",
    icon: Gavel,
    description: "The source regulation document.",
  },
  contract: {
    label: "Contract",
    tone: "neutral",
    icon: FileSignature,
    description: "A synthetic contract in the demonstration corpus.",
  },
  policy: {
    label: "Policy",
    tone: "neutral",
    icon: ScrollText,
    description: "A synthetic internal policy document.",
  },
  case: {
    label: "Case",
    tone: "neutral",
    icon: ClipboardList,
    description: "A synthetic worker case file.",
  },
};

/* ----------------------------------------------------------------- action */

export const ACTION_TYPE: Record<ActionType, Descriptor> = {
  tag_case: {
    label: "Tag case",
    tone: "neutral",
    icon: Tag,
    description: "Marks a synthetic case file for attention. No document is changed.",
  },
  create_review_task: {
    label: "Create review task",
    tone: "info",
    icon: ClipboardList,
    description: "Opens an internal review task. No document is changed.",
  },
  draft_amendment: {
    label: "Draft amendment",
    tone: "review",
    icon: FileSignature,
    description:
      "Drafts a proposed amendment against a synthetic contract's shadow copy. Requires human approval and never edits a real contract.",
  },
};

export const ACTION_STATUS: Record<ActionStatus, Descriptor> = {
  PENDING: {
    label: "Pending",
    tone: "neutral",
    icon: CircleDashed,
    description: "Queued; not yet executed.",
  },
  EXECUTED: {
    label: "Executed",
    tone: "verified",
    icon: CheckCircle2,
    description: "Completed idempotently against synthetic records.",
  },
  AWAITING_APPROVAL: {
    label: "Awaiting approval",
    tone: "review",
    icon: Hourglass,
    description: "Paused for a human decision before anything is written.",
  },
  APPROVED_DRAFT: {
    label: "Approved draft",
    tone: "verified",
    icon: FileSignature,
    description:
      "An approved amendment draft stored against a synthetic contract's shadow copy. The original contract is unchanged.",
  },
  REJECTED: {
    label: "Rejected",
    tone: "critical",
    icon: XCircle,
    description: "A reviewer rejected this action; nothing was written.",
  },
};

export const ACTION_AUTONOMY: Record<ActionAutonomy, Descriptor> = {
  auto: {
    label: "Automatic",
    tone: "neutral",
    icon: CircleDashed,
    description: "Non-consequential; executes without a human decision.",
  },
  approval_required: {
    label: "Approval required",
    tone: "review",
    icon: UserCheck,
    description: "Consequential; a human must decide before it runs.",
  },
};

export const APPROVAL_STATUS: Record<ApprovalStatus, Descriptor> = {
  PENDING: {
    label: "Pending decision",
    tone: "review",
    icon: Hourglass,
    description: "Waiting for a reviewer to approve or reject.",
  },
  APPROVED: {
    label: "Approved",
    tone: "verified",
    icon: CheckCircle2,
    description: "A reviewer approved the proposed action.",
  },
  REJECTED: {
    label: "Rejected",
    tone: "critical",
    icon: XCircle,
    description: "A reviewer rejected the proposed action.",
  },
};

/* ---------------------------------------------- recovery, change detection */

/**
 * How to present `Run.recovery`. Only the safe fields the contract defines are
 * used: availability, checkpoint, attempt count and a sanitized error label.
 */
export function recoveryDescriptor(recovery: RecoveryInfo): Descriptor {
  const checkpoint = recovery.checkpoint_state ? RUN_STATE[recovery.checkpoint_state].label : null;

  if (recovery.recovery_available) {
    return {
      label: "Recovery available",
      tone: "review",
      icon: RefreshCw,
      description: checkpoint
        ? `The run can resume from its ${checkpoint.toLowerCase()} checkpoint.`
        : "The run can resume from its last checkpoint.",
    };
  }

  if (recovery.attempt_count > 0) {
    return {
      label: "Recovered from checkpoint",
      tone: "verified",
      icon: BadgeCheck,
      description: checkpoint
        ? `A retry resumed from the ${checkpoint.toLowerCase()} checkpoint and the run continued.`
        : "A retry resumed the run from its last checkpoint.",
    };
  }

  return {
    label: "No recovery outstanding",
    tone: "neutral",
    icon: CircleDashed,
    description: "No recoverable failure has been recorded for this run.",
  };
}

/** How to present `Run.change_detection`. */
export function changeDetectionDescriptor(detection: ChangeDetection): Descriptor {
  if (!detection.changed) {
    return {
      label: "Unchanged document",
      tone: "neutral",
      icon: CircleSlash,
      description:
        "The uploaded document has the same content hash as the previously analysed source.",
    };
  }

  return {
    label: detection.previous_source_sha256 ? "Changed document" : "New document",
    tone: "info",
    icon: FileDiff,
    description: detection.previous_source_sha256
      ? "The content hash differs from the previously analysed source."
      : "No earlier source hash was recorded, so this document is analysed as new.",
  };
}

/**
 * Shorten a hash for display. The full value is never dropped by callers — it is
 * rendered for assistive technology alongside the shortened form.
 */
export function shortenHash(value: string, visible = 12): string {
  if (visible <= 0 || value.length <= visible) return value;
  return `${value.slice(0, visible)}…`;
}

/* --------------------------------------------------------------- helpers */

export function humanReviewDescriptor(required: boolean): Descriptor {
  return required
    ? {
        label: "Human review required",
        tone: "review",
        icon: UserCheck,
        description: "This finding must be read by a person before any action is taken.",
      }
    : {
        label: "No human review required",
        tone: "neutral",
        icon: CircleDashed,
        description: "This finding did not meet the threshold for mandatory human review.",
      };
}
