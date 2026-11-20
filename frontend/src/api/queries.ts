/** React Query hooks + keys. Live updates are merged into these caches by LiveProvider. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import {
  AlertList,
  AssetDetail,
  AssetList,
  Diagnostics,
  DeviceList,
  Evaluation,
  HarnessResult,
  Me,
  ModelList,
  PredictionList,
  ReplayStatus,
  Report,
  SensorHistory,
  Stats,
  DeadLetter,
  TelemetryList,
  type Alert,
} from "./schemas";

export const keys = {
  me: ["me"] as const,
  assets: ["assets"] as const,
  asset: (id: string) => ["asset", id] as const,
  predictions: (id: string) => ["predictions", id] as const,
  diagnostics: (id: string) => ["diagnostics", id] as const,
  sensors: (id: string) => ["sensors", id] as const,
  report: (id: string) => ["report", id] as const,
  alerts: (params: string) => ["alerts", params] as const,
  models: ["models"] as const,
  stats: ["stats"] as const,
  devices: ["devices"] as const,
  replay: ["replay"] as const,
  evaluation: ["evaluation"] as const,
};

export const useMe = () => useQuery({ queryKey: keys.me, queryFn: () => api("/auth/me", Me), staleTime: 60_000 });
export const useAssets = () => useQuery({ queryKey: keys.assets, queryFn: () => api("/assets", AssetList) });
export const useAsset = (id: string) =>
  useQuery({ queryKey: keys.asset(id), queryFn: () => api(`/assets/${encodeURIComponent(id)}`, AssetDetail), retry: (n, e) => (e as { status?: number }).status !== 404 && n < 2 });
export const usePredictions = (id: string, enabled = true) =>
  useQuery({ queryKey: keys.predictions(id), queryFn: () => api(`/assets/${encodeURIComponent(id)}/predictions?limit=2000`, PredictionList), enabled });
export const useDiagnostics = (id: string, enabled = true) =>
  useQuery({ queryKey: keys.diagnostics(id), queryFn: () => api(`/assets/${encodeURIComponent(id)}/diagnostics`, Diagnostics), enabled, refetchInterval: 10_000 });
export const useSensors = (id: string, enabled = true) =>
  useQuery({ queryKey: keys.sensors(id), queryFn: () => api(`/assets/${encodeURIComponent(id)}/sensors?limit=400`, SensorHistory), enabled, refetchInterval: 10_000 });
export const useReport = (id: string) =>
  useQuery({ queryKey: keys.report(id), queryFn: () => api(`/assets/${encodeURIComponent(id)}/report`, Report) });
export function useAlerts(params: Record<string, string | undefined> = {}) {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][]).toString();
  return useQuery({ queryKey: keys.alerts(qs), queryFn: () => api(`/alerts${qs ? `?${qs}` : ""}`, AlertList) });
}
export const useModels = () => useQuery({ queryKey: keys.models, queryFn: () => api("/models", ModelList), staleTime: 300_000 });
export const useStats = () => useQuery({ queryKey: keys.stats, queryFn: () => api("/stats", Stats), refetchInterval: 5000 });
export const useDevices = () => useQuery({ queryKey: keys.devices, queryFn: () => api("/devices", DeviceList), refetchInterval: 5000 });
export const useReplay = () => useQuery({ queryKey: keys.replay, queryFn: () => api("/sim/replay/status", ReplayStatus), refetchInterval: 2000 });
export const useDeadLetter = () => useQuery({ queryKey: ["dead-letter"], queryFn: () => api("/dead-letter?limit=20", DeadLetter), refetchInterval: 10_000 });
export const useLastTelemetry = (id: string | null) =>
  useQuery({ queryKey: ["telemetry-last", id], queryFn: () => api(`/assets/${encodeURIComponent(id as string)}/telemetry?limit=1`, TelemetryList), enabled: !!id, refetchInterval: 5000 });
export const useEvaluation = () => useQuery({ queryKey: keys.evaluation, queryFn: () => api("/evaluation", Evaluation), staleTime: 300_000 });

/** Optimistic acknowledge with rollback (docs/02 §6.1). */
export function useAckAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api(`/alerts/${id}/ack`, null, { method: "POST", json: { by: "dashboard" } }),
    onMutate: async (id: number) => {
      await qc.cancelQueries({ queryKey: ["alerts"] });
      const prev = qc.getQueriesData<{ count: number; items: Alert[] }>({ queryKey: ["alerts"] });
      const now = new Date().toISOString();
      qc.setQueriesData<{ count: number; items: Alert[] }>({ queryKey: ["alerts"] }, (d) =>
        d ? { ...d, items: d.items.map((a) => (a.alert_id === id ? { ...a, acknowledged_at: now, acknowledged_by: "dashboard" } : a)) } : d,
      );
      return { prev };
    },
    onError: (_e, _id, ctx) => ctx?.prev.forEach(([k, v]) => qc.setQueryData(k, v)),
  });
}

export function useReplayAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ action, body }: { action: "start" | "pause" | "resume" | "stop"; body?: unknown }) =>
      api(`/sim/replay/${action}`, ReplayStatus, { method: "POST", json: body ?? {} }),
    onSuccess: (d) => qc.setQueryData(keys.replay, d),
  });
}

export function useHarnessCheck() {
  return useMutation({
    mutationFn: (id: string) => api(`/devices/${encodeURIComponent(id)}/harness-check`, HarnessResult, { method: "POST" }),
  });
}
