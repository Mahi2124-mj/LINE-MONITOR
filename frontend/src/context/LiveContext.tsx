import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { api, wsUrl } from '../api/client';
import type { Alert, CameraStatus, CycleRecord, StationLive, WsMessage } from '../api/types';

export type CameraLiveStatus = CameraStatus & { camera_id: number };
type Listener<T> = (v: T) => void;

/** Fast-changing data (every ~1 s). Kept in its own context so only live widgets re-render. */
interface LiveStatesCtx {
  states: Map<number, StationLive>;
  /** Date.now() when `states` was received (used to extrapolate running cycle timers) */
  receivedAt: number;
}

interface LiveCtx {
  connected: boolean;
  /** Reconnect attempt counter (0 while connected). */
  retries: number;
  openAlerts: number;
  cameraStatus: Map<number, CameraLiveStatus>;
  refreshAlertCount: () => void;
  subscribeCycles: (fn: Listener<CycleRecord>) => () => void;
  subscribeAlerts: (fn: Listener<Alert>) => () => void;
}

const StatesContext = createContext<LiveStatesCtx>({ states: new Map(), receivedAt: 0 });
const MetaContext = createContext<LiveCtx | null>(null);

const MAX_BACKOFF_MS = 15_000;

function isWsMessage(v: unknown): v is WsMessage {
  return typeof v === 'object' && v !== null && 'type' in v && 'data' in v;
}

