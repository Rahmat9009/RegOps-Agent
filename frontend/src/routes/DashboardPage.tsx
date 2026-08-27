// DashboardPage — View 1: operations dashboard.
//
// Current run, pipeline state and progress, documents processed, findings by
// severity, pending approvals, completed actions, and recovery/failure status.
// Everything comes from `GET /api/v1/runs/{run_id}`, polled every two seconds.
//
// Every figure on this screen is read straight off that one response. Nothing is
// aggregated from a second request and nothing is estimated.

import { Link } from "react-router-dom";
import {
  AlertTriangle,
  CircleDashed,
  FileCheck2,
  FileStack,
  Gauge,
  ListFilter,
  Radar,
  RefreshCw,
  ShieldQuestion,
  UserCheck,
  Upload,
} from "lucide-react";

import type { Run } from "@/lib/api";
import { clearActiveRunId, getActiveRunId } from "@/lib/activeRun";
import { formatCount, formatDateTime, formatPercent, pluralize } from "@/lib/format";
import {
  ACTION_STATUS,
  ACTION_TYPE,
  APPROVAL_STATUS,
  RUN_STATE,
  recoveryDescriptor,
} from "@/lib/presentation";
import { useRunPolling } from "@/hooks/useRunPolling";
import { Mono, StatusBadge } from "@/components/Badge";
import { Notice } from "@/components/Notice";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { PipelineMap } from "@/components/PipelineMap";
import { ProgressMeter, Stat } from "@/components/Meter";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";

/** What this console is for, in the words a reviewer would use. */
const MISSION =
  "RegOps reads a regulation, finds where it collides with the documents already in force, and holds every consequential change for a human decision. Nothing is written until someone approves it.";

export function DashboardPage() {
  const runId = getActiveRunId();
  const { run, error, loading, polling, refresh } = useRunPolling(runId);

  if (!runId) {
    return (
      <>
        <Hero
          action={
            <Link className="btn btn--primary btn--lg" to="/intake">
              <Upload size={17} aria-hidden="true" />
              Start a synthetic run
            </Link>
          }
        />
        <Panel title="Current run" icon={Radar}>
          <EmptyState
            icon={Upload}
            title="No run in progress"
            action={
              <Link className="btn btn--primary" to="/intake">
                <Upload size={16} aria-hidden="true" />
                Go to regulation intake
              </Link>
            }
          >
            This console has no run to display. Upload a synthetic regulation to create one.
          </EmptyState>
        </Panel>
      </>
    );
  }

  if (loading && !run) {
    return (
      <>
        <PageHeader title="Operations dashboard" eyebrow="Operations" />
        <Panel title="Current run" icon={Radar}>
          <LoadingState label="Loading current run…" />
        </Panel>
      </>
    );
  }

  if (error && !run) {
    // A run id we can no longer resolve is worse than none: forget it so the
    // console recovers into the empty state on the next visit.
    if (error.kind === "not_found") clearActiveRunId();
    return (
      <>
        <PageHeader title="Operations dashboard" eyebrow="Operations" />
        <Panel title="Current run" icon={Radar}>
          <ErrorState error={error} onRetry={refresh} />
        </Panel>
      </>
    );
  }

  if (!run) return null;

  return <DashboardContent run={run} polling={polling} onRefresh={refresh} />;
}

/** The mission statement. Shown at full height only when there is no run yet. */
function Hero({ action, compact = false }: { action?: React.ReactNode; compact?: boolean }) {
  return (
    <section className="hero" aria-labelledby="mission">
      <span className="hero__eyebrow">Regulatory change operations</span>
      <h1 className="hero__title" id="mission">
        {compact ? "Operations dashboard" : "From citation to decision, on the record."}
      </h1>
      <p className="hero__lede">{MISSION}</p>
      {action ? <div className="hero__actions">{action}</div> : null}
    </section>
  );
}

