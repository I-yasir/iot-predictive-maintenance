import { ArrowDown, ArrowUp } from "lucide-react";
import type { Contributor, SensorMeta } from "../api/schemas";
import s from "./charts.module.css";

export const SUBSYSTEMS = ["Fan", "LPC", "HPC", "Burner", "HPT", "LPT"] as const;

export function scoreColor(score: number): string {
  return score > 70 ? "var(--state-critical)" : score >= 40 ? "var(--state-warning)" : "var(--viz-1)";
}

/** Horizontal bars, sorted descending, colored by band (docs/03 §3.2). */
export function SubsystemBar({ scores }: { scores: Record<string, number> }) {
  const items = Object.entries(scores).sort((a, b) => b[1] - a[1]);
  if (!items.length) return <p className="muted">No subsystem scores yet.</p>;
  return (
    <ul className={s.bars} aria-label="Deviation score per subsystem, 0 to 100">
      {items.map(([k, v]) => (
        <li key={k} className={s.barRow}>
          <span>{k}</span>
          <span className={s.barTrack} role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={v} aria-label={`${k} deviation score`}>
            <span className={s.barFill} style={{ width: `${Math.max(2, v)}%`, background: scoreColor(v), display: "block" }} />
          </span>
          <span className="num" style={{ textAlign: "right" }}>{v.toFixed(0)}</span>
        </li>
      ))}
    </ul>
  );
}

/** Fan → LPC → HPC → Burner → HPT → LPT schematic strip. */
export function SubsystemStrip({ scores }: { scores: Record<string, number> }) {
  return (
    <div className={s.strip} role="list" aria-label="Engine stations from inlet to exhaust">
      {SUBSYSTEMS.map((k) => {
        const v = scores[k];
        const has = v !== undefined;
        return (
          <div key={k} role="listitem" className={s.block}
            style={{ borderColor: has ? scoreColor(v) : "var(--border)", background: has ? `color-mix(in srgb, ${scoreColor(v)} 14%, transparent)` : "transparent" }}>
            <span>{k}</span>
            <span className={s.blockScore}>{has ? v.toFixed(0) : "n/a"}</span>
          </div>
        );
      })}
    </div>
  );
}

export function ContributionList({ items, meta }: { items: Contributor[] | null; meta: Record<string, SensorMeta | undefined> }) {
  if (!items?.length) return <p className="muted">Contributions appear after the first prediction.</p>;
  return (
    <ol className={s.contrib}>
      {items.slice(0, 3).map((c) => {
        const Arrow = c.direction === "up" ? ArrowUp : ArrowDown;
        return (
          <li key={c.sensor}>
            <span className="mono"><strong>{c.sensor}</strong></span>
            <span className="muted">
              {meta[c.sensor]?.description ?? ""} · <Arrow size={12} aria-hidden="true" /> {c.direction === "up" ? "above" : "below"} baseline · {c.effect_on_rul} RUL
            </span>
            <span className="num">{c.pct.toFixed(0)}%</span>
          </li>
        );
      })}
    </ol>
  );
}
