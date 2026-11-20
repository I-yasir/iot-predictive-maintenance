"""P1.3: raw files load into the documented schema (docs/05 §1, §3)."""

from __future__ import annotations

import pytest

from pdm_ml.config import PROFILES
from pdm_ml.io.loader import columns, load_profile, sensor_catalog

EXPECTED = {  # profile: (train rows, train units, test rows, test units) - measured, not from readme
    "FD001": (20631, 100, 13096, 100),
    "FD002": (53759, 260, 33991, 259),
    "FD003": (24720, 100, 16596, 100),
    "FD004": (61249, 249, 41214, 248),
}


def test_catalog_has_21_sensors_in_order() -> None:
    cat = sensor_catalog()
    assert len(cat) == 21
    assert cat[2].symbol == "T30" and cat[2].unit == "°R"
    assert {s.kind for s in cat} == {"measurement", "setpoint"}
    assert len(columns()) == 26


@pytest.mark.parametrize("profile", PROFILES)
def test_counts_schema_and_integrity(profile: str) -> None:
    d = load_profile(profile)
    tr_rows, tr_units, te_rows, te_units = EXPECTED[profile]
    assert (len(d.train), d.train.unit.nunique()) == (tr_rows, tr_units)
    assert (len(d.test), d.test.unit.nunique()) == (te_rows, te_units)
    assert len(d.true_rul) == te_units
    assert list(d.train.columns) == columns()
    for df in (d.train, d.test):
        assert not df.isna().any().any()
        g = df.groupby("unit").cycle
        assert (g.min() == 1).all()
        assert (g.max() == g.count()).all(), "cycles must be contiguous"


def test_unknown_profile_rejected() -> None:
    with pytest.raises(ValueError):
        load_profile("FD009")
