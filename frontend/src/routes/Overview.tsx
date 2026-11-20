import { Check, LayoutGrid, Rows3 } from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useAckAlert, useAlerts, useAssets } from "../api/queries";
import type { Alert, AssetSummary } from "../api/schemas";
import { AssetTile, rulBand } from "../components/AssetTile";
import { FlagIcons } from "../components/Flags";
import { Sparkline } from "../components/Sparkline";
import { SourceBadge, StateChip } from "../components/StateChip";
import { ErrorCard, Loading, NoAssets, NoMatch } from "../components/States";
import ui from "../components/ui.module.css";
import { useNow } from "../hooks/live";
import { absTime, fmtHi, fmtRul, relTime } from "../lib/format";
import { PROFILES, SOURCES, STATE_META, stateMeta, THRESHOLDS } from "../lib/states";
import { PageHead, useActionsDisabled } from "./Shell";
import s from "./overview.module.css";

export type SortKey = "state" | "rul" | "id" | "seen";
const KPI_STATES = ["HEALTHY", "WARNING", "CRITICAL", "OFFLINE"] as const;

export function filterAssets(items: AssetSummary[], p: URLSearchParams): AssetSummary[] {
  const q = (p.get("q") ?? "").trim().toLowerCase();
  const states = p.get("state")?.split(",").filter(Boolean) ?? [];
  const profile = p.get("profile");
  const source = p.get("source");
  const sort = (p.get("sort") ?? "state") as SortKey;
  const out = items.filter(
    (a) =>
      (!q || a.asset_id.toLowerCase().includes(q)) &&
      (!states.length || states.includes(a.state)) &&
      (!profile || a.profile === profile) &&
      (!source || a.source === source),
  );
  const rul = (a: AssetSummary) => a.rul_pred ?? Number.POSITIVE_INFINITY;
  const cmp: Record<SortKey, (a: AssetSummary, b: AssetSummary) => number> = {
    state: (a, b) => stateMeta(a.state).rank - stateMeta(b.state).rank || rul(a) - rul(b) || a.asset_id.localeCompare(b.asset_id),
    rul: (a, b) => rul(a) - rul(b) || a.asset_id.localeCompare(b.asset_id),
    id: (a, b) => a.asset_id.localeCompare(b.asset_id),
    seen: (a, b) => Date.parse(b.last_seen_at ?? "0") - Date.parse(a.last_seen_at ?? "0"),
  };
  return out.sort(cmp[sort] ?? cmp.state);
}

export function Overview() {
  const assets = useAssets();
  const [params, setParams] = useSearchParams();
  const now = useNow(1000);
  const view = params.get("view") === "table" ? "table" : "grid";
  const set = useCallback(
    (k: string, v: string | null) => {
      const p = new URLSearchParams(params);
      if (v) p.set(k, v);
      else p.delete(k);
      setParams(p, { replace: true });
    },
    [params, setParams],
  );
  const items = useMemo(() => assets.data?.items ?? [], [assets.data]);
  const shown = useMemo(() => filterAssets(items, params), [items, params]);
  const byState = assets.data?.by_state ?? {};
  const activeState = params.get("state");

  if (assets.isPending) return (<><PageHead title="System overview" /><Loading label="Loading assets" rows={2} /></>);
  if (assets.isError && !assets.data) return <ErrorCard message={(assets.error as Error).message} onRetry={() => void assets.refetch()} />;

  return (
    <>
      <PageHead title="System overview">
        <span className="muted num">{items.length} assets</span>
      </PageHead>
      {items.length === 0 ? (
        <NoAssets />
      ) : (
        <>
          <section className={s.kpis} aria-label="Fleet status">
            <button className={ui.kpi} aria-pressed={!activeState} onClick={() => set("state", null)}>
              <span className={ui.kpiLabel}>Total</span>
              <span className={ui.kpiValue}>{items.length}</span>
            </button>
            {KPI_STATES.map((st) => {
              const m = STATE_META[st];
              const Icon = m.icon;
              return (
                <button key={st} className={ui.kpi} aria-pressed={activeState === st} onClick={() => set("state", activeState === st ? null : st)}
                  aria-label={`${m.label}: ${byState[st] ?? 0} assets. ${activeState === st ? "Clear filter" : "Filter"}`}>
                  <span className={ui.kpiLabel} style={{ color: `var(--state-${m.token}-text)` }}>
                    <Icon size={14} aria-hidden="true" /> {m.label}
                  </span>
                  <span className={ui.kpiValue}>{byState[st] ?? 0}</span>
                </button>
              );
            })}
          </section>
          <Filters params={params} set={set} view={view} clear={() => setParams(new URLSearchParams(view === "table" ? { view } : {}), { replace: true })} />
          <div className={s.layout}>
            <section aria-label="Assets" style={{ minWidth: 0, display: "grid", gap: 16 }}>
              {shown.length === 0 ? (
                <NoMatch onClear={() => setParams(new URLSearchParams(), { replace: true })} />
              ) : view === "grid" ? (
                <AssetGrid items={shown} now={now} />
              ) : (
                <AssetTable items={shown} now={now} sort={(params.get("sort") ?? "state") as SortKey} onSort={(k) => set("sort", k)} />
              )}
              <RulHistogram items={items} />
            </section>
            <aside className={s.side}>
              <LowestRul items={items} />
              <AlertFeed />
            </aside>
          </div>
        </>
      )}
    </>
  );
}

