// useRunPresence.ts — Puts the run the console is currently watching into the
// application shell, without issuing a single extra request.
//
// The shell needs to show which run is in flight and where it has got to. It
// must not poll for that itself: `GET /runs/{run_id}` is already being polled by
// whichever screen is open, and a second poller would double the request rate
// against the API. So this is a presentation channel only — `useRunPolling`
// publishes the run it already fetched, and the shell reads it.
//
// Nothing here fetches, derives or remembers anything the API did not return.

import { createContext, useContext } from "react";

import type { Run } from "@/lib/api";

export interface RunPresence {
  /** The most recent run any screen has polled, or null. */
  run: Run | null;
  /** Called by `useRunPolling` with each successful response. */
  publish: (run: Run | null) => void;
}

const NO_PRESENCE: RunPresence = { run: null, publish: () => {} };

export const RunPresenceContext = createContext<RunPresence>(NO_PRESENCE);

export function useRunPresence(): RunPresence {
  return useContext(RunPresenceContext);
}
