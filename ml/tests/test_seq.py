"""P1.11 M2 sequence model: causality, streaming parity, ensemble bundle round trip + tamper."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from test_models_and_bundle import small_bundle  # noqa: F401  (fixture)

from pdm_ml.config import SETTINGS
from pdm_ml.models.bundle import BundleIntegrityError, ModelBundle, load_bundle, write_bundle
from pdm_ml.models.seq import SeqConfig, SeqModel, SeqStream, build_windows


@pytest.fixture(scope="module")
def seq_bundle(small_bundle: ModelBundle, fd001_small: pd.DataFrame) -> ModelBundle:  # noqa: F811
    pipe = small_bundle.pipeline
    X, idx = build_windows(pipe.normalize(fd001_small), pipe.sensors_used, 30, pipe.min_cycles)
    life = fd001_small.groupby("unit").cycle.max()
    y = np.minimum(idx.unit.map(life).to_numpy() - idx.cycle.to_numpy(), 125).astype(np.float32)
    seq = SeqModel(pipe.sensors_used, SeqConfig(seq_len=30, width=8)).fit_fixed(X, y, 2)
    model = dataclasses.replace(small_bundle.model, needs_seq=True)
    return dataclasses.replace(small_bundle, model=model, seq=seq, version="test-seq")


def test_windows_are_causal(fd001_small: pd.DataFrame, small_bundle: ModelBundle) -> None:  # noqa: F811
    pipe = small_bundle.pipeline
    g = fd001_small[fd001_small.unit == 2]
    full, idx_full = build_windows(pipe.normalize(g), pipe.sensors_used, 30)
    part, idx_part = build_windows(pipe.normalize(g.head(60)), pipe.sensors_used, 30)
    np.testing.assert_array_equal(full[: len(part)], part)  # appending future rows changes nothing
    assert idx_full.cycle.iloc[0] == g.cycle.iloc[4]  # gated like FeaturePipeline (min_cycles = 5)


def test_stream_matches_batch(fd001_small: pd.DataFrame, small_bundle: ModelBundle) -> None:  # noqa: F811
    pipe = small_bundle.pipeline
    g = fd001_small[fd001_small.unit == 4]
    batch, _ = build_windows(pipe.normalize(g), pipe.sensors_used, 30, min_cycles=1)
    st, state = SeqStream(len(pipe.sensors_used), 30), pipe.new_stream()
    for i, (_, r) in enumerate(g.iterrows()):
        res = pipe.update(state, int(r.cycle), r[list(SETTINGS)].to_numpy(float), r.to_dict())
        np.testing.assert_allclose(st.update(int(r.cycle), res.z), batch[i], atol=1e-6)


def test_ensemble_bundle_round_trip_and_tamper(
    seq_bundle: ModelBundle, fd001_small: pd.DataFrame, tmp_path: Path
) -> None:
    g = fd001_small[fd001_small.unit <= 3]
    before = seq_bundle.predict_history(g)
    with pytest.raises(ValueError):
        seq_bundle.model.predict(before)  # an ensemble bundle refuses LightGBM-only prediction
    lgbm_only = np.clip(seq_bundle.model.point.predict(before[seq_bundle.model.feature_names]), 0, 125)
    assert not np.allclose(before.pred, lgbm_only)  # the M2 half is really used
    assert (before.lo <= before.pred).all() and (before.pred <= before.hi).all()

    path = write_bundle(tmp_path, seq_bundle)
    assert (path / "seq_model.pt").is_file()
    loaded = load_bundle(tmp_path, "FD001")
    assert loaded.seq is not None and loaded.card["seq_model"]["seq_len"] == 30
    np.testing.assert_allclose(loaded.predict_history(g).pred, before.pred, atol=1e-5)
    with (path / "seq_model.pt").open("ab") as f:
        f.write(b"tampered")
    with pytest.raises(BundleIntegrityError):
        load_bundle(tmp_path, "FD001")
