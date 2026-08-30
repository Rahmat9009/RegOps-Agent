// AuditPage — View 8: audit report.
//
// Executed actions, idempotency results, revalidation outcome, processing time,
// evaluation metrics, and the download-audit-package control.
//
// Everything on this screen comes from `GET /runs/{run_id}/audit`. The report
// carries no transition history and no recovery block of its own, so neither is
// reconstructed here: the recovery signal shown is the one the report actually
// contains, `evaluation.resume_success_rate`.

import { useCallback } from "react";
import { Link, useParams } from "react-router-dom";
import {
  CheckCircle2,
  Download,
  FileCheck2,
  FileSignature,
  FlaskConical,
  Gauge,
  LifeBuoy,
  Repeat,
  RefreshCw,
  Timer,
  XCircle,
} from "lucide-react";

import { api, type AuditEvaluation, type AuditReport, type ProposedAction } from "@/lib/api";
import { formatCount, formatDateTime, formatRatio, formatSeconds, pluralize } from "@/lib/format";
import { ACTION_AUTONOMY, ACTION_STATUS, ACTION_TYPE } from "@/lib/presentation";
import { isSafeAuditPackageUrl } from "@/lib/url";
import { useAsync } from "@/hooks/useAsync";
import { Mono, StatusBadge } from "@/components/Badge";
import { Notice } from "@/components/Notice";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { ScoreMeter, Stat } from "@/components/Meter";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";

const EVALUATION_LABELS: Record<keyof AuditEvaluation, { label: string; description: string }> = {
  obligation_precision: {
    label: "Obligation precision",
    description: "Share of extracted obligations that were correct.",
  },
  impact_precision: {
    label: "Impact precision",
    description: "Share of detected impacts that were real.",
  },
  impact_recall: {
    label: "Impact recall",
    description: "Share of real impacts that were detected.",
  },
  citation_correctness: {
    label: "Citation correctness",
    description: "Share of citations that point at the quoted text.",
  },
  false_escalation_rate: {
    label: "False escalation rate",
    description: "Share of escalations to human review that were unnecessary. Lower is better.",
  },
  resume_success_rate: {
    label: "Resume success rate",
    description: "Share of recoverable failures that resumed from a checkpoint successfully.",
  },
};

export function AuditPage() {
  const { runId = "" } = useParams();
  const loader = useCallback(() => api.getRunAudit(runId), [runId]);
  const { data: report, error, loading, reload } = useAsync(loader);

  const crumbs = [
    { label: "Operations", to: "/" },
    { label: `Run ${runId}`, to: `/runs/${runId}` },
    { label: "Audit report" },
  ];

  if (loading) {
    return (
      <>
        <PageHeader title="Audit report" crumbs={crumbs} />
        <Panel title="Report" icon={FileCheck2}>
          <LoadingState label="Loading audit report…" />
        </Panel>
      </>
    );
  }

  if (error || !report) {
    return (
      <>
        <PageHeader title="Audit report" crumbs={crumbs} />
        <Panel title="Report" icon={FileCheck2}>
          {error ? (
            <ErrorState
              error={error}
              onRetry={reload}
              fallbackHref={`/runs/${runId}`}
              fallbackLabel="Back to run detail"
            />
          ) : null}
        </Panel>
      </>
    );
  }

  return <AuditContent report={report} onReload={reload} />;
}

