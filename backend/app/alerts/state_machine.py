"""P3.6 asset health state machine with hysteresis (docs/02 §3). Pure logic, no I/O: table-tested."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class State(StrEnum):
    NEW = "NEW"
    WARMING_UP = "WARMING_UP"
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    OFFLINE = "OFFLINE"
    DEGRADED_DATA = "DEGRADED_DATA"


SEVERITY = {State.HEALTHY: 0, State.WARNING: 1, State.CRITICAL: 2}


@dataclass(frozen=True)
class AlertConfig:
    warning_rul: float = 75
    critical_rul: float = 30
    escalate_after: int = 2
    deescalate_after: int = 5
    deescalate_margin: float = 5
    safety_p10: float = 15
    degraded_after: int = 3
    recover_after: int = 3

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AlertConfig:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})

    def classify(self, rul: float, margin: float = 0.0) -> State:
        if rul <= self.critical_rul + margin:
            return State.CRITICAL
        if rul <= self.warning_rul + margin:
            return State.WARNING
        return State.HEALTHY


@dataclass
class Transition:
    from_state: State
    to_state: State
    reason: str


@dataclass
class AssetHealth:
    """Per-asset alert state. Feed it events; each returns a Transition when the state changes."""

    cfg: AlertConfig
    state: State = State.NEW
    pending: State | None = None  # candidate classified state waiting for enough consecutive votes
    pending_n: int = 0
    before_offline: State | None = None
    bad_streak: int = 0
    good_streak: int = 0
    last_rul: float | None = None

    def _move(self, to: State, reason: str) -> Transition | None:
        if to == self.state:
            return None
        t = Transition(self.state, to, reason)
        self.state, self.pending, self.pending_n = to, None, 0
        return t

    # ---- events ----
    def on_message(self) -> Transition | None:
        """Any accepted message (also ends OFFLINE)."""
        if self.state == State.NEW:
            return self._move(State.WARMING_UP, "first message")
        if self.state == State.OFFLINE:
            prev = self.before_offline or State.WARMING_UP
            self.before_offline = None
            return self._move(prev, "data resumed")
        return None

    def on_data_quality(self, bad: bool) -> Transition | None:
        """bad = message rejected, or accepted with an OOD flag (docs/05 §8)."""
        if bad:
            self.bad_streak, self.good_streak = self.bad_streak + 1, 0
            if self.bad_streak >= self.cfg.degraded_after and self.state not in (State.DEGRADED_DATA, State.NEW):
                if self.state == State.OFFLINE:
                    self.before_offline = None
                return self._move(State.DEGRADED_DATA, f"{self.bad_streak} consecutive rejected/OOD messages")
            return None
        self.good_streak, self.bad_streak = self.good_streak + 1, 0
        if self.state == State.DEGRADED_DATA and self.good_streak >= self.cfg.recover_after:
            to = self.cfg.classify(self.last_rul) if self.last_rul is not None else State.WARMING_UP
            return self._move(to, f"{self.good_streak} consecutive valid messages")
        return None

    def on_prediction(self, rul: float, p10: float) -> Transition | None:
        self.last_rul = rul
        if self.state in (State.DEGRADED_DATA, State.OFFLINE, State.NEW):
            return None
        if p10 <= self.cfg.safety_p10 and self.state != State.CRITICAL:
            return self._move(State.CRITICAL, f"safety override: P10 {p10:.0f} <= {self.cfg.safety_p10:g}")
        if self.state == State.WARMING_UP:
            return self._move(self.cfg.classify(rul), "warm-up complete")
        cur = SEVERITY[self.state]
        up = self.cfg.classify(rul)
        down = self.cfg.classify(rul, margin=self.cfg.deescalate_margin)
        if SEVERITY[up] > cur:
            cand, need = up, self.cfg.escalate_after
        elif SEVERITY[down] < cur:
            cand, need = down, self.cfg.deescalate_after
        else:
            self.pending, self.pending_n = None, 0
            return None
        same_dir = self.pending is not None and (SEVERITY[self.pending] > cur) == (SEVERITY[cand] > cur)
        self.pending_n = self.pending_n + 1 if same_dir else 1
        self.pending = cand
        if self.pending_n >= need:
            verb = "escalated" if SEVERITY[cand] > cur else "recovered"
            return self._move(cand, f"{verb}: RUL {rul:.0f} for {self.pending_n} predictions")
        return None

    def on_offline(self) -> Transition | None:
        if self.state in (State.OFFLINE, State.NEW):
            return None
        self.before_offline = self.state
        return self._move(State.OFFLINE, "no data for 3x the expected interval")

    def on_new_life(self) -> Transition | None:
        self.last_rul, self.bad_streak, self.good_streak, self.before_offline = None, 0, 0, None
        return self._move(State.WARMING_UP, "unit restarted at cycle 1 (new life)")
