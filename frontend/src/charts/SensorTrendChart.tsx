import { useMemo } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";
import type { SensorMeta, SensorRow } from "../api/schemas";
import { DataFallback } from "../components/States";
import { fmtSensor } from "../lib/format";
import s from "./charts.module.css";

export const ROLL_W = 10;
export const ANOMALY_Z = 3;

export interface SensorPoint { cycle: number; raw: number | null; mean: number | null; band: [number, number] | null; anomaly: number | null; z: number | null }

/** Raw points, rolling mean (W=10), baseline band, anomaly dots where |z| > 3 (docs/03 §3.2). */
export function sensorSeries(rows: SensorRow[], sym: string): SensorPoint[] {
  const out: SensorPoint[] = [];
  const win: number[] = [];
  for (const r of rows) {
    const v = r.raw[sym];
    const raw = typeof v === "number" && Number.isFinite(v) ? v : null;
    if (raw !== null) {
      win.push(raw);
      if (win.length > ROLL_W) win.shift();
    }
    const z = r.dev_z[sym] ?? null;
    out.push({
      cycle: r.cycle,
      raw,
      mean: win.length ? win.reduce((a, b) => a + b, 0) / win.length : null,
      band: r.band[sym] ?? null,
      anomaly: z !== null && Math.abs(z) > ANOMALY_Z ? raw : null,
      z,
    });
  }
  return out;
}

export function SensorSmall({ meta, rows, constant, syncId, height = 180 }: { meta: SensorMeta; rows: SensorRow[]; constant?: boolean; syncId?: string; height?: number }) {
  const data = useMemo(() => sensorSeries(rows, meta.symbol), [rows, meta.symbol]);
  const last = data[data.length - 1];
  const nAnom = data.filter((d) => d.anomaly !== null).length;
  const label = `${meta.symbol} ${meta.description}: latest ${fmtSensor(meta.symbol, last?.raw)} ${meta.unit}` +
    (last?.z !== null && last?.z !== undefined ? `, deviation ${last.z.toFixed(1)} sigma` : "") + `, ${nAnom} anomalous cycles shown`;
  return (
    <figure className={`${s.small} ${constant ? s.smallConst : ""}`} style={{ margin: 0 }} data-testid={`sensor-${meta.symbol}`}>
      <figcaption className={s.smallHead}>
        <span>
          <strong className="mono">{meta.symbol}</strong> <span className="muted">{meta.description}</span>
        </span>
        <span className="num">
          {fmtSensor(meta.symbol, last?.raw)} {meta.unit !== "-" ? <span className="unit">{meta.unit}</span> : null}
          {last?.z !== null && last?.z !== undefined ? <span className="muted"> · z {last.z.toFixed(1)}</span> : null}
        </span>
      </figcaption>
      {constant ? <p className="muted" style={{ font: "var(--type-small)" }}>Constant in this profile (not used by the model).</p> : null}
      <div role="img" aria-label={label} style={{ width: "100%", height }}>
        <div aria-hidden="true" style={{ width: "100%", height: "100%" }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} syncId={syncId} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--border)" strokeOpacity={0.5} vertical={false} />
            <XAxis dataKey="cycle" type="number" domain={["dataMin", "dataMax"]} tick={{ fill: "var(--text-secondary)", fontSize: 11 }} stroke="var(--border)" />
            <YAxis domain={["auto", "auto"]} tick={{ fill: "var(--text-secondary)", fontSize: 11 }} stroke="var(--border)" width={56}
              tickFormatter={(v: number) => fmtSensor(meta.symbol, v)} />
            <Tooltip isAnimationActive={false} content={<SensorTip sym={meta.symbol} unit={meta.unit} />} />
            <Area dataKey="band" fill="var(--surface-2)" stroke="var(--border)" fillOpacity={1} isAnimationActive={false} />
            <Scatter dataKey="raw" fill="var(--viz-1)" fillOpacity={0.4} shape={<Dot r={1.5} k="raw" />} isAnimationActive={false} />
            <Line dataKey="mean" stroke="var(--viz-1)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
            <Scatter dataKey="anomaly" fill="var(--state-warning)" shape={<Dot r={3} k="anomaly" />} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
        </div>
      </div>
      <DataFallback caption={label} columns={["Cycle", "Value", "Rolling mean", "Baseline low", "Baseline high", "z"]}
        rows={data.slice(-100).map((d) => [d.cycle, fmtSensor(meta.symbol, d.raw), fmtSensor(meta.symbol, d.mean), fmtSensor(meta.symbol, d.band?.[0]), fmtSensor(meta.symbol, d.band?.[1]), d.z === null ? "—" : d.z.toFixed(2)])} />
    </figure>
  );
}

function Dot({ cx, cy, r, fill, fillOpacity, k, payload }: { cx?: number; cy?: number; r: number; fill?: string; fillOpacity?: number; k: "raw" | "anomaly"; payload?: SensorPoint }) {
  // Recharts still calls the shape for null values (placed at the plot edge): skip them
  if (cx === undefined || cy === undefined || Number.isNaN(cy) || !payload || payload[k] === null) return null;
  return <circle cx={cx} cy={cy} r={r} fill={fill} fillOpacity={fillOpacity} />;
}

function SensorTip({ active, payload, sym, unit }: { active?: boolean; payload?: { payload: SensorPoint }[]; sym: string; unit: string }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className={s.tooltip}>
      <strong>Cycle {d.cycle}</strong>
      <span>{fmtSensor(sym, d.raw)} {unit}</span>
      <span>Mean ({ROLL_W}) {fmtSensor(sym, d.mean)}</span>
      {d.band ? <span>Baseline {fmtSensor(sym, d.band[0])}–{fmtSensor(sym, d.band[1])}</span> : null}
      {d.z !== null ? <span>z {d.z.toFixed(2)}{Math.abs(d.z) > ANOMALY_Z ? " (anomalous)" : ""}</span> : null}
    </div>
  );
}
