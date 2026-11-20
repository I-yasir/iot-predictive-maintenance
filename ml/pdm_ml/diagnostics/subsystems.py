"""Deviation-based diagnostics for the component detail report (docs/05 §7.6).

Indicative only: C-MAPSS has no fault-mode labels (PRD non-goal 3).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from pdm_ml.features.window import FEATURE_KINDS, META_FEATURES

SUBSYSTEM_ORDER: tuple[str, ...] = ("Fan", "LPC", "HPC", "Burner", "HPT", "LPT", "Engine")
SCORE_Z_FULL_SCALE = 6.0  # |z| = 6 -> score 100


@dataclass
class FleetBaseline:
    """Healthy-phase statistics of regime-normalised sensors (rows with true RUL >= cap)."""

    sensors: tuple[str, ...]
    mean: np.ndarray
    std: np.ndarray

    @classmethod
    def fit(cls, z: pd.DataFrame, rul: pd.Series, sensors: Sequence[str], cap: int) -> FleetBaseline:
        healthy = z.loc[rul.to_numpy() >= cap, list(sensors)]
        return cls(tuple(sensors), healthy.mean().to_numpy(), healthy.std().replace(0, 1.0).to_numpy())


def asset_baseline(
    z_history: np.ndarray, fleet: FleetBaseline, min_rows: int = 20
) -> tuple[np.ndarray, np.ndarray]:
    """Per-asset healthy baseline from its first `min_rows` cycles; falls back to the fleet baseline."""
    if len(z_history) >= min_rows:
        h = z_history[:min_rows]
        sd = h.std(axis=0, ddof=1)
        sd = np.where(sd > 0, sd, fleet.std)
        return h.mean(axis=0), sd
    return fleet.mean, fleet.std


def deviation_z(current_ewm: np.ndarray, base_mu: np.ndarray, base_sd: np.ndarray) -> np.ndarray:
    return (np.asarray(current_ewm) - base_mu) / base_sd


def subsystem_scores(z_dev: Mapping[str, float], subsystem_of: Mapping[str, str]) -> dict[str, float]:
    groups: dict[str, list[float]] = defaultdict(list)
    for s, z in z_dev.items():
        groups[subsystem_of[s]].append(abs(float(z)))
    return {
        sub: round(min(100.0, 100.0 * float(np.mean(v)) / SCORE_Z_FULL_SCALE), 1)
        for sub in SUBSYSTEM_ORDER
        if (v := groups.get(sub))
    }


def sensor_contributions(
    contrib_row: np.ndarray, feature_names: Sequence[str], z_dev: Mapping[str, float], top: int = 3
) -> list[dict[str, float | str]]:
    """Aggregate SHAP values per sensor -> top contributors with % share and direction vs baseline."""
    per_sensor: dict[str, float] = defaultdict(float)
    for name, v in zip(feature_names, contrib_row[: len(feature_names)], strict=True):
        if name in META_FEATURES:
            continue
        sensor = name.rsplit("_", 1)[0]
        assert name.rsplit("_", 1)[1] in FEATURE_KINDS
        per_sensor[sensor] += float(v)
    total = sum(abs(v) for v in per_sensor.values()) or 1.0
    ranked = sorted(per_sensor.items(), key=lambda kv: abs(kv[1]), reverse=True)[:top]
    return [
        {
            "sensor": s,
            "pct": round(100 * abs(v) / total, 1),
            "effect_on_rul": "lowers" if v < 0 else "raises",
            "direction": "up" if z_dev.get(s, 0.0) >= 0 else "down",
        }
        for s, v in ranked
    ]