function AuditContent({ report, onReload }: { report: AuditReport; onReload: () => void }) {
  // The URL is validated before it reaches an href — see lib/url.ts.
  const packageUrl = isSafeAuditPackageUrl(report.audit_package_url)
    ? report.audit_package_url
    : null;
  const packageUrlRejected =
    report.audit_package_url != null && report.audit_package_url !== "" && packageUrl === null;

  // A rejected action was never carried out, so it must never appear in a table
  // headed "executed". The contract's audit does not return rejected actions, but
  // if one ever arrived it is separated here rather than silently counted.
  const carriedOut = report.executed_actions.filter((action) => action.status !== "REJECTED");
  const notCarriedOut = report.executed_actions.filter((action) => action.status === "REJECTED");
  const approvedDrafts = carriedOut.filter((action) => action.status === "APPROVED_DRAFT");
  const amendmentApproved = approvedDrafts.length > 0;

  return (
    <>
      <PageHeader
        title="Audit report"
        lede={`Generated ${formatDateTime(report.generated_at)} for run ${report.run_id}.`}
        crumbs={[
          { label: "Operations", to: "/" },
          { label: `Run ${report.run_id}`, to: `/runs/${report.run_id}` },
          { label: "Audit report" },
        ]}
        actions={
          <button type="button" className="btn btn--sm" onClick={onReload}>
            <RefreshCw size={14} aria-hidden="true" />
            Refresh
          </button>
        }
      />

      <AuditOutcome
        amendmentApproved={amendmentApproved}
        resolved={report.revalidation.findings_resolved}
        remaining={report.revalidation.findings_remaining}
        actions={carriedOut.length}
      />

      <Notice tone="review" title="Synthetic run record" icon={FlaskConical}>
        This audit covers a synthetic demonstration run. Approved amendments exist as drafts against
        shadow copies; no real contract was changed and no legal determination was made.
      </Notice>

      <div className="grid grid--4">
        <Stat
          index={0}
          label="Documents processed"
          value={formatCount(report.processing.documents_processed)}
          icon={<FileCheck2 size={13} aria-hidden="true" />}
        />
        <Stat
          index={1}
          label="Processing time"
          value={formatSeconds(report.processing.total_seconds)}
          icon={<Timer size={13} aria-hidden="true" />}
        />
        <Stat
          index={2}
          label="Findings resolved"
          value={formatCount(report.revalidation.findings_resolved)}
          tone={report.revalidation.findings_resolved > 0 ? "verified" : "neutral"}
          note="Confirmed by revalidation"
          icon={<RefreshCw size={13} aria-hidden="true" />}
        />
        <Stat
          index={3}
          label="Findings remaining"
          value={formatCount(report.revalidation.findings_remaining)}
          tone={report.revalidation.findings_remaining > 0 ? "review" : "verified"}
          note={report.revalidation.findings_remaining > 0 ? "Still detected" : "None remaining"}
          icon={<Gauge size={13} aria-hidden="true" />}
        />
      </div>

      <Panel
        title="Actions carried out"
        icon={FileCheck2}
        description="Every action this run actually carried out, with its final status. An action a reviewer rejected never runs and is not listed here."
        flush
      >
        {carriedOut.length === 0 ? (
          <div className="panel__body">
            <EmptyState title="No actions were carried out">
              The run completed without any action being executed. A rejected amendment is a valid
              outcome that executes nothing.
            </EmptyState>
          </div>
        ) : (
          <ActionTable actions={carriedOut} />
        )}
      </Panel>

      {notCarriedOut.length > 0 ? (
        <Panel
          title="Recorded but not executed"
          icon={XCircle}
          tone="critical"
          description="Actions the API returned with a rejected status. Nothing was written for any of them."
          flush
        >
          <ActionTable actions={notCarriedOut} />
        </Panel>
      ) : null}

      <div className="grid grid--2">
        <Panel
          title="Duplicate prevention"
          icon={Repeat}
          description="Every action carries an idempotency key. Repeated attempts are detected and stopped before execution."
        >
          <div className="stack">
            <div className="grid grid--4">
              <Stat
                index={0}
                label="Duplicates prevented"
                value={formatCount(report.idempotency.duplicate_actions_prevented)}
                tone="verified"
                note="Stopped before execution"
              />
              <Stat
                index={1}
                label="Duplicate attempt rate"
                value={formatRatio(report.idempotency.duplicate_action_rate)}
                note="Share of attempts that repeated a key"
              />
            </div>
            <p className="field__hint">
              Both figures describe attempts that were detected as duplicates and stopped before
              execution; neither indicates that a duplicate action ran. The rate is the share of all
              action attempts that repeated an idempotency key — the total attempt count is not part
              of the audit record, so a prevented count above zero always comes with a rate above
              zero.
            </p>
          </div>
        </Panel>

        <Panel
          title="Recovery and revalidation"
          icon={LifeBuoy}
          description="How the run coped with failure, and how many detected findings its executed actions resolved."
        >
          <div className="stack">
            {report.evaluation ? (
              <ScoreMeter
                label="Resume success rate"
                value={report.evaluation.resume_success_rate}
                description="Share of recoverable failures that resumed from a checkpoint successfully. This is the only recovery figure the audit record carries."
                tone={report.evaluation.resume_success_rate >= 0.85 ? "verified" : "review"}
              />
            ) : (
              <p className="field__hint">
                The API returned no evaluation block, so this report carries no recovery figure.
              </p>
            )}
            <div className="grid grid--4">
              <Stat
                index={0}
                label="Resolved"
                value={formatCount(report.revalidation.findings_resolved)}
                tone={report.revalidation.findings_resolved > 0 ? "verified" : "neutral"}
              />
              <Stat
                index={1}
                label="Remaining"
                value={formatCount(report.revalidation.findings_remaining)}
                tone={report.revalidation.findings_remaining > 0 ? "review" : "verified"}
              />
            </div>
            <p className="field__hint">
              A run whose amendment was rejected executes nothing and revalidates nothing, so it
              resolves none.
            </p>
          </div>
        </Panel>
      </div>

      <Panel
        title="Evaluation metrics"
        icon={Gauge}
        description="Measured against the synthetic evaluation set for this run."
      >
        {report.evaluation ? (
          <div className="grid grid--2">
            {(Object.keys(EVALUATION_LABELS) as (keyof AuditEvaluation)[]).map((key) => {
              const meta = EVALUATION_LABELS[key];
              const value = report.evaluation?.[key] ?? 0;
              const lowerIsBetter = key === "false_escalation_rate";
              const good = lowerIsBetter ? value <= 0.1 : value >= 0.85;
              return (
                <ScoreMeter
                  key={key}
                  label={meta.label}
                  value={value}
                  description={meta.description}
                  tone={good ? "verified" : "review"}
                />
              );
            })}
          </div>
        ) : (
          <EmptyState icon={Gauge} title="No evaluation metrics were reported">
            The API returned no evaluation block for this run.
          </EmptyState>
        )}
      </Panel>

      <Panel title="Audit package" icon={Download}>
        {packageUrl ? (
          <div className="stack">
            <p>
              The audit package bundles the executed actions, evidence chains, and revalidation
              results for this run. The link is a short-lived signed <Mono>https</Mono> URL issued by
              the backend and expires on its own.
            </p>
            <a className="btn btn--primary btn--lg" href={packageUrl} download rel="noreferrer" target="_blank">
              <Download size={17} aria-hidden="true" />
              Download audit package
            </a>
          </div>
        ) : (
          <div className="stack">
            <button type="button" className="btn btn--lg" disabled aria-describedby="package-unavailable">
              <Download size={17} aria-hidden="true" />
              Download audit package
            </button>
            <p className="field__hint" id="package-unavailable">
              {packageUrlRejected ? (
                <>
                  Unavailable: the API returned an <Mono>audit_package_url</Mono> that is not the
                  absolute <Mono>https://</Mono> signed URL the contract defines, so this console
                  will not turn it into a link.
                </>
              ) : (
                <>
                  Unavailable: the API returned no <Mono>audit_package_url</Mono> for this run. The
                  control stays disabled rather than pointing at a URL this console invented.
                </>
              )}
            </p>
          </div>
        )}
      </Panel>
    </>
  );
}