function Filters({ params, set, view, clear }: { params: URLSearchParams; set: (k: string, v: string | null) => void; view: string; clear: () => void }) {
  const any = ["q", "state", "profile", "source", "sort"].some((k) => params.get(k));
  return (
    <div className={s.filters} role="search">
      <label className={s.search}>
        Search asset ID
        <input type="search" value={params.get("q") ?? ""} onChange={(e) => set("q", e.target.value || null)} placeholder="e.g. FD001-T034" />
      </label>
      <label>
        State
        <select value={params.get("state") ?? ""} onChange={(e) => set("state", e.target.value || null)}>
          <option value="">All</option>
          {Object.entries(STATE_META).map(([k, m]) => <option key={k} value={k}>{m.label}</option>)}
        </select>
      </label>
      <label>
        Profile
        <select value={params.get("profile") ?? ""} onChange={(e) => set("profile", e.target.value || null)}>
          <option value="">All</option>
          {PROFILES.map((p) => <option key={p}>{p}</option>)}
        </select>
      </label>
      <label>
        Source
        <select value={params.get("source") ?? ""} onChange={(e) => set("source", e.target.value || null)}>
          <option value="">All</option>
          {SOURCES.map((p) => <option key={p}>{p}</option>)}
        </select>
      </label>
      <label>
        Sort
        <select value={params.get("sort") ?? "state"} onChange={(e) => set("sort", e.target.value === "state" ? null : e.target.value)}>
          <option value="state">State (critical first)</option>
          <option value="rul">RUL (lowest first)</option>
          <option value="id">Asset ID</option>
          <option value="seen">Last seen</option>
        </select>
      </label>
      <div role="group" aria-label="View" style={{ display: "flex", gap: 4 }}>
        <button aria-pressed={view === "grid"} onClick={() => set("view", null)} aria-label="Grid view"><LayoutGrid size={16} aria-hidden="true" /></button>
        <button aria-pressed={view === "table"} onClick={() => set("view", "table")} aria-label="Table view"><Rows3 size={16} aria-hidden="true" /></button>
      </div>
      {any ? <button className="ghost" onClick={clear}>Clear filters</button> : null}
    </div>
  );
}

/** Roving tabindex: arrow keys move focus in the grid, Enter opens (docs/02 §6.1). */
function AssetGrid({ items, now }: { items: AssetSummary[]; now: number }) {
  const refs = useRef<(HTMLAnchorElement | null)[]>([]);
  const [focus, setFocus] = useState(0);
  const gridRef = useRef<HTMLDivElement>(null);
  const cols = () => {
    const g = gridRef.current;
    if (!g || items.length < 2) return 1;
    const top = refs.current[0]?.offsetTop;
    return Math.max(1, refs.current.filter((r) => r && r.offsetTop === top).length);
  };
  const onKey = (i: number) => (e: React.KeyboardEvent) => {
    const step: Record<string, number> = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: cols(), ArrowUp: -cols(), Home: -i, End: items.length - 1 - i };
    const d = step[e.key];
    if (d === undefined) return;
    e.preventDefault();
    const j = Math.min(items.length - 1, Math.max(0, i + d));
    setFocus(j);
    refs.current[j]?.focus();
  };
  const f = Math.min(focus, items.length - 1);
  return (
    <div className={s.grid} ref={gridRef} role="list" aria-label="Asset tiles">
      {items.map((a, i) => (
        <div role="listitem" key={a.asset_id} style={{ display: "grid" }}>
          <AssetTile a={a} now={now} ref={(el) => (refs.current[i] = el)} tabIndex={i === f ? 0 : -1} onKeyDown={onKey(i)} />
        </div>
      ))}
    </div>
  );
}

