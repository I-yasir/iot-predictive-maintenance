import { expect, type Page } from "@playwright/test";

export const PASSWORD = process.env.PDM_PASSWORD ?? process.env.DASHBOARD_PASSWORD ?? "";

export async function login(page: Page) {
  expect(PASSWORD, "set PDM_PASSWORD or DASHBOARD_PASSWORD").not.toBe("");
  await page.goto("/login");
  await page.getByLabel("Dashboard password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/overview/);
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible(); // shell rendered, safe to Tab
}
