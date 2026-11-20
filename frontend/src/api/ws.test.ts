import { describe, expect, it, vi } from "vitest";
import { backoffDelay, WsClient, type WsState } from "./ws";

class FakeSocket {
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  closed = false;
  close() {
    if (this.closed) return;
    this.closed = true;
    this.onclose?.();
  }
}

function setup() {
  const sockets: FakeSocket[] = [];
  const timers: { fn: () => void; ms: number }[] = [];
  const states: [WsState, number | null][] = [];
  const events: unknown[] = [];
  const resync = vi.fn();
  const c = new WsClient({
    url: "ws://x",
    onEvent: (e) => events.push(e),
    onState: (s, i) => states.push([s, i.retryInMs]),
    onResync: resync,
    createSocket: () => {
      const s = new FakeSocket();
      sockets.push(s);
      return s as unknown as WebSocket;
    },
    setTimer: (fn, ms) => timers.push({ fn, ms }),
    clearTimer: () => {},
  });
  return { c, sockets, timers, states, events, resync };
}

describe("WsClient", () => {
  it("goes live and resyncs on open", () => {
    const t = setup();
    t.c.start();
    expect(t.c.state).toBe("connecting");
    t.sockets[0].onopen?.();
    expect(t.c.state).toBe("live");
    expect(t.resync).toHaveBeenCalledTimes(1);
  });

  it("backs off 1, 2, 4 ... capped at 30 s, and resets after a successful reconnect", () => {
    const t = setup();
    t.c.start();
    for (let i = 0; i < 8; i++) {
      t.sockets[i].close();
      expect(t.c.state).toBe("reconnecting");
      t.timers[i].fn();
    }
    expect(t.timers.map((x) => x.ms)).toEqual([1000, 2000, 4000, 8000, 16000, 30000, 30000, 30000]);
    t.sockets[8].onopen?.();
    expect(t.c.state).toBe("live");
    expect(t.resync).toHaveBeenCalledTimes(1);
    t.sockets[8].close();
    expect(t.timers[8].ms).toBe(1000);
  });

  it("parses valid events and drops malformed ones", () => {
    const t = setup();
    t.c.start();
    t.sockets[0].onmessage?.({ data: "not json" });
    t.sockets[0].onmessage?.({ data: JSON.stringify({ type: "nope" }) });
    t.sockets[0].onmessage?.({ data: JSON.stringify({ type: "heartbeat", ts: 1 }) });
    expect(t.events).toEqual([{ type: "heartbeat", ts: 1 }]);
  });

  it("stop() closes without scheduling a reconnect", () => {
    const t = setup();
    t.c.start();
    t.sockets[0].onopen?.();
    t.c.stop();
    expect(t.c.state).toBe("closed");
    expect(t.timers).toHaveLength(0);
  });

  it("backoffDelay caps at the last step", () => {
    expect(backoffDelay(0)).toBe(1000);
    expect(backoffDelay(99)).toBe(30000);
  });
});
