/** Runtime validation of API and WebSocket payloads (docs/04 §2.4: zod). Shapes mirror backend/app/api. */
import { z } from "zod";

export const STATES = ["NEW", "WARMING_UP", "HEALTHY", "WARNING", "CRITICAL", "OFFLINE", "DEGRADED_DATA"] as const;
export const State = z.enum(STATES);
export type State = z.infer<typeof State>;

const num = z.number().nullable();
const flags = z.array(z.string()).nullable().transform((f) => f ?? []);

export const AssetSummary = z.object({
  asset_id: z.string(),
  site_id: z.string(),
  profile: z.string(),
  source: z.string(),
  display_name: z.string().nullable().optional(),
  life_id: z.number(),
  state: State,
  last_cycle: z.number().nullable(),
  last_seen_at: z.string().nullable(),
  expected_interval_s: num.optional(),
  true_rul_at_end: num.optional(),
  pred_cycle: num,
  pred_status: z.string().nullable(),
  rul_pred: num,
  rul_p10: num,
  rul_p90: num,
  health_index: num,
  flags,
  model_version: z.string().nullable(),
  true_rul: num,
  sparkline: z.array(z.number().nullable()).optional().default([]),
});
export type AssetSummary = z.infer<typeof AssetSummary>;

export const AssetList = z.object({ count: z.number(), by_state: z.record(z.number()), items: z.array(AssetSummary) });
export type AssetList = z.infer<typeof AssetList>;

export const AssetDetail = AssetSummary.extend({
  lives: z.array(z.number()).default([]),
  last_rejection: z.object({ reason: z.string(), detail: z.string().nullable(), received_at: z.string() }).nullable(),
});
export type AssetDetail = z.infer<typeof AssetDetail>;

export const Prediction = z.object({
  prediction_id: z.number(),
  cycle: z.number(),
  created_at: z.string(),
  model_version: z.string(),
  status: z.string(),
  rul_pred: num,
  rul_p10: num,
  rul_p90: num,
  health_index: num,
  state: State,
  flags,
  latency_ms: num,
  true_rul: num,
});
export type Prediction = z.infer<typeof Prediction>;
export const PredictionList = z.object({ asset_id: z.string(), life_id: z.number(), items: z.array(Prediction) });

export const Contributor = z.object({
  sensor: z.string(),
  pct: z.number(),
  effect_on_rul: z.enum(["lowers", "raises"]),
  direction: z.enum(["up", "down"]),
});
export type Contributor = z.infer<typeof Contributor>;

export const Diagnostics = z.object({
  asset_id: z.string(),
  note: z.string(),
  latest: z
    .object({
      cycle: z.number(),
      rul_pred: num,
      rul_p10: num,
      rul_p90: num,
      health_index: num,
      flags,
      contributors: z.array(Contributor).nullable(),
      subsystem_scores: z.record(z.number()).nullable(),
      model_version: z.string(),
    })
    .nullable(),
  latest_telemetry: z
    .object({ cycle: z.number(), sensors: z.record(z.number()), settings: z.record(z.number()), regime: num })
    .nullable(),
  sensor_subsystem: z.record(z.string().nullable()),
  units: z.record(z.string()),
});
export type Diagnostics = z.infer<typeof Diagnostics>;

export const SensorMeta = z.object({ symbol: z.string(), description: z.string(), unit: z.string(), subsystem: z.string() });
export type SensorMeta = z.infer<typeof SensorMeta>;
export const SensorRow = z.object({
  cycle: z.number(),
  regime: num,
  flags,
  raw: z.record(z.number()),
  dev_z: z.record(z.number()).optional().default({}),
  band: z.record(z.tuple([z.number(), z.number()])).optional().default({}),
});
export type SensorRow = z.infer<typeof SensorRow>;
export const SensorHistory = z.object({
  asset_id: z.string(),
  life_id: z.number(),
  sensors: z.array(SensorMeta),
  model_sensors: z.array(z.string()),
  constant_sensors: z.array(z.string()),
  baseline_source: z.enum(["asset", "fleet"]).nullable(),
  items: z.array(SensorRow),
});
export type SensorHistory = z.infer<typeof SensorHistory>;

export const Alert = z.object({
  alert_id: z.number(),
  asset_id: z.string(),
  life_id: z.number(),
  cycle: z.number(),
  from_state: z.string(),
  to_state: z.string(),
  rul_pred: num,
  reason: z.string().nullable(),
  created_at: z.string(),
  acknowledged_at: z.string().nullable().optional(),
  acknowledged_by: z.string().nullable().optional(),
});
export type Alert = z.infer<typeof Alert>;
export const AlertList = z.object({ count: z.number(), items: z.array(Alert) });

export const ModelInfo = z
  .object({
    profile: z.string(),
    model_version: z.string(),
    point_estimate: z.string(),
    has_sequence_model: z.boolean(),
    cap: z.number(),
    conformal_q: num,
    window: z.number(),
    sensors_used: z.array(z.string()),
    feature_names: z.array(z.string()),
    cv: z.record(z.unknown()).nullable(),
    test: z.record(z.unknown()).nullable(),
    training: z.record(z.unknown()).nullable(),
    created_utc: z.string().nullable(),
  })
  .passthrough();
export type ModelInfo = z.infer<typeof ModelInfo>;
export const ModelList = z.object({ items: z.array(ModelInfo) });

