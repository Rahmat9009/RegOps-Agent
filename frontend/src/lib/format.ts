// format.ts — Display formatting only. No data fetching, no API knowledge.

/** ISO 8601 timestamp -> locale date + time, or an em dash when absent. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

/** ISO 8601 date -> locale date, or an em dash when absent. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date);
}

/** Clock time only — used for client-observed transitions. */
export function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

/** 0..1 -> "63%" */
export function formatRatio(value: number): string {
  return `${Math.round(value * 100)}%`;
}

/** 0..100 -> "49%" */
export function formatPercent(value: number): string {
  return `${Math.round(value)}%`;
}

export function formatSeconds(value: number): string {
  if (value < 60) return `${value.toFixed(1)} s`;
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value % 60);
  return `${minutes} min ${seconds} s`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatCount(value: number): string {
  return new Intl.NumberFormat().format(value);
}

/** "conflicts_with" -> "Conflicts with" (fallback for unmapped enum values). */
export function humanizeToken(token: string): string {
  const spaced = token.replace(/[_-]+/g, " ").toLowerCase();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** Pluralise a countable noun without an i18n dependency. */
export function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return `${formatCount(count)} ${count === 1 ? singular : plural}`;
}
