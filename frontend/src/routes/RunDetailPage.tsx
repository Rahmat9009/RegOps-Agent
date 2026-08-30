// RunDetailPage — View 3: run detail.
//
// Processing stages, partition progress, the run's authoritative transition
// history, recoverable-failure state and change detection.
//
// The timeline shows ONLY the server-recorded transitions the API returns, with
// their recorded actor, timestamp and safe reason label. No agent reasoning or
// chain-of-thought is shown, because none is returned and none may be invented.
// Nothing on this screen is reconstructed from what the browser happened to see:
// the client's only contribution is noticing which entries are new to it, so that
// exactly those animate in.

import { useEffect, useRef } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Clock,
  FileCheck2,
  FileDiff,
  Layers,
  ListFilter,
  Radar,
  RefreshCw,
  UserCheck,
} from "lucide-react";

import type { RunTransition } from "@/lib/api";
import { formatCount, formatDateTime, formatPercent, formatTime } from "@/lib/format";
import { APPROVAL_STATUS, RUN_STATE, isTerminalState } from "@/lib/presentation";
import { useRunPolling } from "@/hooks/useRunPolling";
import { Mono, StatusBadge } from "@/components/Badge";
import { Notice } from "@/components/Notice";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { PipelineMap } from "@/components/PipelineMap";
import { ProgressMeter } from "@/components/Meter";
import { ChangeDetectionDetails, RecoveryDetails } from "@/components/RunInsights";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";

export function RunDetailPage() {
  const { runId = "" } = useParams();
  const { run, error, loading, polling, refresh } = useRunPolling(runId || null);

  if (loading && !run) {
    return (
      <>
        <PageHeader title="Run detail" eyebrow="Run" />
        <Panel title="Run" icon={Radar}>
          <LoadingState label="Loading run…" />
        </Panel>
      </>
    );
  }

  if (error && !run) {
    return (
      <>
        <PageHeader title="Run detail" eyebrow="Run" />
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
        <Notice
          tone="review"
          title="Recoverable failure — resuming from checkpoint"
          icon={RefreshCw}
          live
        >
          A partition failed. The run is retrying and will continue to a later state on its own. The
          recovery record below reports the checkpoint, the attempt count and the sanitized error
          the API returned.
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
        title="Run lifecycle"
        icon={Layers}
        description="The pipeline states declared by the API contract. The current stage is marked with its name, not only its colour."
        tone={run.state === "AWAITING_APPROVAL" ? "review" : undefined}
      >
        <div className="stack">
          <PipelineMap current={run.state} />

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
            <p className="field__hint">
              Partition counters are reserved for a later phase and are reported as zero for this
              run.
            </p>
          )}
        </div>
      </Panel>

      <div className="grid grid--2">
        <Panel
          title="Recorded state transitions"
          icon={Clock}
          description="The run's server-recorded history, oldest first."
        >
          <TransitionTimeline transitions={run.transitions} />
        </Panel>

        <div className="stack">
          <Panel title="Run record" icon={Radar}>
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
          </Panel>

          <Panel
            title="Recovery"
            icon={RefreshCw}
            description="Checkpoint, attempt count and sanitized error reported by the API."
            tone={run.state === "FAILED_RECOVERABLE" ? "review" : undefined}
          >
            <RecoveryDetails recovery={run.recovery} />
          </Panel>

          <Panel
            title="Change detection"
            icon={FileDiff}
            description="Whether this source document differs from the previously analysed one."
          >
            <ChangeDetectionDetails detection={run.change_detection} />
          </Panel>
        </div>
      </div>

      {pending.length > 0 ? (
        <Panel title="Pending approvals" icon={UserCheck} tone="review">
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

function transitionKey(transition: RunTransition, index: number): string {
  return `${index}:${transition.from_state ?? ""}->${transition.to_state}@${transition.occurred_at}`;
}

/**
 * The run's authoritative transition history, rendered oldest to newest exactly
 * as the API ordered it. Each entry shows the recorded state change, when it
 * happened, which backend actor recorded it and the safe reason label — nothing
 * is inferred from what this browser happened to observe.
 *
 * The only client-side judgement is which entries this screen had not rendered
 * before. Those, and only those, animate in; a history that was already on
 * screen is never replayed.
 */
function TransitionTimeline({ transitions }: { transitions: RunTransition[] }) {
  const seen = useRef<Set<string> | null>(null);
  const keys = transitions.map(transitionKey);

  // On the first render nothing is new — the reader is arriving at an existing
  // history, not watching it happen.
  const firstRender = seen.current === null;
  const isNew = keys.map((key) => !firstRender && !seen.current?.has(key));

  useEffect(() => {
    if (seen.current === null) seen.current = new Set(keys);
    else for (const key of keys) seen.current.add(key);
  });

  if (transitions.length === 0) {
    return (
      <EmptyState icon={Clock} title="No transitions recorded">
        The API returned no transition history for this run.
      </EmptyState>
    );
  }

  const lastIndex = transitions.length - 1;

  return (
    <>
      <ol className="timeline">
        {transitions.map((transition, index) => {
          const descriptor = RUN_STATE[transition.to_state];
          const Icon = descriptor.icon;
          const from = transition.from_state ? RUN_STATE[transition.from_state].label : null;

          const classes = ["timeline__item", `timeline__item--${descriptor.tone}`];
          if (index === lastIndex) classes.push("timeline__item--latest");
          if (isNew[index]) classes.push("timeline__item--new");

          return (
            <li key={keys[index]} className={classes.join(" ")}>
              <span className="timeline__dot" aria-hidden="true">
                <Icon size={13} />
              </span>
              <span className="timeline__body">
                <StatusBadge descriptor={descriptor} srPrefix="State:" />
                <span className="timeline__time">
                  {formatTime(transition.occurred_at)} ·{" "}
                  {from ? `from ${from}` : "first recorded state"} · {transition.actor}
                </span>
                <span className="timeline__reason">
                  {transition.reason ?? descriptor.description}
                </span>
              </span>
            </li>
          );
        })}
      </ol>
      <p className="field__hint">
        Server-recorded transitions in the order the API returned them, oldest first. Reason and
        actor are backend-assigned labels; no agent reasoning is shown.
      </p>
    </>
  );
}