/**
 * The closing statement: what this run ended up doing. Read entirely from the
 * audit record — an approved amendment appears in the report as an
 * `APPROVED_DRAFT`, and a run where none does executed no amendment.
 */
function AuditOutcome({
  amendmentApproved,
  resolved,
  remaining,
  actions,
}: {
  amendmentApproved: boolean;
  resolved: number;
  remaining: number;
  actions: number;
}) {
  return (
    <section
      className={amendmentApproved ? "outcome outcome--verified" : "outcome"}
      aria-label="Run outcome"
    >
      <span className="outcome__icon" aria-hidden="true">
        {amendmentApproved ? <CheckCircle2 size={26} /> : <FileSignature size={26} />}
      </span>
      <div className="outcome__body">
        <strong className="outcome__title">
          {amendmentApproved
            ? "An amendment was approved and stored as a draft"
            : "No amendment was approved in this run"}
        </strong>
        <p className="outcome__text">
          {amendmentApproved ? (
            <>
              {pluralize(actions, "action")} carried out. Revalidation confirmed{" "}
              {pluralize(resolved, "finding")} resolved, with {formatCount(remaining)} still
              detected. The draft sits against a synthetic contract&rsquo;s shadow copy; no real
              contract was changed.
            </>
          ) : (
            <>
              {pluralize(actions, "action")} carried out, none of them an amendment. A rejected
              amendment executes nothing and revalidates nothing, which is why{" "}
              {pluralize(resolved, "finding")} were resolved and {formatCount(remaining)} remain.
            </>
          )}
        </p>
      </div>
    </section>
  );
}

function ActionTable({ actions }: { actions: ProposedAction[] }) {
  return (
    <div className="table-wrap">
      <table className="table table--dense">
        <thead>
          <tr>
            <th scope="col">Action</th>
            <th scope="col">Type</th>
            <th scope="col">Autonomy</th>
            <th scope="col">Status</th>
            <th scope="col">Finding</th>
            <th scope="col">Idempotency key</th>
          </tr>
        </thead>
        <tbody>
          {actions.map((action) => (
            <tr key={action.action_id}>
              <th scope="row" className="rowhead">
                <Mono>{action.action_id}</Mono>
              </th>
              <td>
                <StatusBadge descriptor={ACTION_TYPE[action.type]} srPrefix="Type:" />
              </td>
              <td>
                <StatusBadge descriptor={ACTION_AUTONOMY[action.autonomy]} srPrefix="Autonomy:" />
              </td>
              <td>
                <StatusBadge descriptor={ACTION_STATUS[action.status]} srPrefix="Status:" />
              </td>
              <td>
                <Link to={`/findings/${action.finding_id}`}>
                  <Mono>{action.finding_id}</Mono>
                </Link>
              </td>
              <td>
                <Mono>{action.idempotency_key}</Mono>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
