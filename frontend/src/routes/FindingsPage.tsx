// FindingsPage — View 4: findings list with search and filters.
//
// `GET /runs/{run_id}/findings` returns FindingSummary records, which carry
// severity, verdict, status and the human-review flag but not the score set. The
// four score fields this view is required to show live on `Finding`, so each listed
// row is hydrated with `GET /findings/{finding_id}`. That is an N+1 call pattern;
// CONTRACT_REQUESTS.md CR-007 asks for the scores on the summary instead.

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ListFilter, Loader2, Search } from "lucide-react";

import { api, type Finding, type FindingSummary, type Severity } from "@/lib/api";
import { formatRatio, pluralize } from "@/lib/format";
import {
  FINDING_STATUS,
  RELATIONSHIP,
  SEVERITY,
  SEVERITY_ORDER,
  SOURCE_AUTHORITY,
  VERDICT,
  humanReviewDescriptor,
} from "@/lib/presentation";
import { useAsync } from "@/hooks/useAsync";
import { Mono, StatusBadge } from "@/components/Badge";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { EmptyState, ErrorState, NoResultsState, SkeletonRows } from "@/components/states";

const SEARCH_DEBOUNCE_MS = 300;

export function FindingsPage() {
  const { runId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();

  const severityParam = searchParams.get("severity");
  const severity: Severity | "" = isSeverity(severityParam) ? severityParam : "";
  const queryParam = searchParams.get("q") ?? "";

  const [queryInput, setQueryInput] = useState(queryParam);
  const [debouncedQuery, setDebouncedQuery] = useState(queryParam);

  // Debounce so typing does not issue a request per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(queryInput), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [queryInput]);

  // Keep the URL shareable, without pushing a history entry per keystroke.
  useEffect(() => {
    const next = new URLSearchParams();
    if (severity) next.set("severity", severity);
    if (debouncedQuery) next.set("q", debouncedQuery);
    setSearchParams(next, { replace: true });
  }, [severity, debouncedQuery, setSearchParams]);

  const loader = useCallback(
    () =>
      api.listRunFindings(runId, {
        severity: severity === "" ? null : severity,
        q: debouncedQuery.trim() === "" ? null : debouncedQuery.trim(),
      }),
    [runId, severity, debouncedQuery],
  );

  const { data, error, loading, refreshing, reload } = useAsync(loader);
  const items = useMemo(() => data?.items ?? [], [data]);
  const details = useFindingDetails(items);

  const filtersActive = severity !== "" || debouncedQuery.trim() !== "";

  function clearFilters(): void {
    setQueryInput("");
    setDebouncedQuery("");
    setSearchParams(new URLSearchParams(), { replace: true });
  }

  return (
    <>
      <PageHeader
        title="Findings"
        lede="Potential conflicts detected between the regulation's obligations and the synthetic corpus. Severity is operational, not legal."
        crumbs={[
          { label: "Operations", to: "/" },
          { label: `Run ${runId}`, to: `/runs/${runId}` },
          { label: "Findings" },
        ]}
      />

      <Panel title="All findings" icon={ListFilter} flush>
        <div className="filters">
          <div className="field">
            <label className="field__label" htmlFor="findings-search">
              Search
            </label>
            <input
              id="findings-search"
              className="input"
              type="search"
              placeholder="Target id or obligation text"
              value={queryInput}
              onChange={(event) => setQueryInput(event.target.value)}
              aria-describedby="findings-search-hint"
            />
            <p className="field__hint" id="findings-search-hint">
              Free-text search over target and obligation text.
            </p>
          </div>

          <div className="field">
            <label className="field__label" htmlFor="findings-severity">
              Operational severity
            </label>
            <select
              id="findings-severity"
              className="select"
              value={severity}
              onChange={(event) => {
                const next = new URLSearchParams(searchParams);
                if (event.target.value) next.set("severity", event.target.value);
                else next.delete("severity");
                setSearchParams(next, { replace: true });
              }}
            >
              <option value="">All severities</option>
              {SEVERITY_ORDER.map((level) => (
                <option key={level} value={level}>
                  {SEVERITY[level].label}
                </option>
              ))}
            </select>
          </div>

          {filtersActive ? (
            <button type="button" className="btn btn--sm" onClick={clearFilters}>
              Clear filters
            </button>
          ) : null}

          <p className="filters__count" role="status">
            {refreshing ? (
              <>
                <Loader2 size={13} aria-hidden="true" className="spin" /> Searching…
              </>
            ) : data ? (
              pluralize(data.total, "finding")
            ) : (
              ""
            )}
          </p>
        </div>

        <div className="panel__body">
          {loading ? (
            <SkeletonRows rows={4} />
          ) : error ? (
            <ErrorState
              error={error}
              onRetry={reload}
              fallbackHref={`/runs/${runId}`}
              fallbackLabel="Back to run detail"
            />
          ) : items.length === 0 && filtersActive ? (
            <NoResultsState onClear={clearFilters} />
          ) : items.length === 0 ? (
            <EmptyState icon={Search} title="No findings yet">
              Findings appear after the mapping stage produces candidates and verification assigns
              a verdict. Keep the run detail page open to watch progress.
            </EmptyState>
          ) : (
            <FindingsTable items={items} details={details} />
          )}
        </div>
      </Panel>
    </>
  );
}

function FindingsTable({
  items,
  details,
}: {
  items: FindingSummary[];
  details: Record<string, Finding | null>;
}) {
  return (
    <div className="table-wrap">
      <table className="table">
        <caption>
          Every finding shows its verdict, operational severity, evidence strength, source
          authority, interpretation confidence, and whether human review is required.
        </caption>
        <thead>
          <tr>
            <th scope="col">Finding</th>
            <th scope="col">Relationship</th>
            <th scope="col">Severity</th>
            <th scope="col">Verdict</th>
            <th scope="col">Evidence</th>
            <th scope="col">Interpretation</th>
            <th scope="col">Review</th>
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const detail = details[item.finding_id];
            return (
              <tr key={item.finding_id}>
                <th scope="row" style={{ background: "transparent", textTransform: "none" }}>
                  <Link to={`/findings/${item.finding_id}`}>
                    <Mono>{item.finding_id}</Mono>
                  </Link>
                  <span className="field__hint" style={{ display: "block" }}>
                    <Mono>{item.target_id}</Mono>
                  </span>
                </th>
                <td>
                  <StatusBadge
                    descriptor={RELATIONSHIP[item.relationship]}
                    srPrefix="Relationship:"
                  />
                </td>
                <td>
                  <StatusBadge descriptor={SEVERITY[item.severity]} srPrefix="Severity:" />
                </td>
                <td>
                  <StatusBadge descriptor={VERDICT[item.verdict]} srPrefix="Verdict:" />
                </td>
                <td>
                  {detail === undefined ? (
                    <span className="field__hint">Loading…</span>
                  ) : detail === null ? (
                    <span className="field__hint">Unavailable</span>
                  ) : (
                    <span className="stack stack--tight">
                      <strong>{formatRatio(detail.scores.evidence_strength)}</strong>
                      <StatusBadge
                        descriptor={SOURCE_AUTHORITY[detail.scores.source_authority]}
                        srPrefix="Source authority:"
                      />
                    </span>
                  )}
                </td>
                <td>
                  {detail ? (
                    <strong>{formatRatio(detail.scores.interpretation_confidence)}</strong>
                  ) : (
                    <span className="field__hint">—</span>
                  )}
                </td>
                <td>
                  <StatusBadge
                    descriptor={humanReviewDescriptor(item.human_review_required)}
                    label={item.human_review_required ? "Required" : "Not required"}
                    srPrefix="Human review:"
                  />
                </td>
                <td>
                  <StatusBadge descriptor={FINDING_STATUS[item.status]} srPrefix="Status:" />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Hydrate each listed finding with its score set. `undefined` means "still
 * loading", `null` means the detail call failed — the row degrades rather than
 * failing the whole table.
 */
function useFindingDetails(items: FindingSummary[]): Record<string, Finding | null> {
  const [details, setDetails] = useState<Record<string, Finding | null>>({});
  const ids = items.map((item) => item.finding_id).join(",");

  useEffect(() => {
    if (!ids) return;
    let cancelled = false;

    void Promise.all(
      ids.split(",").map(async (id): Promise<[string, Finding | null]> => {
        try {
          return [id, await api.getFinding(id)];
        } catch {
          return [id, null];
        }
      }),
    ).then((entries) => {
      if (cancelled) return;
      setDetails(Object.fromEntries(entries));
    });

    return () => {
      cancelled = true;
    };
  }, [ids]);

  return details;
}

function isSeverity(value: string | null): value is Severity {
  return value === "low" || value === "medium" || value === "high";
}
