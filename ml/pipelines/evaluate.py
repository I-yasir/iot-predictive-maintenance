"""P1.8: ONE-TIME evaluation of the CURRENT bundles on the official test sets.

Predicts at the last observed cycle of every test engine and compares with RUL_FD00x.txt.
Writes ml/reports/test_{profile}.md/.json + plots and records the metrics in the model card.

    python ml/pipelines/evaluate.py
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from pdm_ml.config import PROFILES, artifacts_dir, reports_dir  # noqa: E402
from pdm_ml.evaluate.metrics import alert_confusion, rmse_by_bucket, summarize  # noqa: E402
from pdm_ml.io.loader import load_profile  # noqa: E402
from pdm_ml.labels.rul import test_rul  # noqa: E402
from pdm_ml.models.bundle import load_bundle, update_model_card  # noqa: E402

# PRD §4.1
TARGETS = {"FD001": (16.0, 500.0), "FD002": (22.0, 3000.0), "FD003": (16.0, 600.0), "FD004": (24.0, 4500.0)}


def evaluate_profile(profile: str) -> dict[str, Any]:
    b = load_bundle(artifacts_dir(), profile)
    d = load_profile(profile)
    F = b.predict_history(d.test)  # features + pred/lo/hi per cycle (LightGBM, or LightGBM+M2 mean)
    last = F.loc[F.groupby("unit").cycle.idxmax()].set_index("unit").sort_index()
    if len(last) != len(d.true_rul):
        raise RuntimeError(f"{profile}: {len(d.true_rul) - len(last)} test units shorter than min_cycles")
    y = d.true_rul.loc[last.index].to_numpy(float)
    pred, lo, hi = (last[c].to_numpy(float) for c in ("pred", "lo", "hi"))
    m = summarize(y, pred, lo, hi)
    m["rmse_by_true_rul"] = rmse_by_bucket(y, pred)
    rmse_t, score_t = TARGETS[profile]
    m["targets"] = {"rmse": rmse_t, "nasa_score": score_t}
    m["meets_rmse_target"] = m["rmse"] <= rmse_t
    m["meets_score_target"] = m["nasa_score"] <= score_t
    m["beats_ridge_15pct_cv"] = b.card["cv"]["rmse_mean"] <= 0.85 * b.card["cv"]["ridge_rmse_mean"]
    cm = alert_confusion(y, pred)

    out_dir = reports_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    _plots(profile, b, d, F, y, pred, lo, hi, last.index.to_numpy())
    (out_dir / f"test_{profile}.json").write_text(
        json.dumps({"model_version": b.version, **m}, indent=2, default=float)
    )
    md = [
        f"# Official test evaluation — {profile}",
        "",
        f"Model `{b.version}` · {int(m['n'])} test engines · last observed cycle vs `RUL_{profile}.txt` (uncapped truth).",
        f"Selected config: `{b.card['training']['config']}`"
        + (" + M2 sequence model (point = mean)" if b.seq is not None else "")
        + f" · conformal margin ±{b.model.conformal_q:.1f} cycles.",
        "",
        "| Metric | Value | Target |",
        "|---|---|---|",
        f"| RMSE (cycles) | **{m['rmse']:.2f}** | ≤ {rmse_t:g} {'✅' if m['meets_rmse_target'] else '❌'} |",
        f"| NASA score | **{m['nasa_score']:.0f}** | ≤ {score_t:g} {'✅' if m['meets_score_target'] else '❌'} |",
        f"| MAE | {m['mae']:.2f} | |",
        f"| Bias (pred − true) | {m['bias']:+.2f} | |",
        f"| Late by > 20 cycles | {m['late_gt20_share']:.1%} | ≤ 10% |",
        f"| P10–P90 coverage | {m['coverage_p10_p90']:.1%} | 75–90% |",
        f"| Mean interval width | {m['mean_interval_width']:.1f} | |",
        f"| Critical recall | {m['critical_recall']:.2f} | ≥ 0.90 |",
        f"| False Critical among healthy | {m['false_critical_rate']:.1%} | ≤ 5% |",
        f"| CV RMSE model / Ridge | {b.card['cv']['rmse_mean']:.2f} / {b.card['cv']['ridge_rmse_mean']:.2f} | ≥ 15% better {'✅' if m['beats_ridge_15pct_cv'] else '❌'} |",
        "",
        "RMSE by true RUL: " + " · ".join(f"{k}: {v:.1f}" for k, v in m["rmse_by_true_rul"].items()),
        "",
        "## Alert confusion (thresholds 75 / 30)",
        "",
        cm.to_markdown()
        if hasattr(cm, "to_markdown") and _has_tabulate()
        else "```\n" + cm.to_string() + "\n```",
        "",
        f"![pred vs true](test_{profile}_scatter.png)",
        f"![trajectories](test_{profile}_trajectories.png)",
    ]
    (out_dir / f"test_{profile}.md").write_text("\n".join(md) + "\n")
    update_model_card(artifacts_dir(), profile, b.version, {"test": {k: v for k, v in m.items()}})
    return m


def _has_tabulate() -> bool:
    try:
        import tabulate  # noqa: F401
    except ImportError:
        return False
    return True


def _plots(
    profile: str,
    b: Any,
    d: Any,
    F: pd.DataFrame,
    y: np.ndarray,
    pred: np.ndarray,
    lo: np.ndarray,
    hi: np.ndarray,
    units: np.ndarray,
) -> None:
    fig, ax = plt.subplots(figsize=(5.5, 5))
    ax.errorbar(y, pred, yerr=[pred - lo, hi - pred], fmt="o", ms=3, alpha=0.5, elinewidth=0.6)
    lim = max(200, float(y.max()) + 10)
    ax.plot([0, lim], [0, lim], "k--", lw=1)
    ax.set(xlabel="true RUL (cycles)", ylabel="predicted RUL (P10–P90)", title=f"{profile} test, last cycle")
    fig.tight_layout()
    fig.savefig(reports_dir() / f"test_{profile}_scatter.png", dpi=110)
    plt.close(fig)

    truth = test_rul(d.test, d.true_rul)
    order = np.argsort(y)
    pick = units[order[np.linspace(0, len(order) - 1, 6).astype(int)]]
    fig, axes = plt.subplots(2, 3, figsize=(13, 6), sharey=True)
    for ax, u in zip(axes.ravel(), pick, strict=True):
        g = F[F.unit == u]
        p, lo_g, hi_g = g.pred, g.lo, g.hi
        ax.fill_between(g.cycle, lo_g, hi_g, alpha=0.2)
        ax.plot(g.cycle, p, label="predicted")
        tr = truth[d.test.unit == u]
        ax.plot(d.test.cycle[d.test.unit == u], tr, "--", color="grey", label="true")
        ax.axhline(75, color="#D29922", ls=":", lw=1)
        ax.axhline(30, color="#F85149", ls=":", lw=1)
        ax.set_title(f"unit {u}")
    axes[0, 0].legend()
    fig.suptitle(f"{profile}: predicted vs true RUL over each test trajectory")
    fig.tight_layout()
    fig.savefig(reports_dir() / f"test_{profile}_trajectories.png", dpi=110)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profiles", nargs="+", default=list(PROFILES), choices=PROFILES)
    args = ap.parse_args(argv)
    rows = []
    for p in args.profiles:
        m = evaluate_profile(p)
        rows.append(
            {
                "profile": p,
                "rmse": m["rmse"],
                "nasa_score": m["nasa_score"],
                "coverage": m["coverage_p10_p90"],
                "critical_recall": m["critical_recall"],
                "meets_rmse": m["meets_rmse_target"],
            }
        )
    print(pd.DataFrame(rows).set_index("profile").round(3).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
