// RunDetailPage — View 3: run detail.
//
// Processing stages, partition progress, the transitions this client observed
// while polling, and recoverable-failure state.
//
// The timeline shows ONLY state values returned by the API plus the time this
// browser first observed them. No agent reasoning or chain-of-thought is shown,
// because none is returned and none may be invented.

import { Link, useParams } from "react-router-dom";
import {
  Clock,
  FileCheck2,
  Layers,
  ListFilter,
  Radar,
  RefreshCw,
  UserCheck,
} from "lucide-react";

import { formatCount, formatDateTime, formatPercent, formatTime } from "@/lib/format";
import { APPROVAL_STATUS, RUN_STATE, isTerminalState } from "@/lib/presentation";
import { useRunPolling, type ObservedTransition } from "@/hooks/useRunPolling";
import { Mono, StatusBadge } from "@/components/Badge";
import { Notice } from "@/components/Notice";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { PipelineMap } from "@/components/PipelineMap";
import { ProgressMeter } from "@/components/Meter";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";

export function RunDetailPage() {
  const { runId = "" } = useParams();
  const { run, error, loading, polling, transitions, refresh } = useRunPolling(runId || null);

  if (loading && !run) {
    return (
      <>
        <PageHeader title="Run detail" />
        <Panel title="Run" icon={Radar}>
          <LoadingState label="Loading run…" />
        </Panel>
      </>
    );
  }

  if (error && !run) {
    return (
      <>
        <PageHeader title="Run detail" />
        <Panel title="Run" icon={Radar}>
          <ErrorState error={error} onRetry={refresh} />
        </Panel>
      </>
    );
  }

  if (!run) return null;

  const descriptor = RUN_STATE[run.state];
  const pending = run.pending_approvals ?? [];
  const partitionsTotal = run.progress.partitions_total ?? 0;

  return (
    <>
      <PageHeader
        title={run.regulation.title}
        lede={descriptor.description}
        crumbs={[{ label: "Operations", to: "/" }, { label: `Run ${run.run_id}` }]}
        status={
          <StatusBadge
            descriptor={descriptor}
            srPrefix="Run state:"
            size="lg"
            animateIcon={descriptor.active === true}
          />
        }
        actions={
          <>
            <Link className="btn btn--sm" to={`/runs/${run.run_id}/findings`}>
              <ListFilter size={14} aria-hidden="true" />
              Findings
            </Link>
            {run.state === "COMPLETED" ? (
              <Link className="btn btn--sm" to={`/runs/${run.run_id}/audit`}>
                <FileCheck2 size={14} aria-hidden="true" />
                Audit
              </Link>
            ) : null}
            <button type="button" className="btn btn--sm" onClick={refresh}>
              <RefreshCw size={14} aria-hidden="true" />
              Refresh
            </button>
          </>
        }
      />

      {error ? (
        <Notice tone="review" title="The last poll failed" live>
          {error.message} The console is showing the most recent successful response.
        </Notice>
      ) : null}

      {run.state === "FAILED_RECOVERABLE" ? (
        <Notice tone="review" title="Recoverable failure — resuming from checkpoint" icon={RefreshCw} live>
          A partition failed. The run is retrying and will continue to a later state on its own.
          The API contract does not expose the failed partition index, retry count, or checkpoint
          resume flag (see <Mono>CONTRACT_REQUESTS.md</Mono> CR-003), so this console does not
          display them.
        </Notice>
      ) : null}

      {run.state === "FAILED" ? (
        <Notice tone="critical" title="Run failed" live>
          The run stopped and will not continue. Nothing further will be executed.
        </Notice>
      ) : null}

      {run.state === "AWAITING_APPROVAL" && pending.length > 0 ? (
        <Notice tone="review" title="Paused for human approval" icon={UserCheck} live>
          A consequential action is waiting on a decision. Approving it produces an{" "}
          <Mono>APPROVED_DRAFT</Mono> amendment against a synthetic contract&rsquo;s shadow copy —
          no real contract is modified.
        </Notice>
      ) : null}

      <Panel
        title="Processing stages"
        icon={Layers}
        description="The pipeline states declared by the API contract. The current stage is marked."
      >
        <PipelineMap current={run.state} />
      </Panel>

      <div className="grid grid--2">
        <Panel title="Progress" icon={Radar}>
          <div className="stack">
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
                label="Partition progress"
                percent={((run.progress.partitions_complete ?? 0) / partitionsTotal) * 100}
                detail={`${formatCount(run.progress.partitions_complete ?? 0)} of ${formatCount(
                  partitionsTotal,
                )} partitions`}
                tone={run.state === "FAILED_RECOVERABLE" ? "review" : "info"}
              />
            ) : (
              <Notice tone="info">
                Partition counters are reserved for a later phase and are reported as zero for this
                run.
              </Notice>
            )}

            <dl className="dl">
              <dt>Run</dt>
              <dd>
                <Mono>{run.run_id}</Mono>
              </dd>
              <dt>Regulation</dt>
              <dd>
                <Mono>{run.regulation.reg_id}</Mono>
              </dd>
              <dt>Jurisdiction</dt>
              <dd>{run.regulation.jurisdiction ?? "Not reported"}</dd>
              <dt>Created</dt>
              <dd>{formatDateTime(run.created_at)}</dd>
              <dt>Updated</dt>
              <dd>{formatDateTime(run.updated_at)}</dd>
              <dt>Polling</dt>
              <dd>
                {polling
                  ? "Active — GET /api/v1/runs/{run_id} every 2 s"
                  : isTerminalState(run.state)
                    ? "Stopped — the run reached a terminal state"
                    : "Stopped — the run is waiting on a human decision"}
              </dd>
            </dl>
          </div>
        </Panel>

        <Panel
          title="Observed state transitions"
          icon={Clock}
          description="Recorded by this browser while polling. It is not a server-side history."
        >
          <TransitionTimeline transitions={transitions} />
        </Panel>
      </div>

      {pending.length > 0 ? (
        <Panel title="Pending approvals" icon={UserCheck}>
          <ul className="stack stack--tight" style={{ listStyle: "none" }}>
            {pending.map((approval) => (
              <li key={approval.approval_id}>
                <Link
                  className="link-card"
                  to={`/approvals/${approval.approval_id}?run=${run.run_id}`}
                >
                  <span className="stack stack--tight">
                    <strong>Review proposed action</strong>
                    <span className="field__hint">
                      Approval <Mono>{approval.approval_id}</Mono> · action{" "}
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
        </Panel>
      ) : null}
    </>
  );
}

function TransitionTimeline({ transitions }: { transitions: ObservedTransition[] }) {
  if (transitions.length === 0) {
    return (
      <EmptyState icon={Clock} title="No transitions observed yet">
        The first observation is recorded as soon as the run responds to a poll.
      </EmptyState>
    );
  }

  return (
    <>
      <ol className="timeline">
        {transitions.map((transition, index) => {
          const descriptor = RUN_STATE[transition.state];
          const Icon = descriptor.icon;
          return (
            <li key={`${transition.state}-${index}`} className="timeline__item">
              <span className="timeline__dot" aria-hidden="true">
                <Icon size={13} />
              </span>
              <span className="timeline__body">
                <StatusBadge descriptor={descriptor} srPrefix="State:" />
                <span className="timeline__time">
                  Observed {formatTime(transition.observedAt)} · API reported{" "}
                  {formatTime(transition.reportedAt)}
                </span>
                <span className="field__hint">{descriptor.description}</span>
              </span>
            </li>
          );
        })}
      </ol>
      <p className="field__hint">
        These are state values returned by the API together with the time this browser first saw
        them. Transitions that happened before this page was opened are not listed, and no agent
        reasoning is shown.
      </p>
    </>
  );
}
