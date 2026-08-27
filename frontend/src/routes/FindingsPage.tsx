// FindingsPage — View 4: findings list with search, filters and pagination.
//
// `GET /runs/{run_id}/findings` returns FindingSummary records that carry the
// full score set, so every column this view is required to show comes from the
// list response itself. There is no per-row detail request.
//
// `items` is one page; `total` and `by_severity` describe the complete filtered
// result. Changing a filter always returns the reader to the first page.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ChevronLeft, ChevronRight, ListFilter, Loader2, Search } from "lucide-react";

import {
  api,
  type FindingStatus,
  type FindingSummary,
  type FindingVerdict,
  type Severity,
  type SourceAuthority,
} from "@/lib/api";
import { formatCount, pluralize } from "@/lib/format";
import {
  buildFindingsSearch,
  filterKey,
  FINDINGS_PAGE_SIZE,
  nextOffset,
  pageRange,
  previousOffset,
  readFindingsQuery,
} from "@/lib/pagination";
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
import { ScoreBar } from "@/components/Meter";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { EmptyState, ErrorState, NoResultsState, SkeletonRows } from "@/components/states";

const SEARCH_DEBOUNCE_MS = 300;

/**
 * Short labels for the table only. A column heading already supplies the
 * category, so repeating it in every cell costs width without adding meaning —
 * and the full label still reaches assistive technology through `srPrefix`.
 * These are display strings, never identifiers.
 */
const SEVERITY_SHORT: Record<Severity, string> = { high: "High", medium: "Medium", low: "Low" };

const VERDICT_SHORT: Record<FindingVerdict, string> = {
  survived: "Survived",
  refuted: "Refuted",
  uncertain: "Uncertain",
};

const AUTHORITY_SHORT: Record<SourceAuthority, string> = {
  primary_government: "Primary government",
  secondary: "Secondary",
  internal: "Internal",
};

const STATUS_SHORT: Record<FindingStatus, string> = {
  OPEN: "Open",
  AWAITING_APPROVAL: "Awaiting approval",
  RESOLVED: "Resolved",
};

export function FindingsPage() {
  const { runId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();

  const query = readFindingsQuery(searchParams);
  const { severity, offset } = query;

  const [queryInput, setQueryInput] = useState(query.q);
  const [debouncedQuery, setDebouncedQuery] = useState(query.q);

  // Debounce so typing does not issue a request per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(queryInput.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [queryInput]);

  // Keep the URL shareable, without pushing a history entry per keystroke. A
  // filter change resets the offset: page 3 of the old filter means nothing under
  // the new one.
  const activeFilters = filterKey({ severity, q: debouncedQuery });
  const lastFilters = useRef(activeFilters);

  useEffect(() => {
    const filtersChanged = lastFilters.current !== activeFilters;
    lastFilters.current = activeFilters;
    const next = buildFindingsSearch({
      severity,
      q: debouncedQuery,
      offset: filtersChanged ? 0 : offset,
    });
    setSearchParams(next, { replace: true });
  }, [activeFilters, severity, debouncedQuery, offset, setSearchParams]);

  const loader = useCallback(
    () =>
      api.listRunFindings(runId, {
        severity: severity === "" ? null : severity,
        q: debouncedQuery === "" ? null : debouncedQuery,
        limit: FINDINGS_PAGE_SIZE,
        offset,
      }),
    [runId, severity, debouncedQuery, offset],
  );

  const { data, error, loading, refreshing, reload } = useAsync(loader);
  const items = useMemo(() => data?.items ?? [], [data]);

  const filtersActive = severity !== "" || debouncedQuery !== "";
  const range = pageRange(offset, items.length, data?.total ?? 0);

  function updateSearch(next: { severity?: typeof severity; offset?: number }): void {
    setSearchParams(
      buildFindingsSearch({
        severity: next.severity ?? severity,
        q: debouncedQuery,
        // Any severity change starts again at the first page.
        offset: next.severity !== undefined ? 0 : (next.offset ?? offset),
      }),
      { replace: true },
    );
  }

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
                const value = event.target.value;
                updateSearch({
                  severity: value === "low" || value === "medium" || value === "high" ? value : "",
                });
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
              range.total === 0 ? (
                pluralize(0, "finding")
              ) : (
                `${formatCount(range.first)}–${formatCount(range.last)} of ${pluralize(
                  range.total,
                  "finding",
                )}`
              )
            ) : (
              ""
            )}
          </p>
        </div>

        {data && data.total > 0 ? (
          <div className="filters filters--counts">
            <span className="field__hint">Across the whole filtered result:</span>
            <div className="chip-row">
              {SEVERITY_ORDER.map((level) => (
                <StatusBadge
                  key={level}
                  descriptor={SEVERITY[level]}
                  label={`${SEVERITY[level].label}: ${formatCount(data.by_severity[level])}`}
                  srPrefix="Filtered count —"
                />
              ))}
            </div>
          </div>
        ) : null}

        {loading ? (
          <div className="panel__body">
            <SkeletonRows rows={6} />
          </div>
        ) : error ? (
          <div className="panel__body">
            <ErrorState
              error={error}
              onRetry={reload}
              fallbackHref={`/runs/${runId}`}
              fallbackLabel="Back to run detail"
            />
          </div>
        ) : items.length === 0 && filtersActive ? (
          <div className="panel__body">
            <NoResultsState onClear={clearFilters} />
          </div>
        ) : items.length === 0 ? (
          <div className="panel__body">
            <EmptyState icon={Search} title="No findings yet">
              Findings appear after the mapping stage produces candidates and verification assigns a
              verdict. Keep the run detail page open to watch progress.
            </EmptyState>
          </div>
        ) : (
          <FindingsTable items={items} />
        )}

        {data && (range.hasPrevious || range.hasNext) ? (
          <nav className="pager" aria-label="Findings pages">
            <button
              type="button"
              className="btn btn--sm"
              disabled={!range.hasPrevious}
              onClick={() => updateSearch({ offset: previousOffset(offset) })}
            >
              <ChevronLeft size={14} aria-hidden="true" />
              Previous page
            </button>
            <span className="pager__status">
              {`${formatCount(range.first)}–${formatCount(range.last)} of ${formatCount(
                range.total,
              )}`}
            </span>
            <button
              type="button"
              className="btn btn--sm"
              disabled={!range.hasNext}
              onClick={() =>
                updateSearch({ offset: nextOffset(offset, FINDINGS_PAGE_SIZE, range.total) })
              }
            >
              Next page
              <ChevronRight size={14} aria-hidden="true" />
            </button>
          </nav>
        ) : null}
      </Panel>
    </>
  );
}

