// ApprovalPage — View 7: approval screen.
//
// Shows the proposed amendment, its evidence, a before/after comparison from the
// deterministic shadow-state preview, and the approve / reject controls.
//
// Two things this screen must never do:
//   1. Imply that approval modifies a real contract. It records an APPROVED_DRAFT
//      amendment against a synthetic contract's shadow copy.
//   2. Send `decided_by`. Reviewer identity is assigned by the backend; the request
//      body carries only `decision` and `note`.

import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  FileSignature,
  FlaskConical,
  GitCompare,
  Loader2,
  ShieldAlert,
  UserCheck,
  XCircle,
} from "lucide-react";

import {
  api,
  SHADOW_COPY_NOTICE,
  toRegOpsApiError,
  type Approval,
  type CounterfactualPreview,
  type Finding,
  type RegOpsApiError,
  type Run,
} from "@/lib/api";
import { formatCount, formatDateTime, pluralize } from "@/lib/format";
import {
  ACTION_AUTONOMY,
  ACTION_STATUS,
  ACTION_TYPE,
  APPROVAL_STATUS,
  SEVERITY,
} from "@/lib/presentation";
import { Mono, StatusBadge, Tag } from "@/components/Badge";
import { Notice } from "@/components/Notice";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";

interface ApprovalContext {
  run: Run;
  approval: Approval;
  finding: Finding | null;
  preview: CounterfactualPreview | null;
}

