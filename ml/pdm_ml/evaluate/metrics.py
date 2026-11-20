"""Evaluation metrics (docs/05 §7.5)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from pdm_ml.config import CRITICAL_RUL, WARNING_RUL

STATES: tuple[str, ...] = ("Healthy", "Warning", "Critical")
type ArrayLike = Sequence[float] | np.ndarray | pd.Series


def rmse(pred: ArrayLike, true: ArrayLike) -> float:
    d = np.asarray(pred, float) - np.asarray(true, float)
    return float(np.sqrt(np.mean(d**2)))


def nasa_score(pred: ArrayLike, true: ArrayLike) -> float:
    """PHM08 asymmetric score (PDF eq. 11); d = predicted - true, late predictions penalised more."""
    d = np.asarray(pred, float) - np.asarray(true, float)
    return float(np.sum(np.where(d < 0, np.exp(-d / 13.0) - 1, np.exp(d / 10.0) - 1)))


def coverage(true: ArrayLike, lo: ArrayLike, hi: ArrayLike) -> float:
    y = np.asarray(true, float)
    return float(np.mean((y >= np.asarray(lo)) & (y <= np.asarray(hi))))


def rul_state(rul: ArrayLike, warning: float = WARNING_RUL, critical: float = CRITICAL_RUL) -> np.ndarray:
    r = np.asarray(rul, float)
    return np.where(r <= critical, "Critical", np.where(r <= warning, "Warning", "Healthy"))


def alert_confusion(true_rul: ArrayLike, pred_rul: ArrayLike) -> pd.DataFrame:
    t = pd.Categorical(rul_state(true_rul), STATES)
    p = pd.Categorical(rul_state(pred_rul), STATES)
    return pd.crosstab(t, p, rownames=["true"], colnames=["predicted"], dropna=False)


def summarize(
    true: ArrayLike, pred: ArrayLike, lo: ArrayLike | None = None, hi: ArrayLike | None = None
) -> dict[str, float]:
    y, p = np.asarray(true, float), np.asarray(pred, float)
    cm = alert_confusion(y, p)
    crit_total = cm.loc["Critical"].sum()
    healthy_total = cm.loc["Healthy"].sum()
    out = {
        "n": float(len(y)),
        "rmse": rmse(p, y),
        "nasa_score": nasa_score(p, y),
        "mae": float(np.mean(np.abs(p - y))),
        "bias": float(np.mean(p - y)),
        "late_gt20_share": float(np.mean(p - y > 20)),
        "critical_recall": float(cm.loc["Critical", "Critical"] / crit_total) if crit_total else float("nan"),
        "false_critical_rate": float(cm.loc["Healthy", "Critical"] / healthy_total)
        if healthy_total
        else float("nan"),
    }
    if lo is not None and hi is not None:
        out["coverage_p10_p90"] = coverage(y, lo, hi)
        out["mean_interval_width"] = float(np.mean(np.asarray(hi) - np.asarray(lo)))
    return out


def rmse_by_bucket(true: ArrayLike, pred: ArrayLike) -> dict[str, float]:
    y, p = np.asarray(true, float), np.asarray(pred, float)
    edges = [(0, 30, "<=30"), (30, 75, "31-75"), (75, 125, "76-125"), (125, 10_000, ">125")]
    out = {}
    for lo, hi, name in edges:
        m = (y > lo) & (y <= hi) if lo else (y <= hi)
        out[name] = rmse(p[m], y[m]) if m.any() else float("nan")
    return out
