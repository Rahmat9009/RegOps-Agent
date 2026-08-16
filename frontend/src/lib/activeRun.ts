// activeRun.ts — Remembers which run the console is looking at.
//
// This is browser state, not API data: the contract has no run-listing endpoint
// (CONTRACT_REQUESTS.md CR-001), so after a reload the console needs the last
// `run_id` it created in order to call `GET /runs/{run_id}` again.

const STORAGE_KEY = "regops.activeRunId";

export function getActiveRunId(): string | null {
  try {
    return globalThis.localStorage?.getItem(STORAGE_KEY) ?? null;
  } catch {
    return null;
  }
}

export function setActiveRunId(runId: string): void {
  try {
    globalThis.localStorage?.setItem(STORAGE_KEY, runId);
  } catch {
    // A console without storage still works; it just forgets on reload.
  }
}

export function clearActiveRunId(): void {
  try {
    globalThis.localStorage?.removeItem(STORAGE_KEY);
  } catch {
    // Nothing to clean up.
  }
}
