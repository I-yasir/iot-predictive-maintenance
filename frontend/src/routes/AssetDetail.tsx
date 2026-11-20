import { ChevronRight, Download, Printer } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useAckAlert, useAlerts, useAsset, useDiagnostics, useModels, usePredictions, useSensors } from "../api/queries";
import { Report, type AssetDetail as AssetT, type Diagnostics, type ModelInfo, type SensorHistory, type SensorMeta } from "../api/schemas";
import { ContributionList, SUBSYSTEMS, SubsystemBar, SubsystemStrip } from "../charts/Diagnostics";
import { RulTrendChart } from "../charts/RulTrendChart";
import { SensorSmall } from "../charts/SensorTrendChart";
import cs from "../charts/charts.module.css";
import { FlagList } from "../components/Flags";
import { HealthGauge } from "../components/HealthGauge";
import { SourceBadge, StateChip } from "../components/StateChip";
import { ErrorCard, Loading } from "../components/States";
import { useNow } from "../hooks/live";
import { absTime, fmtRul, fmtSensor, relTime } from "../lib/format";
import { FLAG_TEXT, MIN_CYCLES, stateMeta, THRESHOLDS } from "../lib/states";
import { AssetSelector } from "./AssetSelector";
import { useActionsDisabled } from "./Shell";
import s from "./detail.module.css";

export const TABS = ["summary", "sensors", "subsystems", "alerts", "model"] as const;
type Tab = (typeof TABS)[number];
const TAB_LABEL: Record<Tab, string> = { summary: "Summary", sensors: "Sensors", subsystems: "Subsystems", alerts: "Alerts", model: "Model" };

