import { stateMeta } from "../lib/states";
import s from "./ui.module.css";

/** Color + icon + text label, always (docs/03 §1.2, WCAG 1.4.1). */
export function StateChip({ state, extra }: { state: string; extra?: string }) {
  const m = stateMeta(state);
  const Icon = m.icon;
  return (
    <span className={`${s.chip} ${s[m.token]}`} data-state={state}>
      <Icon size={14} aria-hidden="true" />
      {m.label}
      {extra ? <span className="num"> {extra}</span> : null}
    </span>
  );
}

export function SourceBadge({ source }: { source: string }) {
  return (
    <span className={s.badge} title={`Data source: ${source}`}>
      {source === "VIRTUAL_ESP32" ? "V-ESP32" : source}
    </span>
  );
}
