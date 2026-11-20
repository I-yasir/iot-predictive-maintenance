import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { BASE_ROUTES, mockFetch } from "../test/fixtures";
import { renderApp } from "../test/render";
import { parseUnits, posToSpeed, speedToPos } from "./TestPage";

const STATS = { ingest: { since: new Date().toISOString(), counts: { accepted: 10 }, rejected_by_reason: {}, rate_msgs_s_10s: 1, latency_ms: { p50: 5, p95: 9, max: 12 } },
  active_assets: 1, drift_assets: 0, dead_letter_24h: [{ reason: "schema", n: 2 }], mqtt_connected: true, db_ok: true };
const ROUTES = {
  ...BASE_ROUTES,
  "/stats": STATS,
  "/dead-letter": { items: [{ id: 1, received_at: new Date().toISOString(), transport: "http", topic: null, asset_id: "X", reason: "schema", detail: "bad", raw: "{oops", raw_truncated: false }] },
  "/devices": { items: [{ device_id: "FD001-E001", asset_id: "FD001-E001", source: "ESP32", state: "HEALTHY", last_seen_at: new Date().toISOString(), last_cycle: 40, fw: "0.3.0", ip: "192.168.1.20", rssi: -61, online: true, last_status_at: null }] },
  "/evaluation": { labels: ["Healthy", "Warning", "Critical"], items: [] },
  "/sim/replay/status": { state: "IDLE", config: null, stats: null },
};

describe("Test & Simulation", () => {
  it("parses unit lists and maps the log-scale speed slider to 0.5–50 cycles/s", () => {
    expect(parseUnits("1, 5, 30-32")).toEqual([1, 5, 30, 31, 32]);
    expect(parseUnits("a")).toBeNull();
    expect(posToSpeed(0)).toBe(0.5);
    expect(posToSpeed(100)).toBe(50);
    expect(posToSpeed(speedToPos(5))).toBe(5);
  });

  it("US-10: starts a replay with the chosen subset, split, units, speed and transport; pause/stop follow the state", async () => {
    let state = "IDLE";
    const calls = mockFetch({
      ...ROUTES,
      "/sim/replay/status": () => ({ state, config: null, stats: null }),
      "POST /sim/replay/start": () => { state = "RUNNING"; return { state, config: {}, stats: { sent: 0, accepted: 0, failed: 0, rate_msgs_s: 0, last_error: null, progress: { "FD002-T003": { cycle: 4, of: 120 } } } }; },
      "POST /sim/replay/pause": () => { state = "PAUSED"; return { state, config: {}, stats: null }; },
      "POST /sim/replay/stop": () => { state = "STOPPED"; return { state, config: {}, stats: null }; },
    });
    const user = userEvent.setup();
    renderApp("/test");
    await screen.findByText("IDLE");
    await user.selectOptions(screen.getByLabelText("Profile"), "FD002");
    await user.selectOptions(screen.getByLabelText("Split"), "train");
    await user.clear(screen.getByLabelText("Unit numbers"));
    await user.type(screen.getByLabelText("Unit numbers"), "3, 7-8");
    await user.selectOptions(screen.getByLabelText("Transport"), "mqtt");
    await user.click(screen.getByRole("button", { name: /Start replay/ }));
    await waitFor(() => expect(screen.getByTestId("replay-state")).toHaveTextContent("RUNNING"));
    const body = JSON.parse(calls.find((c) => c.path === "/sim/replay/start")!.body!);
    expect(body).toMatchObject({ profile: "FD002", split: "train", units: [3, 7, 8], transport: "mqtt", speed_cps: 5 });
    expect(screen.getByRole("progressbar", { name: "FD002-T003 progress" })).toHaveAttribute("aria-valuenow", "4");
    await user.click(screen.getByRole("button", { name: /Pause/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /Resume/ })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /Stop/ }));
    await waitFor(() => expect(screen.getByTestId("replay-state")).toHaveTextContent("STOPPED"));
  });

  it("US-13: runs harness checks for an ESP32 and shows the pass/fail checklist", async () => {
    mockFetch({ ...ROUTES, "POST /devices/FD001-E001/harness-check": { device_id: "FD001-E001", window: 40, rate_msgs_s: 1.0, passed: false,
      checks: [{ check: "schema", ok: true, detail: "40 accepted" }, { check: "sequence", ok: false, detail: "missing seq [12]" }, { check: "latency", ok: true, detail: { p50: 40, p95: 90 } }] } });
    const user = userEvent.setup();
    renderApp("/test");
    const panel = await screen.findByRole("region", { name: "ESP32 devices (Mode 2)" });
    await user.click(await within(panel).findByRole("button", { name: "Run harness checks" }));
    const res = await screen.findByTestId("harness-result");
    expect(res).toHaveTextContent("FAIL (40 messages)");
    expect(within(res).getAllByLabelText("passed")).toHaveLength(2);
    expect(within(res).getByLabelText("failed")).toBeInTheDocument();
    expect(within(panel).getByText("40 / 90 ms")).toBeInTheDocument();
    expect(screen.getByText(/\{oops/)).toBeInTheDocument();
  });
});
