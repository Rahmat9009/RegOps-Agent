// mode.test.ts — Live-mode selection for the hosted deployment.
//
// The hosted build is configured entirely by two Vite variables. These cover the
// values a real deployment can actually produce, including the misconfigurations
// that must NOT silently look like a live console.

import { describe, expect, it } from "vitest";

import { DEFAULT_API_BASE_URL, resolveApiBaseUrl, resolveApiMode } from "./mode";

/** The exact value the hosted deployment sets. */
const LIVE_BASE_URL = "https://regops-api-vx2qltpxca-ey.a.run.app/api/v1";

describe("resolveApiMode", () => {
  it("selects http for the hosted deployment's exact value", () => {
    expect(resolveApiMode("http")).toBe("http");
  });

  it("accepts the value case-insensitively and with surrounding whitespace", () => {
    for (const raw of ["HTTP", "Http", " http ", "\thttp\n"]) {
      expect(resolveApiMode(raw), `${JSON.stringify(raw)} should select http`).toBe("http");
    }
  });

  it("defaults to the offline mock when the variable is unset", () => {
    expect(resolveApiMode(undefined)).toBe("mock");
  });

  it("falls back to mock rather than guessing at anything else", () => {
    // A misconfigured deployment must show obviously synthetic mock data, never
    // a live-looking console pointed at nothing.
    for (const raw of ["", "   ", "mock", "https", "htp", "true", "1", "live"]) {
      expect(resolveApiMode(raw), `${JSON.stringify(raw)} should fall back to mock`).toBe("mock");
    }
  });
});

describe("resolveApiBaseUrl", () => {
  it("keeps the absolute Cloud Run base URL the hosted build is given", () => {
    expect(resolveApiBaseUrl(LIVE_BASE_URL)).toBe(LIVE_BASE_URL);
  });

  it("trims surrounding whitespace from a copied-in value", () => {
    expect(resolveApiBaseUrl(`  ${LIVE_BASE_URL}\n`)).toBe(LIVE_BASE_URL);
  });

  it("falls back to the relative default when unset or blank", () => {
    expect(resolveApiBaseUrl(undefined)).toBe(DEFAULT_API_BASE_URL);
    expect(resolveApiBaseUrl("")).toBe(DEFAULT_API_BASE_URL);
    expect(resolveApiBaseUrl("   ")).toBe(DEFAULT_API_BASE_URL);
  });

  it("keeps the relative default a relative path so the dev proxy still applies", () => {
    expect(DEFAULT_API_BASE_URL.startsWith("/")).toBe(true);
  });
});
