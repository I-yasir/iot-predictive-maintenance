import { forwardRef, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { AssetSummary } from "../api/schemas";
import { absTime, fmtHi, fmtRul, relTime } from "../lib/format";
import { MIN_CYCLES } from "../lib/states";
import { FlagIcons } from "./Flags";
import { Sparkline } from "./Sparkline";
import { SourceBadge, StateChip } from "./StateChip";
import s from "./ui.module.css";

export function rulBand(a: { rul_p10: number | null; rul_p90: number | null }): string {
  return a.rul_p10 === null || a.rul_p90 === null ? "" : `${fmtRul(a.rul_p10)}–${fmtRul(a.rul_p90)}`;
}

/** Asset tile (docs/03 §3.1). One state-change pulse, disabled under reduced motion by global CSS. */
export const AssetTile = forwardRef<HTMLAnchorElement, { a: AssetSummary; now: number; tabIndex?: number; onKeyDown?: React.KeyboardEventHandler }>(
  function AssetTile({ a, now, tabIndex, onKeyDown }, ref) {
    const prev = useRef(a.state);
    const [pulse, setPulse] = useState(false);
    useEffect(() => {
      if (prev.current !== a.state) {
        prev.current = a.state;
        setPulse(true);
        const t = setTimeout(() => setPulse(false), 650);
        return () => clearTimeout(t);
      }
    }, [a.state]);
    const warming = a.state === "WARMING_UP" || a.state === "NEW" || a.rul_pred === null;
    const offline = a.state === "OFFLINE";
    const cls = [
      s.tile,
      a.state === "CRITICAL" && s.tileCritical,
      offline && s.tileOffline,
      a.state === "DEGRADED_DATA" && s.tileDegraded,
      warming && s.tileWarming,
      pulse && s.tilePulse,
    ].filter(Boolean).join(" ");
    const n = Math.min(a.last_cycle ?? 0, MIN_CYCLES);
    return (
      <Link
        ref={ref}
        to={`/assets/${encodeURIComponent(a.asset_id)}`}
        className={cls}
        tabIndex={tabIndex}
        onKeyDown={onKeyDown}
        data-testid="asset-tile"
        title={`Cycle ${a.last_cycle ?? "—"} · health index ${fmtHi(a.health_index)}`}
        aria-label={`${a.asset_id}, ${a.state.toLowerCase().replace("_", " ")}, RUL ${warming ? "not available yet" : `${fmtRul(a.rul_pred)} cycles`}`}
      >
        <div className={s.tileTop}>
          <StateChip state={a.state} extra={a.state === "WARMING_UP" ? `(${n}/${MIN_CYCLES})` : undefined} />
          <FlagIcons flags={a.flags} />
        </div>
        <div className={s.tileId}>{a.asset_id}</div>
        {warming ? (
          <div className="muted">{a.state === "WARMING_UP" ? "Collecting baseline" : "No prediction yet"}</div>
        ) : (
          <div>
            <span className={`${s.rulHero} ${offline ? s.stale : ""}`}>{fmtRul(a.rul_pred)}</span> <span className="unit">cycles</span>
            {offline ? <span className="muted"> · stale</span> : null}
            <div className={s.band}>[{rulBand(a)}]</div>
          </div>
        )}
        <Sparkline values={a.sparkline} />
        <div className={s.tileMeta}>
          <SourceBadge source={a.source} />
          <span title={absTime(a.last_seen_at)}>{offline ? `Offline · last seen ${relTime(a.last_seen_at, now)}` : relTime(a.last_seen_at, now)}</span>
        </div>
      </Link>
    );
  },
);
