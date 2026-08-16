// DashboardPage — View 1: operations dashboard.
//
// Current run, pipeline state and progress, documents processed, findings by
// severity, pending approvals, completed actions, and recovery/failure status.
// Everything comes from `GET /api/v1/runs/{run_id}`, polled every two seconds.

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
import { ACTION_STATUS, ACTION_TYPE, APPROVAL_STATUS, RUN_STATE } from "@/lib/presentation";
import { useRunPolling } from "@/hooks/useRunPolling";
import { Mono, StatusBadge } from "@/components/Badge";
import { Notice } from "@/components/Notice";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { PipelineMap } from "@/components/PipelineMap";
import { ProgressMeter, Stat } from "@/components/Meter";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";

export function DashboardPage() {
  const runId = getActiveRunId();
  const { run, error, loading, polling, refresh } = useRunPolling(runId);

  if (!runId) {
    return (
      <>
        <PageHeader
          title="Operations dashboard"
          lede="Current run status across the RegOps pipeline."
        />
        <Panel title="Current run" icon={Radar}>
          <EmptyState
            icon={Upload}
            title="No run in progress"
            action={
              <Link className="btn btn--primary" to="/intake">
                <Upload size={16} aria-hidden="true" />
                Start a regulation intake
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
        <PageHeader title="Operations dashboard" />
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
        <PageHeader title="Operations dashboard" />
        <Panel title="Current run" icon={Radar}>
          <ErrorState error={error} onRetry={refresh} />
        </Panel>
      </>
    );
  }

  if (!run) return null;

  return <DashboardContent run={run} polling={polling} onRefresh={refresh} />;
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
      <PageHeader
        title="Operations dashboard"
        lede={descriptor.description}
        status={
          <StatusBadge
            descriptor={descriptor}
            srPrefix="Run state:"
            size="lg"
            animateIcon={descriptor.active === true}
          />
        }
        actions={
          <button type="button" className="btn btn--sm" onClick={onRefresh}>
            <RefreshCw size={14} aria-hidden="true" />
            Refresh
          </button>
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

      <Panel
        title="Current run"
        icon={Radar}
        description={`${run.regulation.title} · ${run.regulation.reg_id}`}
        actions={
          <>
            <Link className="btn btn--sm" to={`/runs/${run.run_id}`}>
              Run detail
            </Link>
            <Link className="btn btn--sm" to={`/runs/${run.run_id}/findings`}>
              Findings
            </Link>
          </>
        }
      >
        <div className="stack">
          <dl className="dl">
            <dt>Run</dt>
            <dd>
              <Mono>{run.run_id}</Mono>
            </dd>
            <dt>Source file</dt>
            <dd>
              <Mono>{run.regulation.source_filename}</Mono>
            </dd>
            <dt>Started</dt>
            <dd>{formatDateTime(run.created_at)}</dd>
            <dt>Last update</dt>
            <dd>
              {formatDateTime(run.updated_at)}
              {polling ? " · polling every 2 s" : " · polling stopped"}
            </dd>
          </dl>

          <PipelineMap current={run.state} />

          <ProgressMeter
            label="Documents processed"
            percent={run.progress.percent}
            detail={`${formatCount(run.progress.documents_processed)} of ${formatCount(
              run.progress.documents_total,
            )} · ${formatPercent(run.progress.percent)}`}
            tone={run.state === "COMPLETED" ? "verified" : "info"}
          />

          {run.progress.partitions_total && run.progress.partitions_total > 0 ? (
            <ProgressMeter
              label="Partitions complete"
              percent={
                ((run.progress.partitions_complete ?? 0) / run.progress.partitions_total) * 100
              }
              detail={`${formatCount(run.progress.partitions_complete ?? 0)} of ${formatCount(
                run.progress.partitions_total,
              )}`}
              tone={run.state === "FAILED_RECOVERABLE" ? "review" : "info"}
            />
          ) : null}
        </div>
      </Panel>

      <Panel
        title="Findings by severity"
        icon={ListFilter}
        description="Operational severity assigned during verification."
        actions={
          <Link className="btn btn--sm" to={`/runs/${run.run_id}/findings`}>
            Open findings
          </Link>
        }
      >
        {totalFindings === 0 ? (
          <EmptyState icon={CircleDashed} title="No findings yet">
            Findings appear once the mapping stage has produced candidates and verification has
            run.
          </EmptyState>
        ) : (
          <div className="grid grid--4">
            <Stat
              label="High"
              value={formatCount(severities.high)}
              tone="critical"
              icon={<AlertTriangle size={14} aria-hidden="true" />}
              note="Priority for review"
            />
            <Stat
              label="Medium"
              value={formatCount(severities.medium)}
              tone="review"
              icon={<ShieldQuestion size={14} aria-hidden="true" />}
              note="Warrants review"
            />
            <Stat
              label="Low"
              value={formatCount(severities.low)}
              icon={<CircleDashed size={14} aria-hidden="true" />}
              note="Minor impact"
            />
            <Stat
              label="Total"
              value={formatCount(totalFindings)}
              icon={<FileStack size={14} aria-hidden="true" />}
              note="All detected findings"
            />
          </div>
        )}
      </Panel>

      <div className="grid grid--2">
        <Panel title="Pending approvals" icon={UserCheck}>
          {pending.length === 0 ? (
            <EmptyState icon={CircleDashed} title="Nothing waiting on a decision">
              Consequential actions pause here for a human. None are pending right now.
            </EmptyState>
          ) : (
            <ul className="stack stack--tight" style={{ listStyle: "none" }}>
              {pending.map((approval) => (
                <li key={approval.approval_id}>
                  <Link
                    className="link-card"
                    to={`/approvals/${approval.approval_id}?run=${run.run_id}`}
                  >
                    <span className="stack stack--tight">
                      <strong>
                        <Mono>{approval.approval_id}</Mono>
                      </strong>
                      <span className="field__hint">
                        Action <Mono>{approval.action_id}</Mono>
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
            <ul className="stack stack--tight" style={{ listStyle: "none" }}>
              {completed.map((action) => (
                <li key={action.action_id} className="filecard">
                  <span className="filecard__meta stack stack--tight">
                    <span className="filecard__name">{ACTION_TYPE[action.type].label}</span>
                    <span className="filecard__size">
                      <Mono>{action.action_id}</Mono> · finding{" "}
                      <Mono>{action.finding_id}</Mono>
                    </span>
                  </span>
                  <StatusBadge
                    descriptor={ACTION_STATUS[action.status]}
                    srPrefix="Action status:"
                  />
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      {run.state === "COMPLETED" ? (
        <Panel title="Audit" icon={Gauge}>
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

function RecoveryNotice({ run }: { run: Run }) {
  const complete = run.progress.partitions_complete ?? 0;
  const total = run.progress.partitions_total ?? 0;

  return (
    <Notice tone="review" title="Recoverable failure — retrying" icon={RefreshCw} live>
      A partition failed and the run is resuming from its last checkpoint. Processing continues
      automatically; no action is required from you.{" "}
      {total > 0 ? `${pluralize(complete, "partition")} of ${formatCount(total)} completed before the failure.` : null}{" "}
      The API does not yet report the failed partition index or retry count (CR-003), so those are
      not shown rather than guessed.
    </Notice>
  );
}
