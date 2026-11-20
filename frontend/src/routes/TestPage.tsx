import { CheckCircle2, Pause, Play, Square, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useDeadLetter, useDevices, useEvaluation, useHarnessCheck, useLastTelemetry, useReplay, useReplayAction, useStats } from "../api/queries";
import type { HarnessResult, Stats } from "../api/schemas";
import { StateChip } from "../components/StateChip";
import { ErrorCard, Loading } from "../components/States";
import ui from "../components/ui.module.css";
import { useNow } from "../hooks/live";
import { absTime, relTime } from "../lib/format";
import { PROFILES } from "../lib/states";
import { PageHead, useActionsDisabled } from "./Shell";
import s from "./test.module.css";

const REPLAY_TOKEN: Record<string, string> = { IDLE: "offline", RUNNING: "healthy", PAUSED: "warning", COMPLETED: "warming", ERROR: "critical", STOPPED: "offline" };
export const SPEED_MIN = 0.5;
export const SPEED_MAX = 50;
/** log-scale slider: position 0..100 <-> 0.5..50 cycles/s */
export const posToSpeed = (p: number) => Math.round(SPEED_MIN * (SPEED_MAX / SPEED_MIN) ** (p / 100) * 10) / 10;
export const speedToPos = (v: number) => (100 * Math.log(v / SPEED_MIN)) / Math.log(SPEED_MAX / SPEED_MIN);

export function parseUnits(text: string): number[] | null {
  const out = new Set<number>();
  for (const part of text.split(",").map((x) => x.trim()).filter(Boolean)) {
    const m = part.match(/^(\d+)(?:\s*-\s*(\d+))?$/);
    if (!m) return null;
    const a = Number(m[1]);
    const b = m[2] ? Number(m[2]) : a;
    if (b < a || b - a > 300) return null;
    for (let u = a; u <= b; u++) out.add(u);
  }
  return out.size ? [...out].sort((x, y) => x - y) : null;
}

export function TestPage() {
  return (
    <>
      <PageHead title="Test & simulation" />
      <div className={s.grid}>
        <ReplayPanel />
        <IngestHealth />
        <DevicesPanel />
        <BatchEval />
      </div>
      <SetupHelp />
    </>
  );
}

