import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { contrast } from "./contrast";

const css = readFileSync(resolve(__dirname, "../styles/tokens.css"), "utf8");

function block(selector: string): Record<string, string> {
  const start = css.indexOf(selector + " {");
  const body = css.slice(start, css.indexOf("}", start));
  return Object.fromEntries([...body.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6,8})/g)].map((m) => [m[1], m[2]]));
}

const dark = block(":root");
const light = { ...dark, ...block(':root[data-theme="light"]') };
const STATES = ["healthy", "warning", "critical", "offline", "degraded"];

describe.each([
  ["dark", dark],
  ["light", light],
])("%s theme tokens", (_name, t) => {
  it("text meets 4.5:1 on every surface", () => {
    for (const s of ["bg", "surface-1", "surface-2"]) {
      expect(contrast(t["text-primary"], t[s])).toBeGreaterThanOrEqual(4.5);
      expect(contrast(t["text-secondary"], t[s])).toBeGreaterThanOrEqual(4.5);
    }
  });
  it.each(STATES)("state %s label meets 4.5:1 on its tint over cards", (st) => {
    for (const s of ["surface-1", "surface-2"]) {
      expect(contrast(t[`state-${st}-text`], t[`state-${st}-bg`], t[s])).toBeGreaterThanOrEqual(4.5);
      expect(contrast(t[`state-${st}`], t[s])).toBeGreaterThanOrEqual(3); // icons/borders: non-text 3:1
    }
  });
  it("accent links and button text meet 4.5:1", () => {
    expect(contrast(t.accent, t["surface-1"])).toBeGreaterThanOrEqual(4.5);
    expect(contrast(t["on-accent"], t.accent)).toBeGreaterThanOrEqual(4.5);
  });
});

it("light and dark override the same tokens", () => {
  const prefers = css.slice(css.indexOf("@media (prefers-color-scheme: light)"));
  for (const k of Object.keys(block(':root[data-theme="light"]'))) expect(prefers).toContain(`--${k}:`);
});
