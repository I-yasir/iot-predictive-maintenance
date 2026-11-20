"""P1.5: labels, regimes and causal features (batch == streaming)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pdm_ml.config import DEFAULT_INPUTS, MIN_CYCLES, SETTINGS
from pdm_ml.features.pipeline import FeaturePipeline
from pdm_ml.io.loader import ProfileData
from pdm_ml.labels.rul import cap, train_rul
from pdm_ml.labels.rul import test_rul as rul_for_test_split


def test_train_and_test_labels(fd001: ProfileData) -> None:
    r = train_rul(fd001.train)
    last = fd001.train.groupby("unit").tail(1).index
    assert (r.loc[last] == 0).all()
    assert cap(r, 125).max() == 125
    t = rul_for_test_split(fd001.test, fd001.true_rul)
    last_t = fd001.test.groupby("unit").tail(1)
    assert (t.loc[last_t.index].to_numpy() == fd001.true_rul.loc[last_t.unit].to_numpy()).all()


def test_six_regimes_for_multi_condition(fd002: ProfileData) -> None:
    pipe = FeaturePipeline("FD002", DEFAULT_INPUTS["FD002"]).fit(fd002.train)
    z = pipe.normalize(fd002.train)
    assert z.regime.nunique() == 6
    assert not z.regime_ood.any()
    # within each regime normalised sensors are ~N(0,1)
    m = z.groupby("regime")[list(pipe.sensors_used)].mean().abs().to_numpy()
    assert m.max() < 1e-6


def test_single_regime_drops_nothing_needed(fd001: ProfileData) -> None:
    pipe = FeaturePipeline("FD001", DEFAULT_INPUTS["FD001"]).fit(fd001.train)
    assert pipe.sensors_used == DEFAULT_INPUTS["FD001"]
    assert len(pipe.feature_names) == 2 + 5 * 14


def test_gating_and_causality(fd001_small: pd.DataFrame) -> None:
    pipe = FeaturePipeline("FD001", DEFAULT_INPUTS["FD001"]).fit(fd001_small)
    u1 = fd001_small[fd001_small.unit == 1]
    full = pipe.transform(u1)
    assert full.cycle.min() == MIN_CYCLES
    part = pipe.transform(u1[u1.cycle <= 60])
    cols = pipe.feature_names
    np.testing.assert_allclose(full[cols].to_numpy()[: len(part)], part[cols].to_numpy(), rtol=0, atol=1e-10)


@pytest.mark.parametrize("profile_fixture,units", [("fd001", (1, 2, 3)), ("fd002", (5, 17, 101))])
def test_batch_equals_streaming(
    request: pytest.FixtureRequest, profile_fixture: str, units: tuple[int, ...]
) -> None:
    d: ProfileData = request.getfixturevalue(profile_fixture)
    pipe = FeaturePipeline(d.profile, DEFAULT_INPUTS[d.profile]).fit(d.train)
    cols = pipe.feature_names
    for u in units:
        g = d.test[d.test.unit == u]
        batch = pipe.transform(g)[cols].to_numpy()
        state = pipe.new_stream()
        rows = []
        for _, r in g.iterrows():
            res = pipe.update(state, int(r.cycle), r[list(SETTINGS)].to_numpy(float), r.to_dict())
            if res.features is not None:
                rows.append(res.features)
        stream = np.vstack(rows)
        assert stream.shape == batch.shape
        np.testing.assert_allclose(stream, batch, rtol=1e-7, atol=1e-8)


def test_stream_warming_up(fd001: ProfileData) -> None:
    pipe = FeaturePipeline("FD001", DEFAULT_INPUTS["FD001"]).fit(fd001.train)
    state = pipe.new_stream()
    g = fd001.test[fd001.test.unit == 1].head(MIN_CYCLES)
    outs = [
        pipe.update(state, int(r.cycle), r[list(SETTINGS)].to_numpy(float), r.to_dict()).features
        for _, r in g.iterrows()
    ]
    assert all(o is None for o in outs[:-1]) and outs[-1] is not None


def test_regime_ood_flag(fd002: ProfileData) -> None:
    pipe = FeaturePipeline("FD002", DEFAULT_INPUTS["FD002"]).fit(fd002.train)
    assert pipe.normalizer is not None
    _, ood = pipe.normalizer.assign(np.array([[42.0, 0.84, 100.0], [80.0, 2.0, 30.0]]))
    assert list(ood) == [False, True]