export function ApprovalPage() {
  const { approvalId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const runId = searchParams.get("run");

  const [context, setContext] = useState<ApprovalContext | null>(null);
  const [error, setError] = useState<RegOpsApiError | null>(null);
  const [loading, setLoading] = useState(true);

  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState<"approve" | "reject" | null>(null);
  const [decision, setDecision] = useState<Approval | null>(null);
  const [decisionError, setDecisionError] = useState<RegOpsApiError | null>(null);

  const load = useCallback(async (): Promise<void> => {
    if (!runId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const run = await api.getRun(runId);
      const approval = run.pending_approvals?.find((item) => item.approval_id === approvalId);
      if (!approval) {
        setContext({ run, approval: fallbackApproval(approvalId, runId), finding: null, preview: null });
        setError(null);
        return;
      }

      // The contract has no action -> finding lookup, so the finding backing this
      // action is located through the run's findings (CONTRACT_REQUESTS.md CR-008).
      const finding = await findFindingForAction(runId, approval.action_id);
      const preview = await api.previewAction(approval.action_id).catch(() => null);

      setContext({ run, approval, finding, preview });
      setError(null);
    } catch (cause: unknown) {
      setError(toRegOpsApiError(cause));
    } finally {
      setLoading(false);
    }
  }, [runId, approvalId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function decide(value: "approve" | "reject"): Promise<void> {
    setSubmitting(value);
    setDecisionError(null);
    try {
      // Only `decision` and `note` are sent. `decided_by` is backend-assigned.
      const result = await api.decideApproval(approvalId, {
        decision: value,
        note: note.trim() === "" ? null : note.trim(),
      });
      setDecision(result);
    } catch (cause: unknown) {
      setDecisionError(toRegOpsApiError(cause));
    } finally {
      setSubmitting(null);
    }
  }

  const crumbs = [
    { label: "Operations", to: "/" },
    ...(runId ? [{ label: `Run ${runId}`, to: `/runs/${runId}` }] : []),
    { label: "Approval" },
  ];

  if (!runId) {
    return (
      <>
        <PageHeader title="Approval" crumbs={crumbs} />
        <Panel title="Approval" icon={UserCheck}>
          <EmptyState icon={ShieldAlert} title="This approval cannot be opened directly">
            The API contract has no <Mono>GET /approvals/{"{approval_id}"}</Mono>, so an approval
            can only be read through the run that owns it. Open it from the run detail page or the
            operations dashboard. The request is recorded as CR-005 in{" "}
            <Mono>frontend/CONTRACT_REQUESTS.md</Mono>.
          </EmptyState>
        </Panel>
      </>
    );
  }

  if (loading) {
    return (
      <>
        <PageHeader title="Approval" crumbs={crumbs} />
        <Panel title="Proposed action" icon={UserCheck}>
          <LoadingState label="Loading the proposed action and its evidence…" />
        </Panel>
      </>
    );
  }

  if (error || !context) {
    return (
      <>
        <PageHeader title="Approval" crumbs={crumbs} />
        <Panel title="Proposed action" icon={UserCheck}>
          {error ? (
            <ErrorState
              error={error}
              onRetry={() => void load()}
              fallbackHref={`/runs/${runId}`}
              fallbackLabel="Back to run detail"
            />
          ) : null}
        </Panel>
      </>
    );
  }

  const { run, approval, finding, preview } = context;
  const action = finding?.proposed_action ?? null;
  const isPending = run.pending_approvals?.some((item) => item.approval_id === approvalId) ?? false;
  const outcome = decision;

  return (
    <>
      <PageHeader
        title="Approval decision"
        lede={
          outcome
            ? outcome.status === "APPROVED"
              ? "This action was approved. The run continues to execution and revalidation."
              : "This action was rejected. The amendment was not executed; the run continues and completes without it."
            : "A consequential action is paused here. Nothing is written until you decide."
        }
        crumbs={crumbs}
        status={
          <StatusBadge
            descriptor={APPROVAL_STATUS[outcome?.status ?? approval.status]}
            srPrefix="Approval status:"
            size="lg"
          />
        }
      />

      <Notice tone="review" title="Approval does not modify a real contract" icon={FlaskConical}>
        {SHADOW_COPY_NOTICE}
      </Notice>

      {outcome ? <DecisionOutcome decision={outcome} runId={run.run_id} /> : null}

      {!outcome && !isPending ? (
        <Notice tone="info" title="No longer pending">
          This approval is not in the run&rsquo;s pending list. It may already have been decided in
          another session. Open the run detail page to see the current state.
        </Notice>
      ) : null}

      <Panel title="Proposed amendment" icon={FileSignature}>
        {action ? (
          <div className="stack">
            <div className="chip-row">
              <StatusBadge descriptor={ACTION_TYPE[action.type]} srPrefix="Action type:" />
              {/* After a decision, the action's status follows from the Approval the
                  API returned — the run itself is not re-fetched on this screen. */}
              <StatusBadge
                descriptor={
                  ACTION_STATUS[
                    outcome
                      ? outcome.status === "APPROVED"
                        ? "APPROVED_DRAFT"
                        : "REJECTED"
                      : action.status
                  ]
                }
                srPrefix="Action status:"
              />
              <StatusBadge descriptor={ACTION_AUTONOMY[action.autonomy]} srPrefix="Autonomy:" />
            </div>
            <p>{ACTION_TYPE[action.type].description}</p>
            <dl className="dl">
              <dt>Action id</dt>
              <dd>
                <Mono>{action.action_id}</Mono>
              </dd>
              <dt>Approval id</dt>
              <dd>
                <Mono>{approval.approval_id}</Mono>
              </dd>
              <dt>Target</dt>
              <dd>
                <Mono>{finding?.target_id}</Mono> <Tag icon={FlaskConical}>Synthetic</Tag>
              </dd>
              <dt>Idempotency key</dt>
              <dd>
                <Mono>{action.idempotency_key}</Mono>
                <p className="field__hint">
                  Re-submitting the same decision cannot execute the action twice.
                </p>
              </dd>
            </dl>
          </div>
        ) : (
          <EmptyState icon={AlertTriangle} title="The proposed action could not be resolved">
            The approval references action <Mono>{approval.action_id}</Mono>, but no finding in
            this run exposes it. Review the finding list before deciding.
          </EmptyState>
        )}
      </Panel>

      {finding ? (
        <Panel title="Evidence for this decision" icon={GitCompare}>
          <div className="stack">
            <div className="chip-row">
              <StatusBadge descriptor={SEVERITY[finding.severity]} srPrefix="Severity:" />
              <Tag>
                <Mono>{finding.finding_id}</Mono>
              </Tag>
            </div>
            <p>
              <strong>Obligation.</strong> {finding.obligation.statement}
            </p>
            {finding.obligation.evidence[0] ? (
              <figure className="quote">
                <blockquote>{finding.obligation.evidence[0].quote}</blockquote>
                <footer>
                  Regulation <Mono>{finding.obligation.evidence[0].doc_id}</Mono>, page{" "}
                  {finding.obligation.evidence[0].page}
                </footer>
              </figure>
            ) : null}
            {finding.evidence_path
              .filter((item) => item.doc_kind === "contract" || item.doc_kind === "policy")
              .map((item) => (
                <figure className="quote" key={`${item.doc_id}-${item.page}`}>
                  <blockquote>{item.quote}</blockquote>
                  <footer>
                    Synthetic {item.doc_kind} <Mono>{item.doc_id}</Mono>, page {item.page}
                  </footer>
                </figure>
              ))}
            <Link className="btn btn--sm" to={`/findings/${finding.finding_id}`}>
              <ArrowRight size={14} aria-hidden="true" />
              Open the full evidence chain
            </Link>
          </div>
        </Panel>
      ) : null}

      <Panel
        title="Before and after"
        icon={GitCompare}
        description="From the deterministic shadow-state preview. Counts describe detected findings, not legal outcomes."
      >
        {preview ? (
          <div className="stack">
            <div className="compare">
              <div className="compare__col">
                <div className="compare__head">
                  <AlertTriangle size={15} aria-hidden="true" />
                  Before — current shadow baseline
                </div>
                <div className="compare__body">
                  <p>
                    <strong>{formatCount(preview.baseline_finding_count)}</strong> findings detected
                    today.
                  </p>
                  <p className="field__hint">
                    Including <Mono>{finding?.finding_id ?? "this finding"}</Mono>, which is what
                    this amendment targets.
                  </p>
                </div>
              </div>
              <div className="compare__col">
                <div className="compare__head">
                  <CheckCircle2 size={15} aria-hidden="true" />
                  After — simulated shadow copy
                </div>
                <div className="compare__body">
                  <p>
                    <strong>{formatCount(preview.resolved_finding_ids.length)}</strong> predicted to
                    resolve · <strong>{formatCount(preview.unchanged_finding_ids.length)}</strong>{" "}
                    unchanged ·{" "}
                    <strong>{formatCount(preview.new_conflict_ids.length)}</strong> new conflicts.
                  </p>
                  <p className="field__hint">
                    {pluralize(preview.remaining_high_risk_ids.length, "high-risk finding")} would
                    remain.
                  </p>
                </div>
              </div>
            </div>
            <Link
              className="btn btn--sm"
              to={`/actions/${approval.action_id}/preview?approval=${approval.approval_id}&run=${run.run_id}`}
            >
              <ArrowRight size={14} aria-hidden="true" />
              Open the full counterfactual preview
            </Link>
          </div>
        ) : (
          <EmptyState icon={GitCompare} title="No preview available">
            The shadow-state preview could not be loaded for this action. Decide from the evidence
            above, or retry the preview from the finding.
          </EmptyState>
        )}
      </Panel>

      <Panel title="Record your decision" icon={UserCheck}>
        {outcome ? (
          <Notice tone={outcome.status === "APPROVED" ? "verified" : "critical"} title="Decision recorded">
            This approval is now <strong>{APPROVAL_STATUS[outcome.status].label}</strong>. It cannot
            be decided again.
          </Notice>
        ) : (
          <div className="stack">
            <div className="field">
              <label className="field__label" htmlFor="decision-note">
                Note (optional)
              </label>
              <textarea
                id="decision-note"
                className="textarea"
                value={note}
                maxLength={2000}
                onChange={(event) => setNote(event.target.value)}
                aria-describedby="decision-note-hint"
                placeholder="Why you are approving or rejecting this action."
              />
              <p className="field__hint" id="decision-note-hint">
                Stored with the decision in the audit record. Your reviewer identity is assigned by
                the backend; this console never sends it.
              </p>
            </div>

            {decisionError ? (
              <Notice tone="critical" title="The decision was not recorded" live>
                {decisionError.message}
                {decisionError.kind === "conflict"
                  ? " Reload the run to see the decision that was recorded first."
                  : null}
              </Notice>
            ) : null}

            <Notice tone="review" title="What approving does">
              Approving stores an <Mono>APPROVED_DRAFT</Mono> amendment against a synthetic
              contract&rsquo;s shadow copy and lets the run continue to execution and revalidation.
              It does not change a real contract, and it is not a legal determination. Rejecting is
              an equally valid outcome: the amendment is never executed, the finding stays open, and
              the run still completes with an audit record.
            </Notice>

            <div className="row">
              <button
                type="button"
                className="btn btn--approve"
                disabled={submitting !== null || !isPending}
                onClick={() => void decide("approve")}
              >
                {submitting === "approve" ? (
                  <Loader2 size={16} aria-hidden="true" className="spin" />
                ) : (
                  <CheckCircle2 size={16} aria-hidden="true" />
                )}
                Approve draft amendment
              </button>
              <button
                type="button"
                className="btn btn--reject"
                disabled={submitting !== null || !isPending}
                onClick={() => void decide("reject")}
              >
                {submitting === "reject" ? (
                  <Loader2 size={16} aria-hidden="true" className="spin" />
                ) : (
                  <XCircle size={16} aria-hidden="true" />
                )}
                Reject
              </button>
            </div>
          </div>
        )}
      </Panel>
    </>
  );
}

function DecisionOutcome({ decision, runId }: { decision: Approval; runId: string }) {
  const approved = decision.status === "APPROVED";

  return (
    <Notice
      tone={approved ? "verified" : "critical"}
      title={
        approved ? "Approved — recorded as a draft" : "Rejected — the amendment was not executed"
      }
      live
    >
      <dl className="dl">
        <dt>Decided at</dt>
        <dd>{formatDateTime(decision.decided_at)}</dd>
        <dt>Reviewer</dt>
        <dd>
          <Mono>{decision.decided_by ?? "not reported"}</Mono>
          <span className="field__hint"> — assigned by the backend, not submitted by this console.</span>
        </dd>
        {decision.note ? (
          <>
            <dt>Note</dt>
            <dd>{decision.note}</dd>
          </>
        ) : null}
      </dl>
      <p>
        <Link to={`/runs/${runId}`}>Return to run detail</Link> to watch execution and
        revalidation.
      </p>
    </Notice>
  );
}

/** Locate the finding whose proposed action matches — see CR-008. */
async function findFindingForAction(runId: string, actionId: string): Promise<Finding | null> {
  const list = await api.listRunFindings(runId);
  for (const summary of list.items) {
    const detail = await api.getFinding(summary.finding_id).catch(() => null);
    if (detail?.proposed_action?.action_id === actionId) return detail;
  }
  return null;
}

function fallbackApproval(approvalId: string, runId: string): Approval {
  return {
    approval_id: approvalId,
    action_id: "unknown",
    run_id: runId,
    status: "PENDING",
    decided_at: null,
    decided_by: null,
    note: null,
  };
}
