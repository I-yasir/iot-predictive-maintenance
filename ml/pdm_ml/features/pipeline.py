"""FeaturePipeline = RegimeNormalizer + causal window features, with batch and streaming entry points.

This object is serialised into the model bundle (preprocessor.joblib) and is the ONLY feature code the
backend may use (CLAUDE.md: one feature implementation).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from pdm_ml.config import EWM_ALPHA, MIN_CYCLES, WINDOW
from pdm_ml.features.regimes import RegimeNormalizer
from pdm_ml.features.window import StreamState, feature_names, window_features_batch


@dataclass
class StreamResult:
    regime: int
    regime_ood: bool
    z: np.ndarray  # regime-normalised current values (pipeline.sensors order)
    ewm: np.ndarray  # smoothed values
    features: np.ndarray | None  # None while warming up
    n_seen: int


@dataclass
class FeaturePipeline:
    profile: str
    sensors: tuple[str, ...]
    window: int = WINDOW
    alpha: float = EWM_ALPHA
    min_cycles: int = MIN_CYCLES
    normalizer: RegimeNormalizer | None = None
    sensors_used: tuple[str, ...] = field(default_factory=tuple)

    def fit(self, train_df: pd.DataFrame) -> FeaturePipeline:
        self.normalizer = RegimeNormalizer(self.profile, tuple(self.sensors)).fit(train_df)
        self.sensors_used = tuple(s for s in self.sensors if s not in self.normalizer.dropped_)
        return self

    @property
    def feature_names(self) -> list[str]:
        return feature_names(self.sensors_used)

    def _norm(self) -> RegimeNormalizer:
        if self.normalizer is None:
            raise RuntimeError("FeaturePipeline is not fitted")
        return self.normalizer

    def normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        return self._norm().transform(df)

    def transform(self, df: pd.DataFrame, gate: bool = True) -> pd.DataFrame:
        """Batch features for whole trajectories. Keeps unit, cycle, row_in_unit, regime, regime_ood."""
        z = self.normalize(df).sort_values(["unit", "cycle"], kind="stable").reset_index(drop=True)
        feats = window_features_batch(
            z, self.sensors_used, self.window, self.alpha, self.min_cycles, gate=False
        )
        feats["regime"] = z["regime"].to_numpy()
        feats["regime_ood"] = z["regime_ood"].to_numpy()
        if gate:
            feats = feats[feats.row_in_unit >= self.min_cycles - 1].reset_index(drop=True)
        return feats

    # ---- streaming ----
    def new_stream(self) -> StreamState:
        return StreamState(self.sensors_used, self.window, self.alpha, self.min_cycles)

    def update(
        self, state: StreamState, cycle: int, settings: Sequence[float], sensors: Mapping[str, float]
    ) -> StreamResult:
        norm = self._norm()
        regime, ood, z_all = norm.transform_one(settings, sensors)
        idx = [norm.sensors.index(s) for s in self.sensors_used]
        z = z_all[idx]
        feats = state.update(cycle, z)
        assert state.ewm is not None
        return StreamResult(regime, ood, z, state.ewm.copy(), feats, state.n_seen)
