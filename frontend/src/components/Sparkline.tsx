/** 120 x 28 px, no axes, last point emphasized (docs/03 §3.2). Dropping RUL trends down. */
export function Sparkline({ values, width = 120, height = 28, label }: { values: (number | null)[]; width?: number; height?: number; label?: string }) {
  const v = values.filter((x): x is number => x !== null && Number.isFinite(x));
  if (v.length < 2) return <svg width={width} height={height} role="img" aria-label="Not enough data for a trend" />;
  const max = Math.max(...v, 1);
  const min = Math.min(...v, 0);
  const x = (i: number) => (i / (v.length - 1)) * (width - 4) + 2;
  const y = (val: number) => height - 2 - ((val - min) / (max - min || 1)) * (height - 4);
  const d = v.map((val, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(val).toFixed(1)}`).join("");
  const last = v[v.length - 1];
  return (
    <svg width={width} height={height} role="img" aria-label={label ?? `RUL trend from ${Math.round(v[0])} to ${Math.round(last)} cycles`}>
      <path d={d} fill="none" stroke="var(--viz-1)" strokeWidth={1.5} />
      <circle cx={x(v.length - 1)} cy={y(last)} r={2.5} fill="var(--viz-1)" />
    </svg>
  );
}