function DashboardContent({
  run,
  polling,
  onRefresh,
}: {
  run: Run;
  polling: boolean;
  onRefresh: () => void;
}) {
  const descriptor = RUN_STATE[run.state];
  const severities = run.findings_by_severity ?? { low: 0, medium: 0, high: 0 };
  const totalFindings = severities.low + severities.medium + severities.high;
  const pending = run.pending_approvals ?? [];
  const completed = run.completed_actions ?? [];

  return (
    <>
      <Hero
        compact
        action={
          <>
            <Link className="btn btn--primary" to={`/runs/${run.run_id}`}>
              <Radar size={16} aria-hidden="true" />
              Open run detail
            </Link>
            <Link className="btn" to="/intake">
              <Upload size={16} aria-hidden="true" />
              Start a synthetic run
            </Link>
          </>
        }
      />

      {/* Live region: state changes are announced without stealing focus. */}
      <p className="sr-only" role="status">
        Run {run.run_id} is {descriptor.label}. {formatPercent(run.progress.percent)} of documents
        processed.
      </p>

      {run.state === "FAILED_RECOVERABLE" ? <RecoveryNotice run={run} /> : null}

      {run.state === "FAILED" ? (
        <Notice tone="critical" title="Run failed" live>
          This run stopped and cannot continue. No further actions will be executed. Start a new
          intake to analyse the regulation again.
        </Notice>
      ) : null}

      {run.state === "AWAITING_APPROVAL" && pending.length > 0 ? (
        <Notice tone="review" title="A decision is waiting for you" icon={UserCheck} live>
          The pipeline paused because a consequential action requires human approval. Review the
          evidence and the shadow-state preview before deciding.
        </Notice>
      ) : null}

      <ActiveRunCard run={run} polling={polling} onRefresh={onRefresh} pending={pending.length} />

      <section aria-label="Operational metrics">
        <div className="grid grid--3">
          <Stat
            index={0}
            label="High severity"
            value={formatCount(severities.high)}
            tone="critical"
            icon={<AlertTriangle size={13} aria-hidden="true" />}
            note="Priority for review"
          />
          <Stat
            index={1}
            label="Medium severity"
            value={formatCount(severities.medium)}
            tone="review"
            icon={<ShieldQuestion size={13} aria-hidden="true" />}
            note="Warrants review"
          />
          <Stat
            index={2}
            label="Low severity"
            value={formatCount(severities.low)}
            icon={<CircleDashed size={13} aria-hidden="true" />}
            note="Minor impact"
          />
          <Stat
            index={3}
            label="Findings detected"
            value={formatCount(totalFindings)}
            icon={<FileStack size={13} aria-hidden="true" />}
            note="Across the synthetic corpus"
          />
          <Stat
            index={4}
            label="Awaiting decision"
            value={formatCount(pending.length)}
            tone={pending.length > 0 ? "review" : "neutral"}
            icon={<UserCheck size={13} aria-hidden="true" />}
            note={pending.length > 0 ? "Paused for a human" : "Nothing paused"}
          />
          <Stat
            index={5}
            label="Actions completed"
            value={formatCount(completed.length)}
            tone={completed.length > 0 ? "verified" : "neutral"}
            icon={<FileCheck2 size={13} aria-hidden="true" />}
            note="Executed or stored as a draft"
          />
        </div>
      </section>

      <div className="grid grid--2">
        <Panel
          title="Pending approvals"
          icon={UserCheck}
          tone={pending.length > 0 ? "review" : undefined}
        >
          {pending.length === 0 ? (
            <EmptyState icon={CircleDashed} title="Nothing waiting on a decision">
              Consequential actions pause here for a human. None are pending right now.
            </EmptyState>
          ) : (
            <ul className="stack stack--tight list-plain">
              {pending.map((approval) => (
                <li key={approval.approval_id}>
                  <Link
                    className="link-card"
                    to={`/approvals/${approval.approval_id}?run=${run.run_id}`}
                  >
                    <span className="stack stack--tight">
                      <strong>Review proposed action</strong>
                      <span className="field__hint">
                        <Mono>{approval.approval_id}</Mono> · action{" "}
                        <Mono>{approval.action_id}</Mono>
                      </span>
                    </span>
                    <StatusBadge
                      descriptor={APPROVAL_STATUS[approval.status]}
                      srPrefix="Approval status:"
                    />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Completed actions" icon={FileCheck2}>
          {completed.length === 0 ? (
            <EmptyState icon={CircleDashed} title="No actions executed yet">
              Automatic actions execute during the executing stage; approved amendments are stored
              as drafts against a shadow copy.
            </EmptyState>
          ) : (
            <ul className="stack stack--tight list-plain">
              {completed.map((action) => (
                <li key={action.action_id} className="filecard">
                  <span className="filecard__meta stack stack--tight">
                    <span className="filecard__name">{ACTION_TYPE[action.type].label}</span>
                    <span className="filecard__size">
                      <Mono>{action.action_id}</Mono> · finding <Mono>{action.finding_id}</Mono>
                    </span>
                  </span>
                  <StatusBadge descriptor={ACTION_STATUS[action.status]} srPrefix="Action status:" />
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      {run.state === "COMPLETED" ? (
        <Panel title="Audit" icon={Gauge} tone="verified">
          <div className="row">
            <p className="page__lede">
              This run is complete. The audit report records executed actions, idempotency results,
              revalidation outcome, processing time and evaluation metrics.
            </p>
            <Link className="btn btn--primary" to={`/runs/${run.run_id}/audit`}>
              <FileCheck2 size={16} aria-hidden="true" />
              Open audit report
            </Link>
          </div>
        </Panel>
      ) : null}
    </>
  );
}

/** The opening shot: what is running, how far it has got, and what to do next. */
function ActiveRunCard({
  run,
  polling,
  onRefresh,
  pending,
}: {
  run: Run;
  polling: boolean;
  onRefresh: () => void;
  pending: number;
}) {
  const descriptor = RUN_STATE[run.state];
  const partitionsTotal = run.progress.partitions_total ?? 0;

  return (
    <section className="runcard" aria-labelledby="active-run">
      <div className="runcard__head">
        <div className="runcard__ident">
          <span className="eyebrow" id="active-run">
            Active run
          </span>
          <h2 className="runcard__title">{run.regulation.title}</h2>
          <p className="runcard__meta">
            <span>{run.run_id}</span>
            <span aria-hidden="true">·</span>
            <span>{run.regulation.reg_id}</span>
            <span aria-hidden="true">·</span>
            <span>{run.regulation.source_filename}</span>
          </p>
        </div>
        <div className="runcard__status">
          <StatusBadge
            descriptor={descriptor}
            srPrefix="Run state:"
            size="lg"
            animateIcon={descriptor.active === true}
          />
          <span className="field__hint">
            Updated {formatDateTime(run.updated_at)}
            {polling ? " · polling every 2 s" : " · polling stopped"}
          </span>
        </div>
      </div>

      <div className="runcard__rail">
        <PipelineMap current={run.state} />
      </div>

      <ProgressMeter
        label="Documents processed"
        percent={run.progress.percent}
        detail={`${formatCount(run.progress.documents_processed)} of ${formatCount(
          run.progress.documents_total,
        )} · ${formatPercent(run.progress.percent)}`}
        tone={run.state === "COMPLETED" ? "verified" : "info"}
      />

      {partitionsTotal > 0 ? (
        <ProgressMeter
          label="Partitions complete"
          percent={((run.progress.partitions_complete ?? 0) / partitionsTotal) * 100}
          detail={`${formatCount(run.progress.partitions_complete ?? 0)} of ${formatCount(
            partitionsTotal,
          )}`}
          tone={run.state === "FAILED_RECOVERABLE" ? "review" : "info"}
        />
      ) : null}

      <div className="runcard__foot">
        {pending > 0 ? (
          <Link className="btn btn--primary" to={`/runs/${run.run_id}`}>
            <UserCheck size={16} aria-hidden="true" />
            {pluralize(pending, "decision")} waiting
          </Link>
        ) : null}
        <Link className="btn" to={`/runs/${run.run_id}`}>
          <Radar size={15} aria-hidden="true" />
          Run detail
        </Link>
        <Link className="btn" to={`/runs/${run.run_id}/findings`}>
          <ListFilter size={15} aria-hidden="true" />
          Findings
        </Link>
        <button type="button" className="btn btn--sm" onClick={onRefresh}>
          <RefreshCw size={14} aria-hidden="true" />
          Refresh
        </button>
      </div>
    </section>
  );
}

function RecoveryNotice({ run }: { run: Run }) {
  const complete = run.progress.partitions_complete ?? 0;
  const total = run.progress.partitions_total ?? 0;
  const recovery = run.recovery;

  return (
    <Notice tone="review" title="Recoverable failure — retrying" icon={RefreshCw} live>
      <p>
        A partition failed and the run is resuming from its last checkpoint. Processing continues
        automatically; no action is required from you.{" "}
        {total > 0
          ? `${pluralize(complete, "partition")} of ${formatCount(total)} completed before the failure.`
          : null}
      </p>
      {recovery ? (
        <p>
          {recoveryDescriptor(recovery).description}{" "}
          {pluralize(recovery.attempt_count, "attempt")} recorded
          {recovery.last_error_code ? (
            <>
              {" "}
              · <Mono>{recovery.last_error_code}</Mono>
            </>
          ) : null}
          . <Link to={`/runs/${run.run_id}`}>Open run detail</Link> for the full recovery record.
        </p>
      ) : (
        <p>The API returned no recovery record for this run, so none is shown.</p>
      )}
    </Notice>
  );
}
