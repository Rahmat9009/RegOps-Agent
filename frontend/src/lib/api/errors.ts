// errors.ts — One error type for every adapter, so screens render failures the
// same way whether they are talking to the mock or the real backend.

import type { APIErrorBody, ErrorDetail } from "./types";

/**
 * How the UI should treat a failure. Derived from HTTP status where available so
 * screens can branch (retry vs. navigate away) without parsing status codes.
 */
export type ApiErrorKind =
  | "validation" // 422 — request rejected
  | "not_found" // 404
  | "conflict" // 409 — e.g. approval already decided
  | "not_implemented" // 501 — operation begins after Phase 0
  | "server" // 5xx
  | "network" // request never completed
  | "unknown";

export class RegOpsApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly kind: ApiErrorKind;
  readonly details: ErrorDetail[];

  constructor(init: {
    code: string;
    message: string;
    status?: number;
    kind?: ApiErrorKind;
    details?: ErrorDetail[] | null;
  }) {
    super(init.message);
    this.name = "RegOpsApiError";
    this.code = init.code;
    this.status = init.status ?? 0;
    this.kind = init.kind ?? kindFromStatus(init.status ?? 0);
    this.details = init.details ?? [];
  }

  /** True when retrying the identical request could plausibly succeed. */
  get retryable(): boolean {
    return this.kind === "network" || this.kind === "server";
  }
}

export function kindFromStatus(status: number): ApiErrorKind {
  if (status === 404) return "not_found";
  if (status === 409) return "conflict";
  if (status === 422) return "validation";
  if (status === 501) return "not_implemented";
  if (status >= 500) return "server";
  if (status === 0) return "network";
  return "unknown";
}

export function isRegOpsApiError(value: unknown): value is RegOpsApiError {
  return value instanceof RegOpsApiError;
}

/** Narrow an unknown `catch` value into something renderable. */
export function toRegOpsApiError(value: unknown): RegOpsApiError {
  if (isRegOpsApiError(value)) return value;
  if (value instanceof Error) {
    return new RegOpsApiError({ code: "unexpected_error", message: value.message, kind: "unknown" });
  }
  return new RegOpsApiError({
    code: "unexpected_error",
    message: "An unexpected error occurred.",
    kind: "unknown",
  });
}

/** Type guard for a parsed response body that matches the contract's APIError. */
export function isAPIErrorBody(value: unknown): value is APIErrorBody {
  if (typeof value !== "object" || value === null) return false;
  const body = value as Record<string, unknown>;
  return typeof body["code"] === "string" && typeof body["message"] === "string";
}
