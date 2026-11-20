"""Operating-regime assignment and regime-wise normalisation (docs/05 §5 steps 2-3).

Fit on training engines only. Used verbatim by training and by the online service.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans

from pdm_ml.config import MULTI_REGIME, N_REGIMES_MULTI, SEED, SETTINGS

OOD_REGIME_SIGMA = 6.0


@dataclass
class RegimeNormalizer:
    profile: str
    sensors: tuple[str, ...]
    # fitted state
    settings_mean_: np.ndarray | None = None
    settings_std_: np.ndarray | None = None
    centroids_: np.ndarray | None = None
    regime_dist_limit_: np.ndarray | None = None  # per regime: mean + 6*std of training distances
    mu_: np.ndarray | None = None  # (n_regimes, n_sensors)
    sd_: np.ndarray | None = None
    dropped_: list[str] = field(default_factory=list)

    @property
    def multi_regime(self) -> bool:
        return self.profile in MULTI_REGIME

    @property
    def n_regimes(self) -> int:
        return N_REGIMES_MULTI if self.multi_regime else 1

    def fit(self, df: pd.DataFrame) -> RegimeNormalizer:
        if self.multi_regime:
            s = df[list(SETTINGS)].to_numpy(float)
            self.settings_mean_ = s.mean(axis=0)
            self.settings_std_ = s.std(axis=0)
            self.settings_std_[self.settings_std_ == 0] = 1.0
            km = KMeans(n_clusters=N_REGIMES_MULTI, n_init=10, random_state=SEED)
            labels = km.fit_predict((s - self.settings_mean_) / self.settings_std_)
            # canonical order: sort clusters by centroid in original units so regime ids are stable
            cents = km.cluster_centers_ * self.settings_std_ + self.settings_mean_
            order = np.lexsort((cents[:, 2], cents[:, 1], cents[:, 0]))
            remap = np.empty_like(order)
            remap[order] = np.arange(len(order))
            self.centroids_ = km.cluster_centers_[order]
            labels = remap[labels]
            d = self._distances((s - self.settings_mean_) / self.settings_std_)
            own = d[np.arange(len(labels)), labels]
            self.regime_dist_limit_ = np.array(
                [
                    own[labels == r].mean() + OOD_REGIME_SIGMA * own[labels == r].std() + 1e-9
                    for r in range(N_REGIMES_MULTI)
                ]
            )
        else:
            labels = np.zeros(len(df), dtype=int)
        x = df[list(self.sensors)].to_numpy(float)
        self.mu_ = np.vstack([x[labels == r].mean(axis=0) for r in range(self.n_regimes)])
        sd = np.vstack([x[labels == r].std(axis=0, ddof=1) for r in range(self.n_regimes)])
        self.dropped_ = [s for j, s in enumerate(self.sensors) if np.all(sd[:, j] == 0)]
        sd[sd == 0] = np.nan
        self.sd_ = sd
        return self

    def _distances(self, z: np.ndarray) -> np.ndarray:
        assert self.centroids_ is not None
        return np.sqrt(((z[:, None, :] - self.centroids_[None, :, :]) ** 2).sum(axis=2))

    def assign(self, settings: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Return (regime id, is_ood) for an (n, 3) array of settings."""
        settings = np.atleast_2d(np.asarray(settings, float))
        if not self.multi_regime:
            return np.zeros(len(settings), dtype=int), np.zeros(len(settings), dtype=bool)
        assert self.settings_mean_ is not None and self.settings_std_ is not None
        assert self.regime_dist_limit_ is not None
        d = self._distances((settings - self.settings_mean_) / self.settings_std_)
        r = d.argmin(axis=1)
        return r, d[np.arange(len(r)), r] > self.regime_dist_limit_[r]

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return a copy with `regime`, `regime_ood` columns and z-scored sensors."""
        if self.mu_ is None or self.sd_ is None:
            raise RuntimeError("RegimeNormalizer is not fitted")
        out = df.copy()
        r, ood = self.assign(df[list(SETTINGS)].to_numpy(float))
        out["regime"] = r
        out["regime_ood"] = ood
        x = df[list(self.sensors)].to_numpy(float)
        out[list(self.sensors)] = (x - self.mu_[r]) / self.sd_[r]
        return out

    def transform_one(
        self, settings: Sequence[float], sensors: Mapping[str, float]
    ) -> tuple[int, bool, np.ndarray]:
        """Online path: one cycle -> (regime, regime_ood, z vector in self.sensors order)."""
        if self.mu_ is None or self.sd_ is None:
            raise RuntimeError("RegimeNormalizer is not fitted")
        r_arr, ood_arr = self.assign(np.asarray(settings, float)[None, :])
        r = int(r_arr[0])
        x = np.array([float(sensors[s]) for s in self.sensors])
        return r, bool(ood_arr[0]), (x - self.mu_[r]) / self.sd_[r]
