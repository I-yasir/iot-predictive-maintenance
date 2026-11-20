import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import fs from "node:fs";

const PASSWORD = process.env.PDM_PASSWORD ?? process.env.DASHBOARD_PASSWORD ?? "";
const SHOTS = process.env.PDM_SHOTS ?? "e2e-screens";
const VIEWPORTS = [
  { name: "375", width: 375, height: 812 },
  { name: "768", width: 768, height: 1024 },
  { name: "1280", width: 1280, height: 800 },
  { name: "1920", width: 1920, height: 1080 },
];

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Dashboard password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/overview/);
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible(); // shell rendered, safe to Tab
}

async function firstAssetId(page: Page): Promise<string> {
  const res = await page.request.get("/api/v1/assets");
  const body = await res.json();
  const live = body.items.find((a: { state: string }) => a.state !== "OFFLINE") ?? body.items[0];
  return live.asset_id;
}

async function axe(page: Page, label: string): Promise<string[]> {
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  return r.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .flatMap((v) => v.nodes.slice(0, 3).map((n) => `${label}: ${v.id} (${v.impact}) ${n.target.join(" ")} :: ${n.failureSummary?.split("\n")[1]?.trim() ?? ""}`));
}

test.beforeAll(() => {
  expect(PASSWORD, "set PDM_PASSWORD or DASHBOARD_PASSWORD").not.toBe("");
  fs.mkdirSync(SHOTS, { recursive: true });
});

const SCHEMES = ["dark", "light"] as const;
for (const vp of VIEWPORTS) for (const scheme of SCHEMES) {
  test.describe(`viewport ${vp.name}px ${scheme}`, () => {
    test.use({ viewport: { width: vp.width, height: vp.height }, colorScheme: scheme });

    test("views render, no serious axe violations, no horizontal scroll", async ({ page }) => {
      await login(page);
      const id = await firstAssetId(page);
      const pages: [string, string, () => Promise<void>][] = [
        ["overview", "/overview", async () => { await expect(page.getByRole("heading", { name: /overview/i }).first()).toBeVisible(); }],
        ["detail", `/assets/${id}`, async () => { await expect(page.getByRole("tab", { name: /summary/i })).toBeVisible(); }],
        ["detail-sensors", `/assets/${id}?tab=sensors`, async () => { await expect(page.getByRole("tabpanel")).toBeVisible(); }],
        ["detail-subsystems", `/assets/${id}?tab=subsystems`, async () => { await expect(page.getByRole("tabpanel")).toBeVisible(); }],
        ["alerts", "/alerts", async () => { await expect(page.getByRole("heading", { name: /alerts/i }).first()).toBeVisible(); }],
        ["test", "/test", async () => { await expect(page.getByRole("heading", { name: /test/i }).first()).toBeVisible(); }],
        ["model", "/about/model", async () => { await expect(page.getByRole("heading").first()).toBeVisible(); }],
      ];
      const problems: string[] = [];
      for (const [name, url, ready] of pages) {
        await page.goto(url);
        await ready();
        await page.waitForTimeout(1200); // let charts animate in and live data land
        await page.screenshot({ path: `${SHOTS}/${vp.name}-${scheme}-${name}.png`, fullPage: true });
        problems.push(...(await axe(page, `${vp.name} ${scheme} ${name}`)));
        const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        if (over > 1) problems.push(`${vp.name} ${scheme} ${name}: page scrolls horizontally by ${over}px`);
      }
      expect(problems, problems.join("\n")).toEqual([]);
    });
  });
}

test.describe("keyboard and motion", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("skip link, tabs and asset grid work from the keyboard", async ({ page }) => {
    await login(page);
    await page.keyboard.press("Tab");
    const first = page.locator(":focus");
    await expect(first).toHaveText(/skip/i);
    await page.keyboard.press("Enter");

    const id = await firstAssetId(page);
    await page.goto(`/assets/${id}`);
    await page.getByRole("tab", { name: /summary/i }).focus();
    await page.keyboard.press("ArrowRight");
    await expect(page.getByRole("tab", { name: /sensors/i })).toBeFocused();
    await expect(page).toHaveURL(/tab=sensors/);
    await page.keyboard.press("ArrowLeft");
    await expect(page.getByRole("tab", { name: /summary/i })).toBeFocused();
  });

  test("focus is always visible", async ({ page }) => {
    await login(page);
    await expect(page.getByLabel("Fleet status")).toBeVisible(); // data loaded, so Tab reaches main content
    for (let i = 0; i < 8; i++) {
      await page.keyboard.press("Tab");
      const outline = await page.evaluate(() => {
        const el = document.activeElement as HTMLElement | null;
        if (!el || el === document.body) return "none";
        const cs = getComputedStyle(el);
        return cs.outlineStyle !== "none" && cs.outlineWidth !== "0px" ? "ok" : cs.boxShadow !== "none" ? "ok" : `missing on ${el.tagName}.${el.className}`;
      });
      expect(outline, `Tab #${i + 1}`).toBe("ok");
    }
  });

  test("reduced motion disables animation", async ({ browser }) => {
    const ctx = await browser.newContext({ reducedMotion: "reduce", viewport: { width: 1280, height: 800 } });
    const page = await ctx.newPage();
    await login(page);
    const anim = await page.evaluate(() => {
      const els = Array.from(document.querySelectorAll<HTMLElement>("*"));
      return els.filter((el) => {
        const cs = getComputedStyle(el);
        const dur = parseFloat(cs.animationDuration) || 0;
        return cs.animationName !== "none" && dur > 0.01;
      }).length;
    });
    expect(anim).toBe(0);
    await ctx.close();
  });
});
