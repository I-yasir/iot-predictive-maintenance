/** Mocked API for component tests: realistic shapes taken from the backend responses. */
const iso = (sAgo: number) => new Date(Date.now() - sAgo * 1000).toISOString();

export function asset(id: string, state: string, rul: number | null, extra: Record<string, unknown> = {}) {
  return {
    asset_id: id, site_id: "lab", profile: id.slice(0, 5), source: "REPLAY", display_name: null, life_id: 1, state,
    last_cycle: 120, last_seen_at: iso(2), expected_interval_s: 0.2, true_rul_at_end: null, pred_cycle: 120,
    pred_status: rul === null ? "WARMING_UP" : "OK", rul_pred: rul, rul_p10: rul === null ? null : rul - 10,
    rul_p90: rul === null ? null : rul + 12, health_index: rul === null ? null : Math.min(1, rul / 125), flags: [],
    model_version: "20261120-p3", true_rul: null, sparkline: rul === null ? [] : [rul + 30, rul + 20, rul + 10, rul], ...extra,
  };
}

export const ASSETS = [
  asset("FD001-T034", "CRITICAL", 18, { true_rul: 12 }),
  asset("FD003-T012", "WARNING", 61, { source: "ESP32" }),
  asset("FD001-T010", "HEALTHY", 110),
  asset("FD002-T005", "HEALTHY", 95, { flags: ["LOW_CONFIDENCE"] }),
  asset("FD004-T001", "OFFLINE", 40),
  asset("FD001-T099", "WARMING_UP", null, { last_cycle: 3 }),
  asset("FD002-T077", "HEALTHY", 120),
];

export function assetList(items = ASSETS) {
  const by_state: Record<string, number> = {};
  items.forEach((a) => (by_state[a.state] = (by_state[a.state] ?? 0) + 1));
  return { count: items.length, by_state, items };
}

export const ALERTS = [
  { alert_id: 3, asset_id: "FD001-T034", life_id: 1, cycle: 110, from_state: "WARNING", to_state: "CRITICAL", rul_pred: 29, reason: "rul<=30", created_at: iso(5), acknowledged_at: null, acknowledged_by: null },
  { alert_id: 2, asset_id: "FD003-T012", life_id: 1, cycle: 90, from_state: "HEALTHY", to_state: "WARNING", rul_pred: 72, reason: "rul<=75", created_at: iso(60), acknowledged_at: null, acknowledged_by: null },
  { alert_id: 1, asset_id: "FD001-T034", life_id: 1, cycle: 60, from_state: "HEALTHY", to_state: "WARNING", rul_pred: 74, reason: "rul<=75", created_at: iso(120), acknowledged_at: iso(100), acknowledged_by: "dashboard" },
];

export const PREDICTIONS = {
  asset_id: "FD001-T034", life_id: 1,
  items: Array.from({ length: 116 }, (_, i) => {
    const cycle = i + 5;
    const rul = Math.max(0, 125 - Math.max(0, cycle - 20) * 1.07);
    return { prediction_id: i + 1, cycle, created_at: iso(200 - i), model_version: "20261120-p3", status: "OK", rul_pred: rul,
      rul_p10: rul - 10, rul_p90: rul + 12, health_index: rul / 125, state: rul <= 30 ? "CRITICAL" : rul <= 75 ? "WARNING" : "HEALTHY",
      flags: [], latency_ms: 4, true_rul: 130 - cycle };
  }),
};