const ROW_H = 44;
const VIRTUAL_AFTER = 100;

function AssetTable({ items, now, sort, onSort }: { items: AssetSummary[]; now: number; sort: SortKey; onSort: (k: SortKey) => void }) {
  const nav = useNavigate();
  const [top, setTop] = useState(0);
  const virtual = items.length > VIRTUAL_AFTER;
  const viewH = 70 * 10; // generous window; container is capped at 70vh
  const first = virtual ? Math.max(0, Math.floor(top / ROW_H) - 10) : 0;
  const last = virtual ? Math.min(items.length, first + Math.ceil(viewH / ROW_H) + 20) : items.length;
  const narrow = typeof window !== "undefined" && window.matchMedia("(max-width: 599px)").matches;
  if (narrow) {
    return (
      <div className={s.cards}>
        {items.map((a) => <AssetTile key={a.asset_id} a={a} now={now} />)}
      </div>
    );
  }
  const H = ({ k, children }: { k?: SortKey; children: string }) => (
    <th scope="col" aria-sort={k && sort === k ? "ascending" : undefined}>
      {k ? <button className={s.sortBtn} onClick={() => onSort(k)}>{children}{sort === k ? " ▲" : ""}</button> : children}
    </th>
  );
  return (
    <div className={s.tableWrap} onScroll={(e) => setTop((e.target as HTMLDivElement).scrollTop)} data-testid="asset-table">
      <table>
        <thead>
          <tr>
            <H k="state">State</H><H k="id">Asset</H><H>Profile</H><H>Source</H><H>Cycle</H><H k="rul">RUL</H><H>P10–P90</H><H>Health index</H><H>Trend</H><H k="seen">Last seen</H><H>Flags</H>
          </tr>
        </thead>
        <tbody>
          {virtual && first > 0 ? <tr style={{ height: first * ROW_H }} aria-hidden="true" /> : null}
          {items.slice(first, last).map((a) => (
            <tr key={a.asset_id} tabIndex={0} onClick={() => nav(`/assets/${encodeURIComponent(a.asset_id)}`)}
              onKeyDown={(e) => e.key === "Enter" && nav(`/assets/${encodeURIComponent(a.asset_id)}`)}>
              <td><StateChip state={a.state} /></td>
              <td className="mono"><Link to={`/assets/${encodeURIComponent(a.asset_id)}`} onClick={(e) => e.stopPropagation()}>{a.asset_id}</Link></td>
              <td>{a.profile}</td>
              <td><SourceBadge source={a.source} /></td>
              <td className="r">{a.last_cycle ?? "—"}</td>
              <td className="r"><strong>{fmtRul(a.rul_pred)}</strong></td>
              <td className="r muted">{rulBand(a) || "—"}</td>
              <td className="r">{fmtHi(a.health_index)}</td>
              <td><Sparkline values={a.sparkline} /></td>
              <td title={absTime(a.last_seen_at)}>{relTime(a.last_seen_at, now)}</td>
              <td><FlagIcons flags={a.flags} /></td>
            </tr>
          ))}
          {virtual && last < items.length ? <tr style={{ height: (items.length - last) * ROW_H }} aria-hidden="true" /> : null}
        </tbody>
      </table>
    </div>
  );
}

