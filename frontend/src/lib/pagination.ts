// pagination.ts — Pure helpers for the findings list's filter + page state.
//
// `GET /runs/{run_id}/findings` takes `severity`, `q`, `limit` and `offset`, and
// returns `total` and `by_severity` for the complete filtered result. These
// helpers keep the URL, the request and the rendered range in agreement, and are
// pure so the reset-on-filter-change rule can be tested without a DOM.

import type { Severity } from "@/lib/api";

/** Page size the console requests. Within the contract's 1–100 range. */
export const FINDINGS_PAGE_SIZE = 25;

export interface FindingsQuery {
  /** Empty string means "all severities". */
  severity: Severity | "";
  /** Trimmed free-text search, or an empty string. */
  q: string;
  /** Zero-based offset into the filtered result. */
  offset: number;
}

export function isSeverity(value: string | null): value is Severity {
  return value === "low" || value === "medium" || value === "high";
}

/** Read the query out of the URL, ignoring anything malformed. */
export function readFindingsQuery(params: URLSearchParams): FindingsQuery {
  const severityParam = params.get("severity");
  return {
    severity: isSeverity(severityParam) ? severityParam : "",
    q: (params.get("q") ?? "").trim(),
    offset: parseOffset(params.get("offset")),
  };
}

/** A non-negative integer offset, or 0 for anything else. */
export function parseOffset(value: string | null): number {
  if (value === null) return 0;
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed < 0) return 0;
  return parsed;
}

/** Build the shareable URL query. Defaults are omitted to keep links short. */
export function buildFindingsSearch(query: FindingsQuery): URLSearchParams {
  const params = new URLSearchParams();
  if (query.severity) params.set("severity", query.severity);
  if (query.q) params.set("q", query.q);
  if (query.offset > 0) params.set("offset", String(query.offset));
  return params;
}

/**
 * Identity of the active filters. When this changes, the offset must go back to
 * zero — page 3 of the previous filter is meaningless under a new one.
 */
export function filterKey(query: Pick<FindingsQuery, "severity" | "q">): string {
  return `${query.severity}|${query.q}`;
}

/** Apply the reset rule: a filter change returns the caller to the first page. */
export function nextFindingsQuery(
  previous: FindingsQuery,
  next: Omit<FindingsQuery, "offset"> & { offset?: number },
): FindingsQuery {
  const filtersChanged = filterKey(previous) !== filterKey(next);
  return {
    severity: next.severity,
    q: next.q,
    offset: filtersChanged ? 0 : Math.max(0, next.offset ?? previous.offset),
  };
}

export interface PageRange {
  /** 1-based index of the first visible row, or 0 when the page is empty. */
  first: number;
  /** 1-based index of the last visible row, or 0 when the page is empty. */
  last: number;
  total: number;
  hasPrevious: boolean;
  hasNext: boolean;
}

export function pageRange(offset: number, visibleCount: number, total: number): PageRange {
  const first = visibleCount === 0 ? 0 : offset + 1;
  const last = visibleCount === 0 ? 0 : offset + visibleCount;
  return {
    first,
    last,
    total,
    hasPrevious: offset > 0,
    hasNext: offset + visibleCount < total,
  };
}

/** The previous page's offset, never below zero. */
export function previousOffset(offset: number, limit = FINDINGS_PAGE_SIZE): number {
  return Math.max(0, offset - limit);
}

/** The next page's offset, never past the end of the filtered result. */
export function nextOffset(offset: number, limit = FINDINGS_PAGE_SIZE, total = 0): number {
  const candidate = offset + limit;
  return candidate >= total ? offset : candidate;
}
