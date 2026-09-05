import { useCallback, useEffect, useRef, useState } from "react";
import type { ServiceResult } from "@/types";

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  /** Provenance reported by the backend, e.g. SYNTHETIC. Labelled, never hidden. */
  dataConfidence: string | null;
  fetchedAt: string | null;
  reload: () => void;
}

/**
 * One hook every page uses to talk to the service layer, so loading, error and
 * provenance are handled identically everywhere. Stale responses from a superseded
 * scope change are discarded rather than rendered — switching district twice quickly
 * must not leave the first district's numbers on screen under the second one's name.
 *
 * On failure the previously loaded data is deliberately kept. An operations console
 * that blanks itself the moment a request times out is worse than one showing data
 * from ninety seconds ago clearly labelled as such.
 */
export function useAsync<T>(
  loader: () => Promise<ServiceResult<T>>,
  deps: unknown[],
  options: { immediate?: boolean } = {},
): AsyncState<T> {
  const { immediate = true } = options;
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(immediate);
  const [error, setError] = useState<string | null>(null);
  const [dataConfidence, setDataConfidence] = useState<string | null>(null);
  const [fetchedAt, setFetchedAt] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const runId = useRef(0);

  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    if (!immediate) return;
    const id = ++runId.current;
    let cancelled = false;
    setLoading(true);
    setError(null);

    loaderRef
      .current()
      .then((res) => {
        if (cancelled || id !== runId.current) return;
        setData(res.data);
        setDataConfidence(res.dataConfidence ?? null);
        setFetchedAt(res.fetchedAt);
      })
      .catch((err: unknown) => {
        if (cancelled || id !== runId.current) return;
        setError(err instanceof Error ? err.message : "Unable to load data");
      })
      .finally(() => {
        if (cancelled || id !== runId.current) return;
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce, immediate]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  return { data, loading, error, dataConfidence, fetchedAt, reload };
}
