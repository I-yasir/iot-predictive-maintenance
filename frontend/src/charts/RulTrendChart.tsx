import { useMemo, useState } from "react";
import { Area, Brush, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Alert, Prediction } from "../api/schemas";
import { DataFallback } from "../components/States";
import { fmtHi, fmtRul } from "../lib/format";
import { stateMeta, THRESHOLDS } from "../lib/states";
import s from "./charts.module.css";

interface Row { cycle: number; rul: number | null; band: [number, number] | null; truth: number | null; hi: number | null; state: string }

export function summarizeRul(rows: { cycle: number; rul: number | null }[]): string {
  const v = rows.filter((r) => r.rul !== null);
  if (v.length < 2) return "Not enough predictions for a trend yet.";
  const a = v[0];
  const b = v[v.length - 1];
  const dir = (b.rul as number) < (a.rul as number) ? "decreased" : "increased";
  return `RUL ${dir} from ${fmtRul(a.rul)} to ${fmtRul(b.rul)} cycles over ${b.cycle - a.cycle} cycles`;
}

/** docs/03 §3.2 RulTrendChart: predicted line, P10–P90 band, true RUL (replay), thresholds, alert ticks, brush zoom. */
export function RulTrendChart({ predictions, alerts = [], height = 320, cursorCycle, cap = 125 }: {
  predictions: Prediction[]; alerts?: Alert[]; height?: number; cursorCycle?: number | null; cap?: number;
}) {
  const rows: Row[] = useMemo(() => {
    const byCycle = new Map<number, Row>();
    for (const p of predictions) {
      byCycle.set(p.cycle, {
        cycle: p.cycle,
        rul: p.status === "OK" ? p.rul_pred : null,
        band: p.status === "OK" && p.rul_p10 !== null && p.rul_p90 !== null ? [p.rul_p10, p.rul_p90] : null,
        truth: p.true_rul,
        hi: p.health_index,
        state: p.state,
      });
    }
    return [...byCycle.values()].sort((x, y) => x.cycle - y.cycle);
  }, [predictions]);
  const [zoom, setZoom] = useState<{ startIndex?: number; endIndex?: number }>({});
  const zoomed = zoom.startIndex !== undefined && (zoom.startIndex > 0 || (zoom.endIndex ?? rows.length - 1) < rows.length - 1);
  const yMax = Math.max(150, ...rows.map((r) => Math.max(r.rul ?? 0, r.band?.[1] ?? 0, Math.min(r.truth ?? 0, 400))));
  const hasTruth = rows.some((r) => r.truth !== null);
  const summary = summarizeRul(rows);
  return (
    <div className={s.chartCard}>
      <div className={s.chartHead}>
        <div className={s.legend} aria-hidden="true">
          <span><i className={s.swatch} style={{ background: "var(--viz-1)" }} /> Predicted RUL</span>
          <span><i className={s.swatch} style={{ background: "var(--viz-1)", opacity: 0.3, height: 10 }} /> P10–P90</span>
          {hasTruth ? <span><i className={s.swatch} style={{ borderTop: "2px dashed var(--text-secondary)", height: 0 }} /> True RUL (replay)</span> : null}
        </div>
        {zoomed ? <button onClick={() => setZoom({})}>Reset zoom</button> : null}
      </div>
      <div role="group" aria-label={summary} style={{ width: "100%", height }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 8, right: 76, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--border)" strokeOpacity={0.5} vertical={false} />
            <XAxis dataKey="cycle" type="number" domain={["dataMin", "dataMax"]} allowDataOverflow tick={{ fill: "var(--text-secondary)", fontSize: 12 }} stroke="var(--border)" />
            <YAxis domain={[0, Math.ceil(yMax / 25) * 25]} ticks={Array.from({ length: Math.ceil(yMax / 25) + 1 }, (_, i) => i * 25).filter((t, _i, a) => a.length <= 9 || t % 50 === 0)} tick={{ fill: "var(--text-secondary)", fontSize: 12 }} stroke="var(--border)" width={40} />
            <Tooltip content={<RulTip />} isAnimationActive={false} />
            <Area dataKey="band" stroke="none" fill="var(--viz-1)" fillOpacity={0.18} isAnimationActive={false} connectNulls={false} />
            {hasTruth ? <Line dataKey="truth" stroke="var(--text-secondary)" strokeDasharray="5 4" dot={false} isAnimationActive={false} /> : null}
            <Line dataKey="rul" stroke="var(--viz-1)" strokeWidth={2} dot={false} isAnimationActive={false} connectNulls={false} />
            <ReferenceLine y={THRESHOLDS.warning} stroke="var(--state-warning)" strokeOpacity={0.7} strokeDasharray="6 4" label={{ value: `Warning ${THRESHOLDS.warning}`, position: "right", fill: "var(--state-warning-text)", fontSize: 11 }} />
            <ReferenceLine y={THRESHOLDS.critical} stroke="var(--state-critical)" strokeOpacity={0.7} strokeDasharray="6 4" label={{ value: `Critical ${THRESHOLDS.critical}`, position: "right", fill: "var(--state-critical-text)", fontSize: 11 }} />
            {cap ? <ReferenceLine y={cap} stroke="var(--border)" strokeDasharray="2 4" /> : null}
            {alerts.map((a) => (
              <ReferenceLine key={a.alert_id} x={a.cycle} stroke={`var(--state-${stateMeta(a.to_state).token})`} strokeWidth={2} strokeOpacity={0.8} />
            ))}
            {cursorCycle ? <ReferenceLine x={cursorCycle} stroke="var(--accent)" strokeWidth={2} label={{ value: `cycle ${cursorCycle}`, position: "top", fill: "var(--accent)", fontSize: 11 }} /> : null}
            {rows.length > 20 ? (
              <Brush dataKey="cycle" height={22} stroke="var(--border)" fill="var(--surface-2)" travellerWidth={8} startIndex={zoom.startIndex} endIndex={zoom.endIndex}
                onChange={(r) => setZoom({ startIndex: r.startIndex, endIndex: r.endIndex })} tickFormatter={() => ""} />
            ) : null}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <DataFallback
        caption={summary}
        columns={["Cycle", "RUL", "P10", "P90", "True RUL", "Health index", "State"]}
        rows={rows.slice(-200).map((r) => [r.cycle, fmtRul(r.rul), fmtRul(r.band?.[0]), fmtRul(r.band?.[1]), fmtRul(r.truth), fmtHi(r.hi), stateMeta(r.state).label])}
      />
    </div>
  );
}

function RulTip({ active, payload }: { active?: boolean; payload?: { payload: Row }[] }) {
  if (!active || !payload?.length) return null;
  const r = payload[0].payload;
  return (
    <div className={s.tooltip}>
      <strong>Cycle {r.cycle}</strong>
      <span>RUL {fmtRul(r.rul)} cycles {r.band ? `[${fmtRul(r.band[0])}–${fmtRul(r.band[1])}]` : ""}</span>
      {r.truth !== null ? <span>True RUL {fmtRul(r.truth)}</span> : null}
      <span>Health index {fmtHi(r.hi)}</span>
      <span>{stateMeta(r.state).label}</span>
    </div>
  );
}