function ReplayPanel() {
  const status = useReplay();
  const act = useReplayAction();
  const disabled = useActionsDisabled();
  const [profile, setProfile] = useState("FD001");
  const [split, setSplit] = useState<"test" | "train">("test");
  const [mode, setMode] = useState<"units" | "all" | "random">("units");
  const [units, setUnits] = useState("34");
  const [randomN, setRandomN] = useState(10);
  const [pos, setPos] = useState(speedToPos(5));
  const [transport, setTransport] = useState<"internal" | "mqtt" | "http">("internal");
  const [loop, setLoop] = useState(false);
  const speed = posToSpeed(pos);
  const st = status.data?.state ?? "IDLE";
  const running = st === "RUNNING" || st === "PAUSED";
  const parsed = mode === "units" ? parseUnits(units) : null;
  const invalid = mode === "units" && parsed === null;
  const start = () =>
    act.mutate({ action: "start", body: { profile, split, speed_cps: speed, loop, transport, units: mode === "units" ? parsed : null, random_n: mode === "random" ? randomN : null } });
  const stats = status.data?.stats;
  const progress = Object.entries(stats?.progress ?? {});
  return (
    <section className="card" aria-labelledby="replay-h" style={{ display: "grid", gap: 16 }}>
      <header>
        <h2 id="replay-h">Dataset replay (Mode 1)</h2>
        <span className={`${ui.chip} ${ui[REPLAY_TOKEN[st] ?? "offline"]}`} role="status" data-testid="replay-state">{st}</span>
      </header>
      <fieldset disabled={running || disabled} style={{ border: 0, padding: 0, margin: 0 }}>
        <legend className="sr-only">Replay settings</legend>
        <div className={s.form}>
          <label>Profile<select value={profile} onChange={(e) => setProfile(e.target.value)}>{PROFILES.map((p) => <option key={p}>{p}</option>)}</select></label>
          <label>Split<select value={split} onChange={(e) => setSplit(e.target.value as "test" | "train")}><option value="test">test</option><option value="train">train</option></select></label>
          <label>Units<select value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}><option value="units">Pick units</option><option value="all">All units</option><option value="random">Random N</option></select></label>
          {mode === "units" ? (
            <label>Unit numbers<input value={units} onChange={(e) => setUnits(e.target.value)} placeholder="e.g. 1, 5, 30-34" aria-invalid={invalid} /></label>
          ) : mode === "random" ? (
            <label>N<input type="number" min={1} max={260} value={randomN} onChange={(e) => setRandomN(Number(e.target.value))} /></label>
          ) : <span />}
          <label className={s.wide}>Speed: <strong className="num">{speed} cycles/s</strong>
            <input type="range" min={0} max={100} step={1} value={pos} onChange={(e) => setPos(Number(e.target.value))} aria-valuetext={`${speed} cycles per second`} />
          </label>
          <label>Transport<select value={transport} onChange={(e) => setTransport(e.target.value as typeof transport)}>
            <option value="internal">In-process</option><option value="mqtt">MQTT (same path as devices)</option><option value="http">HTTP /ingest</option></select></label>
          <label className={s.check}><input type="checkbox" checked={loop} onChange={(e) => setLoop(e.target.checked)} /> Loop</label>
        </div>
        {invalid ? <p style={{ color: "var(--state-critical-text)" }} role="alert">Enter unit numbers like 1, 5, 30-34.</p> : null}
      </fieldset>
      <div className={s.controls}>
        <button className="primary" onClick={start} disabled={running || invalid || disabled || act.isPending}><Play size={16} aria-hidden="true" /> Start replay</button>
        {st === "PAUSED" ? (
          <button onClick={() => act.mutate({ action: "resume" })} disabled={disabled}><Play size={16} aria-hidden="true" /> Resume</button>
        ) : (
          <button onClick={() => act.mutate({ action: "pause" })} disabled={st !== "RUNNING" || disabled}><Pause size={16} aria-hidden="true" /> Pause</button>
        )}
        <button onClick={() => act.mutate({ action: "stop" })} disabled={!running || disabled}><Square size={16} aria-hidden="true" /> Stop</button>
        {act.isError ? <span role="alert" style={{ color: "var(--state-critical-text)" }}>{(act.error as Error).message}</span> : null}
      </div>
      <div className={s.counters}>
        {[["Sent", stats?.sent], ["Accepted", stats?.accepted], ["Rejected", stats?.failed], ["Rate", stats?.rate_msgs_s !== undefined ? `${stats.rate_msgs_s}/s` : undefined]].map(([k, v]) => (
          <div key={k as string} className={s.counter}><span className="muted" style={{ font: "var(--type-small)" }}>{k}</span><strong>{v ?? 0}</strong></div>
        ))}
      </div>
      {stats?.last_error ? <p role="alert" style={{ color: "var(--state-critical-text)" }}>{stats.last_error}</p> : null}
      {progress.length ? (
        <ul className={s.progress} aria-label="Progress per unit">
          {progress.map(([id, p]) => (
            <li key={id}>
              <Link to={`/assets/${encodeURIComponent(id)}`} className="mono">{id}</Link>
              <span className={s.track} role="progressbar" aria-valuemin={0} aria-valuemax={p.of} aria-valuenow={p.cycle} aria-label={`${id} progress`}><span className={s.fill} style={{ width: `${(100 * p.cycle) / p.of}%`, display: "block" }} /></span>
              <span className="num muted">{p.cycle}/{p.of}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

/** Keeps a client-side history of /stats counters to chart accepted/rejected per minute. */
function useRateHistory(stats: Stats | undefined) {
  const hist = useRef<{ t: number; acc: number; rej: number }[]>([]);
  const [, force] = useState(0);
  useEffect(() => {
    if (!stats) return;
    const c = stats.ingest.counts;
    const rej = Object.entries(c).filter(([k]) => k !== "accepted" && k !== "duplicate").reduce((a, [, v]) => a + v, 0);
    hist.current = [...hist.current, { t: Date.now(), acc: c.accepted ?? 0, rej }].slice(-120);
    force((x) => x + 1);
  }, [stats]);
  const h = hist.current;
  const bars: { acc: number; rej: number }[] = [];
  for (let i = 1; i < h.length; i++) {
    const dt = (h[i].t - h[i - 1].t) / 60_000 || 1;
    bars.push({ acc: Math.max(0, (h[i].acc - h[i - 1].acc) / dt), rej: Math.max(0, (h[i].rej - h[i - 1].rej) / dt) });
  }
  return bars.slice(-60);
}

function IngestHealth() {
  const stats = useStats();
  const dl = useDeadLetter();
  const bars = useRateHistory(stats.data);
  const [sel, setSel] = useState<number | null>(null);
  if (stats.isPending) return <section className="card"><Loading rows={2} h={60} /></section>;
  if (stats.isError) return <ErrorCard message={(stats.error as Error).message} />;
  const d = stats.data;
  const max = Math.max(1, ...bars.map((b) => b.acc + b.rej));
  const sample = dl.data?.items.find((x) => x.id === sel) ?? dl.data?.items[0];
  return (
    <section className="card" aria-labelledby="ingest-h" style={{ display: "grid", gap: 12 }}>
      <header>
        <h2 id="ingest-h">Ingest health</h2>
        <span className="muted" style={{ font: "var(--type-small)" }}>MQTT {d.mqtt_connected ? "connected" : "disconnected"} · DB {d.db_ok ? "ok" : "failing"}</span>
      </header>
      <div className={s.counters}>
        <div className={s.counter}><span className="muted" style={{ font: "var(--type-small)" }}>Rate (10 s)</span><strong>{d.ingest.rate_msgs_s_10s}/s</strong></div>
        <div className={s.counter}><span className="muted" style={{ font: "var(--type-small)" }}>p50 latency</span><strong>{d.ingest.latency_ms ? `${Math.round(d.ingest.latency_ms.p50)} ms` : "—"}</strong></div>
        <div className={s.counter}><span className="muted" style={{ font: "var(--type-small)" }}>p95 latency</span><strong>{d.ingest.latency_ms ? `${Math.round(d.ingest.latency_ms.p95)} ms` : "—"}</strong></div>
        <div className={s.counter}><span className="muted" style={{ font: "var(--type-small)" }}>Active / drift</span><strong>{d.active_assets} / {d.drift_assets}</strong></div>
      </div>
      <div>
        <h3>Accepted / rejected per minute (this session)</h3>
        {bars.length < 2 ? <p className="muted">Collecting samples (one every 5 s)…</p> : null}
        <div className={s.rate} role="img" aria-label={bars.length ? `Latest: ${Math.round(bars[bars.length - 1].acc)} accepted and ${Math.round(bars[bars.length - 1].rej)} rejected per minute` : "Collecting samples"}>
          {bars.map((b, i) => (
            <div key={i} className={s.rateBar} style={{ height: "100%" }}>
              <span style={{ height: `${(b.acc / max) * 100}%`, background: "var(--viz-1)" }} />
              <span style={{ height: `${(b.rej / max) * 100}%`, background: "var(--state-critical)" }} />
            </div>
          ))}
        </div>
      </div>
      <div>
        <h3>Top rejection reasons (24 h)</h3>
        {d.dead_letter_24h.length ? (
          <table><tbody>{d.dead_letter_24h.slice(0, 6).map((r) => <tr key={r.reason}><td className="mono">{r.reason}</td><td className="r">{r.n}</td></tr>)}</tbody></table>
        ) : <p className="muted">No rejections in the last 24 h.</p>}
      </div>
      {dl.data?.items.length ? (
        <div style={{ display: "grid", gap: 8 }}>
          <label>Dead-letter sample
            <select value={sample?.id ?? ""} onChange={(e) => setSel(Number(e.target.value))}>
              {dl.data.items.map((x) => <option key={x.id} value={x.id}>{absTime(x.received_at)} · {x.reason} · {x.asset_id ?? "unknown asset"}</option>)}
            </select>
          </label>
          {sample ? <><p className="muted">{sample.transport} {sample.topic ?? ""} — {sample.detail}</p><pre className={s.pre}>{sample.raw}{sample.raw_truncated ? "\n…(truncated)" : ""}</pre></> : null}
        </div>
      ) : null}
    </section>
  );
}

function DevicesPanel() {
  const devices = useDevices();
  const check = useHarnessCheck();
  const disabled = useActionsDisabled();
  const now = useNow(2000);
  const [sel, setSel] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, HarnessResult>>({});
  const last = useLastTelemetry(sel);
  const items = devices.data?.items ?? [];
  const run = (id: string) => check.mutate(id, { onSuccess: (r) => setResults((x) => ({ ...x, [id]: r })) });
  return (
    <section className={`card ${s.full}`} id="esp32" aria-labelledby="dev-h" style={{ display: "grid", gap: 12 }}>
      <header><h2 id="dev-h">ESP32 devices (Mode 2)</h2></header>
      {devices.isPending ? <Loading rows={1} h={80} /> : !items.length ? (
        <p className="muted">No ESP32 or virtual ESP32 has sent data yet. Flash the board (see setup help below) or run <code>make harness</code> for a virtual one.</p>
      ) : (
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Devices">
          <table>
            <caption className="sr-only">Devices</caption>
            <thead><tr><th scope="col">Device</th><th scope="col">State</th><th scope="col">Firmware</th><th scope="col" className="r">RSSI</th><th scope="col">IP</th><th scope="col" className="r">Rate</th><th scope="col" className="r">Seq gaps</th><th scope="col" className="r">Latency p50/p95</th><th scope="col">Last seen</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>
              {items.map((d) => {
                const r = results[d.device_id];
                const lat = r?.checks.find((c) => c.check === "latency")?.detail as { p50?: number; p95?: number } | undefined;
                const seq = r?.checks.find((c) => c.check === "sequence");
                return (
                  <tr key={d.device_id} aria-selected={sel === d.device_id}>
                    <td className="mono"><button className="ghost" onClick={() => setSel(d.device_id)} style={{ fontFamily: "var(--font-mono)", padding: 0 }}>{d.device_id}</button></td>
                    <td>{d.state ? <StateChip state={d.state} /> : d.online ? "online" : "—"}</td>
                    <td>{d.fw ?? "—"}</td>
                    <td className="r">{d.rssi ?? "—"}{d.rssi !== null ? <span className="unit"> dBm</span> : null}</td>
                    <td className="mono">{d.ip ?? "—"}</td>
                    <td className="r">{r ? `${r.rate_msgs_s}/s` : "—"}</td>
                    <td className="r">{seq ? (seq.ok ? "0" : String(seq.detail)) : "—"}</td>
                    <td className="r">{lat && typeof lat === "object" ? `${lat.p50} / ${lat.p95} ms` : "—"}</td>
                    <td title={absTime(d.last_seen_at)}>{relTime(d.last_seen_at ?? d.last_status_at, now)}</td>
                    <td><button onClick={() => run(d.device_id)} disabled={disabled || (check.isPending && check.variables === d.device_id) || !d.asset_id}>Run harness checks</button></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {Object.entries(results).map(([id, r]) => (
        <div key={id} data-testid="harness-result">
          <h3>Harness checks · <span className="mono">{id}</span> · {r.passed ? "PASS" : "FAIL"} ({r.window} messages)</h3>
          <ul className={s.checks}>
            {r.checks.map((c) => (
              <li key={c.check}>
                {c.ok ? <CheckCircle2 size={18} color="var(--state-healthy)" aria-label="passed" /> : <XCircle size={18} color="var(--state-critical)" aria-label="failed" />}
                <strong>{c.check}</strong>
                <span className="muted">{typeof c.detail === "string" ? c.detail : JSON.stringify(c.detail)}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
      {check.isError ? <p role="alert" style={{ color: "var(--state-critical-text)" }}>{(check.error as Error).message}</p> : null}
      {sel ? (
        <div>
          <h3>Last payload · <span className="mono">{sel}</span></h3>
          <pre className={s.pre}>{last.data?.items[0] ? JSON.stringify(last.data.items[0], null, 2) : "No telemetry stored for this device."}</pre>
        </div>
      ) : null}
    </section>
  );
}

function BatchEval() {
  const q = useEvaluation();
  return (
    <section className="card" aria-labelledby="eval-h" style={{ display: "grid", gap: 12 }}>
      <header>
        <h2 id="eval-h">Batch evaluation (official test split)</h2>
        <span className="muted" style={{ font: "var(--type-small)" }}>Generated by <code>make evaluate</code></span>
      </header>
      {q.isPending ? <Loading rows={1} h={120} /> : q.isError ? <ErrorCard message={(q.error as Error).message} /> : !q.data.items.length ? <p className="muted">No evaluation report yet. Run <code>make evaluate</code>.</p> : (
        <div className={s.evalGrid}>
          {q.data.items.map((e) => {
            const capped = e.target_basis?.includes("capped");
            const rmse = capped ? e.rmse_capped125 ?? e.rmse : e.rmse;
            const score = capped ? e.nasa_score_capped125 ?? e.nasa_score : e.nasa_score;
            return (
              <div key={e.profile} style={{ display: "grid", gap: 6 }}>
                <strong>{e.profile} <span className="muted mono" style={{ fontWeight: 400 }}>{e.model_version}</span></strong>
                <span className="num">RMSE {rmse.toFixed(2)} {e.targets ? `(target ≤ ${e.targets.rmse}) ${e.meets_rmse_target ? "✓" : "✗"}` : ""}</span>
                <span className="num">NASA score {score.toFixed(0)} {e.targets ? `(≤ ${e.targets.nasa_score}) ${e.meets_score_target ? "✓" : "✗"}` : ""}</span>
                <span className="muted" style={{ font: "var(--type-small)" }}>{e.n} engines · {e.target_basis} · {absTime(e.generated)}</span>
                {e.confusion ? (
                  <table className={s.conf}>
                    <caption className="sr-only">Alert confusion matrix for {e.profile}</caption>
                    <thead><tr><th scope="col">true ↓ / pred →</th>{q.data.labels.map((l) => <th key={l} scope="col">{l.slice(0, 4)}</th>)}</tr></thead>
                    <tbody>{q.data.labels.map((l) => <tr key={l}><th scope="row">{l}</th>{(e.confusion?.[l] ?? []).map((v, i) => <td key={i}>{v}</td>)}</tr>)}</tbody>
                  </table>
                ) : null}
                <span className="muted mono" style={{ font: "var(--type-small)" }}>{e.report}</span>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

function SetupHelp() {
  return (
    <details className="card">
      <summary style={{ font: "var(--type-h2)", color: "var(--text-primary)" }}>Setup help: flash an ESP32</summary>
      <ol style={{ display: "grid", gap: 6, marginTop: 12 }}>
        <li>Install PlatformIO and connect an ESP32 DevKit V1 over USB.</li>
        <li>Copy <code>iot/esp32/include/config.example.h</code> to <code>config.h</code> and fill in Wi-Fi, broker host and the device's MQTT password.</li>
        <li>Add the device to the broker password file: <code>make passwd</code>.</li>
        <li>Build and flash: <code>make esp32-build</code>, then <code>pio run -t upload -d iot/esp32</code>.</li>
        <li>The board appears in the device list above with an ESP32 badge. Click "Run harness checks" after a minute of data.</li>
      </ol>
      <p style={{ marginTop: 8 }}>Full guide: <a href="https://github.com/I-yasir/iot-predictive-maintenance/blob/main/iot/esp32/README.md" target="_blank" rel="noreferrer">iot/esp32/README.md</a></p>
    </details>
  );
}
