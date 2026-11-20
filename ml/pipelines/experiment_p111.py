"""P1.11 experiment (CV only, never touches test files): M2 1D-CNN sequence model vs. the active LightGBM.

Same GroupKFold folds, inner early-stopping split and truncation points as `pdm_ml.evaluate.cv.run_cv`, so
every candidate is scored on identical points. Candidates per profile:
  lgbm         the active p3 configuration (sanity check: must reproduce cv_{profile}.json)
  m2_*         sequence model variants
  ens_*        mean of lgbm and an m2 variant

Adoption rule, fixed BEFORE running (docs/05 §7.5.5): the best candidate by primary CV RMSE [10, 150] replaces
LightGBM for a profile only if it improves primary RMSE by >= 0.5 cycles AND does not worsen the wide
[5, 200] RMSE by more than 0.2. Otherwise LightGBM stays.

    python ml/pipelines/experiment_p111.py FD002 FD004 > ml/reports/p111_experiment.json
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold, GroupShuffleSplit

from pdm_ml.config import DEFAULT_INPUTS, SEED, artifacts_dir
from pdm_ml.evaluate.cv import PRIMARY_RUL_RANGE, truncation_points
from pdm_ml.evaluate.metrics import rmse
from pdm_ml.features.pipeline import FeaturePipeline
from pdm_ml.io.loader import load_split
from pdm_ml.models.lgbm import fit_lgbm, fit_quantile, lgb_params
from pdm_ml.models.seq import SeqConfig, SeqModel, build_windows

LGBM_ACTIVE = {  # p3 selections (docs/05 §7.5.4)
    "FD002": {"window": 100, "params": {"num_leaves": 31, "min_child_samples": 20}},
    "FD004": {"window": 70, "params": {"num_leaves": 31, "min_child_samples": 50}},
    "FD001": {"window": 50, "params": {"num_leaves": 31, "min_child_samples": 20}},
    "FD003": {"window": 70, "params": {"num_leaves": 31, "min_child_samples": 50}},
}
M2_VARIANTS: dict[str, SeqConfig] = {
    "m2_L50": SeqConfig(seq_len=50),
    "m2_L100": SeqConfig(seq_len=100),
    "m2_L50_cap150": SeqConfig(seq_len=50, cap=150),
}
CAP = 125


def _labels(idx: pd.DataFrame, life: pd.Series, cap: int) -> np.ndarray:
    return np.minimum(idx.unit.map(life).to_numpy() - idx.cycle.to_numpy(), cap).astype(np.float32)


def run_profile(p: str, variants: dict[str, SeqConfig], oof_variant: str | None = None) -> dict[str, Any]:
    """`oof_variant`: also fit LightGBM quantiles and return out-of-fold rows for the LightGBM+variant
    ensemble (y, pred, lo, hi), used by train_m2.py for the conformal margin."""
    train = load_split(p, "train")
    life = train.groupby("unit").cycle.max()
    rng = np.random.default_rng(SEED)
    act = LGBM_ACTIVE[p]
    sensors = DEFAULT_INPUTS[p]
    res: dict[str, dict[str, list[float]]] = {}
    epochs: dict[str, list[int]] = {k: [] for k in variants}
    oof: list[pd.DataFrame] = []

    def score(name: str, pred: np.ndarray, y: np.ndarray, prim: np.ndarray) -> None:
        r = res.setdefault(name, {"prim": [], "wide": []})
        r["prim"].append(rmse(pred[prim], y[prim]))
        r["wide"].append(rmse(pred, y))

    for k, (tr_idx, va_idx) in enumerate(GroupKFold(5).split(train, groups=train.unit.to_numpy())):
        t0 = time.time()
        tr, va = train.iloc[tr_idx], train.iloc[va_idx]
        fit_idx, es_idx = next(GroupShuffleSplit(n_splits=1, test_size=0.15, random_state=SEED + k)
                               .split(tr, groups=tr.unit))
        tr_fit, tr_es = tr.iloc[fit_idx], tr.iloc[es_idx]
        pipe = FeaturePipeline(p, sensors, window=act["window"]).fit(tr_fit)
        cols = pipe.feature_names
        F_fit, F_es, F_va = pipe.transform(tr_fit), pipe.transform(tr_es), pipe.transform(va)
        params = lgb_params(act["params"], cols)
        model = fit_lgbm(F_fit[cols], _labels(F_fit, life, CAP), params,
                         X_val=F_es[cols], y_val=_labels(F_es, life, CAP))
        T = truncation_points(F_va, life, rng)  # identical draws to run_cv
        y = (T.unit.map(life) - T.cycle).to_numpy(float)
        prim = (y >= PRIMARY_RUL_RANGE[0]) & (y <= PRIMARY_RUL_RANGE[1])
        p_lgbm = np.clip(model.predict(T[cols], num_iteration=model.best_iteration), 0, CAP)
        score("lgbm", p_lgbm, y, prim)

        su = pipe.sensors_used
        z_fit, z_es, z_va = pipe.normalize(tr_fit), pipe.normalize(tr_es), pipe.normalize(va)
        for name, cfg in variants.items():
            X_fit, i_fit = build_windows(z_fit, su, cfg.seq_len)
            X_es, i_es = build_windows(z_es, su, cfg.seq_len)
            X_va, i_va = build_windows(z_va, su, cfg.seq_len)
            m = SeqModel(su, cfg).fit(X_fit, _labels(i_fit, life, cfg.cap), X_es, _labels(i_es, life, cfg.cap))
            epochs[name] += m.epochs
            pos = pd.MultiIndex.from_frame(i_va).get_indexer(pd.MultiIndex.from_frame(T[["unit", "cycle"]]))
            assert (pos >= 0).all()
            p_m2 = m.predict(X_va[pos])
            score(name, p_m2, y, prim)
            score(f"ens_lgbm+{name}", (p_lgbm + p_m2) / 2, y, prim)
            if name == oof_variant:
                n_it = model.best_iteration or model.current_iteration()
                ens = (p_lgbm + p_m2) / 2
                q10 = fit_quantile(F_fit[cols], _labels(F_fit, life, CAP), params, 0.1, n_it)
                q90 = fit_quantile(F_fit[cols], _labels(F_fit, life, CAP), params, 0.9, n_it)
                lo = np.minimum(np.clip(q10.predict(T[cols]), 0, CAP), ens)
                hi = np.maximum(np.clip(q90.predict(T[cols]), 0, CAP), ens)
                oof.append(pd.DataFrame({"fold": k, "y": y, "pred": ens, "lo": lo, "hi": hi, "prim": prim}))
        print(f"{p} fold {k} {time.time() - t0:.0f}s "
              + " ".join(f"{n}={v['prim'][-1]:.2f}" for n, v in res.items()), file=sys.stderr, flush=True)

    summary = {n: {"rmse_10_150": round(float(np.mean(v["prim"])), 2), "std": round(float(np.std(v["prim"])), 2),
                   "rmse_5_200": round(float(np.mean(v["wide"])), 2), "fold_10_150": [round(x, 2) for x in v["prim"]]}
               for n, v in res.items()}
    base = summary["lgbm"]
    best = min((n for n in summary if n != "lgbm"), key=lambda n: summary[n]["rmse_10_150"])
    adopt = (base["rmse_10_150"] - summary[best]["rmse_10_150"] >= 0.5
             and summary[best]["rmse_5_200"] - base["rmse_5_200"] <= 0.2)
    return {"candidates": summary, "epochs": {k: v for k, v in epochs.items()}, "best": best,
            "adopt": bool(adopt), "decision": best if adopt else "lgbm",
            "oof": pd.concat(oof, ignore_index=True) if oof else None}


def main() -> int:
    profiles = [a for a in sys.argv[1:] if a.startswith("FD")] or ["FD002", "FD004"]
    variants = M2_VARIANTS
    if "--quick" in sys.argv:
        variants = {"m2_L50": SeqConfig(seq_len=50, max_epochs=3)}
    out = {"rule": "adopt best candidate if primary CV RMSE improves >= 0.5 and wide worsens <= 0.2",
           "artifacts_root": str(artifacts_dir().name)}
    for p in profiles:
        out[p] = run_profile(p, variants)
        out[p].pop("oof")
        print(p, json.dumps({k: v["rmse_10_150"] for k, v in out[p]["candidates"].items()}), file=sys.stderr)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