export function LiveProvider({ children }: { children: ReactNode }) {
  const [connected, setConnected] = useState(false);
  const [retries, setRetries] = useState(0);
  const [statesCtx, setStatesCtx] = useState<LiveStatesCtx>({ states: new Map(), receivedAt: 0 });
  const [cameraStatus, setCameraStatus] = useState<Map<number, CameraLiveStatus>>(new Map());
  const [openAlerts, setOpenAlerts] = useState(0);

  const cycleListeners = useRef(new Set<Listener<CycleRecord>>());
  const alertListeners = useRef(new Set<Listener<Alert>>());

  const applyStates = useCallback((list: StationLive[], replace: boolean) => {
    setStatesCtx((prev) => {
      const next = replace ? new Map<number, StationLive>() : new Map(prev.states);
      for (const s of list) next.set(s.station_id, s);
      return { states: next, receivedAt: Date.now() };
    });
  }, []);

  const refreshAlertCount = useCallback(() => {
    api
      .alerts('open', 1000)
      .then((list) => setOpenAlerts(list.filter((a) => !a.acknowledged).length))
      .catch(() => {
        /* backend down: keep last value */
      });
  }, []);

  // --- single shared WebSocket with exponential backoff ---
  useEffect(() => {
    let ws: WebSocket | null = null;
    let stopped = false;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      if (stopped) return;
      try {
        ws = new WebSocket(wsUrl('/ws/live'));
      } catch {
        scheduleReconnect();
        return;
      }
      ws.onopen = () => {
        attempt = 0;
        setRetries(0);
        setConnected(true);
        refreshAlertCount();
      };
      ws.onmessage = (ev: MessageEvent<string>) => {
        let parsed: unknown;
        try {
          parsed = JSON.parse(ev.data);
        } catch {
          return;
        }
        if (!isWsMessage(parsed)) return;
        const msg = parsed;
        switch (msg.type) {
          case 'states':
            applyStates(msg.data, true);
            break;
          case 'cycle': {
            const cycle = msg.data;
            cycleListeners.current.forEach((fn) => fn(cycle));
            break;
          }
          case 'alert': {
            const alert = msg.data;
            if (!alert.acknowledged) setOpenAlerts((n) => n + 1);
            alertListeners.current.forEach((fn) => fn(alert));
            break;
          }
          case 'camera_status': {
            const status = msg.data;
            setCameraStatus((prev) => {
              const next = new Map(prev);
              next.set(status.camera_id, status);
              return next;
            });
            break;
          }
        }
      };
      ws.onclose = () => {
        setConnected(false);
        ws = null;
        scheduleReconnect();
      };
      ws.onerror = () => {
        // onclose follows; nothing else to do
      };
    };

    const scheduleReconnect = () => {
      if (stopped) return;
      attempt += 1;
      setRetries(attempt);
      const delay = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** Math.min(attempt - 1, 4)) + Math.random() * 400;
      timer = setTimeout(connect, delay);
    };

    connect();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      if (ws) {
        ws.onclose = null;
        ws.close();
      }
    };
  }, [applyStates, refreshAlertCount]);

  // REST fallback while the socket is down (e.g. proxy without WS support): poll /api/live.
  useEffect(() => {
    if (connected) return;
    let cancelled = false;
    const poll = () =>
      api
        .live()
        .then((list) => {
          if (!cancelled) applyStates(list, true);
        })
        .catch(() => {
          /* backend down */
        });
    void poll();
    const id = setInterval(poll, 5000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [connected, applyStates]);

  // Alert count safety net (acks done in other tabs, missed messages).
  useEffect(() => {
    refreshAlertCount();
    const id = setInterval(refreshAlertCount, 30_000);
    return () => clearInterval(id);
  }, [refreshAlertCount]);

  const subscribeCycles = useCallback((fn: Listener<CycleRecord>) => {
    cycleListeners.current.add(fn);
    return () => {
      cycleListeners.current.delete(fn);
    };
  }, []);
  const subscribeAlerts = useCallback((fn: Listener<Alert>) => {
    alertListeners.current.add(fn);
    return () => {
      alertListeners.current.delete(fn);
    };
  }, []);

  const meta = useMemo<LiveCtx>(
    () => ({ connected, retries, openAlerts, cameraStatus, refreshAlertCount, subscribeCycles, subscribeAlerts }),
    [connected, retries, openAlerts, cameraStatus, refreshAlertCount, subscribeCycles, subscribeAlerts],
  );

  return (
    <MetaContext.Provider value={meta}>
      <StatesContext.Provider value={statesCtx}>{children}</StatesContext.Provider>
    </MetaContext.Provider>
  );
}

export function useLive(): LiveCtx {
  const v = useContext(MetaContext);
  if (!v) throw new Error('useLive must be used inside <LiveProvider>');
  return v;
}

export function useLiveStates(): LiveStatesCtx {
  return useContext(StatesContext);
}

/** Live state of one station; falls back to `fallback` (e.g. from analytics) before WS data arrived. */
export function useStationLive(stationId: number | undefined, fallback?: StationLive | null): StationLive | null {
  const { states } = useLiveStates();
  if (stationId === undefined) return null;
  return states.get(stationId) ?? fallback ?? null;
}

/** Subscribe to completed cycles (optionally filtered). The callback may change between renders. */
export function useCycleEvents(fn: Listener<CycleRecord>, filter?: { stationId?: number; lineId?: number }): void {
  const { subscribeCycles } = useLive();
  const fnRef = useRef(fn);
  useEffect(() => {
    fnRef.current = fn;
  });
  const stationId = filter?.stationId;
  const lineId = filter?.lineId;
  useEffect(
    () =>
      subscribeCycles((c) => {
        if (stationId !== undefined && c.station_id !== stationId) return;
        if (lineId !== undefined && c.line_id !== lineId) return;
        fnRef.current(c);
      }),
    [subscribeCycles, stationId, lineId],
  );
}

export function useAlertEvents(fn: Listener<Alert>): void {
  const { subscribeAlerts } = useLive();
  const fnRef = useRef(fn);
  useEffect(() => {
    fnRef.current = fn;
  });
  useEffect(() => subscribeAlerts((a) => fnRef.current(a)), [subscribeAlerts]);
}

/**
 * Running cycle time extrapolated client-side between WS updates.
 * Extrapolation is capped so a stalled feed freezes instead of running away.
 */
export function extrapolateElapsed(live: StationLive | null, receivedAt: number, now: number, capSec = 3): number | null {
  if (!live || live.cycle_elapsed_sec === null) return null;
  if (live.state === 'offline' || live.state === 'no_camera') return live.cycle_elapsed_sec;
  const dt = receivedAt > 0 ? Math.min(Math.max(0, (now - receivedAt) / 1000), capSec) : 0;
  return live.cycle_elapsed_sec + dt;
}
