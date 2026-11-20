import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ALERTS, BASE_ROUTES, mockFetch } from "../test/fixtures";
import { currentLocation, renderApp } from "../test/render";

const tiles = () => screen.getAllByTestId("asset-tile");
const tileIds = () => tiles().map((t) => within(t).getByText(/^FD00\d-T\d+$/).textContent);

describe("System Overview", () => {
  it("US-01: each tile shows ID, state (icon + label), RUL with band, last seen and source badge", async () => {
    mockFetch(BASE_ROUTES);
    renderApp("/overview");
    const t = (await screen.findAllByTestId("asset-tile"))[0];
    expect(within(t).getByText("FD001-T034")).toBeInTheDocument();
    expect(within(t).getByText("Critical")).toBeInTheDocument();
    expect(within(t).getByText("18")).toBeInTheDocument();
    expect(within(t).getByText("cycles")).toBeInTheDocument();
    expect(within(t).getByText("[8–30]")).toBeInTheDocument();
    expect(within(t).getByText("REPLAY")).toBeInTheDocument();
    expect(within(t).getByText(/s ago$/)).toBeInTheDocument();
    expect(t).toHaveAttribute("href", "/assets/FD001-T034");
    const esp = tiles().find((x) => within(x).queryByText("FD003-T012"))!;
    expect(within(esp).getByText("ESP32")).toBeInTheDocument();
    const warming = tiles().find((x) => within(x).queryByText("FD001-T099"))!;
    expect(within(warming).getByText("Collecting baseline")).toBeInTheDocument();
    expect(within(warming).getByText(/\(3\/5\)/)).toBeInTheDocument();
    const offline = tiles().find((x) => within(x).queryByText("FD004-T001"))!;
    expect(within(offline).getByText(/stale/)).toBeInTheDocument();
  });

  it("US-02: KPI counts per state and the 5 lowest-RUL assets", async () => {
    mockFetch(BASE_ROUTES);
    renderApp("/overview");
    const kpis = await screen.findByRole("region", { name: "Fleet status" });
    expect(within(kpis).getByRole("button", { name: /^Healthy: 3 assets/ })).toBeInTheDocument();
    expect(within(kpis).getByRole("button", { name: /^Warning: 1 assets/ })).toBeInTheDocument();
    expect(within(kpis).getByRole("button", { name: /^Critical: 1 assets/ })).toBeInTheDocument();
    expect(within(kpis).getByRole("button", { name: /^Offline: 1 assets/ })).toBeInTheDocument();
    expect(within(kpis).getByText("7")).toBeInTheDocument();
    const lowest = screen.getByRole("region", { name: "Lowest RUL" });
    const items = within(lowest).getAllByRole("listitem").map((li) => li.textContent);
    expect(items).toHaveLength(5);
    expect(items[0]).toContain("FD001-T034");
    expect(items[1]).toContain("FD004-T001");
    expect(items[2]).toContain("FD003-T012");
  });

  it("US-03: sorts critical first by default, by RUL on request, and filters by state, profile and source (URL-synced)", async () => {
    mockFetch(BASE_ROUTES);
    const user = userEvent.setup();
    renderApp("/overview");
    await screen.findAllByTestId("asset-tile");
    expect(tileIds().slice(0, 2)).toEqual(["FD001-T034", "FD003-T012"]);
    await user.selectOptions(screen.getByLabelText("Sort"), "rul");
    expect(tileIds().slice(0, 3)).toEqual(["FD001-T034", "FD004-T001", "FD003-T012"]);
    expect(currentLocation).toContain("sort=rul");
    await user.selectOptions(screen.getByLabelText("State"), "HEALTHY");
    expect(tileIds()).toEqual(["FD002-T005", "FD001-T010", "FD002-T077"]);
    await user.selectOptions(screen.getByLabelText("Profile"), "FD002");
    expect(tileIds()).toEqual(["FD002-T005", "FD002-T077"]);
    expect(currentLocation).toMatch(/state=HEALTHY.*profile=FD002|profile=FD002.*state=HEALTHY/);
    await user.selectOptions(screen.getByLabelText("Source"), "ESP32");
    expect(screen.getByText("No assets match these filters.")).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Clear filters" })[0]);
    expect(tiles()).toHaveLength(7);
  });

  it("US-03: clicking a KPI filters to that state", async () => {
    mockFetch(BASE_ROUTES);
    const user = userEvent.setup();
    renderApp("/overview");
    await user.click(await screen.findByRole("button", { name: /^Critical: 1 assets/ }));
    expect(tileIds()).toEqual(["FD001-T034"]);
    expect(currentLocation).toContain("state=CRITICAL");
  });

  it("US-03: table mode lists the same assets", async () => {
    mockFetch(BASE_ROUTES);
    renderApp("/overview?view=table&sort=rul");
    const table = await screen.findByTestId("asset-table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(7);
    expect(rows[0]).toHaveTextContent("FD001-T034");
  });

  it("US-04: live alert feed is newest first with transitions, and Ack is optimistic", async () => {
    let acked = false;
    const calls = mockFetch({ ...BASE_ROUTES, "POST /alerts/3/ack": () => { acked = true; return { ...ALERTS[0], acknowledged_at: new Date().toISOString() }; } });
    const user = userEvent.setup();
    renderApp("/overview");
    const items = await screen.findAllByTestId("alert-item");
    expect(items[0]).toHaveTextContent("FD001-T034");
    expect(items[0]).toHaveTextContent("Warning → Critical, RUL 29");
    expect(items[1]).toHaveTextContent("Healthy → Warning, RUL 72");
    expect(within(items[2]).getByLabelText("Acknowledged")).toBeInTheDocument();
    await user.click(within(items[0]).getByRole("button", { name: /Acknowledge alert FD001-T034/ }));
    await waitFor(() => expect(within(screen.getAllByTestId("alert-item")[0]).getByLabelText("Acknowledged")).toBeInTheDocument());
    expect(acked).toBe(true);
    expect(calls.find((c) => c.method === "POST")?.body).toContain("dashboard");
    expect(within(items[0]).getByRole("link")).toHaveAttribute("href", "/assets/FD001-T034?cycle=110");
  });

  it("shows the empty state with replay and ESP32 actions when there is no telemetry", async () => {
    mockFetch({ ...BASE_ROUTES, "/assets": { count: 0, by_state: {}, items: [] } });
    renderApp("/overview");
    expect(await screen.findByText("No telemetry yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Start dataset replay/ })).toHaveAttribute("href", "/test");
    expect(screen.getByRole("link", { name: /Connect an ESP32/ })).toBeInTheDocument();
  });

  it("redirects to login when the session is missing", async () => {
    mockFetch({ ...BASE_ROUTES, "/auth/me": { authenticated: false, auth_enabled: true } });
    renderApp("/overview");
    expect(await screen.findByLabelText("Dashboard password")).toBeInTheDocument();
  });
});