const SENSORS = ["T24", "T30", "T50", "P30", "Ps30", "phi"];
export const SENSOR_META = [
  { symbol: "T2", description: "Total temperature at fan inlet", unit: "°R", subsystem: "Fan" },
  { symbol: "T24", description: "Total temperature at LPC outlet", unit: "°R", subsystem: "LPC" },
  { symbol: "T30", description: "Total temperature at HPC outlet", unit: "°R", subsystem: "HPC" },
  { symbol: "T50", description: "Total temperature at LPT outlet", unit: "°R", subsystem: "LPT" },
  { symbol: "P30", description: "Total pressure at HPC outlet", unit: "psia", subsystem: "HPC" },
  { symbol: "Ps30", description: "Static pressure at HPC outlet", unit: "psia", subsystem: "HPC" },
  { symbol: "phi", description: "Ratio of fuel flow to Ps30", unit: "pps/psi", subsystem: "Burner" },
];
export const SENSOR_HISTORY = {
  asset_id: "FD001-T034", life_id: 1, sensors: SENSOR_META, model_sensors: SENSORS, constant_sensors: ["T2"], baseline_source: "asset",
  items: Array.from({ length: 30 }, (_, i) => ({
    cycle: 91 + i, regime: 0, flags: [],
    raw: { T2: 518.67, T24: 642 + i * 0.02, T30: 1590 + i * 0.3, T50: 1400 + i * 0.5, P30: 553 - i * 0.05, Ps30: 47.3 + i * 0.02, phi: 521 - i * 0.04 },
    dev_z: { T24: 0.5, T30: 1.2, T50: i > 25 ? 4.2 : 2.1, P30: -1.8, Ps30: 2.6, phi: -0.4 },
    band: Object.fromEntries(SENSORS.map((s) => [s, [1, 2]])),
  })),
};

export const DIAGNOSTICS = {
  asset_id: "FD001-T034", note: "Indicative: C-MAPSS has no fault-mode labels (PRD non-goal 3).",
  latest: { cycle: 120, rul_pred: 18, rul_p10: 8, rul_p90: 30, health_index: 0.14, flags: [],
    contributors: [{ sensor: "T50", pct: 31.2, effect_on_rul: "lowers", direction: "up" }, { sensor: "Ps30", pct: 22.4, effect_on_rul: "lowers", direction: "up" }, { sensor: "phi", pct: 12.1, effect_on_rul: "lowers", direction: "down" }],
    subsystem_scores: { Fan: 20.5, LPC: 12, HPC: 55.3, Burner: 31, HPT: 10, LPT: 78.4 }, model_version: "20261120-p3" },
  latest_telemetry: null,
  sensor_subsystem: { T24: "LPC", T30: "HPC", T50: "LPT", P30: "HPC", Ps30: "HPC", phi: "Burner" },
  units: { T24: "°R", T30: "°R", T50: "°R", P30: "psia", Ps30: "psia", phi: "pps/psi" },
};

export const MODELS = { items: [{ profile: "FD001", model_version: "20261120-p3", point_estimate: "LightGBM", has_sequence_model: false, cap: 125, conformal_q: 9.5, window: 50,
  sensors_used: SENSORS, feature_names: ["f1", "f2"], cv: { rmse_mean: 13.1 }, test: { rmse: 14.23, nasa_score: 284.2, target_basis: "uncapped truth" }, training: {}, created_utc: iso(3600) }] };

export type Handler = (init?: RequestInit) => unknown;

export function mockFetch(routes: Record<string, unknown | Handler>) {
  const calls: { path: string; method: string; body?: string }[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname.replace("/api/v1", "") + url.search;
    calls.push({ path, method: init?.method ?? "GET", body: init?.body as string | undefined });
    const key = Object.keys(routes).sort((a, b) => b.length - a.length).find((k) => {
      const [m, p] = k.includes(" ") ? k.split(" ") : ["GET", k];
      return m === (init?.method ?? "GET") && (path === p || path.split("?")[0] === p);
    });
    if (!key) return new Response(JSON.stringify({ detail: `no mock for ${path}` }), { status: 404 });
    const r = routes[key];
    const body = typeof r === "function" ? (r as Handler)(init) : r;
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  globalThis.fetch = fn as unknown as typeof fetch;
  return calls;
}

export const BASE_ROUTES = {
  "/auth/me": { authenticated: true, auth_enabled: true },
  "/assets": assetList(),
  "/alerts": { count: ALERTS.length, items: ALERTS },
  "/models": MODELS,
};
