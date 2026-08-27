// useRunPolling.ts — `GET /api/v1/runs/{run_id}` every 2 seconds, per the frozen
// polling model. No WebSockets.
//
// The hook records no history of its own: `Run.transitions` is the authoritative,
// server-recorded, oldest-to-newest history, so every screen reads it from the
// polled run rather than from anything this client observed.
//
// Each successful response is also published to `RunPresenceContext` so the
// application shell can show the live run without polling a second time.

import { useCallback, useEffect, useState } from "react";

import { api, toRegOpsApiError, type RegOpsApiError, type Run } from "@/lib/api";
import { shouldPoll } from "@/lib/presentation";
import { useRunPresence } from "@/hooks/useRunPresence";

export const POLL_INTERVAL_MS = 2000;

export interface RunPolling {
  run: Run | null;
  error: RegOpsApiError | null;
  loading: boolean;
  /** True while the hook is still polling for further changes. */
  polling: boolean;
  refresh: () => void;
}

export function useRunPolling(runId: string | null): RunPolling {
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState<RegOpsApiError | null>(null);
  const [loading, setLoading] = useState(runId !== null);
  const [nonce, setNonce] = useState(0);
  const { publish } = useRunPresence();

  // A new run id starts from a clean slate.
  useEffect(() => {
    setRun(null);
    setError(null);
    setLoading(runId !== null);
    publish(null);
  }, [runId, publish]);

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
        publish(next);

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
  }, [runId, nonce, publish]);

  const refresh = useCallback(() => setNonce((value) => value + 1), []);

  return {
    run,
    error,
    loading,
    polling: run !== null && shouldPoll(run.state),
    refresh,
  };
}
