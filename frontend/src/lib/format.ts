/** Number/time formatting rules from docs/03 §4. */
export function fmtRul(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : String(Math.round(v));
}
export function fmtHi(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : v.toFixed(2);
}
/** Sensor values: 2 decimals, 4 for BPR / W32 and the operating settings (dataset precision). */
const FOUR = new Set(["BPR", "W32", "setting_1", "setting_2", "setting_3"]);
export function fmtSensor(symbol: string, v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v.toFixed(FOUR.has(symbol) ? 4 : 2);
}
export function relTime(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "never";
  const s = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (s < 60) return `${s} s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.round(h / 24)} d ago`;
}
export function absTime(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : "";
}
export function clockTime(ms: number): string {
  return new Date(ms).toLocaleTimeString();
}
