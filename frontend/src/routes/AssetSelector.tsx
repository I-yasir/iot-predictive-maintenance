import { useMemo, useRef, useState } from "react";
import { useAssets } from "../api/queries";
import { fmtRul } from "../lib/format";
import { stateMeta } from "../lib/states";
import s from "./detail.module.css";

/** Searchable combobox of all assets, grouped by state, RUL ascending (docs/03 §3.3, ARIA 1.2 combobox). */
export function AssetSelector({ current, onSelect }: { current?: string; onSelect: (id: string) => void }) {
  const assets = useAssets();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLUListElement>(null);
  const opts = useMemo(() => {
    const items = (assets.data?.items ?? []).filter((a) => a.asset_id.toLowerCase().includes(q.toLowerCase()));
    return items.sort((a, b) => stateMeta(a.state).rank - stateMeta(b.state).rank || (a.rul_pred ?? 1e9) - (b.rul_pred ?? 1e9));
  }, [assets.data, q]);
  const choose = (id: string) => {
    setOpen(false);
    setQ("");
    onSelect(id);
  };
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((i) => Math.min(opts.length - 1, i + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => Math.max(0, i - 1)); }
    else if (e.key === "Enter" && open && opts[active]) { e.preventDefault(); choose(opts[active].asset_id); }
    else if (e.key === "Escape") setOpen(false);
  };
  let lastState = "";
  return (
    <div className={s.selector}>
      <label>
        Component
        <input role="combobox" aria-expanded={open} aria-controls="asset-listbox" aria-autocomplete="list"
          aria-activedescendant={open && opts[active] ? `opt-${opts[active].asset_id}` : undefined}
          value={open ? q : (current ?? "")} placeholder="Search assets" onFocus={() => { setOpen(true); setActive(0); }}
          onBlur={() => setTimeout(() => setOpen(false), 150)} onChange={(e) => { setQ(e.target.value); setActive(0); setOpen(true); }} onKeyDown={onKey} />
      </label>
      {open ? (
        <ul id="asset-listbox" role="listbox" className={s.listbox} ref={listRef}>
          {opts.length === 0 ? <li className={s.group}>No match</li> : null}
          {opts.slice(0, 200).map((a, i) => {
            const header = a.state !== lastState ? stateMeta(a.state).label : null;
            lastState = a.state;
            return [
              header ? <li key={`h-${a.state}`} role="presentation" className={s.group}>{header}</li> : null,
              <li key={a.asset_id} id={`opt-${a.asset_id}`} role="option" aria-selected={i === active} className={s.option}
                onMouseDown={(e) => { e.preventDefault(); choose(a.asset_id); }} onMouseEnter={() => setActive(i)}>
                <span>{a.asset_id}</span><span className="num muted">{a.rul_pred === null ? "—" : `${fmtRul(a.rul_pred)} cyc`}</span>
              </li>,
            ];
          })}
        </ul>
      ) : null}
    </div>
  );
}
