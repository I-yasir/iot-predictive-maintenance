import { useEffect, useState } from "react";
import { StateChip } from "../components/StateChip";
import { contrast } from "../lib/contrast";
import { STATE_META } from "../lib/states";
import { PageHead } from "./Shell";

const SURFACES = ["--bg", "--surface-1", "--surface-2"];
const TEXT = ["--text-primary", "--text-secondary", "--accent"];
const VIZ = ["--viz-1", "--viz-2", "--viz-3", "--viz-4", "--viz-5", "--viz-6"];

function read(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** P4.1 token story page: every state color with its measured contrast in the active theme. */
export function Tokens() {
  const [, tick] = useState(0);
  useEffect(() => {
    const o = new MutationObserver(() => tick((x) => x + 1));
    o.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => o.disconnect();
  }, []);
  const tokens = [...new Set(Object.values(STATE_META).map((m) => m.token))];
  return (
    <>
      <PageHead title="Design tokens" />
      <p className="muted">Measured in the current theme (toggle in the top bar). Text needs 4.5:1, icons and borders 3:1.</p>
      <section className="card">
        <header><h3>States</h3></header>
        <table>
          <thead><tr><th>State</th><th>Chip</th><th className="r">Label on tint (card)</th><th className="r">Label on tint (raised)</th><th className="r">Icon on card</th></tr></thead>
          <tbody>
            {tokens.map((t) => {
              const fg = read(`--state-${t}-text`);
              const bg = read(`--state-${t}-bg`) || "#00000000";
              const ok = (v: number, min: number) => <span style={{ color: v >= min ? "var(--state-healthy-text)" : "var(--state-critical-text)" }}>{v.toFixed(2)} {v >= min ? "pass" : "FAIL"}</span>;
              const safeBg = bg === "transparent" ? "#00000000" : bg;
              const state = Object.entries(STATE_META).find(([, m]) => m.token === t)?.[0] ?? "NEW";
              return (
                <tr key={t} data-testid={`token-${t}`}>
                  <td className="mono">{t}</td>
                  <td><StateChip state={state} /></td>
                  <td className="r">{ok(contrast(fg, safeBg, read("--surface-1")), 4.5)}</td>
                  <td className="r">{ok(contrast(fg, safeBg, read("--surface-2")), 4.5)}</td>
                  <td className="r">{ok(contrast(read(`--state-${t}`), read("--surface-1")), 3)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
      <section className="card">
        <header><h3>Text on surfaces</h3></header>
        <table>
          <thead><tr><th>Text</th>{SURFACES.map((s) => <th key={s} className="r mono">{s}</th>)}</tr></thead>
          <tbody>{TEXT.map((t) => <tr key={t}><td className="mono" style={{ color: `var(${t})` }}>{t}</td>{SURFACES.map((s) => <td key={s} className="r num">{contrast(read(t), read(s)).toFixed(2)}</td>)}</tr>)}</tbody>
        </table>
      </section>
      <section className="card">
        <header><h3>Data visualization</h3></header>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {VIZ.map((v) => <span key={v} className="mono" style={{ display: "inline-flex", gap: 6, alignItems: "center" }}><i style={{ width: 24, height: 12, background: `var(${v})`, display: "inline-block", borderRadius: 2 }} />{v}</span>)}
        </div>
      </section>
    </>
  );
}
