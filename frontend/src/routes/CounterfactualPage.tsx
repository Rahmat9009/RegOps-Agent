// CounterfactualPage — View 6: counterfactual shadow-state preview.
//
// `POST /actions/{action_id}/preview` reruns the same matching and validation
// pipeline against a shadow copy and returns deterministic counts and ids. The
// narrative is explicitly non-authoritative and is labelled as such.

import { useCallback } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  FlaskConical,
  GitCompare,
  Layers,
  MessageSquareText,
  TrendingUp,
  UserCheck,
  type LucideIcon,
} from "lucide-react";

import { api, type CounterfactualPreview } from "@/lib/api";
import { formatCount, pluralize } from "@/lib/format";
import { useAsync } from "@/hooks/useAsync";
import { Mono, StatusBadge } from "@/components/Badge";
import { Notice } from "@/components/Notice";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { Stat } from "@/components/Meter";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";

export function CounterfactualPage() {
  const { actionId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const approvalId = searchParams.get("approval");
  const runId = searchParams.get("run");

  const loader = useCallback(() => api.previewAction(actionId), [actionId]);
  const { data: preview, error, loading, reload } = useAsync(loader);

  const crumbs = [
    { label: "Operations", to: "/" },
    ...(runId ? [{ label: `Run ${runId}`, to: `/runs/${runId}` }] : []),
    { label: "Counterfactual preview" },
  ];

  return (
    <>
      <PageHeader
        title="Counterfactual preview"
        lede="What the finding picture would look like if this action were applied. Nothing here has been executed."
        crumbs={crumbs}
        status={
          <span className="badge badge--review badge--lg">
            <FlaskConical size={18} aria-hidden="true" />
            Shadow-state simulation
          </span>
        }
      />

      <Notice tone="review" title="This is a shadow-state simulation" icon={FlaskConical}>
        The result below comes from rerunning the same matching and validation pipeline against a{" "}
        <strong>shadow copy</strong> of the synthetic corpus. No document has been changed, no
        action has been executed, and nothing here is a legal determination.
      </Notice>

      {loading ? (
        <Panel title="Predicted outcome" icon={GitCompare}>
          <LoadingState label="Running the shadow-state simulation…" />
        </Panel>
      ) : error || !preview ? (
        <Panel title="Predicted outcome" icon={GitCompare}>
          {error ? (
            <ErrorState
              error={error}
              onRetry={reload}
              fallbackHref={runId ? `/runs/${runId}` : "/"}
              fallbackLabel={runId ? "Back to run detail" : "Back to dashboard"}
            />
          ) : null}
        </Panel>
      ) : (
        <PreviewContent preview={preview} approvalId={approvalId} runId={runId} />
      )}
    </>
  );
}

function PreviewContent({
  preview,
  approvalId,
  runId,
}: {
  preview: CounterfactualPreview;
  approvalId: string | null;
  runId: string | null;
}) {
  const resolved = preview.resolved_finding_ids.length;
  const unchanged = preview.unchanged_finding_ids.length;
  const introduced = preview.new_conflict_ids.length;

  return (
    <>
      <Panel
        title="Predicted outcome"
        icon={GitCompare}
        description={`Shadow run ${preview.shadow_run_id} · action ${preview.action_id}`}
      >
        <div className="stack">
          <div className="grid grid--4">
            <Stat
              label="Findings before"
              value={formatCount(preview.baseline_finding_count)}
              note="Baseline detected today"
              icon={<Layers size={14} aria-hidden="true" />}
            />
            <Stat
              label="Predicted to resolve"
              value={formatCount(resolved)}
              tone="verified"
              note="Would no longer be detected"
              icon={<CheckCircle2 size={14} aria-hidden="true" />}
            />
            <Stat
              label="Unchanged"
              value={formatCount(unchanged)}
              note="Still detected afterwards"
              icon={<CircleDashed size={14} aria-hidden="true" />}
            />
            <Stat
              label="New conflicts introduced"
              value={formatCount(introduced)}
              tone={introduced > 0 ? "critical" : "neutral"}
              note={introduced > 0 ? "Caused by this action" : "None introduced"}
              icon={<AlertTriangle size={14} aria-hidden="true" />}
            />
          </div>

          <Notice
            tone={preview.detected_finding_picture_improves ? "verified" : "critical"}
            title={
              preview.detected_finding_picture_improves
                ? "The detected finding picture improves"
                : "The detected finding picture does not improve"
            }
            icon={preview.detected_finding_picture_improves ? TrendingUp : AlertTriangle}
          >
            This is a deterministic comparison of detected findings before and after the simulated
            change. It describes detection only — it is not a statement about legal compliance.
          </Notice>
        </div>
      </Panel>

      <div className="grid grid--2">
        <IdListPanel
          title="Predicted to resolve"
          icon={CheckCircle2}
          description="Findings the shadow rerun no longer detects."
          ids={preview.resolved_finding_ids}
          emptyText="No findings would be resolved by this action."
        />
        <IdListPanel
          title="Unchanged"
          icon={CircleDashed}
          description="Findings still detected after the simulated change."
          ids={preview.unchanged_finding_ids}
          emptyText="No findings would remain unchanged."
        />
        <IdListPanel
          title="New conflicts introduced"
          icon={AlertTriangle}
          description="Conflicts that appear only because of this action."
          ids={preview.new_conflict_ids}
          emptyText="This action introduces no new conflicts."
        />
        <IdListPanel
          title="Remaining high-risk cases"
          icon={AlertTriangle}
          description="High-severity findings still present after the simulated change."
          ids={preview.remaining_high_risk_ids}
          emptyText="No high-risk findings would remain."
        />
      </div>

      <Panel
        title="Narrative"
        icon={MessageSquareText}
        description="Explanatory text only. The counts and identifiers above are authoritative; this paragraph is not."
      >
        {preview.narrative ? (
          <>
            <p>{preview.narrative}</p>
            <p className="field__hint">
              The narrative describes the deterministic result; it does not compute it. Where the
              two disagree, the counts and identifiers are correct.
            </p>
          </>
        ) : (
          <EmptyState icon={MessageSquareText} title="No narrative was returned">
            The deterministic counts above stand on their own.
          </EmptyState>
        )}
      </Panel>

      {approvalId ? (
        <div className="row">
          <Link
            className="btn btn--primary"
            to={`/approvals/${approvalId}${runId ? `?run=${runId}` : ""}`}
          >
            <UserCheck size={16} aria-hidden="true" />
            Back to the approval decision
          </Link>
        </div>
      ) : null}

      <p className="field__hint">
        <StatusBadge
          descriptor={{
            label: "Simulation only",
            tone: "review",
            icon: FlaskConical,
            description: "",
          }}
        />{" "}
        Shadow run <Mono>{preview.shadow_run_id}</Mono> is discarded after the preview.
      </p>
    </>
  );
}

function IdListPanel({
  title,
  icon,
  description,
  ids,
  emptyText,
}: {
  title: string;
  icon: LucideIcon;
  description: string;
  ids: string[];
  emptyText: string;
}) {
  const Icon = icon;
  return (
    <section className="panel" aria-label={title}>
      <div className="panel__head">
        <h2 className="panel__title">
          <Icon size={17} />
          {title}
        </h2>
        <span className="panel__actions">
          <span className="tag">{pluralize(ids.length, "finding")}</span>
        </span>
        <p className="panel__desc">{description}</p>
      </div>
      <div className="panel__body">
        {ids.length === 0 ? (
          <p className="field__hint">{emptyText}</p>
        ) : (
          <ul className="id-list">
            {ids.map((id) => (
              <li key={id}>{id}</li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
