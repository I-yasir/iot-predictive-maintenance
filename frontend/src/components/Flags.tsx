import { Activity, Gauge, Info, TrendingDown, Waves } from "lucide-react";
import { FLAG_TEXT } from "../lib/states";
import s from "./ui.module.css";

const ICON: Record<string, typeof Info> = { LOW_CONFIDENCE: Info, OOD: Gauge, DRIFT: Waves, JUMP: TrendingDown, gap: Activity };
const SHOWN = ["LOW_CONFIDENCE", "OOD", "DRIFT", "JUMP"];

export function FlagIcons({ flags }: { flags: string[] }) {
  const f = flags.filter((x) => SHOWN.includes(x));
  if (!f.length) return null;
  return (
    <span className={s.flags}>
      {f.map((x) => {
        const Icon = ICON[x] ?? Info;
        return (
          <span key={x} className={s.flag} title={FLAG_TEXT[x]} role="img" aria-label={FLAG_TEXT[x]}>
            <Icon size={14} aria-hidden="true" />
          </span>
        );
      })}
    </span>
  );
}

export function FlagList({ flags }: { flags: string[] }) {
  if (!flags.length) return <p className="muted">No flags on the latest prediction.</p>;
  return (
    <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 4 }}>
      {flags.map((f) => (
        <li key={f}>
          <strong className="mono">{f}</strong> — {FLAG_TEXT[f] ?? "See docs/05 §8."}
        </li>
      ))}
    </ul>
  );
}
