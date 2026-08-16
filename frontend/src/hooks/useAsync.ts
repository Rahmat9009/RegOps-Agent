// useAsync.ts — Load-once-with-reload for any RegOpsApi call.
//
// Callers pass a memoised loader (useCallback), so the effect re-runs exactly when
// its inputs change. Errors are always RegOpsApiError, so screens can branch on
// `error.kind` without knowing about HTTP.

import { useCallback, useEffect, useRef, useState } from "react";

import { toRegOpsApiError, type RegOpsApiError } from "@/lib/api";

export interface AsyncResource<T> {
  data: T | null;
  error: RegOpsApiError | null;
  /** True only during the first load; refreshes do not blank the screen. */
  loading: boolean;
  /** True while any load is in flight, including a refresh. */
  refreshing: boolean;
  reload: () => void;
}

export function useAsync<T>(loader: () => Promise<T>): AsyncResource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<RegOpsApiError | null>(null);
  const [refreshing, setRefreshing] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [nonce, setNonce] = useState(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setRefreshing(true);

    loader()
      .then((result) => {
        if (cancelled || !mounted.current) return;
        setData(result);
        setError(null);
      })
      .catch((cause: unknown) => {
        if (cancelled || !mounted.current) return;
        setError(toRegOpsApiError(cause));
      })
      .finally(() => {
        if (cancelled || !mounted.current) return;
        setRefreshing(false);
        setLoaded(true);
      });

    return () => {
      cancelled = true;
    };
  }, [loader, nonce]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  return { data, error, loading: !loaded, refreshing, reload };
}
