import { useCallback, useEffect, useRef, useState } from 'react';
import { getClusterStatus } from '../api/catchmentApi';

const IDLE_INTERVAL_MS = 8000;
const ACTIVE_INTERVAL_MS = 2000;

/**
 * Polls the gateway's /v1/cluster view.
 *
 * Polling pauses while the tab is hidden and speeds up while an analysis is
 * running, so the cluster panel shows stages moving between nodes.
 *
 * @param {{ active?: boolean }} [options]
 * @returns {{
 *   mode: 'loading' | 'distributed' | 'single-node' | 'error',
 *   data: Object | null,
 *   error: string | null,
 *   updatedAt: number | null,
 *   refresh: () => void,
 * }}
 */
export default function useClusterStatus({ active = false } = {}) {
  const [state, setState] = useState({ mode: 'loading', data: null, error: null, updatedAt: null });
  const controllerRef = useRef(null);
  // The FastAPI app has no cluster view; stop polling once that is known.
  const singleNodeRef = useRef(false);

  const refresh = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    try {
      const data = await getClusterStatus({ signal: controller.signal });
      if (controller.signal.aborted) return;
      singleNodeRef.current = !data;
      setState({ mode: data ? 'distributed' : 'single-node', data, error: null, updatedAt: Date.now() });
    } catch (err) {
      if (controller.signal.aborted) return;
      setState((prev) => ({ ...prev, mode: prev.data ? prev.mode : 'error', error: err.message || 'Cluster status unavailable' }));
    }
  }, []);

  useEffect(() => {
    let timer = null;
    const schedule = () => {
      clearTimeout(timer);
      if (singleNodeRef.current || document.visibilityState === 'hidden') return;
      timer = setTimeout(async () => {
        await refresh();
        schedule();
      }, active ? ACTIVE_INTERVAL_MS : IDLE_INTERVAL_MS);
    };
    const onVisibility = () => {
      if (document.visibilityState === 'visible' && !singleNodeRef.current) {
        refresh();
        schedule();
      } else {
        clearTimeout(timer);
      }
    };
    if (!singleNodeRef.current) refresh();
    schedule();
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVisibility);
      controllerRef.current?.abort();
    };
  }, [active, refresh]);

  return { ...state, refresh };
}
