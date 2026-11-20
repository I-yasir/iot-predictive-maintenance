"""P1.6-P1.7, P1.9: grouped CV model selection, final fit and versioned bundles.

Never reads the official test files (that is pipelines/evaluate.py, run once).

    python ml/pipelines/train.py                      # all profiles, full selection
    python ml/pipelines/train.py --profiles FD001 --quick
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

from pdm_ml.config import (
    DEFAULT_INPUTS,
    MULTI_REGIME,
    PROFILES,
    RUL_CAP_DEFAULT,
    artifacts_dir,
    find_root,
    raw_dir,
    reports_dir,
)
from pdm_ml.diagnostics.subsystems import FleetBaseline
from pdm_ml.drift.reference import DriftReference
from pdm_ml.evaluate.cv import CVConfig, run_cv
from pdm_ml.features.pipeline import FeaturePipeline
from pdm_ml.io.loader import load_split, sensor_catalog
from pdm_ml.labels.rul import train_rul
from pdm_ml.models.bundle import ModelBundle, sha256_file, write_bundle
from pdm_ml.models.lgbm import RULModel, conformal_margin, fit_lgbm, fit_quantile, lgb_params

GRID: list[dict[str, Any]] = [
    {"num_leaves": nl, "min_child_samples": mc} for nl in (15, 31) for mc in (20, 50)
]
CAPS = (110, 125, 140, 160)  # 160 added after 140 won at the grid edge in every profile (CV only)
WINDOWS = (
    30,
    50,
    70,
    100,
)  # P1.10: longer windows improved CV on every profile (ml/reports/p110_experiment.json)
EXTRA_SENSORS_MULTI = ("P15", "farB")
MIN_GAIN_EXTRA = 0.3  # cycles of CV RMSE an extra sensor must buy (docs/05 §3.4)


def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=find_root(), text=True
        ).strip()
    except Exception:
        return "nogit"


def select(
    profile: str, train: pd.DataFrame, quick: bool
) -> tuple[CVConfig, list[dict[str, Any]], dict[str, Any]]:
    runs: list[dict[str, Any]] = []

    def cv(cfg: CVConfig, stage: str) -> dict[str, Any]:
        t0 = time.time()
        r = run_cv(train, cfg)
        r["stage"] = stage
        log(
            f"{profile} {stage:<8} {cfg.label():<60} RMSE {r['rmse_mean']:.2f} ± {r['rmse_std']:.2f} ({time.time() - t0:.0f}s)"
        )
        runs.append(r)
        return r

    sensors = DEFAULT_INPUTS[profile]
    grid = GRID[:1] if quick else GRID
    results = [
        cv(CVConfig(profile, sensors, RUL_CAP_DEFAULT, g, baseline=(i == 0)), "grid")
        for i, g in enumerate(grid)
    ]
    baseline = {
        "ridge_rmse_mean": results[0]["ridge_rmse_mean"],
        "ridge_rmse_std": results[0]["ridge_rmse_std"],
    }
    best = min(results, key=lambda r: r["rmse_mean"])
    best_params, best_cap, best_sensors, best_w = best["params"], RUL_CAP_DEFAULT, sensors, WINDOWS[0]

    if not quick:
        for w in WINDOWS[1:]:
            r = cv(CVConfig(profile, sensors, RUL_CAP_DEFAULT, best_params, window=w), "window")
            if r["rmse_mean"] < best["rmse_mean"]:
                best, best_w = r, w
        for c in CAPS:
            if c != RUL_CAP_DEFAULT:
                r = cv(CVConfig(profile, sensors, c, best_params, window=best_w), "cap")
                if r["rmse_mean"] < best["rmse_mean"]:
                    best, best_cap = r, c
        if profile in MULTI_REGIME:
            ext = (*sensors, *EXTRA_SENSORS_MULTI)
            r = cv(CVConfig(profile, ext, best_cap, best_params, window=best_w), "sensors")
            if r["rmse_mean"] <= best["rmse_mean"] - MIN_GAIN_EXTRA:
                best, best_sensors = r, ext

    final = CVConfig(profile, tuple(best_sensors), best_cap, best_params, quantiles=True, window=best_w)
    return final, runs, baseline


def train_profile(profile: str, quick: bool, version: str) -> dict[str, Any]:
    train = load_split(profile, "train")
    cfg, runs, baseline = select(profile, train, quick)
    log(f"{profile} selected {cfg.label()} -> calibration CV with quantile models")
    calib = run_cv(train, cfg)
    oof = calib["oof"]
    q = conformal_margin(oof.y.to_numpy(), oof.lo.to_numpy(), oof.hi.to_numpy(), 0.8)
    raw_cov = float(((oof.y >= oof.lo) & (oof.y <= oof.hi)).mean())
    cal_cov = float(((oof.y >= (oof.lo - q).clip(lower=0)) & (oof.y <= oof.hi + q)).mean())
    log(
        f"{profile} CV RMSE {calib['rmse_mean']:.2f}; interval coverage raw {raw_cov:.2f} -> conformal {cal_cov:.2f} (q={q:.1f})"
    )

    # ---- final fit on all training engines ----
    pipe = FeaturePipeline(profile, cfg.sensors, window=cfg.window, alpha=cfg.alpha).fit(train)
    cols = pipe.feature_names
    F = pipe.transform(train)
    life = train.groupby("unit").cycle.max()
    y = (F.unit.map(life) - F.cycle).clip(upper=cfg.cap).astype(float)
    params = lgb_params(cfg.params, cols)
    rounds = max(50, int(calib["best_iteration_mean"]))
    point = fit_lgbm(F[cols], y, params, num_boost_round=rounds)
    q10 = fit_quantile(F[cols], y, params, 0.1, rounds)
    q90 = fit_quantile(F[cols], y, params, 0.9, rounds)
    model = RULModel(cols, cfg.cap, point, q10, q90, q)

    z = pipe.normalize(train)
    rul = train_rul(train)
    fleet = FleetBaseline.fit(z, rul, pipe.sensors_used, cfg.cap)
    drift = DriftReference.fit(train.drop(columns=["unit", "cycle"]), z, rul, pipe.sensors_used, cfg.cap)
    cat = sensor_catalog()
    cv_summary = {
        "rmse_mean": calib["rmse_mean"],
        "rmse_std": calib["rmse_std"],
        "nasa_score_per_unit_mean": calib["nasa_score_per_unit_mean"],
        "ridge_rmse_mean": baseline["ridge_rmse_mean"],
        "interval_coverage_raw": raw_cov,
        "interval_coverage_conformal": cal_cov,
    }
    card = {
        "created_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "training": {
            "config": cfg.label(),
            "params": params,
            "rounds": rounds,
            "sensors": list(cfg.sensors),
            "sensors_used": list(pipe.sensors_used),
            "dropped_constant": pipe.normalizer.dropped_ if pipe.normalizer else [],
            "window": pipe.window,
            "ewm_alpha": pipe.alpha,
            "min_cycles": pipe.min_cycles,
            "train_units": int(train.unit.nunique()),
            "train_rows": len(train),
        },
        "data_sha256": {f"train_{profile}.txt": sha256_file(raw_dir() / f"train_{profile}.txt")},
        "cv": cv_summary,
        "test": None,  # filled by pipelines/evaluate.py
    }
    bundle = ModelBundle(
        profile, version, pipe, model, fleet, {s.symbol: s.subsystem for s in cat}, drift, card
    )
    path = write_bundle(artifacts_dir(), bundle)
    log(f"{profile} bundle written: {path}")

    report = {
        "profile": profile,
        "selected": cfg.label(),
        "cap": cfg.cap,
        "sensors": list(cfg.sensors),
        "params": cfg.params,
        "conformal_q": q,
        "baseline": baseline,
        "cv": cv_summary,
        "bundle_version": version,
        "runs": [{k: v for k, v in r.items() if k != "oof"} for r in runs],
    }
    reports_dir().mkdir(parents=True, exist_ok=True)
    (reports_dir() / f"cv_{profile}.json").write_text(json.dumps(report, indent=2, default=float))
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profiles", nargs="+", default=list(PROFILES), choices=PROFILES)
    ap.add_argument("--quick", action="store_true", help="single grid point, no ablations (smoke test)")
    ap.add_argument("--version", default=None, help="bundle version (default YYYYMMDD-<git sha>)")
    args = ap.parse_args(argv)
    version = args.version or f"{dt.date.today():%Y%m%d}-{git_sha()}"
    summary = {p: train_profile(p, args.quick, version) for p in args.profiles}
    log("done: " + ", ".join(f"{p} CV RMSE {r['cv']['rmse_mean']:.2f}" for p, r in summary.items()))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
