import { Download, Printer } from "lucide-react";
import { useEffect } from "react";
import { useParams } from "react-router-dom";
import { useReport } from "../api/queries";
import { SUBSYSTEMS } from "../charts/Diagnostics";
import { RulTrendChart } from "../charts/RulTrendChart";
import { ErrorCard, Loading } from "../components/States";
import { absTime, fmtHi, fmtRul } from "../lib/format";
import { stateMeta } from "../lib/states";
import { downloadReport, groundTruthError } from "./AssetDetail";
import s from "./report.module.css";

/** Printable diagnostic report, light theme forced (docs/03 §3.3). */
export function AssetReport() {
  const { assetId = "" } = useParams();
  const q = useReport(assetId);
  useEffect(() => {
    const el = document.documentElement;
    const prev = el.dataset.theme;
    el.dataset.theme = "light";
    return () => {
      if (prev) el.dataset.theme = prev;
    };
  }, []);
  if (q.isPending) return <div style={{ padding: 24 }}><Loading rows={3} /></div>;
  if (q.isError) return <div style={{ padding: 24 }}><ErrorCard message={(q.error as Error).message} onRetry={() => void q.refetch()} /></div>;
  const { asset: a, diagnostics: d, predictions, alerts, model } = q.data;
  const life = predictions;
  const gt = groundTruthError(a);
  const contrib = d.latest?.contributors ?? [];
  const scores = d.latest?.subsystem_scores ?? {};
  return (
    <article className={s.page} data-testid="printable-report">
      <div className={s.toolbar}>
        <button onClick={() => void downloadReport(a.asset_id)}><Download size={16} aria-hidden="true" /> Export JSON</button>
        <button className="primary" onClick={() => window.print()}><Printer size={16} aria-hidden="true" /> Print</button>
      </div>
      <header className={s.head}>
        <div>
          <h1>Diagnostic report · <span className="mono">{a.asset_id}</span></h1>
          <p>Profile {a.profile} · source {a.source} · life {a.life_id} · cycle {a.last_cycle ?? "—"}</p>
        </div>
        <div style={{ textAlign: "right", fontSize: 12 }}>
          <div>Generated {new Date().toLocaleString()}</div>
          <div>Model <span className="mono">{String(model?.model_version ?? d.latest?.model_version ?? "—")}</span></div>
        </div>
      </header>
      <section className={s.nums}>
        <div className={s.num}>State<strong>{stateMeta(a.state).label}</strong></div>
        <div className={s.num}>RUL (cycles)<strong>{fmtRul(a.rul_pred)}</strong>P10–P90 {fmtRul(a.rul_p10)}–{fmtRul(a.rul_p90)}</div>
        <div className={s.num}>Health index<strong>{fmtHi(a.health_index)}</strong></div>
        <div className={s.num}>{gt ? (gt.final ? "Final-cycle error" : "Current error") : "Ground truth"}<strong>{gt ? `${gt.err >= 0 ? "+" : ""}${Math.round(gt.err)}` : "n/a"}</strong>{gt ? "cycles (pred − true)" : "not a replay unit"}</div>
      </section>
      <section>
        <h2>RUL trend</h2>
        <RulTrendChart predictions={life} alerts={alerts.filter((x) => x.life_id === a.life_id)} height={260} />
      </section>
      <section>
        <h2>Top contributing sensors</h2>
        {contrib.length ? (
          <table><thead><tr><th>Sensor</th><th>Direction vs baseline</th><th>Effect on RUL</th><th className="r">Share</th></tr></thead>
            <tbody>{contrib.map((c) => <tr key={c.sensor}><td className="mono">{c.sensor}</td><td>{c.direction === "up" ? "above" : "below"}</td><td>{c.effect_on_rul}</td><td className="r">{c.pct.toFixed(0)}%</td></tr>)}</tbody></table>
        ) : <p>No contributions yet.</p>}
      </section>
      <section>
        <h2>Subsystem deviation</h2>
        <table><thead><tr><th>Subsystem</th><th className="r">Score (0–100)</th></tr></thead>
          <tbody>{[...SUBSYSTEMS, "Engine"].filter((k) => scores[k] !== undefined).map((k) => <tr key={k}><td>{k}</td><td className="r">{scores[k].toFixed(0)}</td></tr>)}</tbody></table>
      </section>
      <section>
        <h2>Alert history</h2>
        {alerts.length ? (
          <table><thead><tr><th>Time</th><th className="r">Cycle</th><th>Transition</th><th className="r">RUL</th><th>Ack</th></tr></thead>
            <tbody>{alerts.map((x) => <tr key={x.alert_id}><td>{absTime(x.created_at)}</td><td className="r">{x.cycle}</td><td>{stateMeta(x.from_state).label} → {stateMeta(x.to_state).label}</td><td className="r">{fmtRul(x.rul_pred)}</td><td>{x.acknowledged_at ? "yes" : "no"}</td></tr>)}</tbody></table>
        ) : <p>No alerts.</p>}
      </section>
      <footer className={s.foot}>
        {d.note} Subsystem scores are an indicative deviation analysis, not a confirmed root cause. RUL is predicted in engine cycles from NASA C-MAPSS-trained models; intervals are split-conformal calibrated P10–P90.
      </footer>
    </article>
  );
}
