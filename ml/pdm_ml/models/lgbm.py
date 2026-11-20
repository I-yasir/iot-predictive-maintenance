"""Model ladder (docs/05 §7): M0 Ridge baseline, M1 LightGBM point + quantile models, split-conformal widening."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import RidgeCV

from pdm_ml.config import SEED

BASE_PARAMS: dict[str, Any] = {
    "objective": "regression",
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_child_samples": 20,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "seed": SEED,
    "deterministic": True,
    "force_row_wise": True,
    "verbose": -1,
    "num_threads": 0,
}
MAX_ROUNDS = 2000
EARLY_STOPPING = 100


def lgb_params(
    overrides: dict[str, Any] | None = None, feature_names: list[str] | None = None
) -> dict[str, Any]:
    p = {**BASE_PARAMS, **(overrides or {})}
    if feature_names is not None and "cycle" in feature_names:
        # RUL can only decrease as cycles increase, all else equal
        p["monotone_constraints"] = [-1 if f == "cycle" else 0 for f in feature_names]
    return p


def fit_lgbm(
    X: pd.DataFrame,
    y: pd.Series | np.ndarray,
    params: dict[str, Any],
    num_boost_round: int | None = None,
    X_val: pd.DataFrame | None = None,
    y_val: pd.Series | np.ndarray | None = None,
) -> lgb.Booster:
    train = lgb.Dataset(X, y, free_raw_data=True)
    if X_val is not None and y_val is not None:
        return lgb.train(
            params,
            train,
            num_boost_round=num_boost_round or MAX_ROUNDS,
            valid_sets=[lgb.Dataset(X_val, y_val, reference=train)],
            callbacks=[lgb.early_stopping(EARLY_STOPPING, verbose=False)],
        )
    return lgb.train(params, train, num_boost_round=num_boost_round or MAX_ROUNDS)


def fit_quantile(
    X: pd.DataFrame, y: pd.Series | np.ndarray, params: dict[str, Any], alpha: float, rounds: int
) -> lgb.Booster:
    # LightGBM does not support monotone constraints with the quantile objective
    q = {k: v for k, v in params.items() if k != "monotone_constraints"}
    return lgb.train(
        {**q, "objective": "quantile", "alpha": alpha}, lgb.Dataset(X, y), num_boost_round=rounds
    )


@dataclass
class RidgeBaseline:
    """M0: standardised features + RidgeCV."""

    mu_: pd.Series | None = None
    sd_: pd.Series | None = None
    model_: RidgeCV | None = None

    def fit(self, X: pd.DataFrame, y: pd.Series | np.ndarray) -> RidgeBaseline:
        self.mu_, self.sd_ = X.mean(), X.std().replace(0, 1.0)
        self.model_ = RidgeCV(alphas=np.logspace(-2, 3, 12)).fit((X - self.mu_) / self.sd_, y)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        assert self.model_ is not None
        return np.asarray(self.model_.predict((X - self.mu_) / self.sd_))


def conformal_margin(y: np.ndarray, lo: np.ndarray, hi: np.ndarray, target: float = 0.8) -> float:
    """Split-conformal (CQR) margin: widen [lo, hi] by q so empirical coverage >= target."""
    scores = np.maximum(np.asarray(lo) - y, y - np.asarray(hi))
    n = len(scores)
    level = min(1.0, np.ceil((n + 1) * target) / n)
    return float(max(0.0, np.quantile(scores, level, method="higher")))


@dataclass
class RULModel:
    """Point + interval model for one profile, operating on FeaturePipeline features."""

    feature_names: list[str]
    cap: int
    point: lgb.Booster
    q10: lgb.Booster
    q90: lgb.Booster
    conformal_q: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)

    def predict(self, X: pd.DataFrame | np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        Xa = X[self.feature_names] if isinstance(X, pd.DataFrame) else np.atleast_2d(X)
        pred = np.clip(self.point.predict(Xa), 0, self.cap)
        lo = np.clip(self.q10.predict(Xa), 0, self.cap)
        hi = np.clip(self.q90.predict(Xa), 0, self.cap)
        lo, hi = np.minimum(lo, pred), np.maximum(hi, pred)
        lo = np.clip(lo - self.conformal_q, 0, None)
        hi = hi + self.conformal_q  # upper bound may exceed the cap: truth can
        return pred, lo, hi

    def contributions(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        """SHAP values (n, n_features + 1); last column = base value. Sum = raw (unclipped) prediction."""
        Xa = X[self.feature_names] if isinstance(X, pd.DataFrame) else np.atleast_2d(X)
        return np.asarray(self.point.predict(Xa, pred_contrib=True))
