// intakeSampleShortcut.test.ts — Guards the intake shortcut's adapter gating.
//
// The "Insert a synthetic sample document" button builds a 192-byte placeholder
// PDF in the browser. That is fine against the mock adapter, but the live worker
// matches the regulation by exact content hash, so in `http` mode the shortcut
// would hand the reviewer a document the backend cannot recognise. The screen
// therefore offers it only in mock mode and points at the repository sample
// instead.
//
// `API_MODE` is resolved once, at module load, from `import.meta.env`. Each case
// below stubs the variable, resets the module registry and re-imports the whole
// graph, so React, React Router and the page all come from the same fresh
// registry and the markup reflects that build's mode. `StaticRouter` is used
// because the suite renders to a string, with no DOM to attach history to.

import { afterEach, describe, expect, it, vi } from "vitest";

const SHORTCUT_LABEL = "Insert a synthetic sample document";
const SAMPLE_PATH = "samples/regops-synthetic-regulation-2026.pdf";

async function renderIntakePage(apiMode: string): Promise<string> {
  vi.resetModules();
  vi.stubEnv("VITE_API_MODE", apiMode);

  const [{ createElement }, { renderToStaticMarkup }, { StaticRouter }, { IntakePage }] =
    await Promise.all([
      import("react"),
      import("react-dom/server"),
      import("react-router-dom"),
      import("./IntakePage"),
    ]);

  return renderToStaticMarkup(
    createElement(StaticRouter, { location: "/intake" }, createElement(IntakePage)),
  );
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe("regulation intake sample shortcut", () => {
  it("keeps the shortcut in mock adapter mode", async () => {
    const markup = await renderIntakePage("mock");

    expect(markup).toContain(SHORTCUT_LABEL);
  });

  it("omits the shortcut in live API mode", async () => {
    const markup = await renderIntakePage("http");

    expect(markup).not.toContain(SHORTCUT_LABEL);
  });

  it("points at the repository sample in live API mode", async () => {
    const markup = await renderIntakePage("http");

    expect(markup).toContain(SAMPLE_PATH);
  });
});
