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

    const payload = await readJson(response);

    if (!response.ok) {
      if (isAPIErrorBody(payload)) {
        throw new RegOpsApiError({
          code: payload.code,
          message: payload.message,
          status: response.status,
          details: payload.details ?? [],
        });
      }
      throw new RegOpsApiError({
        code: `http_${response.status}`,
        message: `Request failed with status ${response.status}.`,
        status: response.status,
        kind: kindFromStatus(response.status),
      });
    }

    return payload as T;
  }
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text();
  if (text.length === 0) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    // A non-JSON body from a proxy or gateway is still a failure we must report.
    return { code: "invalid_response", message: text.slice(0, 500) };
  }
}
