// httpAdapter.ts — Real HTTP client for contracts/openapi.yaml.
//
// Implements all eight contract operations and nothing else. Every failure is
// normalised into RegOpsApiError so screens do not branch on transport details.
//
// Notes on the contract:
//   * POST /runs is multipart/form-data — the browser sets the boundary, so we
//     must NOT set a Content-Type header for that request.
//   * 501 responses are expected for operations that begin after Phase 0; they
//     surface as RegOpsApiError with kind "not_implemented".

import type { ListFindingsParams, RegOpsApi } from "./client";
import { isAPIErrorBody, kindFromStatus, RegOpsApiError } from "./errors";
import type {
  Approval,
  ApprovalDecision,
  AuditReport,
  CounterfactualPreview,
  CreateRunInput,
  Finding,
  FindingList,
  HealthStatus,
  Run,
} from "./types";

export interface HttpRegOpsApiOptions {
  /** Base path, e.g. "/api/v1". Trailing slashes are trimmed. */
  baseUrl?: string;
  /** Injectable for tests. */
  fetchImpl?: typeof fetch;
}

export class HttpRegOpsApi implements RegOpsApi {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: HttpRegOpsApiOptions = {}) {
    this.baseUrl = (options.baseUrl ?? "/api/v1").replace(/\/+$/, "");
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  }

  async getHealth(): Promise<HealthStatus> {
    return this.request<HealthStatus>("GET", "/health");
  }

  async createRun(input: CreateRunInput): Promise<Run> {
    const form = new FormData();
    form.append("regulation_file", input.regulation_file, input.regulation_file.name);
    // Booleans cross a multipart boundary as text; the contract's boolean field
    // is parsed from the canonical lowercase form.
    form.append("synthetic_ack", input.synthetic_ack ? "true" : "false");
    return this.request<Run>("POST", "/runs", { body: form });
  }

  async getRun(runId: string): Promise<Run> {
    return this.request<Run>("GET", `/runs/${encodeURIComponent(runId)}`);
  }

  async listRunFindings(runId: string, params?: ListFindingsParams): Promise<FindingList> {
    const query = new URLSearchParams();
    if (params?.severity) query.set("severity", params.severity);
    if (params?.q) query.set("q", params.q);
    const queryString = query.toString();
    const suffix = queryString ? `?${queryString}` : "";
    return this.request<FindingList>("GET", `/runs/${encodeURIComponent(runId)}/findings${suffix}`);
  }

  async getFinding(findingId: string): Promise<Finding> {
    return this.request<Finding>("GET", `/findings/${encodeURIComponent(findingId)}`);
  }

  async previewAction(actionId: string): Promise<CounterfactualPreview> {
    return this.request<CounterfactualPreview>(
      "POST",
      `/actions/${encodeURIComponent(actionId)}/preview`,
    );
  }

  async decideApproval(approvalId: string, body: ApprovalDecision): Promise<Approval> {
    // Only `decision` and `note` are ever sent. `decided_by` is backend-assigned
    // and is deliberately not constructible from this call site.
    const payload: ApprovalDecision = { decision: body.decision, note: body.note ?? null };
    return this.request<Approval>(
      "POST",
      `/approvals/${encodeURIComponent(approvalId)}/decision`,
      { json: payload },
    );
  }

  async getRunAudit(runId: string): Promise<AuditReport> {
    return this.request<AuditReport>("GET", `/runs/${encodeURIComponent(runId)}/audit`);
  }

  /* ---------------------------------------------------------------- internal */

  private async request<T>(
    method: string,
    path: string,
    options: { json?: unknown; body?: BodyInit } = {},
  ): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    let body: BodyInit | undefined = options.body;

    if (options.json !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(options.json);
    }
    // For FormData we intentionally leave Content-Type unset so the browser can
    // generate the multipart boundary.

    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, { method, headers, body });
    } catch (cause) {
      throw new RegOpsApiError({
        code: "network_error",
        message:
          cause instanceof Error
            ? `Could not reach the RegOps API: ${cause.message}`
            : "Could not reach the RegOps API.",
        status: 0,
        kind: "network",
      });
    }

    let text: string;
    try {
      text = await response.text();
    } catch (cause) {
      throw new RegOpsApiError({
        code: "network_error",
        message:
          cause instanceof Error
            ? `The response body could not be read: ${cause.message}`
            : "The response body could not be read.",
        status: 0,
        kind: "network",
      });
    }

    const parsed = tryParseJson(text);

    if (!response.ok) {
      // Non-2xx keeps the contract's structured APIError handling.
      if (isAPIErrorBody(parsed)) {
        throw new RegOpsApiError({
          code: parsed.code,
          message: parsed.message,
          status: response.status,
          details: parsed.details ?? [],
        });
      }
      throw new RegOpsApiError({
        code: `http_${response.status}`,
        message: `Request failed with status ${response.status}.`,
        status: response.status,
        kind: kindFromStatus(response.status),
      });
    }

    // A 2xx must carry a JSON object. Every successful response in the contract is
    // a schema object, so an empty, malformed, non-JSON or non-object body is a
    // broken response — it is reported, never cast to T.
    if (text.trim().length === 0) {
      throw invalidResponse(response.status, "The API returned an empty response body.");
    }
    if (parsed === undefined) {
      throw invalidResponse(
        response.status,
        `The API returned a body that is not valid JSON: ${preview(text)}`,
      );
    }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      throw invalidResponse(
        response.status,
        `The API returned ${describe(parsed)} where a JSON object was expected.`,
      );
    }

    return parsed as T;
  }
}

/** Returns `undefined` when the text is not valid JSON (JSON `null` parses to `null`). */
function tryParseJson(text: string): unknown {
  if (text.trim().length === 0) return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
}

function invalidResponse(status: number, message: string): RegOpsApiError {
  return new RegOpsApiError({ code: "invalid_response", message, status, kind: "unknown" });
}

function describe(value: unknown): string {
  if (value === null) return "a JSON null";
  if (Array.isArray(value)) return "a JSON array";
  return `a JSON ${typeof value}`;
}

function preview(text: string): string {
  const trimmed = text.trim();
  return trimmed.length > 200 ? `${trimmed.slice(0, 200)}…` : trimmed;
}
