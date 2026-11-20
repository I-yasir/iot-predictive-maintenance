"""Causal window features (docs/05 §5 steps 4-7).

Two implementations of the *same* maths, kept side by side and tested for parity:
  * `window_features_batch`  - vectorised, for training/evaluation over whole trajectories
  * `StreamState.update`     - one cycle at a time, for the online inference service
Every feature at cycle t uses only cycles <= t of the same unit.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.signal import lfilter

from pdm_ml.config import EWM_ALPHA, MIN_CYCLES, WINDOW

FEATURE_KINDS: tuple[str, ...] = ("ewm", "mean", "std", "slope", "delta")
META_FEATURES: tuple[str, ...] = ("cycle", "window_len")


def feature_names(sensors: Sequence[str]) -> list[str]:
    return [*META_FEATURES, *(f"{s}_{k}" for s in sensors for k in FEATURE_KINDS)]


def _ewm(z: np.ndarray, alpha: float) -> np.ndarray:
    """y0 = x0; y_t = a*x_t + (1-a)*y_{t-1}; z shape (n, k)."""
    zi = (1 - alpha) * z[0:1, :]
    y, _ = lfilter([alpha], [1.0, -(1 - alpha)], z, axis=0, zi=zi)
    return np.asarray(y)


def _unit_features(z: np.ndarray, t: np.ndarray, window: int, alpha: float, min_cycles: int) -> np.ndarray:
    n, k = z.shape
    t = t.astype(float) - float(t[0])  # centring improves numerical stability, slope unchanged
    ewm = _ewm(z, alpha)
    idx = np.arange(n)
    lo = np.maximum(0, idx - window + 1)
    cnt = (idx - lo + 1).astype(float)

    def wsum(a: np.ndarray) -> np.ndarray:
        c = np.vstack([np.zeros((1,) + a.shape[1:]), np.cumsum(a, axis=0)])
        return c[idx + 1] - c[lo]

    tt = t[:, None]
    sx, sxx, sxt = wsum(z), wsum(z * z), wsum(z * tt)
    st, stt = wsum(tt), wsum(tt * tt)
    c = cnt[:, None]
    mean = sx / c
    var = np.where(c > 1, (sxx - sx * sx / c) / np.maximum(c - 1, 1), 0.0)
    std = np.sqrt(np.clip(var, 0, None))
    den = c * stt - st * st
    slope = np.where(den > 1e-12, (c * sxt - sx * st) / np.where(den > 1e-12, den, 1.0), 0.0)
    first = np.cumsum(z[:min_cycles], axis=0) / np.arange(1, min(n, min_cycles) + 1)[:, None]
    base = np.vstack([first, np.repeat(first[-1:], max(n - min_cycles, 0), axis=0)])
    delta = ewm - base
    per_sensor = np.stack([ewm, mean, std, slope, delta], axis=2).reshape(n, k * len(FEATURE_KINDS))
    return np.hstack([cnt[:, None] * 0, cnt[:, None], per_sensor])  # cycle column filled by caller


def window_features_batch(
    z: pd.DataFrame,
    sensors: Sequence[str],
    window: int = WINDOW,
    alpha: float = EWM_ALPHA,
    min_cycles: int = MIN_CYCLES,
    gate: bool = True,
) -> pd.DataFrame:
    """z: regime-normalised frame with unit, cycle and sensor columns. Returns unit, cycle, row_in_unit + features."""
    z = z.sort_values(["unit", "cycle"], kind="stable")
    names = feature_names(sensors)
    blocks, units, cycles, rows = [], [], [], []
    for u, g in z.groupby("unit", sort=False):
        arr = _unit_features(g[list(sensors)].to_numpy(float), g.cycle.to_numpy(), window, alpha, min_cycles)
        arr[:, 0] = g.cycle.to_numpy()
        blocks.append(arr)
        units.append(np.full(len(g), u))
        cycles.append(g.cycle.to_numpy())
        rows.append(np.arange(len(g)))
    out = pd.DataFrame(np.vstack(blocks), columns=names)
    out.insert(0, "unit", np.concatenate(units))
    out.insert(1, "row_in_unit", np.concatenate(rows))
    out["cycle"] = out["cycle"].astype(int)
    if gate:
        out = out[out.row_in_unit >= min_cycles - 1]
    return out.reset_index(drop=True)


@dataclass
class StreamState:
    """Per-asset rolling state for online feature computation (bounded memory)."""

    sensors: tuple[str, ...]
    window: int = WINDOW
    alpha: float = EWM_ALPHA
    min_cycles: int = MIN_CYCLES
    n_seen: int = 0
    t0: float | None = None
    ewm: np.ndarray | None = None
    first_sum: np.ndarray | None = None
    buf_z: deque[np.ndarray] = field(default_factory=deque)
    buf_t: deque[float] = field(default_factory=deque)

    @property
    def warming_up(self) -> bool:
        return self.n_seen < self.min_cycles

    def update(self, cycle: int, z: np.ndarray) -> np.ndarray | None:
        """Add one regime-normalised cycle; return the feature vector or None while warming up."""
        z = np.asarray(z, float)
        if self.t0 is None:
            self.t0 = float(cycle)
        t = float(cycle) - self.t0
        self.ewm = z.copy() if self.ewm is None else self.alpha * z + (1 - self.alpha) * self.ewm
        if self.n_seen < self.min_cycles:
            self.first_sum = z.copy() if self.first_sum is None else self.first_sum + z
        self.n_seen += 1
        self.buf_z.append(z)
        self.buf_t.append(t)
        while len(self.buf_z) > self.window:
            self.buf_z.popleft()
            self.buf_t.popleft()
        if self.warming_up:
            return None
        zz = np.vstack(self.buf_z)
        tt = np.asarray(self.buf_t)[:, None]
        c = float(len(zz))
        sx, sxx, sxt = zz.sum(0), (zz * zz).sum(0), (zz * tt).sum(0)
        st, stt = tt.sum(), (tt * tt).sum()
        mean = sx / c
        std = np.sqrt(np.clip((sxx - sx * sx / c) / (c - 1), 0, None)) if c > 1 else np.zeros_like(sx)
        den = c * stt - st * st
        slope = (c * sxt - sx * st) / den if den > 1e-12 else np.zeros_like(sx)
        assert self.first_sum is not None
        base = self.first_sum / min(self.n_seen, self.min_cycles)
        delta = self.ewm - base
        per_sensor = np.stack([self.ewm, mean, std, slope, delta], axis=1).reshape(-1)
        return np.concatenate([[float(cycle), c], per_sensor])