export function LowestRul({ items }: { items: AssetSummary[] }) {
  const low = items.filter((a) => a.rul_pred !== null).sort((a, b) => (a.rul_pred as number) - (b.rul_pred as number)).slice(0, 5);
  const max = 150;
  const pct = (v: number) => `${Math.min(100, (v / max) * 100)}%`;
  return (
    <section className="card" aria-labelledby="lowest-h">
      <header><h3 id="lowest-h">Lowest RUL</h3></header>
      {low.length === 0 ? <p className="muted">No predictions yet.</p> : (
        <ol className={s.lowest}>
          {low.map((a) => (
            <li key={a.asset_id}>
              <Link to={`/assets/${encodeURIComponent(a.asset_id)}`}>
                <span style={{ display: "flex", gap: 8, alignItems: "center" }}><StateChip state={a.state} /> <span className="mono">{a.asset_id}</span></span>
                <span className="num"><strong>{fmtRul(a.rul_pred)}</strong> <span className="unit">cyc</span></span>
                <span className={s.lowTrack} aria-hidden="true">
                  {a.rul_p10 !== null && a.rul_p90 !== null ? <span className={s.lowBand} style={{ left: pct(a.rul_p10), width: `calc(${pct(a.rul_p90)} - ${pct(a.rul_p10)})` }} /> : null}
                  <span className={s.lowPoint} style={{ left: pct(a.rul_pred as number) }} />
                </span>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

export function AlertFeed({ limit = 50 }: { limit?: number }) {
  const alerts = useAlerts({ limit: String(limit) });
  const ack = useAckAlert();
  const disabled = useActionsDisabled();
  const now = useNow(5000);
  return (
    <section className="card" aria-labelledby="feed-h">
      <header>
        <h3 id="feed-h">Live alerts</h3>
        <Link to="/alerts" style={{ font: "var(--type-small)" }}>All alerts</Link>
      </header>
      {alerts.isPending ? <Loading rows={3} h={48} /> : !alerts.data?.items.length ? <p className="muted">No alerts yet.</p> : (
        <ul className={s.feed} aria-live="polite" aria-relevant="additions">
          {alerts.data.items.map((a) => <AlertItem key={a.alert_id} a={a} now={now} disabled={disabled} onAck={() => ack.mutate(a.alert_id)} />)}
        </ul>
      )}
    </section>
  );
}

function AlertItem({ a, now, disabled, onAck }: { a: Alert; now: number; disabled: boolean; onAck: () => void }) {
  return (
    <li className={`${s.feedItem} ${a.acknowledged_at ? s.acked : ""}`} data-testid="alert-item">
      <Link to={`/assets/${encodeURIComponent(a.asset_id)}?cycle=${a.cycle}`}>
        <span className={s.feedTitle}>
          <StateChip state={a.to_state} /> <span className="mono">{a.asset_id}</span>
        </span>
        <span className="muted" style={{ font: "var(--type-small)" }}>
          {stateMeta(a.from_state).label} → {stateMeta(a.to_state).label}
          {a.rul_pred !== null ? `, RUL ${fmtRul(a.rul_pred)}` : ""} · cycle {a.cycle} · <span title={absTime(a.created_at)}>{relTime(a.created_at, now)}</span>
        </span>
      </Link>
      {a.acknowledged_at ? (
        <span className="muted" title={`Acknowledged by ${a.acknowledged_by ?? "?"} at ${absTime(a.acknowledged_at)}`}><Check size={16} aria-label="Acknowledged" /></span>
      ) : (
        <button onClick={onAck} disabled={disabled} aria-label={`Acknowledge alert ${a.asset_id} ${a.to_state} at cycle ${a.cycle}`}>Ack</button>
      )}
    </li>
  );
}

function RulHistogram({ items }: { items: AssetSummary[] }) {
  const v = items.filter((a) => a.rul_pred !== null).map((a) => a.rul_pred as number);
  if (v.length < 2) return null;
  const top = Math.max(150, Math.ceil(Math.max(...v) / 25) * 25);
  const bins = Array.from({ length: top / 25 }, (_, i) => ({ lo: i * 25, n: 0 }));
  v.forEach((x) => bins[Math.min(bins.length - 1, Math.floor(x / 25))].n++);
  const max = Math.max(...bins.map((b) => b.n), 1);
  const color = (lo: number) => (lo < THRESHOLDS.critical ? "var(--state-critical)" : lo < THRESHOLDS.warning ? "var(--state-warning)" : "var(--state-healthy)");
  return (
    <details className="card" open={typeof window !== "undefined" && window.matchMedia("(min-width: 1024px)").matches}>
      <summary><h3 style={{ display: "inline" }}>Fleet RUL distribution</h3></summary>
      <div className={s.hist} role="img" aria-label={`RUL histogram in 25-cycle bins: ${bins.map((b) => `${b.lo}–${b.lo + 24}: ${b.n}`).join(", ")}`} style={{ marginTop: 12 }}>
        {bins.map((b) => <div key={b.lo} className={s.histBar} style={{ height: `${(b.n / max) * 100}%`, background: color(b.lo) }} title={`${b.lo}–${b.lo + 24} cycles: ${b.n}`} />)}
      </div>
      <div className={s.histAxis}><span>0</span><span>{top / 2}</span><span>{top} cycles</span></div>
    </details>
  );
}
