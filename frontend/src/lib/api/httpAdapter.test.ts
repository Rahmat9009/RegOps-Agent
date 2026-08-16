import { describe, expect, it, vi } from "vitest";

import { HttpRegOpsApi } from "./httpAdapter";
import { RegOpsApiError } from "./errors";
import type { Approval } from "./types";

interface Captured {
  url: string;
  init: RequestInit;
}

/** A fetch stub that records the request and returns a fixed response. */
function stubFetch(response: Response): { fetchImpl: typeof fetch; calls: Captured[] } {
  const calls: Captured[] = [];
  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init: init ?? {} });
    return response;
  }) as unknown as typeof fetch;
  return { fetchImpl, calls };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("HttpRegOpsApi successful-response validation", () => {
  it("throws invalid_response when a 200 body is not valid JSON", async () => {
    const { fetchImpl } = stubFetch(
      new Response("<html>gateway timeout</html>", {
        status: 200,
        headers: { "Content-Type": "text/html" },
      }),
    );
    const api = new HttpRegOpsApi({ fetchImpl });

    const error = await api.getHealth().catch((cause: unknown) => cause);

    expect(error).toBeInstanceOf(RegOpsApiError);
    expect((error as RegOpsApiError).code).toBe("invalid_response");
    expect((error as RegOpsApiError).kind).toBe("unknown");
  });

  it("throws invalid_response when a 200 body is empty", async () => {
    const { fetchImpl } = stubFetch(new Response("", { status: 200 }));
    const api = new HttpRegOpsApi({ fetchImpl });

    const error = await api.getRun("RUN-001").catch((cause: unknown) => cause);

    expect(error).toBeInstanceOf(RegOpsApiError);
    expect((error as RegOpsApiError).code).toBe("invalid_response");
    expect((error as RegOpsApiError).kind).toBe("unknown");
  });

  it("throws invalid_response when a 200 body is JSON but not an object", async () => {
    for (const body of ["null", '"a string"', "42", "[1,2,3]"]) {
      const { fetchImpl } = stubFetch(
        new Response(body, { status: 200, headers: { "Content-Type": "application/json" } }),
      );
      const api = new HttpRegOpsApi({ fetchImpl });

      const error = await api.getRun("RUN-001").catch((cause: unknown) => cause);

      expect(error, `body ${body} should be refused`).toBeInstanceOf(RegOpsApiError);
      expect((error as RegOpsApiError).code).toBe("invalid_response");
    }
  });

  it("returns the parsed object for a well-formed 200", async () => {
    const { fetchImpl } = stubFetch(jsonResponse({ status: "ok", version: "0.1.0" }));
    const api = new HttpRegOpsApi({ fetchImpl });

    await expect(api.getHealth()).resolves.toEqual({ status: "ok", version: "0.1.0" });
  });
});

describe("HttpRegOpsApi error-response handling", () => {
  it("preserves a structured APIError body", async () => {
    const { fetchImpl } = stubFetch(
      jsonResponse(
        {
          code: "approval_already_decided",
          message: "Approval APR-0001 was already approved.",
          details: [{ location: ["body", "decision"], message: "already set", type: "conflict" }],
        },
        409,
      ),
    );
    const api = new HttpRegOpsApi({ fetchImpl });

    const error = (await api
      .decideApproval("APR-0001", { decision: "approve" })
      .catch((cause: unknown) => cause)) as RegOpsApiError;

    expect(error).toBeInstanceOf(RegOpsApiError);
    expect(error.code).toBe("approval_already_decided");
    expect(error.status).toBe(409);
    expect(error.kind).toBe("conflict");
    expect(error.details).toHaveLength(1);
  });

  it("falls back to an http_<status> code when the error body is not an APIError", async () => {
    const { fetchImpl } = stubFetch(new Response("nope", { status: 502 }));
    const api = new HttpRegOpsApi({ fetchImpl });

    const error = (await api.getRun("RUN-001").catch((cause: unknown) => cause)) as RegOpsApiError;

    expect(error.code).toBe("http_502");
    expect(error.kind).toBe("server");
  });
});

describe("HttpRegOpsApi request construction", () => {
  const approval: Approval = {
    approval_id: "APR-0001",
    action_id: "ACT-0001",
    run_id: "RUN-001",
    status: "APPROVED",
    decided_at: "2026-08-16T09:04:00Z",
    // The backend assigns this. It must come back in the response and never go out.
    decided_by: "demo-reviewer",
    note: null,
  };

  it("never sends decided_by in an approval decision", async () => {
    const { fetchImpl, calls } = stubFetch(jsonResponse(approval));
    const api = new HttpRegOpsApi({ fetchImpl });

    await api.decideApproval("APR-0001", { decision: "approve", note: "Evidence is sufficient." });

    const body = JSON.parse(String(calls[0]?.init.body)) as Record<string, unknown>;

    expect(Object.keys(body).sort()).toEqual(["decision", "note"]);
    expect(body).not.toHaveProperty("decided_by");
    expect(body["decision"]).toBe("approve");
  });

  it("does not smuggle decided_by through an over-supplied body", async () => {
    const { fetchImpl, calls } = stubFetch(jsonResponse(approval));
    const api = new HttpRegOpsApi({ fetchImpl });

    // Simulates a caller that has been handed a full Approval object by mistake.
    const overSupplied = { decision: "reject", note: null, decided_by: "someone-else" };
    await api.decideApproval("APR-0001", overSupplied as Parameters<typeof api.decideApproval>[1]);

    const body = JSON.parse(String(calls[0]?.init.body)) as Record<string, unknown>;

    expect(body).not.toHaveProperty("decided_by");
    expect(Object.keys(body).sort()).toEqual(["decision", "note"]);
  });

  it("accepts the backend-assigned reviewer from the response", async () => {
    const { fetchImpl } = stubFetch(jsonResponse(approval));
    const api = new HttpRegOpsApi({ fetchImpl });

    const result = await api.decideApproval("APR-0001", { decision: "approve" });

    expect(result.decided_by).toBe("demo-reviewer");
  });

  it("posts the regulation as multipart form data without a Content-Type header", async () => {
    const { fetchImpl, calls } = stubFetch(
      jsonResponse({ run_id: "RUN-001", state: "INGESTED" }, 202),
    );
    const api = new HttpRegOpsApi({ fetchImpl });
    const file = new File(["%PDF-1.4"], "reg.pdf", { type: "application/pdf" });

    await api.createRun({ regulation_file: file, synthetic_ack: true });

    const call = calls[0];
    expect(call?.init.method).toBe("POST");
    expect(call?.init.body).toBeInstanceOf(FormData);

    const form = call?.init.body as FormData;
    expect(form.get("synthetic_ack")).toBe("true");
    expect(form.get("regulation_file")).toBeInstanceOf(File);

    // The browser must set the multipart boundary itself.
    const headers = call?.init.headers as Record<string, string>;
    expect(headers).not.toHaveProperty("Content-Type");
  });

  it("builds findings query parameters only for supplied filters", async () => {
    const { fetchImpl, calls } = stubFetch(jsonResponse({ items: [], total: 0 }));
    const api = new HttpRegOpsApi({ fetchImpl });

    await api.listRunFindings("RUN-001", { severity: "high", q: null });

    expect(calls[0]?.url).toBe("/api/v1/runs/RUN-001/findings?severity=high");
  });
});
