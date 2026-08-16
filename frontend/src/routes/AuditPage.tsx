// AuditPage — View 8: audit report.
//
// Executed actions, idempotency results, revalidation outcome, processing time,
// evaluation metrics, and the download-audit-package control.

import { useCallback } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Download,
  FileCheck2,
  FlaskConical,
  Gauge,
  Repeat,
  RefreshCw,
  Timer,
} from "lucide-react";

import { api, type AuditEvaluation, type AuditReport } from "@/lib/api";
import { formatCount, formatDateTime, formatRatio, formatSeconds } from "@/lib/format";
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

      <Notice tone="review" title="Synthetic run record" icon={FlaskConical}>
        This audit covers a synthetic demonstration run. Approved amendments exist as drafts against
        shadow copies; no real contract was changed and no legal determination was made.
      </Notice>

      <div className="grid grid--4">
        <Stat
          label="Documents processed"
          value={formatCount(report.processing.documents_processed)}
          icon={<FileCheck2 size={14} aria-hidden="true" />}
        />
        <Stat
          label="Processing time"
          value={formatSeconds(report.processing.total_seconds)}
          icon={<Timer size={14} aria-hidden="true" />}
        />
        <Stat
          label="Findings resolved"
          value={formatCount(report.revalidation.findings_resolved)}
          tone="verified"
          note="Confirmed by revalidation"
          icon={<RefreshCw size={14} aria-hidden="true" />}
        />
        <Stat
          label="Findings remaining"
          value={formatCount(report.revalidation.findings_remaining)}
          tone={report.revalidation.findings_remaining > 0 ? "review" : "verified"}
          note={report.revalidation.findings_remaining > 0 ? "Still detected" : "None remaining"}
          icon={<Gauge size={14} aria-hidden="true" />}
        />
      </div>

      <Panel
        title="Executed actions"
        icon={FileCheck2}
        description="Every action this run carried out, with its final status."
        flush
      >
        {report.executed_actions.length === 0 ? (
          <div className="panel__body">
            <EmptyState title="No actions were executed">
              The run completed without any action being carried out.
            </EmptyState>
          </div>
        ) : (
          <div className="table-wrap">
            <table className="table">
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
                {report.executed_actions.map((action) => (
                  <tr key={action.action_id}>
                    <th scope="row" style={{ background: "transparent", textTransform: "none" }}>
                      <Mono>{action.action_id}</Mono>
                    </th>
                    <td>
                      <StatusBadge descriptor={ACTION_TYPE[action.type]} srPrefix="Type:" />
                    </td>
                    <td>
                      <StatusBadge
                        descriptor={ACTION_AUTONOMY[action.autonomy]}
                        srPrefix="Autonomy:"
                      />
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
        )}
      </Panel>

      <div className="grid grid--2">
        <Panel
          title="Idempotency"
          icon={Repeat}
          description="Every action carries an idempotency key. Repeated attempts are detected and stopped before execution."
        >
          <div className="stack">
            <div className="grid grid--2">
              <Stat
                label="Duplicate attempts prevented"
                value={formatCount(report.idempotency.duplicate_actions_prevented)}
                tone="verified"
                note="Detected by idempotency key and stopped"
              />
              <Stat
                label="Duplicate attempt rate"
                value={formatRatio(report.idempotency.duplicate_action_rate)}
                note="Share of attempts that were duplicates"
              />
            </div>
            <p className="field__hint">
              Both figures count action attempts that were detected as duplicates and prevented.
              They do not indicate that any duplicate action was executed.
            </p>
          </div>
        </Panel>

        <Panel
          title="Revalidation"
          icon={RefreshCw}
          description="The pipeline was rerun after execution to confirm which detected findings the run's actions resolved. A run whose amendment was rejected resolves none."
        >
          <div className="grid grid--2">
            <Stat
              label="Resolved"
              value={formatCount(report.revalidation.findings_resolved)}
              tone="verified"
            />
            <Stat
              label="Remaining"
              value={formatCount(report.revalidation.findings_remaining)}
              tone={report.revalidation.findings_remaining > 0 ? "review" : "verified"}
            />
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
              results for this run.
            </p>
            <a
              className="btn btn--primary"
              href={packageUrl}
              download
              rel="noreferrer"
              target="_blank"
            >
              <Download size={16} aria-hidden="true" />
              Download audit package
            </a>
          </div>
        ) : (
          <div className="stack">
            <button type="button" className="btn" disabled aria-describedby="package-unavailable">
              <Download size={16} aria-hidden="true" />
              Download audit package
            </button>
            <p className="field__hint" id="package-unavailable">
              {packageUrlRejected ? (
                <>
                  Unavailable: the API returned an <Mono>audit_package_url</Mono> that is not an
                  absolute <Mono>https://</Mono> URL, so this console will not turn it into a link.
                </>
              ) : (
                <>
                  Unavailable: the API returned no <Mono>audit_package_url</Mono> for this run. The
                  control stays disabled rather than pointing at a URL this console invented.
                </>
              )}{" "}
              See CR-006 in <Mono>frontend/CONTRACT_REQUESTS.md</Mono>.
            </p>
          </div>
        )}
      </Panel>
    </>
  );
}
