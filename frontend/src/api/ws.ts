/**
 * WebSocket client with exponential backoff (1 -> 30 s) and a resync hook (docs/02 §7 "Reconnecting").
 * States: connecting -> live; on close -> reconnecting (timer) -> connecting ...; stop() -> closed.
 * `onResync` fires after every successful (re)connect so the caller can refetch the REST snapshot.
 */
import { WsEvent } from "./schemas";

export type WsState = "connecting" | "live" | "reconnecting" | "closed";

export interface WsOptions {
  url: string;
  onEvent: (e: WsEvent) => void;
  onState?: (s: WsState, info: { attempt: number; retryInMs: number | null }) => void;
  onResync?: () => void;
  /** injectable for tests */
  createSocket?: (url: string) => WebSocket;
  setTimer?: (fn: () => void, ms: number) => unknown;
  clearTimer?: (t: unknown) => void;
}

export const BACKOFF_MS = [1000, 2000, 4000, 8000, 16000, 30000];

export function backoffDelay(attempt: number): number {
  return BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)];
}

export class WsClient {
  state: WsState = "closed";
  attempt = 0;
  private sock: WebSocket | null = null;
  private timer: unknown = null;
  private stopped = false;
  constructor(private o: WsOptions) {}

  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.timer !== null) (this.o.clearTimer ?? clearTimeout)(this.timer as ReturnType<typeof setTimeout>);
    this.timer = null;
    this.sock?.close();
    this.sock = null;
    this.set("closed", null);
  }

  private set(s: WsState, retryInMs: number | null): void {
    this.state = s;
    this.o.onState?.(s, { attempt: this.attempt, retryInMs });
  }

  private connect(): void {
    this.set("connecting", null);
    const sock = (this.o.createSocket ?? ((u) => new WebSocket(u)))(this.o.url);
    this.sock = sock;
    sock.onopen = () => {
      this.attempt = 0;
      this.set("live", null);
      this.o.onResync?.();
    };
    sock.onmessage = (m: MessageEvent) => {
      try {
        const parsed = WsEvent.safeParse(JSON.parse(String(m.data)));
        if (parsed.success) this.o.onEvent(parsed.data);
      } catch {
        /* ignore malformed frames */
      }
    };
    sock.onclose = () => {
      if (this.sock !== sock) return;
      this.sock = null;
      if (this.stopped) return;
      const delay = backoffDelay(this.attempt);
      this.attempt += 1;
      this.set("reconnecting", delay);
      this.timer = (this.o.setTimer ?? setTimeout)(() => {
        this.timer = null;
        if (!this.stopped) this.connect();
      }, delay);
    };
    sock.onerror = () => sock.close();
  }
}

export function wsUrl(path = "/ws/v1/stream"): string {
  const { protocol, host } = window.location;
  return `${protocol === "https:" ? "wss" : "ws"}://${host}${path}`;
}
