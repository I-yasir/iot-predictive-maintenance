/** Live layer: one WebSocket for the app, merged into the React Query caches (docs/02 §7). */
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { backendHealth, type BackendHealth } from "../api/client";
import { keys } from "../api/queries";
import type { Alert, AssetList, PredictionEvent, WsEvent } from "../api/schemas";
import { WsClient, wsUrl, type WsState } from "../api/ws";

export const STALE_AFTER_MS = 10_000;

export interface LiveState {
  ws: WsState;
  retryInMs: number | null;
  /** WS has not been live for > 10 s: data is shown but marked stale */
  stale: boolean;
  backend: BackendHealth;
  lastEventAt: number | null;
  /** most recent alert received over WS (for the aria-live region) */
  lastAlert: Alert | null;
}

const Ctx = createContext<LiveState>({
  ws: "closed",
  retryInMs: null,
  stale: false,
  backend: backendHealth.state,
  lastEventAt: null,
  lastAlert: null,
});
export const useLive = () => useContext(Ctx);

export function applyPrediction(qc: QueryClient, p: PredictionEvent): boolean {
  let known = false;
  qc.setQueryData<AssetList>(keys.assets, (d) => {
    if (!d) return d;
    const items = d.items.map((a) => {
      if (a.asset_id !== p.asset_id) return a;
      known = true;
      const ok = p.status === "OK" && p.rul_pred !== null;
      const spark = a.life_id !== p.life_id ? [] : a.sparkline;
      return {
        ...a,
        life_id: p.life_id,
        state: p.state,
        last_cycle: Math.max(a.life_id === p.life_id ? (a.last_cycle ?? 0) : 0, p.cycle),
        last_seen_at: p.ts,
        pred_cycle: p.cycle,
        pred_status: p.status,
        rul_pred: p.rul_pred,
        rul_p10: p.rul_p10,
        rul_p90: p.rul_p90,
        health_index: p.health_index,
        flags: p.flags,
        true_rul: p.true_rul,
        sparkline: ok ? [...spark, p.rul_pred].slice(-50) : spark,
      };
    });
    const by_state: Record<string, number> = {};
    items.forEach((a) => (by_state[a.state] = (by_state[a.state] ?? 0) + 1));
    return { ...d, items, by_state };
  });
  qc.setQueryData(keys.predictions(p.asset_id), (d: { life_id: number; items: unknown[] } | undefined) => {
    if (!d || d.life_id !== p.life_id) return d;
    return {
      ...d,
      items: [
        ...d.items,
        { prediction_id: -Date.now(), cycle: p.cycle, created_at: p.ts, model_version: "", status: p.status, rul_pred: p.rul_pred,
          rul_p10: p.rul_p10, rul_p90: p.rul_p90, health_index: p.health_index, state: p.state, flags: p.flags,
          latency_ms: p.latency_ms ?? null, true_rul: p.true_rul },
      ],
    };
  });
  qc.setQueryData(keys.asset(p.asset_id), (a: Record<string, unknown> | undefined) =>
    a ? { ...a, state: p.state, life_id: p.life_id, last_cycle: p.cycle, last_seen_at: p.ts, rul_pred: p.rul_pred,
          rul_p10: p.rul_p10, rul_p90: p.rul_p90, health_index: p.health_index, flags: p.flags, pred_cycle: p.cycle,
          pred_status: p.status, true_rul: p.true_rul } : a,
  );
  return known;
}

export function applyEvent(qc: QueryClient, e: WsEvent, refetchAssets: () => void): void {
  switch (e.type) {
    case "prediction":
      if (!applyPrediction(qc, e.data)) refetchAssets();
      break;
    case "alert":
      qc.setQueriesData<{ count: number; items: Alert[] }>({ queryKey: ["alerts"] }, (d) =>
        d && !d.items.some((a) => a.alert_id === e.data.alert_id) ? { count: d.count + 1, items: [e.data, ...d.items] } : d,
      );
      break;
    case "alert_ack": {
      const id = Number(e.data.alert_id);
      qc.setQueriesData<{ count: number; items: Alert[] }>({ queryKey: ["alerts"] }, (d) =>
        d ? { ...d, items: d.items.map((a) => (a.alert_id === id ? { ...a, acknowledged_at: String(e.data.acknowledged_at), acknowledged_by: String(e.data.acknowledged_by) } : a)) } : d,
      );
      break;
    }
    case "asset_status":
      qc.setQueryData<AssetList>(keys.assets, (d) => {
        if (!d) return d;
        const items = d.items.map((a) => (a.asset_id === e.data.asset_id ? { ...a, state: e.data.state, last_seen_at: e.data.last_seen ?? a.last_seen_at } : a));
        const by_state: Record<string, number> = {};
        items.forEach((a) => (by_state[a.state] = (by_state[a.state] ?? 0) + 1));
        return { ...d, items, by_state };
      });
      break;
    case "sim_status":
      qc.setQueryData(keys.replay, e.data);
      break;
    default:
      break;
  }
}

export function LiveProvider({ children, enabled = true }: { children: ReactNode; enabled?: boolean }) {
  const qc = useQueryClient();
  const [state, setState] = useState<LiveState>({ ws: "closed", retryInMs: null, stale: false, backend: backendHealth.state, lastEventAt: null, lastAlert: null });
  const downSince = useRef<number | null>(Date.now());
  const pendingRefetch = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => backendHealth.subscribe((b) => setState((s) => ({ ...s, backend: b }))), []);

  useEffect(() => {
    if (!enabled) return;
    const refetchAssets = () => {
      if (pendingRefetch.current) return;
      pendingRefetch.current = setTimeout(() => {
        pendingRefetch.current = null;
        void qc.invalidateQueries({ queryKey: keys.assets });
      }, 1000);
    };
    const client = new WsClient({
      url: wsUrl(),
      onEvent: (e) => {
        applyEvent(qc, e, refetchAssets);
        setState((s) => ({ ...s, lastEventAt: Date.now(), lastAlert: e.type === "alert" ? e.data : s.lastAlert }));
      },
      onState: (ws, info) => {
        if (ws === "live") downSince.current = null;
        else if (downSince.current === null) downSince.current = Date.now();
        setState((s) => ({ ...s, ws, retryInMs: info.retryInMs, stale: ws === "live" ? false : s.stale }));
      },
      onResync: () => void qc.invalidateQueries(),
    });
    client.start();
    const iv = setInterval(() => {
      const d = downSince.current;
      setState((s) => {
        const stale = d !== null && Date.now() - d > STALE_AFTER_MS;
        return stale === s.stale ? s : { ...s, stale };
      });
    }, 1000);
    return () => {
      clearInterval(iv);
      client.stop();
      if (pendingRefetch.current) clearTimeout(pendingRefetch.current);
    };
  }, [qc, enabled]);

  return <Ctx.Provider value={state}>{children}</Ctx.Provider>;
}

/** Re-render every `ms` (relative times). */
export function useNow(ms = 1000): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}
