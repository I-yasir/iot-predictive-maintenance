import { fmtHi } from "../lib/format";
import s from "./ui.module.css";

/** Semicircle 0-1; Critical < 0.25, Warning 0.25-0.6, Healthy > 0.6 (docs/03 §3.2). */
export function HealthGauge({ value, size = 160 }: { value: number | null; size?: number }) {
  const r = size / 2 - 10;
  const cx = size / 2;
  const cy = size / 2;
  const arc = (a0: number, a1: number) => {
    const p = (a: number) => [cx - r * Math.cos(Math.PI * a), cy - r * Math.sin(Math.PI * a)];
    const [x0, y0] = p(a0);
    const [x1, y1] = p(a1);
    return `M${x0},${y0} A${r},${r} 0 0 1 ${x1},${y1}`;
  };
  const v = value === null ? null : Math.min(1, Math.max(0, value));
  const label = v === null ? "Health index unavailable" : `Health index ${fmtHi(v)} of 1`;
  const needle = v === null ? null : [cx - (r - 14) * Math.cos(Math.PI * v), cy - (r - 14) * Math.sin(Math.PI * v)];
  return (
    <div className={s.gauge}>
      <svg width={size} height={size / 2 + 12} role="img" aria-label={label}>
        <path d={arc(0, 0.25)} stroke="var(--state-critical)" strokeWidth={10} fill="none" />
        <path d={arc(0.25, 0.6)} stroke="var(--state-warning)" strokeWidth={10} fill="none" />
        <path d={arc(0.6, 1)} stroke="var(--state-healthy)" strokeWidth={10} fill="none" />
        {needle ? <line x1={cx} y1={cy} x2={needle[0]} y2={needle[1]} stroke="var(--text-primary)" strokeWidth={3} strokeLinecap="round" /> : null}
        <circle cx={cx} cy={cy} r={5} fill="var(--text-primary)" />
      </svg>
      <div className={s.gaugeValue} aria-hidden="true">{fmtHi(v)}</div>
      <span className="muted" style={{ font: "var(--type-small)" }}>health index</span>
    </div>
  );
}
