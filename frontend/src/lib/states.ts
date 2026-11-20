import { AlertOctagon, AlertTriangle, CheckCircle2, CircleDashed, DatabaseZap, Loader, WifiOff, type LucideIcon } from "lucide-react";
import type { State } from "../api/schemas";

export interface StateMeta {
  label: string;
  token: "healthy" | "warning" | "critical" | "offline" | "warming" | "degraded";
  icon: LucideIcon;
  /** sort order: most urgent first (docs/03 §1.2: Critical sorted first) */
  rank: number;
}

export const STATE_META: Record<State, StateMeta> = {
  CRITICAL: { label: "Critical", token: "critical", icon: AlertOctagon, rank: 0 },
  WARNING: { label: "Warning", token: "warning", icon: AlertTriangle, rank: 1 },
  DEGRADED_DATA: { label: "Data issue", token: "degraded", icon: DatabaseZap, rank: 2 },
  OFFLINE: { label: "Offline", token: "offline", icon: WifiOff, rank: 3 },
  HEALTHY: { label: "Healthy", token: "healthy", icon: CheckCircle2, rank: 4 },
  WARMING_UP: { label: "Warming up", token: "warming", icon: Loader, rank: 5 },
  NEW: { label: "New", token: "warming", icon: CircleDashed, rank: 6 },
};

export function stateMeta(s: string): StateMeta {
  return STATE_META[s as State] ?? STATE_META.NEW;
}

/** Flag explanations shown in tooltips (docs/05 §8). */
export const FLAG_TEXT: Record<string, string> = {
  LOW_CONFIDENCE: "Low confidence: the P10–P90 band is wider than 60 cycles or fewer than 15 cycles are in the window.",
  OOD: "Out of distribution: a sensor or the operating point is outside the training range.",
  DRIFT: "Drift: recent healthy-looking readings differ from the training data (KS > 0.3 on ≥ 3 sensors).",
  JUMP: "Prediction jump: RUL changed by more than 25 cycles since the previous cycle.",
  gap: "Cycle gap: one or more cycles were missing before this one.",
  out_of_order: "Out of order: this cycle arrived after a later one and was stored without a new prediction.",
  clock_skew: "Clock skew: the device timestamp differs from server time by more than the allowed margin.",
};

export const THRESHOLDS = { warning: 75, critical: 30 } as const;
export const MIN_CYCLES = 5;
export const PROFILES = ["FD001", "FD002", "FD003", "FD004"] as const;
export const SOURCES = ["REPLAY", "ESP32", "VIRTUAL_ESP32", "LIVE"] as const;
