import { describe, expect, it } from "vitest";

import { isSafeAuditPackageUrl } from "./url";

describe("isSafeAuditPackageUrl", () => {
  it("accepts an absolute https URL", () => {
    expect(isSafeAuditPackageUrl("https://storage.example.com/audit/RUN-001.zip")).toBe(true);
  });

  it("accepts https regardless of scheme casing", () => {
    expect(isSafeAuditPackageUrl("HTTPS://storage.example.com/audit.zip")).toBe(true);
  });

  it("rejects plain http", () => {
    expect(isSafeAuditPackageUrl("http://storage.example.com/audit.zip")).toBe(false);
  });

  it.each([
    ["javascript:alert(1)"],
    ["JavaScript:alert(1)"],
    ["data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg=="],
    ["blob:https://example.com/1234"],
    ["file:///etc/passwd"],
    ["vbscript:msgbox(1)"],
  ])("rejects the unsafe scheme %s", (value) => {
    expect(isSafeAuditPackageUrl(value)).toBe(false);
  });

  it("rejects a scheme hidden behind leading whitespace", () => {
    expect(isSafeAuditPackageUrl("   javascript:alert(1)")).toBe(false);
  });

  it("rejects relative and protocol-relative paths", () => {
    expect(isSafeAuditPackageUrl("/api/v1/runs/RUN-001/audit/package")).toBe(false);
    expect(isSafeAuditPackageUrl("audit.zip")).toBe(false);
    expect(isSafeAuditPackageUrl("//storage.example.com/audit.zip")).toBe(false);
  });

  it("rejects an https URL with no host", () => {
    // Note: "https:///audit.zip" is NOT in this list — WHATWG normalises the extra
    // slash away, making it a valid URL with the host "audit.zip".
    expect(isSafeAuditPackageUrl("https://")).toBe(false);
    expect(isSafeAuditPackageUrl("https:")).toBe(false);
  });

  it("rejects empty, blank and absent values", () => {
    expect(isSafeAuditPackageUrl("")).toBe(false);
    expect(isSafeAuditPackageUrl("   ")).toBe(false);
    expect(isSafeAuditPackageUrl(null)).toBe(false);
    expect(isSafeAuditPackageUrl(undefined)).toBe(false);
  });
});
