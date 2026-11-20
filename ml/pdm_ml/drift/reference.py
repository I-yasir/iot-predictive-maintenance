"""OOD and drift reference statistics (docs/05 §8)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import ks_2samp

from pdm_ml.config import SEED

REF_SAMPLE_SIZE = 500
KS_THRESHOLD = 0.3
KS_MIN_SENSORS = 3
DRIFT_WINDOW = 50
DRIFT_MIN_RUL = 100


@dataclass
class DriftReference:
    sensors: tuple[str, ...]
    healthy_sample: dict[str, list[float]]  # regime-normalised healthy-phase values
    raw_min: dict[str, float]
    raw_max: dict[str, float]

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
        w = np.asarray(z_window)[-DRIFT_WINDOW:]
        stats = {
            s: float(ks_2samp(w[:, j], self.healthy_sample[s]).statistic) for j, s in enumerate(self.sensors)
        }
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
