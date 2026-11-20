"""OOD and drift reference statistics (docs/05 §8)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from pdm_ml.config import SEED

REF_SAMPLE_SIZE = 500
KS_THRESHOLD = 0.3
KS_MIN_SENSORS = 3
DRIFT_WINDOW = 50
DRIFT_MIN_RUL = 100


def ks_statistic(a: np.ndarray, b_sorted: np.ndarray) -> float:
    """Two-sample KS statistic sup|F_a - F_b| (same value as scipy.stats.ks_2samp(a, b).statistic), with b
    pre-sorted. About 30x cheaper than scipy's wrapper, which matters on the per-message streaming path."""
    a_sorted = np.sort(a)
    pts = np.concatenate([a_sorted, b_sorted])
    fa = np.searchsorted(a_sorted, pts, side="right") / len(a_sorted)
    fb = np.searchsorted(b_sorted, pts, side="right") / len(b_sorted)
    return float(np.max(np.abs(fa - fb)))


@dataclass
class DriftReference:
    sensors: tuple[str, ...]
    healthy_sample: dict[str, list[float]]  # regime-normalised healthy-phase values
    raw_min: dict[str, float]
    raw_max: dict[str, float]
    _ref_sorted: list[np.ndarray] = field(default_factory=list, init=False, repr=False, compare=False)

    @classmethod
    def fit(
        cls, raw: pd.DataFrame, z: pd.DataFrame, rul: pd.Series, sensors: Sequence[str], cap: int
    ) -> DriftReference:
        rng = np.random.default_rng(SEED)
        healthy = z.loc[rul.to_numpy() >= cap]
        idx = rng.choice(len(healthy), size=min(REF_SAMPLE_SIZE, len(healthy)), replace=False)
        return cls(
            tuple(sensors),
            {s: [round(float(v), 5) for v in healthy[s].to_numpy()[idx]] for s in sensors},
            {s: float(raw[s].min()) for s in raw.columns if s not in ("unit", "cycle")},
            {s: float(raw[s].max()) for s in raw.columns if s not in ("unit", "cycle")},
        )

    def ood_sensors(self, values: Mapping[str, float]) -> list[str]:
        """Sensors outside the training range (soft flag; hard limits are in config/profiles)."""
        return [
            s
            for s, v in values.items()
            if s in self.raw_min and not (self.raw_min[s] <= v <= self.raw_max[s])
        ]

    def drift(self, z_window: np.ndarray, rul_pred: float) -> tuple[bool, dict[str, float]]:
        """KS of the last DRIFT_WINDOW regime-normalised cycles vs. healthy reference (only while healthy)."""
        if len(z_window) < DRIFT_WINDOW or rul_pred < DRIFT_MIN_RUL:
            return False, {}
        w = np.asarray(z_window, float)[-DRIFT_WINDOW:]
        if not self._ref_sorted:
            self._ref_sorted = [np.sort(np.asarray(self.healthy_sample[s], float)) for s in self.sensors]
        stats = {s: ks_statistic(w[:, j], self._ref_sorted[j]) for j, s in enumerate(self.sensors)}
        return sum(v > KS_THRESHOLD for v in stats.values()) >= KS_MIN_SENSORS, stats

    def to_json(self) -> dict[str, Any]:
        return {
            "sensors": list(self.sensors),
            "healthy_sample": self.healthy_sample,
            "raw_min": self.raw_min,
            "raw_max": self.raw_max,
            "rules": {
                "ks_threshold": KS_THRESHOLD,
                "ks_min_sensors": KS_MIN_SENSORS,
                "window": DRIFT_WINDOW,
                "min_rul": DRIFT_MIN_RUL,
            },
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> DriftReference:
        return cls(tuple(d["sensors"]), d["healthy_sample"], d["raw_min"], d["raw_max"])