export async function downloadReport(id: string): Promise<void> {
  const r = await api(`/assets/${encodeURIComponent(id)}/report`, Report);
  const blob = new Blob([JSON.stringify(r, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${id}-report-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "")}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function AssetDetail() {
  const { assetId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const nav = useNavigate();
  const tab = (TABS.includes(params.get("tab") as Tab) ? params.get("tab") : "summary") as Tab;
  const asset = useAsset(assetId);
  const now = useNow(1000);
  const select = (id: string) => nav(`/assets/${encodeURIComponent(id)}${tab !== "summary" ? `?tab=${tab}` : ""}`);
  const setTab = (t: Tab) => {
    const p = new URLSearchParams(params);
    if (t === "summary") p.delete("tab");
    else p.set("tab", t);
    setParams(p, { replace: true });
  };
  const onTabKey = (e: React.KeyboardEvent) => {
    const i = TABS.indexOf(tab);
    const j = e.key === "ArrowRight" ? (i + 1) % TABS.length : e.key === "ArrowLeft" ? (i + TABS.length - 1) % TABS.length : -1;
    if (j < 0) return;
    e.preventDefault();
    setTab(TABS[j]);
    document.getElementById(`tab-${TABS[j]}`)?.focus();
  };

  if (asset.isPending) return <Loading label="Loading asset" rows={3} />;
  if (asset.isError) {
    const status = (asset.error as { status?: number }).status;
    if (status === 404)
      return (
        <div className="card" style={{ display: "grid", gap: 12 }}>
          <h1>Asset not found</h1>
          <p className="muted">No asset called <span className="mono">{assetId}</span>. Choose another one:</p>
          <AssetSelector onSelect={select} />
        </div>
      );
    return <ErrorCard message={(asset.error as Error).message} onRetry={() => void asset.refetch()} />;
  }
  const a = asset.data;
  return (
    <>
      <header className={s.head}>
        <nav className={s.crumb} aria-label="Breadcrumb">
          <Link to="/overview">Overview</Link> <ChevronRight size={12} aria-hidden="true" /> <span className="mono" aria-current="page">{a.asset_id}</span>
        </nav>
        <div className={s.titleRow}>
          <h1 className="mono">{a.asset_id}</h1>
          <StateChip state={a.state} extra={a.state === "WARMING_UP" ? `(${Math.min(a.last_cycle ?? 0, MIN_CYCLES)}/${MIN_CYCLES})` : undefined} />
          <SourceBadge source={a.source} />
          <div className={s.actions}>
            <AssetSelector current={a.asset_id} onSelect={select} />
            <button onClick={() => void downloadReport(a.asset_id)} style={{ alignSelf: "end" }}><Download size={16} aria-hidden="true" /> Export report</button>
            <Link className="btn" style={{ alignSelf: "end" }} to={`/assets/${encodeURIComponent(a.asset_id)}/report`} target="_blank"><Printer size={16} aria-hidden="true" /> Open printable</Link>
          </div>
        </div>
        <div className={s.meta}>
          <span>Profile <strong>{a.profile}</strong></span>
          <span>Cycle <strong className="num">{a.last_cycle ?? "—"}</strong></span>
          <span>Life <strong className="num">{a.life_id}</strong></span>
          <span title={absTime(a.last_seen_at)}>Last seen <strong>{relTime(a.last_seen_at, now)}</strong></span>
          {a.state === "DEGRADED_DATA" && a.last_rejection ? <span style={{ color: "var(--state-degraded-text)" }}>Data quality issue: {a.last_rejection.reason}</span> : null}
        </div>
      </header>
      <div role="tablist" aria-label="Report sections" className={s.tabs} onKeyDown={onTabKey}>
        {TABS.map((t) => (
          <button key={t} id={`tab-${t}`} role="tab" aria-selected={tab === t} aria-controls={`panel-${t}`} tabIndex={tab === t ? 0 : -1} className={s.tab} onClick={() => setTab(t)}>
            {TAB_LABEL[t]}
          </button>
        ))}
      </div>
      <section role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "summary" && <SummaryTab a={a} cursor={params.get("cycle") ? Number(params.get("cycle")) : null} />}
        {tab === "sensors" && <SensorsTab id={a.asset_id} />}
        {tab === "subsystems" && <SubsystemsTab id={a.asset_id} />}
        {tab === "alerts" && <AlertsTab id={a.asset_id} />}
        {tab === "model" && <ModelTab a={a} />}
      </section>
    </>
  );
}

export function groundTruthError(a: Pick<AssetT, "true_rul_at_end" | "true_rul" | "rul_pred" | "pred_cycle">): { err: number; final: boolean; cycle: number | null } | null {
  if (a.rul_pred === null) return null;
  if (a.true_rul_at_end !== null && a.true_rul_at_end !== undefined) return { err: a.rul_pred - a.true_rul_at_end, final: true, cycle: a.pred_cycle };
  if (a.true_rul !== null) return { err: a.rul_pred - a.true_rul, final: false, cycle: a.pred_cycle };
  return null;
}

function SummaryTab({ a, cursor }: { a: AssetT; cursor: number | null }) {
  const preds = usePredictions(a.asset_id);
  const alerts = useAlerts({ asset: a.asset_id, limit: "200" });
  const diag = useDiagnostics(a.asset_id);
  const sensors = useSensors(a.asset_id);
  const models = useModels();
  const cap = models.data?.items.find((m) => m.profile === a.profile)?.cap ?? 125;
  const warming = a.rul_pred === null;
  const eta = !warming && a.expected_interval_s ? (a.rul_pred as number) * a.expected_interval_s : null;
  const gt = groundTruthError(a);
  const meta = Object.fromEntries((sensors.data?.sensors ?? []).map((m) => [m.symbol, m]));
  const lifeAlerts = (alerts.data?.items ?? []).filter((x) => x.life_id === a.life_id);
  return (
    <div className={s.summary}>
      <div className={s.stack}>
        <div className={`card ${s.heroCard}`}>
          <div>
            <h3>Remaining useful life</h3>
            {warming ? (
              <p style={{ font: "var(--type-h2)", marginTop: 8 }}>Collecting baseline</p>
            ) : (
              <>
                <div className={s.hero}>{fmtRul(a.rul_pred)} <span className="unit" style={{ font: "var(--type-h2)" }}>cycles</span></div>
                <div className="muted num">P10–P90: {fmtRul(a.rul_p10)}–{fmtRul(a.rul_p90)} cycles</div>
                <p style={{ marginTop: 8 }}>
                  Estimated failure in ~{fmtRul(a.rul_pred)} cycles
                  {eta !== null ? ` (~${new Date(Date.now() + eta * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} at the current stream rate)` : ""}.
                </p>
                {a.state === "OFFLINE" ? <p className="muted">Asset is offline: this is the last prediction (stale).</p> : null}
              </>
            )}
          </div>
          <HealthGauge value={a.health_index} />
        </div>
        <div className="card">
          <header><h3>RUL trend</h3><span className="muted" style={{ font: "var(--type-small)" }}>Warning ≤ {THRESHOLDS.warning} · Critical ≤ {THRESHOLDS.critical}</span></header>
          {preds.isPending ? <Loading rows={1} h={300} /> : <RulTrendChart predictions={preds.data?.items ?? []} alerts={lifeAlerts} cursorCycle={cursor} cap={cap} />}
        </div>
      </div>
      <div className={s.stack}>
        {gt ? (
          <div className={`card ${s.gt}`} data-testid="gt-card">
            <h3>Ground truth (replay)</h3>
            <p style={{ font: "var(--type-h2)" }} className="num">
              {gt.final ? "Final-cycle error" : `Error at cycle ${gt.cycle}`}: {gt.err >= 0 ? "+" : ""}{Math.round(gt.err)} cycles
            </p>
            <p className="muted">{Math.round(gt.err) === 0 ? "Exact." : gt.err > 0 ? "Predicted later than true (late)." : "Predicted earlier than true (early, the safe side)."}</p>
            {(a.true_rul ?? 0) > cap ? <p className="muted">True RUL is above the {cap}-cycle cap the model predicts up to.</p> : null}
          </div>
        ) : null}
        <div className="card">
          <header><h3>Latest flags</h3></header>
          <FlagList flags={a.flags.filter((f) => f in FLAG_TEXT)} />
        </div>
        <div className="card">
          <header><h3>Top contributing sensors</h3></header>
          <ContributionList items={diag.data?.latest?.contributors ?? null} meta={meta} />
        </div>
      </div>
    </div>
  );
}

export function orderSensors(h: SensorHistory, showAll: boolean): { meta: SensorMeta; constant: boolean }[] {
  const last = h.items[h.items.length - 1];
  const z = (sym: string) => Math.abs(last?.dev_z[sym] ?? 0);
  const model = h.sensors.filter((m) => h.model_sensors.includes(m.symbol)).sort((a, b) => z(b.symbol) - z(a.symbol));
  const rest = showAll ? h.sensors.filter((m) => !h.model_sensors.includes(m.symbol)) : [];
  return [...model.map((meta) => ({ meta, constant: false })), ...rest.map((meta) => ({ meta, constant: h.constant_sensors.includes(meta.symbol) }))];
}

function SensorsTab({ id }: { id: string }) {
  const q = useSensors(id);
  const [all, setAll] = useState(false);
  if (q.isPending) return <Loading rows={2} h={200} />;
  if (q.isError) return <ErrorCard message={(q.error as Error).message} onRetry={() => void q.refetch()} />;
  const h = q.data;
  if (!h.items.length) return <p className="muted">No telemetry for this life yet.</p>;
  const list = orderSensors(h, all);
  return (
    <div className="card" style={{ display: "grid", gap: 12 }}>
      <header>
        <p className="muted">
          Informative sensors of this profile, ordered by current deviation. Band = healthy baseline (mean ± 3σ of the {h.baseline_source === "asset" ? "asset's first 20 cycles" : "training fleet (fewer than 20 cycles so far)"}, per operating regime). Orange dots: |z| &gt; 3.
        </p>
        <label style={{ display: "flex", gap: 8, alignItems: "center", flexDirection: "row" }}>
          <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> Show all 21 sensors
        </label>
      </header>
      <div className={cs.multiples}>
        {list.map(({ meta, constant }) => <SensorSmall key={meta.symbol} meta={meta} rows={h.items} constant={constant} syncId="sensors" />)}
      </div>
    </div>
  );
}

function SubsystemsTab({ id }: { id: string }) {
  const d = useDiagnostics(id);
  const h = useSensors(id);
  if (d.isPending || h.isPending) return <Loading rows={2} h={160} />;
  if (d.isError) return <ErrorCard message={(d.error as Error).message} onRetry={() => void d.refetch()} />;
  const scores = d.data.latest?.subsystem_scores ?? {};
  const meta = Object.fromEntries((h.data?.sensors ?? []).map((m) => [m.symbol, m]));
  return (
    <div className={s.subs}>
      <div className={s.stack}>
        <p className={s.disclaimer} role="note">Indicative deviation analysis, not a confirmed root cause.</p>
        <div className="card"><header><h3>Engine stations</h3></header><SubsystemStrip scores={scores} /></div>
        <div className="card"><header><h3>Deviation score</h3><span className="muted" style={{ font: "var(--type-small)" }}>0–100 · &lt;40 normal · 40–70 elevated · &gt;70 high</span></header><SubsystemBar scores={scores} /></div>
        <div className="card"><header><h3>Top contributing sensors</h3></header><ContributionList items={d.data.latest?.contributors ?? null} meta={meta} /></div>
      </div>
      <SubsystemSensors d={d.data} h={h.data} />
    </div>
  );
}

function SubsystemSensors({ d, h }: { d: Diagnostics; h?: SensorHistory }) {
  const last = h?.items[h.items.length - 1];
  const bySub = useMemo(() => {
    const m: Record<string, string[]> = {};
    Object.entries(d.sensor_subsystem).forEach(([sym, sub]) => sub && (m[sub] ??= []).push(sym));
    return m;
  }, [d.sensor_subsystem]);
  return (
    <div className="card" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: 8, alignContent: "start" }}>
      <header><h3>Sensors by subsystem</h3></header>
      {[...SUBSYSTEMS, "Engine"].filter((k) => bySub[k]).map((k) => (
        <details key={k} open={(d.latest?.subsystem_scores?.[k] ?? 0) >= 40}>
          <summary style={{ font: "var(--type-body)", color: "var(--text-primary)", fontWeight: 600 }}>
            {k} <span className="muted num">· score {d.latest?.subsystem_scores?.[k]?.toFixed(0) ?? "n/a"}</span>
          </summary>
          <div style={{ overflowX: "auto" }} tabIndex={0} role="region" aria-label={`${k} sensors`}><table>
            <thead><tr><th scope="col">Sensor</th><th scope="col" className="r">Value</th><th scope="col" className="r">Baseline</th><th scope="col" className="r">z</th></tr></thead>
            <tbody>
              {bySub[k].map((sym) => {
                const band = last?.band[sym];
                const z = last?.dev_z[sym];
                return (
                  <tr key={sym}>
                    <td style={{ whiteSpace: "normal" }}><span className="mono">{sym}</span> <span className="muted">{h?.sensors.find((m) => m.symbol === sym)?.description}</span></td>
                    <td className="r">{fmtSensor(sym, last?.raw[sym])} {d.units[sym] && d.units[sym] !== "-" ? <span className="unit">{d.units[sym]}</span> : null}</td>
                    <td className="r muted">{band ? `${fmtSensor(sym, (band[0] + band[1]) / 2)} ± ${fmtSensor(sym, (band[1] - band[0]) / 2)}` : "—"}</td>
                    <td className="r" style={{ color: z !== undefined && Math.abs(z) > 3 ? "var(--state-warning-text)" : undefined }}>{z === undefined ? "—" : z.toFixed(1)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table></div>
        </details>
      ))}
      <p className="muted" style={{ font: "var(--type-small)" }}>{d.note}</p>
    </div>
  );
}

function AlertsTab({ id }: { id: string }) {
  const q = useAlerts({ asset: id, limit: "500" });
  const ack = useAckAlert();
  const disabled = useActionsDisabled();
  if (q.isPending) return <Loading rows={1} h={200} />;
  if (q.isError) return <ErrorCard message={(q.error as Error).message} onRetry={() => void q.refetch()} />;
  if (!q.data.items.length) return <div className="card"><p className="muted">No alerts for this asset.</p></div>;
  return (
    <div className="card table-wrap" style={{ maxHeight: "none" }} tabIndex={0} role="region" aria-label={`Alert history for ${id}`}>
      <table>
        <caption className="sr-only">Alert history for {id}</caption>
        <thead><tr><th scope="col">Time</th><th scope="col">Life</th><th scope="col" className="r">Cycle</th><th scope="col">Transition</th><th scope="col" className="r">RUL</th><th scope="col">Acknowledged</th></tr></thead>
        <tbody>
          {q.data.items.map((a) => (
            <tr key={a.alert_id}>
              <td title={absTime(a.created_at)}>{absTime(a.created_at)}</td>
              <td className="num">{a.life_id}</td>
              <td className="r">{a.cycle}</td>
              <td><StateChip state={a.from_state} /> → <StateChip state={a.to_state} /></td>
              <td className="r">{fmtRul(a.rul_pred)}</td>
              <td>{a.acknowledged_at ? <span className="muted">{a.acknowledged_by ?? "yes"} · {absTime(a.acknowledged_at)}</span> : <button disabled={disabled} onClick={() => ack.mutate(a.alert_id)}>Acknowledge</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function testMetrics(m: ModelInfo): { rmse?: number; score?: number; basis?: string; rmseCapped?: number; scoreCapped?: number } {
  const t = (m.test ?? {}) as Record<string, unknown>;
  const n = (k: string) => (typeof t[k] === "number" ? (t[k] as number) : undefined);
  return { rmse: n("rmse"), score: n("nasa_score"), basis: typeof t.target_basis === "string" ? t.target_basis : undefined, rmseCapped: n("rmse_capped125"), scoreCapped: n("nasa_score_capped125") };
}

function ModelTab({ a }: { a: AssetT }) {
  const models = useModels();
  if (models.isPending) return <Loading rows={1} h={200} />;
  const m = models.data?.items.find((x) => x.profile === a.profile);
  if (!m) return <div className="card"><p className="muted">No model loaded for {a.profile}.</p></div>;
  const t = testMetrics(m);
  const width = a.rul_p10 !== null && a.rul_p90 !== null ? a.rul_p90 - a.rul_p10 : null;
  return (
    <div className={s.subs}>
      <div className="card">
        <header><h3>Model</h3><Link to="/about/model">Full model card</Link></header>
        <dl className={s.kv}>
          <dt>Version</dt><dd className="mono">{m.model_version}</dd>
          <dt>Profile</dt><dd>{m.profile}</dd>
          <dt>Point estimate</dt><dd>{m.point_estimate}</dd>
          <dt>Trained</dt><dd>{m.created_utc ? absTime(m.created_utc) : "—"}</dd>
          <dt>Test RMSE</dt><dd>{t.rmse?.toFixed(2) ?? "—"}{t.rmseCapped !== undefined ? ` (truth capped at 125: ${t.rmseCapped.toFixed(2)})` : ""}</dd>
          <dt>NASA score</dt><dd>{t.score?.toFixed(0) ?? "—"}{t.scoreCapped !== undefined ? ` (capped: ${t.scoreCapped.toFixed(0)})` : ""}</dd>
          <dt>Target basis</dt><dd>{t.basis ?? "—"}</dd>
          <dt>Window</dt><dd>{m.window} cycles</dd>
          <dt>Sensors used</dt><dd className="mono" style={{ whiteSpace: "normal" }}>{m.sensors_used.join(", ")}</dd>
          <dt>Features</dt><dd>{m.feature_names.length}</dd>
        </dl>
      </div>
      <div className="card">
        <header><h3>Confidence &amp; drift (latest prediction)</h3></header>
        <dl className={s.kv}>
          <dt>Interval width</dt><dd>{width === null ? "—" : `${Math.round(width)} cycles`} <span className="muted">(low confidence above 60)</span></dd>
          <dt>Low confidence</dt><dd>{a.flags.includes("LOW_CONFIDENCE") ? "Yes" : "No"}</dd>
          <dt>Out of distribution</dt><dd>{a.flags.includes("OOD") ? "Yes" : "No"} <span className="muted">(sensor outside training range)</span></dd>
          <dt>Drift</dt><dd>{a.flags.includes("DRIFT") ? "Yes" : "No"} <span className="muted">(KS &gt; 0.3 on ≥ 3 sensors while RUL ≥ 100)</span></dd>
          <dt>Interval calibration</dt><dd>{m.conformal_q !== null ? `split-conformal ±${m.conformal_q.toFixed(1)} cycles` : "—"}</dd>
          <dt>Alert thresholds</dt><dd>Warning ≤ {THRESHOLDS.warning}, Critical ≤ {THRESHOLDS.critical} cycles</dd>
          <dt>State</dt><dd>{stateMeta(a.state).label}</dd>
        </dl>
      </div>
    </div>
  );
}
