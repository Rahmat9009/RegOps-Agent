// ApprovalPage — View 7: approval screen.
//
// Shows the proposed amendment, its evidence, a before/after comparison from the
// deterministic shadow-state preview, and the approve / reject controls.
//
// Three things this screen must never do:
//   1. Imply that approval modifies a real contract. It records an APPROVED_DRAFT
//      amendment against a synthetic contract's shadow copy.
//   2. Send `decided_by`. Reviewer identity is assigned by the backend; the request
//      body carries only `decision` and `note`.
//   3. Record a decision against evidence it could not load. Eligibility is decided
//      by `evaluateDecisionEligibility`, which gates both the buttons and the
//      submit path — a disabled button is never the only thing standing between a
//      reviewer and an unfounded approval. Nothing missing is ever substituted.

import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  FileSignature,
  FlaskConical,
  GitCompare,
  Link2,
  Loader2,
  Scale,
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
import {
  canSubmitDecision,
  DECISION_BLOCKER_MESSAGE,
  evaluateDecisionEligibility,
} from "@/lib/approvalDecision";
import { formatCount, formatDateTime } from "@/lib/format";
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
  /** Null when this approval is no longer in the run's pending list. */
  approval: Approval | null;
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

  // Computed from what actually loaded, before any early return, so the guard in
  // `decide` and the buttons' disabled state can never disagree.
  const eligibility = evaluateDecisionEligibility({
    approval: context?.approval ?? null,
    finding: context?.finding ?? null,
    action: context?.finding?.proposed_action ?? null,
    preview: context?.preview ?? null,
  });

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
        setContext({ run, approval: null, finding: null, preview: null });
        setError(null);
        return;
      }

      // `Approval.finding_id` is required by the contract, so the finding behind
      // this decision is one request away — no action lookup, no scanning.
      const finding = await api.getFinding(approval.finding_id).catch(() => null);
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
    // The controls are disabled in this case, but the guard lives here as well:
    // eligibility is a safety rule, not a presentation detail.
    if (!canSubmitDecision(eligibility, value)) return;

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

  if (!approval) {
    return (
      <>
        <PageHeader title="Approval" crumbs={crumbs} />
        <Panel title="Proposed action" icon={UserCheck}>
          <EmptyState icon={ShieldAlert} title="No longer pending">
            Approval <Mono>{approvalId}</Mono> is not in run <Mono>{run.run_id}</Mono>&rsquo;s
            pending list. It may already have been decided in another session. The contract has no{" "}
            <Mono>GET /approvals/{"{approval_id}"}</Mono> to read a decided approval back
            (CR-005), so the run detail page is the place to see the outcome.
          </EmptyState>
          <div className="row">
            <Link className="btn btn--primary" to={`/runs/${run.run_id}`}>
              <ArrowRight size={16} aria-hidden="true" />
              Open run detail
            </Link>
          </div>
        </Panel>
      </>
    );
  }

  // Reaching this point means the approval is still in the run's pending list —
  // anything else returned above.
  const action = finding?.proposed_action ?? null;
  const outcome = decision;

  return (
    <>
      <PageHeader
        title="Approval decision"
        lede={
          outcome
            ? outcome.status === "APPROVED"
              ? "This action was approved. The run continues to execution and revalidation."
              : "This action was rejected. The amendment was not executed, and the run completes without executing or revalidating anything."
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

      {outcome ? <DecisionOutcome decision={outcome} runId={run.run_id} /> : null}

      {/* Two columns: the evidence reads top-to-bottom in normal page flow on the
          left, and the decision rail stays in view on the right. The rail is the
          only sticky thing on the screen — the page itself scrolls normally, and
          below 1280px the whole thing collapses into one evidence-first stack. */}
      <div className="review">
        <div className="review__main">
          {/* 1 — the bound finding. What this decision is actually about. */}
          <Panel title="Bound finding" icon={Scale}>
            {finding ? (
              <div className="stack">
                <div className="chip-row">
                  <StatusBadge descriptor={SEVERITY[finding.severity]} srPrefix="Severity:" />
                  <Tag>
                    <Mono>{finding.finding_id}</Mono>
                  </Tag>
                  <Tag>
                    <Mono>{finding.target_id}</Mono>
                  </Tag>
                </div>
                <p>
                  <strong>Obligation.</strong> {finding.obligation.statement}
                </p>
              </div>
            ) : (
              <EmptyState icon={AlertTriangle} title="The bound finding could not be loaded">
                This approval names finding <Mono>{approval.finding_id}</Mono>, but that record did
                not load. Nothing is substituted for it, so no decision can be recorded until it
                does.
              </EmptyState>
            )}
          </Panel>

          {/* 2 — the evidence chain, quoted exactly as the API returned it. */}
          <Panel
            title="Evidence chain"
            icon={Link2}
            description="Regulation citation, then the synthetic clause it collides with. Quoted verbatim."
          >
            {finding ? (
              <div className="stack">
                {finding.obligation.evidence[0] ? (
                  <figure className="quote">
                    <blockquote>{finding.obligation.evidence[0].quote}</blockquote>
                    <footer>
                      Regulation <Mono>{finding.obligation.evidence[0].doc_id}</Mono>, page{" "}
                      {finding.obligation.evidence[0].page}
                    </footer>
                  </figure>
                ) : (
                  <p className="field__hint">
                    The API returned no citation for this obligation, so none is shown.
                  </p>
                )}

                {finding.evidence_path
                  .filter((item) => item.doc_kind === "contract" || item.doc_kind === "policy")
                  .map((item) => (
                    <figure className="quote quote--target" key={`${item.doc_id}-${item.page}`}>
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
            ) : (
              <p className="field__hint">
                No evidence is shown, because the finding this approval is bound to could not be
                loaded.
              </p>
            )}
          </Panel>

          {/* 3 — the proposed action, with its exact identifiers. */}
          <Panel
            title="Proposed action"
            icon={FileSignature}
            tone={outcome ? (outcome.status === "APPROVED" ? "verified" : "critical") : undefined}
          >
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
                The approval references action <Mono>{approval.action_id}</Mono> on finding{" "}
                <Mono>{approval.finding_id}</Mono>, but that action could not be loaded from the
                finding. Nothing is substituted for it, so no decision can be recorded until it
                loads.
              </EmptyState>
            )}
          </Panel>

          {/* 4 — where these records come from, and what the amendment targets. */}
          <Notice tone="review" title="Synthetic sources, shadow copy" icon={FlaskConical}>
            <p>
              The regulation, contract and case records quoted above are synthetic demonstration
              records, not real documents.
            </p>
            <p>{SHADOW_COPY_NOTICE}</p>
          </Notice>
        </div>

        <aside className="review__rail" aria-label="Decision">
          {/* 1 — the exact relationship being decided, kept in view while the
              reader scrolls the evidence. */}
          <section className="deciding" aria-labelledby="deciding-heading">
            <span className="eyebrow" id="deciding-heading">
              Currently deciding
            </span>
            <dl className="deciding__dl">
              <dt>Approval</dt>
              <dd>
                <Mono>{approval.approval_id}</Mono>
              </dd>
              <dt>Action</dt>
              <dd>
                <Mono>{approval.action_id}</Mono>
              </dd>
              <dt>Finding</dt>
              <dd>
                <Mono>{approval.finding_id}</Mono>
              </dd>
            </dl>
          </section>

          {/* 2 — the complete deterministic preview. Every count the API returned,
              never a subset: a reviewer who sees only what improves is deciding
              on half the picture. */}
          <Panel
            title="Counterfactual preview"
            icon={GitCompare}
            tone="model"
            description="Deterministic shadow-state rerun. Simulation only."
          >
            {preview ? (
              <div className="stack stack--tight">
                <dl className="cf">
                  <div className="cf__row">
                    <dt>Findings before</dt>
                    <dd>{formatCount(preview.baseline_finding_count)}</dd>
                  </div>
                  <div
                    className={
                      preview.resolved_finding_ids.length > 0
                        ? "cf__row cf__row--resolved"
                        : "cf__row"
                    }
                  >
                    <dt>Predicted to resolve</dt>
                    <dd>{formatCount(preview.resolved_finding_ids.length)}</dd>
                  </div>
                  <div className="cf__row">
                    <dt>Remaining</dt>
                    <dd>{formatCount(preview.unchanged_finding_ids.length)}</dd>
                  </div>
                  <div
                    className={
                      preview.new_conflict_ids.length > 0
                        ? "cf__row cf__row--introduced"
                        : "cf__row"
                    }
                  >
                    <dt>New conflicts introduced</dt>
                    <dd>{formatCount(preview.new_conflict_ids.length)}</dd>
                  </div>
                  <div
                    className={
                      preview.remaining_high_risk_ids.length > 0
                        ? "cf__row cf__row--risk"
                        : "cf__row"
                    }
                  >
                    <dt>High-risk findings left</dt>
                    <dd>{formatCount(preview.remaining_high_risk_ids.length)}</dd>
                  </div>
                </dl>
                <Link
                  className="btn btn--sm"
                  to={`/actions/${approval.action_id}/preview?approval=${approval.approval_id}&run=${run.run_id}`}
                >
                  <ArrowRight size={14} aria-hidden="true" />
                  Open the full preview
                </Link>
              </div>
            ) : (
              <div className="stack stack--tight">
                <Notice tone="critical" title="No preview available" icon={AlertTriangle} live>
                  The deterministic shadow-state preview could not be loaded for this action, so it
                  cannot be approved — approving without the predicted outcome would be a decision
                  made blind. Rejecting stays available, because it executes nothing.
                </Notice>
                <button type="button" className="btn btn--sm" onClick={() => void load()}>
                  Reload this screen
                </button>
              </div>
            )}
          </Panel>

          {/* 3 — the approval gate. Amber, stated once, impossible to miss. */}
          <div className="gate">
            <span className="gate__icon" aria-hidden="true">
              <ShieldAlert size={22} />
            </span>
            <div>
              <strong className="gate__title">
                This action will not run without your decision.
              </strong>
              <p className="gate__text">
                The pipeline is stopped at <Mono>AWAITING_APPROVAL</Mono>. Nothing is written,
                executed or revalidated until a reviewer approves or rejects this exact action.
              </p>
            </div>
          </div>

          {/* 4 — the controls. */}
          <Panel
            title="Record your decision"
            icon={UserCheck}
            tone={outcome ? (outcome.status === "APPROVED" ? "verified" : "critical") : "review"}
          >
            {outcome ? (
              <Notice
                tone={outcome.status === "APPROVED" ? "verified" : "critical"}
                title="Decision recorded"
              >
                This approval is now <strong>{APPROVAL_STATUS[outcome.status].label}</strong>. It
                cannot be decided again.
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
                    Stored with the decision in the audit record. Your reviewer identity is assigned
                    by the backend; this console never sends it.
                  </p>
                </div>

                {eligibility.blockers.length > 0 ? (
                  <div id="decision-blockers">
                    <Notice
                      tone="critical"
                      title={
                        eligibility.canReject
                          ? "This action cannot be approved"
                          : "No decision can be recorded yet"
                      }
                      icon={ShieldAlert}
                      live
                    >
                      <ul className="stack stack--tight list-plain">
                        {eligibility.blockers.map((blocker) => (
                          <li key={blocker}>{DECISION_BLOCKER_MESSAGE[blocker]}</li>
                        ))}
                      </ul>
                      <p className="field__hint">
                        Nothing is substituted for a record that failed to load. Reload this screen,
                        or open the run detail page to check the finding and its proposed action.
                      </p>
                    </Notice>
                  </div>
                ) : null}

                {decisionError ? (
                  <Notice tone="critical" title="The decision was not recorded" live>
                    {decisionError.message}
                    {decisionError.kind === "conflict"
                      ? " Reload the run to see the decision that was recorded first."
                      : null}
                  </Notice>
                ) : null}

                {/* The two decisions are not mirror images, so they are not drawn as
                    a matched pair. Each states what it actually does above its own
                    control. */}
                <div className="decision decision--stacked">
                  <div className="decision__option decision__option--approve">
                    <strong className="decision__heading">
                      <CheckCircle2 size={18} aria-hidden="true" />
                      Approve
                    </strong>
                    <p className="decision__text">
                      Stores an <Mono>APPROVED_DRAFT</Mono> against the shadow copy and lets the
                      run continue to execution and revalidation. No real contract changes.
                    </p>
                    <button
                      type="button"
                      className="btn btn--approve btn--lg"
                      disabled={submitting !== null || !eligibility.canApprove}
                      onClick={() => void decide("approve")}
                      aria-describedby={eligibility.canApprove ? undefined : "decision-blockers"}
                    >
                      {submitting === "approve" ? (
                        <Loader2 size={17} aria-hidden="true" className="spin" />
                      ) : (
                        <CheckCircle2 size={17} aria-hidden="true" />
                      )}
                      Approve draft amendment
                    </button>
                  </div>

                  <div className="decision__option decision__option--reject">
                    <strong className="decision__heading">
                      <XCircle size={18} aria-hidden="true" />
                      Reject
                    </strong>
                    <p className="decision__text">
                      An equally valid outcome, not a failure. The amendment is marked{" "}
                      <Mono>REJECTED</Mono> and never executed, the finding stays{" "}
                      <Mono>OPEN</Mono>, and the run completes. Nothing is destroyed.
                    </p>
                    <button
                      type="button"
                      className="btn btn--reject btn--lg"
                      disabled={submitting !== null || !eligibility.canReject}
                      onClick={() => void decide("reject")}
                      aria-describedby={eligibility.canReject ? undefined : "decision-blockers"}
                    >
                      {submitting === "reject" ? (
                        <Loader2 size={17} aria-hidden="true" className="spin" />
                      ) : (
                        <XCircle size={17} aria-hidden="true" />
                      )}
                      Reject this amendment
                    </button>
                  </div>
                </div>
              </div>
            )}
          </Panel>
        </aside>
      </div>
    </>
  );
}

function DecisionOutcome({ decision, runId }: { decision: Approval; runId: string }) {
  const approved = decision.status === "APPROVED";

  return (
    <section
      className={approved ? "outcome outcome--verified" : "outcome outcome--critical"}
      role="status"
      aria-label="Decision recorded"
    >
      <span className="outcome__icon" aria-hidden="true">
        {approved ? <CheckCircle2 size={26} /> : <XCircle size={26} />}
      </span>
      <div className="outcome__body stack stack--tight">
        <strong className="outcome__title">
          {approved ? "Approved — recorded as a draft" : "Rejected — nothing was executed"}
        </strong>
        <p className="outcome__text">
          {approved
            ? "The amendment is stored against a synthetic contract's shadow copy. The run continues through execution and revalidation."
            : "The amendment is marked REJECTED and never ran. The finding stays open and the run completes without executing or revalidating anything."}
        </p>
        <dl className="dl">
          <dt>Finding</dt>
          <dd>
            <Link to={`/findings/${decision.finding_id}`}>
              <Mono>{decision.finding_id}</Mono>
            </Link>
          </dd>
          <dt>Decided at</dt>
          <dd>{formatDateTime(decision.decided_at)}</dd>
          <dt>Reviewer</dt>
          <dd>
            <Mono>{decision.decided_by ?? "not reported"}</Mono>
            <span className="field__hint">
              {" "}
              — assigned by the backend, not submitted by this console.
            </span>
          </dd>
          {decision.note ? (
            <>
              <dt>Note</dt>
              <dd>{decision.note}</dd>
            </>
          ) : null}
        </dl>
        <p className="outcome__text">
          <Link to={`/runs/${runId}`}>Return to run detail</Link>
          {approved
            ? " to watch execution and revalidation."
            : " to see the run complete with an audit record."}
        </p>
      </div>
    </section>
  );
}
