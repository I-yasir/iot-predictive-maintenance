import { test, expect, type WebSocketRoute } from "@playwright/test";
import { login } from "./helpers";

/** P5.5 "WS disconnect in UI": drop the live socket and check the indicator recovers on its own. */
test("dropped WebSocket shows Reconnecting, then Live again with a REST resync", async ({ page }) => {
  let connections = 0;
  let current: WebSocketRoute | null = null;
  await page.routeWebSocket(/\/ws\/v1\/stream/, (ws) => {
    connections += 1;
    current = ws;
    ws.connectToServer(); // pass-through to the real backend
  });
  await login(page);
  const status = page.getByRole("banner").getByRole("status");
  await expect(status).toHaveText(/Live/, { timeout: 15_000 });
  expect(connections).toBe(1);

  const resync = page.waitForRequest((r) => r.url().includes("/api/v1/assets"), { timeout: 15_000 });
  await current!.close({ code: 1011, reason: "e2e: simulated drop" });
  await expect(status).toHaveText(/Reconnecting/, { timeout: 5_000 });
  await expect(status).toHaveText(/Live/, { timeout: 15_000 }); // first backoff step is 1 s
  expect(connections).toBe(2);
  await resync; // queries are invalidated on reconnect, so the snapshot is fetched again
});
