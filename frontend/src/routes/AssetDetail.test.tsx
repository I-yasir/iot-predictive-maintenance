import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ALERTS, ASSETS, BASE_ROUTES, DIAGNOSTICS, mockFetch, PREDICTIONS, SENSOR_HISTORY } from "../test/fixtures";
import { currentLocation, renderApp } from "../test/render";

const T034 = { ...ASSETS[0], lives: [1], last_rejection: null };
const ROUTES = {
  ...BASE_ROUTES,
  "/assets/FD001-T034": T034,
  "/assets/FD001-T034/predictions": PREDICTIONS,
  "/assets/FD001-T034/diagnostics": DIAGNOSTICS,
  "/assets/FD001-T034/sensors": SENSOR_HISTORY,
  "/alerts": { count: 3, items: ALERTS },
};

describe("Component Detail Report", () => {
  it("US-05: state, RUL ± interval, health gauge, trend chart with ground truth", async () => {
    mockFetch(ROUTES);
    renderApp("/assets/FD001-T034");
    expect(await screen.findByRole("heading", { name: "FD001-T034" })).toBeInTheDocument();
    expect(screen.getAllByText("Critical")[0]).toBeInTheDocument();
    expect(screen.getByText("P10–P90: 8–30 cycles")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Health index 0.14 of 1" })).toBeInTheDocument();
    expect(await screen.findByRole("img", { name: /^RUL decreased from 125 to \d+ cycles over 115 cycles$/ })).toBeInTheDocument();
    expect(screen.getByText("True RUL (replay)")).toBeInTheDocument();
    const gt = screen.getByTestId("gt-card");
    expect(gt).toHaveTextContent("Error at cycle 120: +6 cycles");
    expect(gt).toHaveTextContent("Predicted later than true");
    expect(screen.getByText(/Estimated failure in ~18 cycles/)).toBeInTheDocument();
  });

  it("US-06: sensor tab shows informative sensors ordered by deviation, baseline band and anomalies, all-21 toggle", async () => {
    mockFetch(ROUTES);
    const user = userEvent.setup();
    renderApp("/assets/FD001-T034?tab=sensors");
    const figs = await screen.findAllByTestId(/^sensor-/);
    expect(figs.map((f) => f.dataset.testid)).toEqual(["sensor-T50", "sensor-Ps30", "sensor-P30", "sensor-T30", "sensor-T24", "sensor-phi"]);
    expect(within(figs[0]).getByRole("img", { name: /T50 Total temperature at LPT outlet: latest 1414.50 °R, deviation 4.2 sigma, 4 anomalous cycles shown/ })).toBeInTheDocument();
    expect(screen.getByText(/asset's first 20 cycles/)).toBeInTheDocument();
    await user.click(screen.getByLabelText("Show all 21 sensors"));
    expect(within(screen.getByTestId("sensor-T2")).getByText(/Constant in this profile/)).toBeInTheDocument();
  });

  it("US-07: subsystem panel with stations, sorted deviation bars, top-3 contributors and disclaimer", async () => {
    mockFetch(ROUTES);
    renderApp("/assets/FD001-T034?tab=subsystems");
    expect(await screen.findByRole("note")).toHaveTextContent("Indicative deviation analysis, not a confirmed root cause.");
    const stations = screen.getByRole("list", { name: "Engine stations from inlet to exhaust" });
    expect(within(stations).getAllByRole("listitem").map((x) => x.textContent)).toEqual(["Fan21", "LPC12", "HPC55", "Burner31", "HPT10", "LPT78"]);
    const meters = screen.getAllByRole("meter");
    expect(meters.map((m) => m.getAttribute("aria-label"))).toEqual(["LPT deviation score", "HPC deviation score", "Burner deviation score", "Fan deviation score", "LPC deviation score", "HPT deviation score"]);
    const contrib = screen.getAllByRole("list").find((l) => l.tagName === "OL")!;
    expect(within(contrib).getAllByRole("listitem").map((x) => x.textContent?.slice(0, 4))).toEqual(["T50T", "Ps30", "phiR"]);
    expect(within(contrib).getAllByText(/above baseline · lowers RUL/)).toHaveLength(2);
    expect(within(contrib).getByText(/below baseline · lowers RUL/)).toBeInTheDocument();
  });

  it("US-08: alert history with acknowledge, and model version with confidence/drift flags", async () => {
    const calls = mockFetch({ ...ROUTES, "POST /alerts/3/ack": { ...ALERTS[0], acknowledged_at: new Date().toISOString(), acknowledged_by: "dashboard" } });
    const user = userEvent.setup();
    renderApp("/assets/FD001-T034?tab=alerts");
    const table = await screen.findByRole("table", { name: "Alert history for FD001-T034" });
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    await user.click(within(table).getAllByRole("button", { name: "Acknowledge" })[0]);
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/alerts/3/ack")).toBe(true));
    await user.click(screen.getByRole("tab", { name: "Model" }));
    expect(currentLocation).toBe("/assets/FD001-T034?tab=model");
    expect(await screen.findByText("20261120-p3")).toBeInTheDocument();
    expect(screen.getByText("14.23")).toBeInTheDocument();
    expect(screen.getByText(/Low confidence/)).toBeInTheDocument();
    expect(screen.getByText(/KS > 0.3 on ≥ 3 sensors/)).toBeInTheDocument();
  });

  it("US-09: exports the report as JSON and opens the printable page", async () => {
    const report = { asset: T034, diagnostics: DIAGNOSTICS, predictions: PREDICTIONS.items, alerts: ALERTS, model: { model_version: "20261120-p3" } };
    mockFetch({ ...ROUTES, "/assets/FD001-T034/report": report });
    const created: Blob[] = [];
    URL.createObjectURL = vi.fn((b: Blob) => { created.push(b); return "blob:x"; });
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const user = userEvent.setup();
    renderApp("/assets/FD001-T034");
    await user.click(await screen.findByRole("button", { name: /Export report/ }));
    await waitFor(() => expect(click).toHaveBeenCalled());
    const json = JSON.parse(await new Promise<string>((res) => { const r = new FileReader(); r.onload = () => res(String(r.result)); r.readAsText(created[0]); }));
    expect(created[0].type).toBe("application/json");
    expect(json.asset.asset_id).toBe("FD001-T034");
    expect(json.predictions).toHaveLength(116);
    expect(screen.getByRole("link", { name: /Open printable/ })).toHaveAttribute("href", "/assets/FD001-T034/report");
    click.mockRestore();
  });

  it("US-09: printable report shows summary, contributors, subsystems and alert history", async () => {
    const report = { asset: T034, diagnostics: DIAGNOSTICS, predictions: PREDICTIONS.items, alerts: ALERTS, model: { model_version: "20261120-p3" } };
    mockFetch({ ...ROUTES, "/assets/FD001-T034/report": report });
    renderApp("/assets/FD001-T034/report");
    const page = await screen.findByTestId("printable-report");
    expect(page).toHaveTextContent("Diagnostic report · FD001-T034");
    expect(page).toHaveTextContent("Model 20261120-p3");
    expect(page).toHaveTextContent("LPT78");
    expect(page).toHaveTextContent("Warning → Critical");
    expect(page).toHaveTextContent("not a confirmed root cause");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("keeps the tab when switching component and shows 'Asset not found' for unknown IDs", async () => {
    mockFetch(ROUTES);
    renderApp("/assets/NOPE-1");
    expect(await screen.findByRole("heading", { name: "Asset not found" })).toBeInTheDocument();
    expect(screen.getByRole("combobox")).toBeInTheDocument();
  });

  it("selector switches asset and keeps the current tab", async () => {
    mockFetch({ ...ROUTES, "/assets/FD003-T012": { ...ASSETS[1], lives: [1], last_rejection: null }, "/assets/FD003-T012/sensors": { ...SENSOR_HISTORY, asset_id: "FD003-T012" } });
    const user = userEvent.setup();
    renderApp("/assets/FD001-T034?tab=sensors");
    await screen.findAllByTestId(/^sensor-/);
    await user.click(screen.getByRole("combobox"));
    await user.click(await screen.findByRole("option", { name: /FD003-T012/ }));
    expect(currentLocation).toBe("/assets/FD003-T012?tab=sensors");
  });
});
