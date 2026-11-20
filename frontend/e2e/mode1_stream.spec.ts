import { test, expect } from "@playwright/test";
import { login } from "./helpers";

/**
 * P5.2 Mode 1 stream: drive a replay from the Test page exactly as a user would and watch it land.
 * FD001 test units chosen from RUL_FD001.txt: six end with true RUL <= 30 (37 41 36 56 90 66), two in the
 * warning band (79 38) and two healthy (1 85). Longest history is 147 cycles, about 8 s at 20 cycles/s.
 */
const UNITS = [37, 41, 36, 56, 90, 66, 79, 38, 1, 85];
const CRITICAL_UNITS = [37, 41, 36, 56, 90, 66];
const id = (u: number) => `FD001-T${String(u).padStart(3, "0")}`;

test.describe("P5.2 Mode 1 stream", () => {
  test.use({ viewport: { width: 1440, height: 900 } });
  test.setTimeout(120_000);

  test("replay from /test: tiles, state changes, critical alert, predicted vs true RUL", async ({ page }) => {
    await login(page);
    await page.request.post("/api/v1/sim/replay/stop"); // clean slate if a previous run is still going
    const t0 = new Date(Date.now() - 2000).toISOString();

    await page.goto("/test");
    const panel = page.getByRole("region", { name: "Dataset replay (Mode 1)" });
    await panel.getByLabel("Profile").selectOption("FD001");
    await panel.getByLabel("Split").selectOption("test");
    await panel.getByRole("combobox", { name: /^Units/ }).selectOption("units");
    await panel.getByLabel("Unit numbers").fill(UNITS.join(", "));
    const slider = panel.getByRole("slider");
    await slider.focus();
    for (let i = 0; i < 100; i++) {
      const v = Number((await slider.getAttribute("aria-valuetext"))?.split(" ")[0]);
      if (v === 20) break;
      await page.keyboard.press(v < 20 ? "ArrowRight" : "ArrowLeft");
    }
    await expect(slider).toHaveAttribute("aria-valuetext", "20 cycles per second");
    // Record every state each tile shows, in the page, from before the start: at 20 cycles/s the whole run takes
    // ~8 s and an engine that stops sending is Offline 3 intervals (0.15 s) later (docs/02 §3), so states have to
    // be sampled while they happen rather than read at the end.
    await page.evaluate(() => {
      const w = window as unknown as { __seen: Record<string, string[]> };
      w.__seen = {};
      setInterval(() => {
        document.querySelectorAll("[data-testid=asset-tile]").forEach((el) => {
          const [aid, st] = (el.getAttribute("aria-label") ?? "").split(", ");
          const list = (w.__seen[aid] ??= []);
          if (list[list.length - 1] !== st) list.push(st);
        });
      }, 50);
    });
    await panel.getByRole("button", { name: "Start replay" }).click();
    await expect(panel.getByTestId("replay-state")).toHaveText("RUNNING", { timeout: 10_000 });

    // tiles appear and move through states while the replay runs
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Overview", exact: true }).click();
    const tile = (u: number) => page.getByRole("link", { name: new RegExp(`^${id(u)},`) });
    for (const u of UNITS) await expect(tile(u)).toBeVisible({ timeout: 15_000 });
    await expect.poll(async () => (await page.request.get("/api/v1/sim/replay/status").then((r) => r.json())).state,
      { timeout: 60_000 }).toBe("COMPLETED");
    await page.waitForTimeout(500);
    const seen = await page.evaluate(() => (window as unknown as { __seen: Record<string, string[]> }).__seen);
    const s37 = seen[id(37)] ?? [];
    const s1 = seen[id(1)] ?? [];
    // Tiles must visibly move through states. (At 20 cycles/s an engine is Critical for its last ~10 cycles,
    // under half a second, and Offline 3 intervals later, so the Critical moment itself is checked through the
    // alert log below rather than by sampling tiles.)
    expect(new Set(s37.filter((x) => x !== "offline")).size, `FD001-T037 went through: ${s37.join(" → ")}`)
      .toBeGreaterThanOrEqual(2);
    expect(s1, `FD001-T001 went through: ${s1.join(" → ")}`).toContain("healthy");
    test.info().annotations.push({ type: "states", description: `T037: ${s37.join(" → ")} | T001: ${s1.join(" → ")}` });

    // at least one Critical alert raised in this run for a unit whose true RUL <= 30
    const alerts = await page.request.get("/api/v1/alerts?limit=500").then((r) => r.json());
    const fresh = alerts.items.filter((a: { created_at: string; to_state: string; asset_id: string }) =>
      a.created_at >= t0 && a.to_state === "CRITICAL" && CRITICAL_UNITS.map(id).includes(a.asset_id));
    expect(fresh.length).toBeGreaterThanOrEqual(1);
    await page.goto("/alerts");
    await expect(page.getByRole("row").filter({ hasText: fresh[0].asset_id }).filter({ hasText: /critical/i }).first()).toBeVisible();

    // detail view shows predicted vs true RUL
    await page.goto(`/assets/${id(37)}`);
    await expect(page.getByText("True RUL (replay)")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Ground truth (replay)" })).toBeVisible();
    await expect(page.getByText(/Final-cycle error: [+-]?\d+ cycles/)).toBeVisible();
    const a37 = await page.request.get(`/api/v1/assets/${id(37)}`).then((r) => r.json());
    expect(a37.true_rul_at_end).toBe(21);
    expect(Math.abs(a37.rul_pred - 21)).toBeLessThanOrEqual(10);
  });
});
