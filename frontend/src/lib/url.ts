// url.ts — URL safety checks for values the API hands us.
//
// `AuditReport.audit_package_url` is an opaque string the backend controls. It is
// rendered into an anchor's href, so it is validated before use: anything that is
// not an absolute https:// URL is refused and the control stays disabled. This
// keeps `javascript:`, `data:`, `blob:`, `file:` and plain-http values out of the
// DOM entirely rather than relying on the browser to be unhelpful with them.

/**
 * True only for a syntactically valid, absolute `https://` URL.
 *
 * Deliberately strict:
 *   - relative paths are rejected (they cannot be validated without a base)
 *   - `http:` is rejected — an audit package must not travel in the clear
 *   - every other scheme is rejected, including `javascript:` and `data:`
 */
export function isSafeAuditPackageUrl(value: string | null | undefined): boolean {
  if (typeof value !== "string") return false;

  const candidate = value.trim();
  if (candidate.length === 0) return false;

  let parsed: URL;
  try {
    parsed = new URL(candidate);
  } catch {
    return false;
  }

  // `URL` lowercases the scheme, so a single comparison is enough.
  if (parsed.protocol !== "https:") return false;

  // `https:` with no host (e.g. "https:///x") is not a usable download target.
  return parsed.hostname.length > 0;
}
