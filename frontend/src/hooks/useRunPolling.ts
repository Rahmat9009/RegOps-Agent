// useRunPolling.ts — `GET /api/v1/runs/{run_id}` every 2 seconds, per the frozen
// polling model. No WebSockets.
//
// It also records the state transitions it observes while polling. Those are real
// values returned by the API together with the wall-clock time this client first
// saw them — nothing is inferred, and no agent reasoning is displayed. The
// contract has no server-side transition history (see CONTRACT_REQUESTS.md
// CR-002), so this list is explicitly labelled as client-observed in the UI.

import { useCallback, useEffect, useRef, useState } from "react";

import { api, toRegOpsApiError, type RegOpsApiError, type Run, type RunState } from "@/lib/api";
import { shouldPoll } from "@/lib/presentation";

export const POLL_INTERVAL_MS = 2000;

export interface ObservedTransition {
  state: RunState;
  /** ISO timestamp at which this client first observed the state. */
  observedAt: string;
  /** `updated_at` reported by the API for that observation. */
  reportedAt: string;
}

export interface RunPolling {
  run: Run | null;
  error: RegOpsApiError | null;
  loading: boolean;
  /** True while the hook is still polling for further changes. */
  polling: boolean;
  transitions: ObservedTransition[];
  refresh: () => void;
}

export function useRunPolling(runId: string | null): RunPolling {
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState<RegOpsApiError | null>(null);
  const [loading, setLoading] = useState(runId !== null);
  const [transitions, setTransitions] = useState<ObservedTransition[]>([]);
  const [nonce, setNonce] = useState(0);
  const lastState = useRef<RunState | null>(null);

  // A new run id means a fresh observation log.
  useEffect(() => {
    setRun(null);
    setError(null);
    setTransitions([]);
    setLoading(runId !== null);
    lastState.current = null;
  }, [runId]);

  useEffect(() => {
    if (!runId) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const tick = async (): Promise<void> => {
      try {
        const next = await api.getRun(runId);
        if (cancelled) return;

        setRun(next);
        setError(null);

        if (lastState.current !== next.state) {
          lastState.current = next.state;
          setTransitions((previous) => [
            ...previous,
            {
              state: next.state,
              observedAt: new Date().toISOString(),
              reportedAt: next.updated_at,
            },
          ]);
        }

        if (shouldPoll(next.state)) {
          timer = setTimeout(() => void tick(), POLL_INTERVAL_MS);
        }
      } catch (cause: unknown) {
        if (cancelled) return;
        const apiError = toRegOpsApiError(cause);
        setError(apiError);
        // Transport hiccups should not end the demo; contract errors should.
        if (apiError.retryable) {
          timer = setTimeout(() => void tick(), POLL_INTERVAL_MS);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void tick();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [runId, nonce]);

  const refresh = useCallback(() => setNonce((value) => value + 1), []);

  return {
    run,
    error,
    loading,
    polling: run !== null && shouldPoll(run.state),
    transitions,
    refresh,
  };
}
