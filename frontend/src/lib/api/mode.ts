// mode.ts — Resolves which adapter the console runs against, and where the real
// one points.
//
// These are read from build-time Vite variables (`VITE_API_MODE`,
// `VITE_API_BASE_URL`) exactly once, in index.ts. They live here as pure
// functions so the hosted-deployment selection can be tested without rebuilding
// the bundle for each case.
//
// Neither value is a secret. Everything a `VITE_`-prefixed variable holds is
// inlined into the published bundle and is readable by anyone who loads the
// page, so no credential may ever be passed this way.

export type ApiMode = "mock" | "http";

/** The base path used when `VITE_API_BASE_URL` is unset or blank. */
export const DEFAULT_API_BASE_URL = "/api/v1";

/**
 * `http` only for an explicit, case-insensitive "http". Everything else —
 * unset, blank, a typo, a stray quote — falls back to the offline mock, so a
 * misconfigured deployment shows obviously synthetic data rather than silently
 * pointing at nothing.
 */
export function resolveApiMode(raw: string | undefined): ApiMode {
  return (raw ?? "").trim().toLowerCase() === "http" ? "http" : "mock";
}

/**
 * The base URL for the real client. A blank or missing value falls back to the
 * relative default, which the Vite dev proxy serves locally; hosted deployments
 * set the absolute Cloud Run origin instead. Trailing slashes are left for
 * `HttpRegOpsApi` to trim.
 */
export function resolveApiBaseUrl(raw: string | undefined): string {
  const trimmed = (raw ?? "").trim();
  return trimmed.length > 0 ? trimmed : DEFAULT_API_BASE_URL;
}
