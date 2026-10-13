import { useCallback, useEffect, useRef, useState, type DependencyList, type Dispatch, type SetStateAction } from 'react';

export interface PollingResult<T> {
  data: T | undefined;
  error: unknown;
  /** true until the first response for the current deps arrived */
  loading: boolean;
  /** true while any request (initial or refresh) is running */
  fetching: boolean;
  reload: () => void;
  setData: Dispatch<SetStateAction<T | undefined>>;
}

/**
 * Fetch `fn` now and then every `intervalMs` (0 = fetch once). Data is reset whenever `deps` change,
 * kept across background refreshes. Polling pauses while the tab is hidden.
 */
export function usePolling<T>(fn: () => Promise<T>, deps: DependencyList, intervalMs = 15_000): PollingResult<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [fetching, setFetching] = useState(false);
  const [tick, setTick] = useState(0);
  const fnRef = useRef(fn);

  useEffect(() => {
    fnRef.current = fn;
  });

  // Reset when the identity of what we fetch changes.
  useEffect(() => {
    setData(undefined);
    setError(null);
    setLoading(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let skipped = false;

    const schedule = () => {
      if (cancelled || intervalMs <= 0) return;
      timer = setTimeout(() => void run(false), intervalMs);
    };

    // refresh right away when the tab becomes visible again after a skipped refresh
    const onVisible = () => {
      if (!document.hidden && skipped && !cancelled) {
        skipped = false;
        if (timer) clearTimeout(timer);
        void run(false);
      }
    };
    document.addEventListener('visibilitychange', onVisible);

    async function run(initial: boolean) {
      if (cancelled) return;
      if (!initial && document.hidden) {
        skipped = true;
        schedule();
        return;
      }
      setFetching(true);
      try {
        const r = await fnRef.current();
        if (!cancelled) {
          setData(r);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e);
      } finally {
        if (!cancelled) {
          setLoading(false);
          setFetching(false);
          schedule();
        }
      }
    }

    void run(true);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick, intervalMs]);

  const reload = useCallback(() => setTick((t) => t + 1), []);

  return { data, error, loading, fetching, reload, setData };
}
