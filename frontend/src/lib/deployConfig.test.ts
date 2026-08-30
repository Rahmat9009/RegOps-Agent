// deployConfig.test.ts — Guards the hosted deployment configuration.
//
// The console is a single-page app served as static files: every deep link a
// reviewer can be handed (`/runs/:id`, `/findings/:id`,
// `/approvals/:id?run=...`) is a path the host has no file for. If the SPA
// fallback or the build settings regress, those links 404 in production while
// every local check still passes — so the configuration itself is asserted here.

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

interface VercelConfig {
  framework?: string;
  installCommand?: string;
  buildCommand?: string;
  outputDirectory?: string;
  rewrites?: { source: string; destination: string }[];
}

const vercelConfig = JSON.parse(
  readFileSync(new URL("../../vercel.json", import.meta.url), "utf8"),
) as VercelConfig;

const viteConfigSource = readFileSync(new URL("../../vite.config.ts", import.meta.url), "utf8");

const envExample = readFileSync(new URL("../../.env.example", import.meta.url), "utf8");

describe("vercel.json build settings", () => {
  it("installs from the lockfile and builds with the project's own script", () => {
    // `npm ci` (not `npm install`) so a deployed bundle matches the lockfile the
    // local checks ran against.
    expect(vercelConfig.installCommand).toBe("npm ci");
    expect(vercelConfig.buildCommand).toBe("npm run build");
  });

  it("publishes Vite's dist directory", () => {
    expect(vercelConfig.outputDirectory).toBe("dist");
    expect(vercelConfig.framework).toBe("vite");
  });
});

describe("vercel.json SPA fallback", () => {
  const rewrites = vercelConfig.rewrites ?? [];

  it("declares exactly one catch-all rewrite to index.html", () => {
    expect(rewrites).toHaveLength(1);
    expect(rewrites[0]?.destination).toBe("/index.html");
  });

  it("matches every deep link the console can hand out", () => {
    const source = rewrites[0]?.source ?? "";
    // Vercel anchors `source` as a full-path match.
    const pattern = new RegExp(`^${source}$`);

    const deepLinks = [
      "/",
      "/intake",
      "/runs/6577c771-1d4a-4011-a390-4853671ff824",
      "/runs/6577c771-1d4a-4011-a390-4853671ff824/findings",
      "/runs/6577c771-1d4a-4011-a390-4853671ff824/audit",
      "/findings/f575073e-a974-5361-994e-9c1674416a17",
      "/actions/8df576ba-d1d9-5c2c-b488-64409f93ff93/preview",
      "/approvals/d7d37eb7-b7b7-58eb-bda9-460d18d473ea",
    ];

    for (const path of deepLinks) {
      expect(pattern.test(path), `${path} must fall back to index.html`).toBe(true);
    }
  });

  it("matches the approval path independently of its ?run= query string", () => {
    // Vercel matches `source` against the path only and carries the query
    // through to the destination, so the approval screen still receives `?run=`.
    // The rewrite must therefore not depend on the query being present.
    const source = rewrites[0]?.source ?? "";
    const pattern = new RegExp(`^${source}$`);

    expect(pattern.test("/approvals/d7d37eb7-b7b7-58eb-bda9-460d18d473ea")).toBe(true);
  });
});

describe("build output safety", () => {
  it("builds without source maps", () => {
    // Published assets must not ship original sources or inlined build values.
    expect(viteConfigSource).toMatch(/sourcemap:\s*false/);
  });

  it("does not define a serverless backend or proxy for the hosted deployment", () => {
    // A rewrite to an external origin, or a Vercel function directory, would put
    // a proxy in front of Cloud Run that nothing here tests or secures.
    const config = vercelConfig as Record<string, unknown>;
    expect(config["functions"]).toBeUndefined();
    expect(config["routes"]).toBeUndefined();
    for (const rewrite of vercelConfig.rewrites ?? []) {
      expect(rewrite.destination.startsWith("/")).toBe(true);
      expect(rewrite.destination).not.toMatch(/^https?:/i);
    }
  });
});

describe(".env.example", () => {
  it("documents both variables the hosted build needs", () => {
    expect(envExample).toMatch(/VITE_API_MODE/);
    expect(envExample).toMatch(/VITE_API_BASE_URL/);
  });

  it("keeps mock the committed default so a clone runs offline", () => {
    expect(envExample).toMatch(/^VITE_API_MODE=mock$/m);
  });

  it("carries no credential-shaped value", () => {
    // Every VITE_ variable is inlined into the public bundle.
    expect(envExample).not.toMatch(/(api[_-]?key|secret|token|password|bearer)\s*=\s*\S/i);
  });
});
