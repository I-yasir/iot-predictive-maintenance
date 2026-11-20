import { defineConfig } from "@playwright/test";
import fs from "node:fs";

// P4.9: runs against the real stack (backend on :8000, `npm run preview` on :8080).
// Start them first: `make backend` and `make frontend-preview`, then a replay so
// there is live data. Set PDM_PASSWORD (defaults to DASHBOARD_PASSWORD).
// Use a pre-installed Chromium when the bundled one is absent (e.g. CI images).
const sysChromium = "/opt/pw-browsers/chromium";
const executablePath = process.env.PW_CHROMIUM ?? (fs.existsSync(sysChromium) && fs.statSync(sysChromium).isFile() ? sysChromium : undefined);

export default defineConfig({
  testDir: "e2e",
  outputDir: "test-results",
  timeout: 60_000,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.PDM_DASHBOARD_URL ?? "http://localhost:8080",
    launchOptions: executablePath ? { executablePath } : {},
    trace: "off",
  },
});
