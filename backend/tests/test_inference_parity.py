"""P3.5 done-when: online predictions at the last cycle equal the offline evaluate.py path."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from conftest import post, replay_msgs
from fastapi.testclient import TestClient

from pdm_ml.io.loader import load_split


@pytest.mark.parametrize("profile,units,tol", [
    ("FD001", [31, 34, 76], 1e-6),   # LightGBM bundle
    ("FD002", [3], 1e-4),            # LightGBM + M2 (float32 CNN: batch vs single-sample sums)
])
def test_online_equals_offline(client: TestClient, profile: str, units: list[int], tol: float) -> None:
    bundle = client.app.state.registry.get(profile)
    test = load_split(profile, "test")
    for u in units:
        for m in replay_msgs(profile, [u]):
            assert post(client, m).status_code == 200
        offline = bundle.predict_history(test[test.unit == u]).iloc[-1]
        with client.app.state.engine.connect() as c:
            online = c.execute(sa.text(
                "SELECT rul_pred, rul_p10, rul_p90 FROM predictions WHERE asset_id = :a ORDER BY cycle DESC LIMIT 1"),
                {"a": f"{profile}-T{u:03d}"}).mappings().one()
        assert online["rul_pred"] == pytest.approx(offline.pred, abs=max(tol, 1e-4))  # REAL column = float32
        assert online["rul_p10"] == pytest.approx(offline.lo, abs=1e-3)
        assert online["rul_p90"] == pytest.approx(offline.hi, abs=1e-3)


def test_in_memory_prediction_is_exact(client: TestClient) -> None:
    """Same check without the float32 DB column: the runtime's own number."""
    bundle = client.app.state.registry.get("FD001")
    msgs = replay_msgs("FD001", [34])
    for m in msgs[:-1]:
        post(client, m)
    last = post(client, msgs[-1]).json()["rul_pred"]  # rounded to 2 decimals in the response
    test = load_split("FD001", "test")
    offline = bundle.predict_history(test[test.unit == 34]).iloc[-1].pred
    rt = client.app.state.ingest.assets["FD001-T034"].runtime
    assert rt.last_rul == pytest.approx(offline, abs=1e-6)
    assert last == pytest.approx(offline, abs=0.006)
