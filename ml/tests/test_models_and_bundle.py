"""P1.6-P1.9 on a small FD001 slice: metrics, CV, intervals, contributions, diagnostics, bundle integrity."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pdm_ml.config import DEFAULT_INPUTS, SETTINGS
from pdm_ml.diagnostics.subsystems import FleetBaseline, sensor_contributions, subsystem_scores
from pdm_ml.drift.reference import DriftReference
from pdm_ml.evaluate.cv import CVConfig, run_cv
from pdm_ml.evaluate.metrics import alert_confusion, nasa_score, rmse
from pdm_ml.features.pipeline import FeaturePipeline
from pdm_ml.io.loader import sensor_catalog
from pdm_ml.labels.rul import train_rul
from pdm_ml.models.bundle import BundleIntegrityError, ModelBundle, load_bundle, write_bundle
from pdm_ml.models.lgbm import RULModel, conformal_margin, fit_lgbm, fit_quantile, lgb_params


def test_nasa_score_is_asymmetric() -> None:
    assert nasa_score([110], [100]) > nasa_score([90], [100]) > 0
    assert nasa_score([100], [100]) == 0
    assert rmse([1, 3], [1, 1]) == pytest.approx(np.sqrt(2))


def test_alert_confusion_shape() -> None:
    cm = alert_confusion([10, 50, 100], [12, 80, 100])
    assert cm.shape == (3, 3) and cm.to_numpy().sum() == 3


def test_conformal_margin_reaches_target() -> None:
    rng = np.random.default_rng(0)
    y = rng.normal(0, 1, 2000)
    lo, hi = np.full_like(y, -0.5), np.full_like(y, 0.5)
    q = conformal_margin(y, lo, hi, 0.8)
    assert np.mean((y >= lo - q) & (y <= hi + q)) >= 0.8


def test_cv_runs_by_engine(fd001_small: pd.DataFrame) -> None:
    r = run_cv(
        fd001_small,
        CVConfig("FD001", DEFAULT_INPUTS["FD001"], 125, {"num_leaves": 15}, quantiles=True, baseline=True),
        n_splits=4,
    )
    oof = r["oof"]
    # each validation engine appears in exactly one fold
    assert oof.groupby("unit").fold.nunique().max() == 1
    assert (oof.lo <= oof.pred).all() and (oof.pred <= oof.hi).all()
    assert 0 < r["rmse_mean"] < 60 and "ridge_rmse_mean" in r


@pytest.fixture(scope="module")
def small_bundle(fd001_small: pd.DataFrame) -> ModelBundle:
    pipe = FeaturePipeline("FD001", DEFAULT_INPUTS["FD001"]).fit(fd001_small)
    cols = pipe.feature_names
    F = pipe.transform(fd001_small)
    life = fd001_small.groupby("unit").cycle.max()
    y = (F.unit.map(life) - F.cycle).clip(upper=125)
    params = lgb_params({"num_leaves": 15}, cols)
    model = RULModel(
        cols,
        125,
        fit_lgbm(F[cols], y, params, 60),
        fit_quantile(F[cols], y, params, 0.1, 60),
        fit_quantile(F[cols], y, params, 0.9, 60),
        conformal_q=3.0,
    )
    z = pipe.normalize(fd001_small)
    rul = train_rul(fd001_small)
    return ModelBundle(
        "FD001",
        "test-0",
        pipe,
        model,
        FleetBaseline.fit(z, rul, pipe.sensors_used, 125),
        {s.symbol: s.subsystem for s in sensor_catalog()},
        DriftReference.fit(fd001_small.drop(columns=["unit", "cycle"]), z, rul, pipe.sensors_used, 125),
        {"note": "unit test"},
    )


def test_intervals_and_contributions(small_bundle: ModelBundle, fd001_small: pd.DataFrame) -> None:
    F = small_bundle.pipeline.transform(fd001_small)
    pred, lo, hi = small_bundle.model.predict(F)
    assert (lo <= pred).all() and (pred <= hi).all() and (pred <= 125).all() and (lo >= 0).all()
    contrib = small_bundle.model.contributions(F.head(50))
    raw = small_bundle.model.point.predict(F.head(50)[small_bundle.model.feature_names])
    np.testing.assert_allclose(contrib.sum(axis=1), raw, rtol=1e-6, atol=1e-6)
    z_dev = {s: 1.0 for s in small_bundle.pipeline.sensors_used}
    top = sensor_contributions(contrib[-1], small_bundle.model.feature_names, z_dev)
    assert len(top) == 3 and abs(sum(t["pct"] for t in top)) <= 100.0
    scores = subsystem_scores({"T30": 3.0, "Ps30": -6.0, "T24": 0.0}, small_bundle.subsystem_of)
    assert scores == {"LPC": 0.0, "HPC": 75.0}


def test_drift_and_ood(small_bundle: ModelBundle) -> None:
    d = small_bundle.drift
    assert d.ood_sensors({"T30": 1590.0, "T50": 5000.0}) == ["T50"]
    healthy = np.column_stack([np.asarray(d.healthy_sample[s][:50]) for s in d.sensors])
    assert d.drift(healthy, rul_pred=120)[0] is False
    assert d.drift(healthy + 3.0, rul_pred=120)[0] is True
    assert d.drift(healthy + 3.0, rul_pred=40)[0] is False  # degradation explains it


def test_bundle_round_trip_and_tamper(
    small_bundle: ModelBundle, fd001_small: pd.DataFrame, tmp_path: Path
) -> None:
    path = write_bundle(tmp_path, small_bundle)
    loaded = load_bundle(tmp_path, "FD001")
    assert loaded.version == "test-0"
    g = fd001_small[fd001_small.unit == 3]
    F = small_bundle.pipeline.transform(g)
    np.testing.assert_allclose(loaded.model.predict(F)[0], small_bundle.model.predict(F)[0], atol=1e-9)
    # streaming through the loaded pipeline gives the same last prediction
    state = loaded.pipeline.new_stream()
    for _, r in g.iterrows():
        res = loaded.pipeline.update(state, int(r.cycle), r[list(SETTINGS)].to_numpy(float), r.to_dict())
    assert res.features is not None
    np.testing.assert_allclose(
        loaded.model.predict(res.features[None, :])[0][0], small_bundle.model.predict(F)[0][-1], atol=1e-6
    )
    # tamper
    with (path / "model_point.txt").open("a") as f:
        f.write("\n# tampered\n")
    with pytest.raises(BundleIntegrityError):
        load_bundle(tmp_path, "FD001")
