"""P1.11: build LightGBM + M2 ensemble bundles for the profiles where the pre-registered CV rule adopted it.

Reads ml/reports/p111_experiment.json (decision per profile). For each adopted profile:
  1. calibration CV of the ensemble (same folds/points) -> split-conformal margin and coverage
  2. M2 refit on all training engines for the median CV epoch count, on the active bundle's normaliser
  3. new bundle = active LightGBM point/quantile models + preprocessor + M2, CURRENT moved to it

    python ml/pipelines/train_m2.py --version 20261120-p4
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import Any

import numpy as np
from experiment_p111 import CAP, M2_VARIANTS, run_profile  # same directory
from train import git_sha

from pdm_ml.config import artifacts_dir, reports_dir
from pdm_ml.io.loader import load_split
from pdm_ml.models.bundle import ModelBundle, load_bundle, write_bundle
from pdm_ml.models.lgbm import RULModel, conformal_margin
from pdm_ml.models.seq import SeqModel, build_windows


def build(profile: str, variant: str, version: str, experiment: dict[str, Any]) -> dict[str, Any]:
    cfg = M2_VARIANTS[variant]
    calib = run_profile(profile, {variant: cfg}, oof_variant=variant)
    oof = calib["oof"]
    q = conformal_margin(oof.y.to_numpy(), oof.lo.to_numpy(), oof.hi.to_numpy(), 0.8)
    raw_cov = float(((oof.y >= oof.lo) & (oof.y <= oof.hi)).mean())
    cal_cov = float(((oof.y >= (oof.lo - q).clip(lower=0)) & (oof.y <= oof.hi + q)).mean())
    ens = calib["candidates"][f"ens_lgbm+{variant}"]
    epochs = int(np.median(experiment["epochs"][variant]))
    print(f"{profile}: ensemble CV {ens['rmse_10_150']} (wide {ens['rmse_5_200']}); coverage raw {raw_cov:.3f} "
          f"-> conformal {cal_cov:.3f} (q={q:.1f}); M2 refit {epochs} epochs", file=sys.stderr, flush=True)

    base = load_bundle(artifacts_dir(), profile)
    if base.seq is not None:
        raise RuntimeError(f"{profile}: CURRENT ({base.version}) already has an M2 model")
    train = load_split(profile, "train")
    life = train.groupby("unit").cycle.max()
    X, idx = build_windows(base.pipeline.normalize(train), base.pipeline.sensors_used, cfg.seq_len,
                           base.pipeline.min_cycles)
    y = np.minimum(idx.unit.map(life).to_numpy() - idx.cycle.to_numpy(), cfg.cap).astype(np.float32)
    seq = SeqModel(base.pipeline.sensors_used, cfg).fit_fixed(X, y, epochs)

    m = base.model
    model = RULModel(m.feature_names, CAP, m.point, m.q10, m.q90, q, needs_seq=True)
    card = {k: v for k, v in base.card.items() if k not in ("test", "seq_model", "library_versions")}
    card.update({
        "created_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "derived_from": base.version,
        "point_estimate": f"mean(LightGBM {base.version}, M2 {variant})",
        "cv": {**base.card["cv"], "rmse_mean": ens["rmse_10_150"], "rmse_std": ens["std"],
               "rmse_wide_mean": ens["rmse_5_200"], "lgbm_rmse_mean": base.card["cv"]["rmse_mean"],
               "interval_coverage_raw": raw_cov, "interval_coverage_conformal": cal_cov},
        "test": None,
    })
    bundle = ModelBundle(profile, version, base.pipeline, model, base.fleet_baseline, base.subsystem_of,
                         base.drift, card, seq=seq)
    path = write_bundle(artifacts_dir(), bundle)
    print(f"{profile}: wrote {path}", file=sys.stderr)
    return {"profile": profile, "variant": variant, "conformal_q": q, "coverage_raw": raw_cov,
            "coverage_conformal": cal_cov, "cv": ens, "epochs": epochs, "derived_from": base.version}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", required=True)
    args = ap.parse_args(argv)
    exp = json.loads((reports_dir() / "p111_experiment.json").read_text())
    out = []
    for p in ("FD001", "FD002", "FD003", "FD004"):
        if p in exp and exp[p]["adopt"]:
            variant = exp[p]["decision"].removeprefix("ens_lgbm+")
            if variant not in M2_VARIANTS:
                raise SystemExit(f"{p}: decision {exp[p]['decision']} is not an ensemble this script builds")
            out.append(build(p, variant, args.version, exp[p]))
    (reports_dir() / "p111_bundles.json").write_text(json.dumps(out, indent=2, default=float) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