export const Report = z.object({
  asset: AssetDetail,
  diagnostics: Diagnostics,
  predictions: z.array(Prediction),
  alerts: z.array(Alert),
  model: z.record(z.unknown()).nullable(),
});
export type Report = z.infer<typeof Report>;

export const Latency = z.object({ p50: z.number(), p95: z.number(), max: z.number() }).nullable();
export const Stats = z.object({
  ingest: z.object({
    since: z.string(),
    counts: z.record(z.number()),
    rejected_by_reason: z.record(z.number()),
    rate_msgs_s_10s: z.number(),
    latency_ms: Latency,
  }),
  active_assets: z.number(),
  drift_assets: z.number(),
  dead_letter_24h: z.array(z.object({ reason: z.string(), n: z.number() })),
  mqtt_connected: z.boolean(),
  db_ok: z.boolean(),
});
export type Stats = z.infer<typeof Stats>;

export const ReplayStatus = z.object({
  state: z.string(),
  config: z.record(z.unknown()).nullable(),
  stats: z
    .object({
      sent: z.number(),
      accepted: z.number(),
      failed: z.number(),
      rate_msgs_s: z.number().optional(),
      last_error: z.string().nullable().optional(),
      progress: z.record(z.object({ cycle: z.number(), of: z.number() })).optional(),
    })
    .passthrough()
    .nullable(),
});
export type ReplayStatus = z.infer<typeof ReplayStatus>;

export const Device = z.object({
  device_id: z.string(),
  asset_id: z.string().nullable(),
  source: z.string().nullable(),
  state: z.string().nullable(),
  last_seen_at: z.string().nullable(),
  last_cycle: num,
  fw: z.string().nullable(),
  ip: z.string().nullable(),
  rssi: num,
  online: z.boolean().nullable(),
  last_status_at: z.string().nullable(),
});
export type Device = z.infer<typeof Device>;
export const DeviceList = z.object({ items: z.array(Device) });

export const HarnessResult = z.object({
  device_id: z.string(),
  window: z.number(),
  rate_msgs_s: z.number(),
  passed: z.boolean(),
  checks: z.array(z.object({ check: z.string(), ok: z.boolean(), detail: z.unknown() })),
});
export type HarnessResult = z.infer<typeof HarnessResult>;

export const Evaluation = z.object({
  labels: z.array(z.string()),
  items: z.array(
    z
      .object({
        profile: z.string(),
        generated: z.string(),
        model_version: z.string(),
        n: z.number(),
        rmse: z.number(),
        nasa_score: z.number(),
        rmse_capped125: z.number().optional(),
        nasa_score_capped125: z.number().optional(),
        target_basis: z.string().optional(),
        targets: z.object({ rmse: z.number(), nasa_score: z.number() }).optional(),
        meets_rmse_target: z.boolean().optional(),
        meets_score_target: z.boolean().optional(),
        critical_recall: z.number().optional(),
        confusion: z.record(z.array(z.number())).nullable(),
        report: z.string(),
      })
      .passthrough(),
  ),
});
export type Evaluation = z.infer<typeof Evaluation>;

export const Me = z.object({ authenticated: z.boolean(), auth_enabled: z.boolean() });

// ---- WebSocket events (docs/04 §5.5)
export const PredictionEvent = z.object({
  asset_id: z.string(),
  life_id: z.number(),
  cycle: z.number(),
  status: z.string(),
  rul_pred: num,
  rul_p10: num,
  rul_p90: num,
  health_index: num,
  state: State,
  flags,
  true_rul: num,
  ts: z.string(),
  latency_ms: z.number().optional(),
  profile: z.string().optional(),
  source: z.string().optional(),
});
export type PredictionEvent = z.infer<typeof PredictionEvent>;
export const AssetStatusEvent = z.object({
  asset_id: z.string(),
  state: State,
  life_id: z.number(),
  last_cycle: num,
  last_seen: z.string().nullable(),
});
export type AssetStatusEvent = z.infer<typeof AssetStatusEvent>;

export const WsEvent = z.discriminatedUnion("type", [
  z.object({ type: z.literal("prediction"), data: PredictionEvent }),
  z.object({ type: z.literal("alert"), data: Alert }),
  z.object({ type: z.literal("alert_ack"), data: z.record(z.unknown()) }),
  z.object({ type: z.literal("asset_status"), data: AssetStatusEvent }),
  z.object({ type: z.literal("sim_status"), data: z.record(z.unknown()) }),
  z.object({ type: z.literal("device_status"), data: z.record(z.unknown()) }),
  z.object({ type: z.literal("heartbeat"), ts: z.union([z.string(), z.number()]).optional() }),
]);
export type WsEvent = z.infer<typeof WsEvent>;

export const DeadLetter = z.object({
  items: z.array(z.object({
    id: z.number(), received_at: z.string(), transport: z.string().nullable(), topic: z.string().nullable(),
    asset_id: z.string().nullable(), reason: z.string(), detail: z.string().nullable(), raw: z.string(), raw_truncated: z.boolean(),
  })),
});
export type DeadLetter = z.infer<typeof DeadLetter>;
export const TelemetryList = z.object({
  asset_id: z.string(), life_id: z.number(),
  items: z.array(z.object({ cycle: z.number(), received_at: z.string(), device_ts: z.string().nullable(), seq: z.number().nullable(),
    settings: z.record(z.number()), sensors: z.record(z.number()), regime: z.number().nullable(), flags: z.array(z.string()) })),
});
