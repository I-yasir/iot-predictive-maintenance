"""Leakage-safe grouped cross-validation (docs/05 §6).

* Split by engine (GroupKFold); FeaturePipeline refit inside each fold on fold-train engines only.
* Early stopping uses an inner hold-out of fold-train engines (never the validation fold).
* Validation mimics the official test set: truncation points with at least min(31, life) observed cycles,
  sampled with true remaining life in [5, 200] and scored against the UNCAPPED truth so caps are comparable.
  Primary metric `rmse_mean` = points in the documented challenge range [10, 150] (PDF);
  `rmse_wide_mean` = all sampled points [5, 200] (long-horizon behaviour, P1.10).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold, GroupShuffleSplit

from pdm_ml.config import EWM_ALPHA, SEED, WINDOW
from pdm_ml.evaluate.metrics import nasa_score, rmse
from pdm_ml.features.pipeline import FeaturePipeline
from pdm_ml.models.lgbm import RidgeBaseline, blend_horizons, fit_lgbm, fit_quantile, lgb_params

TRUNC_PER_UNIT = 5
# PDF (Saxena et al., §IV): "The test data set RULs ranged between 10 and 150 cycles" -> primary range
PRIMARY_RUL_RANGE = (10, 150)
TRUNC_RUL_RANGE = (5, 200)  # sampling range; wide metric
MIN_OBSERVED = 31


@dataclass
class CVConfig:
    profile: str
    sensors: tuple[str, ...]
    cap: int
    params: dict[str, Any] = field(default_factory=dict)
    quantiles: bool = False
    baseline: bool = False
    cap_high: int | None = None  # P1.10 horizon blend: second point model trained with a higher cap
    window: int = WINDOW
    alpha: float = EWM_ALPHA

    def label(self) -> str:
        p = ",".join(f"{k}={v}" for k, v in sorted(self.params.items()))
        blend = f";blend={self.cap_high}" if self.cap_high else ""
        feat = "" if (self.window, self.alpha) == (WINDOW, EWM_ALPHA) else f";W={self.window},a={self.alpha}"
        return f"cap={self.cap}{blend};n_sensors={len(self.sensors)}{feat};{p}"


def truncation_points(feats: pd.DataFrame, life: pd.Series, rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for u, g in feats.groupby("unit", sort=False):
        L = int(life[u])
        rem = L - g.cycle
        cand = g[
            (g.cycle >= min(MIN_OBSERVED, L)) & (rem >= TRUNC_RUL_RANGE[0]) & (rem <= TRUNC_RUL_RANGE[1])
        ]
        if len(cand):
            rows.append(
                cand.sample(min(TRUNC_PER_UNIT, len(cand)), random_state=int(rng.integers(2**31 - 1)))
            )
    return pd.concat(rows)


def run_cv(train: pd.DataFrame, cfg: CVConfig, n_splits: int = 5) -> dict[str, Any]:
    rng = np.random.default_rng(SEED)
    life = train.groupby("unit").cycle.max()
    units = train.unit.to_numpy()
    fold_rmse, fold_wide, fold_score, ridge_rmse, iters, iters_high = [], [], [], [], [], []
    oof: list[pd.DataFrame] = []
    for k, (tr_idx, va_idx) in enumerate(GroupKFold(n_splits).split(train, groups=units)):
        tr, va = train.iloc[tr_idx], train.iloc[va_idx]
        # inner split of fold-train engines for early stopping
        inner = GroupShuffleSplit(n_splits=1, test_size=0.15, random_state=SEED + k)
        fit_idx, es_idx = next(inner.split(tr, groups=tr.unit))
        tr_fit, tr_es = tr.iloc[fit_idx], tr.iloc[es_idx]

        pipe = FeaturePipeline(cfg.profile, cfg.sensors, window=cfg.window, alpha=cfg.alpha).fit(tr_fit)
        cols = pipe.feature_names
        F_fit, F_es, F_va = pipe.transform(tr_fit), pipe.transform(tr_es), pipe.transform(va)
        # labels aligned with gated feature rows via (unit, cycle); life = last cycle of run-to-failure unit
        y_fit = _labels(F_fit, life, cfg.cap)
        y_es = _labels(F_es, life, cfg.cap)
        params = lgb_params(cfg.params, cols)
        model = fit_lgbm(F_fit[cols], y_fit, params, X_val=F_es[cols], y_val=y_es)
        iters.append(model.best_iteration or model.current_iteration())

        T = truncation_points(F_va, life, rng)
        y_true = (T.unit.map(life) - T.cycle).to_numpy(float)
        pred = np.clip(model.predict(T[cols], num_iteration=model.best_iteration), 0, cfg.cap)
        hi_cap = cfg.cap
        if cfg.cap_high:
            m_hi = fit_lgbm(
                F_fit[cols],
                _labels(F_fit, life, cfg.cap_high),
                params,
                X_val=F_es[cols],
                y_val=_labels(F_es, life, cfg.cap_high),
            )
            iters_high.append(m_hi.best_iteration or m_hi.current_iteration())
            p_hi = np.clip(m_hi.predict(T[cols], num_iteration=m_hi.best_iteration), 0, cfg.cap_high)
            pred = blend_horizons(pred, p_hi, cfg.cap)
            hi_cap = cfg.cap_high
        prim = (y_true >= PRIMARY_RUL_RANGE[0]) & (y_true <= PRIMARY_RUL_RANGE[1])
        fold_rmse.append(rmse(pred[prim], y_true[prim]))
        fold_wide.append(rmse(pred, y_true))
        fold_score.append(nasa_score(pred[prim], y_true[prim]) / prim.sum())
        rec = pd.DataFrame(
            {"fold": k, "unit": T.unit.to_numpy(), "cycle": T.cycle.to_numpy(), "y": y_true, "pred": pred}
        )
        if cfg.quantiles:
            n = iters[-1]
            q10 = fit_quantile(F_fit[cols], y_fit, params, 0.1, n)
            y_hi = _labels(F_fit, life, hi_cap)  # upper quantile learns the long horizon when blending
            q90 = fit_quantile(F_fit[cols], y_hi, params, 0.9, iters_high[-1] if cfg.cap_high else n)
            lo = np.minimum(np.clip(q10.predict(T[cols]), 0, cfg.cap), pred)
            hi = np.maximum(np.clip(q90.predict(T[cols]), 0, hi_cap), pred)
            rec["lo"], rec["hi"] = lo, hi
        if cfg.baseline:
            rb = RidgeBaseline().fit(F_fit[cols], y_fit)
            ridge_rmse.append(rmse(np.clip(rb.predict(T[cols]), 0, cfg.cap)[prim], y_true[prim]))
        oof.append(rec)
    out: dict[str, Any] = {
        "config": cfg.label(),
        "cap": cfg.cap,
        "sensors": list(cfg.sensors),
        "params": cfg.params,
        "rmse_mean": float(np.mean(fold_rmse)),
        "rmse_std": float(np.std(fold_rmse)),
        "rmse_wide_mean": float(np.mean(fold_wide)),
        "cap_high": cfg.cap_high,
        "window": cfg.window,
        "alpha": cfg.alpha,
        "best_iteration_high_mean": int(np.mean(iters_high)) if iters_high else None,
        "nasa_score_per_unit_mean": float(np.mean(fold_score)),
        "best_iteration_mean": int(np.mean(iters)),
        "fold_rmse": [float(x) for x in fold_rmse],
        "oof": pd.concat(oof, ignore_index=True),
    }
    if cfg.baseline:
        out["ridge_rmse_mean"] = float(np.mean(ridge_rmse))
        out["ridge_rmse_std"] = float(np.std(ridge_rmse))
    return out


def _labels(feats: pd.DataFrame, life: pd.Series, cap_value: int) -> np.ndarray:
    return np.minimum(feats.unit.map(life).to_numpy() - feats.cycle.to_numpy(), cap_value).astype(float)