/**
 * The table scrolls inside its own container in both directions, so a wide row
 * never pushes the page sideways and the column headings stay put while a long
 * page is read.
 */
function FindingsTable({ items }: { items: FindingSummary[] }) {
  return (
    <div className="table-wrap table-wrap--tall">
      <table className="table table--dense">
        <caption className="sr-only">
          Every finding shows its operational severity, relationship, verdict, evidence strength,
          source authority, interpretation confidence, and whether human review is required.
        </caption>
        <thead>
          <tr>
            <th scope="col">Finding</th>
            <th scope="col">Severity</th>
            <th scope="col">Relationship</th>
            <th scope="col">Verdict</th>
            <th scope="col">Evidence</th>
            <th scope="col">Interpretation</th>
            <th scope="col">Review</th>
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.finding_id}>
              <th scope="row" className="rowhead">
                <Link to={`/findings/${item.finding_id}`}>
                  <Mono>{item.finding_id}</Mono>
                </Link>
                <span className="field__hint" style={{ display: "block" }}>
                  <Mono>{item.target_id}</Mono>
                </span>
              </th>
              <td>
                <StatusBadge
                  descriptor={SEVERITY[item.severity]}
                  label={SEVERITY_SHORT[item.severity]}
                  srPrefix={`Severity: ${SEVERITY[item.severity].label},`}
                />
              </td>
              <td>
                <StatusBadge descriptor={RELATIONSHIP[item.relationship]} srPrefix="Relationship:" />
              </td>
              <td>
                <StatusBadge
                  descriptor={VERDICT[item.verdict]}
                  label={VERDICT_SHORT[item.verdict]}
                  srPrefix={`Verdict: ${VERDICT[item.verdict].label},`}
                />
              </td>
              <td>
                <span className="stack stack--tight">
                  <ScoreBar label="Evidence strength" value={item.scores.evidence_strength} />
                  <StatusBadge
                    descriptor={SOURCE_AUTHORITY[item.scores.source_authority]}
                    label={AUTHORITY_SHORT[item.scores.source_authority]}
                    srPrefix={`Source authority: ${
                      SOURCE_AUTHORITY[item.scores.source_authority].label
                    },`}
                  />
                </span>
              </td>
              <td>
                <ScoreBar
                  label="Interpretation confidence"
                  value={item.scores.interpretation_confidence}
                />
              </td>
              <td>
                <StatusBadge
                  descriptor={humanReviewDescriptor(item.human_review_required)}
                  label={item.human_review_required ? "Required" : "Not required"}
                  srPrefix="Human review:"
                />
              </td>
              <td>
                <StatusBadge
                  descriptor={FINDING_STATUS[item.status]}
                  label={STATUS_SHORT[item.status]}
                  srPrefix="Status:"
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
