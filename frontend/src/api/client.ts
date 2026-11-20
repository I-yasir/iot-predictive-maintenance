/** Fetch wrapper: same-origin cookies, zod validation, and backend-reachability tracking (docs/02 §7). */
import type { ZodType, ZodTypeDef } from "zod";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

type Listener = (s: BackendHealth) => void;
export interface BackendHealth {
  reachable: boolean;
  consecutiveFailures: number;
  lastOkAt: number | null;
}

/** 3 consecutive 5xx/network failures -> "Backend unreachable" banner; any success clears it. */
export const FAILURES_FOR_DOWN = 3;

class HealthTracker {
  state: BackendHealth = { reachable: true, consecutiveFailures: 0, lastOkAt: null };
  private listeners = new Set<Listener>();
  subscribe(l: Listener): () => void {
    this.listeners.add(l);
    return () => this.listeners.delete(l);
  }
  ok(): void {
    this.set({ reachable: true, consecutiveFailures: 0, lastOkAt: Date.now() });
  }
  fail(): void {
    const n = this.state.consecutiveFailures + 1;
    this.set({ ...this.state, consecutiveFailures: n, reachable: n < FAILURES_FOR_DOWN });
  }
  private set(s: BackendHealth): void {
    const changed = s.reachable !== this.state.reachable || s.consecutiveFailures !== this.state.consecutiveFailures;
    this.state = s;
    if (changed || s.reachable) this.listeners.forEach((l) => l(s));
  }
}
export const backendHealth = new HealthTracker();

/** Called on 401 so the app can route to /login. */
let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void): void {
  onUnauthorized = fn;
}

export async function api<T>(
  path: string,
  schema: ZodType<T, ZodTypeDef, unknown> | null,
  init: RequestInit & { json?: unknown } = {},
): Promise<T> {
  const { json, ...rest } = init;
  let res: Response;
  try {
    res = await fetch(`/api/v1${path}`, {
      credentials: "same-origin",
      ...rest,
      headers: { Accept: "application/json", ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...rest.headers },
      body: json !== undefined ? JSON.stringify(json) : rest.body,
      signal: rest.signal ?? AbortSignal.timeout(10_000),
    });
  } catch (e) {
    if ((e as Error).name === "AbortError" && rest.signal?.aborted) throw e;
    backendHealth.fail();
    throw new ApiError(0, "Backend unreachable");
  }
  if (res.status >= 500) backendHealth.fail();
  else backendHealth.ok();
  if (res.status === 401) {
    onUnauthorized();
    throw new ApiError(401, "Sign in required");
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, msg);
  }
  const data: unknown = await res.json();
  if (!schema) return data as T;
  const parsed = schema.safeParse(data);
  if (!parsed.success) {
    console.error("API schema mismatch", path, parsed.error.issues);
    throw new ApiError(res.status, `Unexpected response from ${path}`);
  }
  return parsed.data;
}
