"""P3.4: every row of the docs/02 §8 error matrix + dedupe/order/gap/new-life rules (docs/02 §2)."""

from __future__ import annotations

import copy
import json

import sqlalchemy as sa
from conftest import API_KEY, post, replay_msgs
from fastapi.testclient import TestClient


def q(client: TestClient, sql: str, **kw):
    with client.app.state.engine.connect() as c:
        return [dict(r) for r in c.execute(sa.text(sql), kw).mappings().all()]


def test_accept_autoregister_and_warmup(client: TestClient) -> None:
    msgs = replay_msgs(units=[1])
    for m in msgs[:6]:
        r = post(client, m)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "accepted"
    a = q(client, "SELECT * FROM assets")[0]
    assert a["asset_id"] == "FD001-T001" and a["source"] == "REPLAY" and a["last_cycle"] == 6
    preds = q(client, "SELECT status, rul_pred FROM predictions ORDER BY cycle")
    assert [p["status"] for p in preds] == ["WARMING_UP"] * 4 + ["OK"] * 2  # MIN_CYCLES = 5
    assert a["state"] in ("HEALTHY", "WARNING", "CRITICAL")
    assert not q(client, "SELECT * FROM alerts WHERE from_state = 'NEW'")  # no alert for the first message


def test_auth_and_size(client: TestClient) -> None:
    m = replay_msgs()[0]
    assert post(client, m, key=None).status_code == 401
    assert post(client, m, key="wrong").status_code == 401
    big = copy.deepcopy(m)
    big["meta"]["pad"] = "x" * 900
    big["sensors"].update({f"x{i}": 1.0 for i in range(400)})
    r = post(client, big)
    assert r.status_code == 413 and r.json()["reason"] == "too_large"


def test_rejections_go_to_dead_letter(client: TestClient) -> None:
    m = replay_msgs()[0]
    cases = {
        "parse_error": b'{"schema_version": "1.0", ',
        "schema:sensors.T30": {**m, "sensors": {k: v for k, v in m["sensors"].items() if k != "T30"}},
        "range:T30": {**m, "sensors": {**m["sensors"], "T30": 99999.0}},
        "unknown_profile": {**m, "profile": "FD009"},
        "unsupported_version": {**m, "schema_version": "2.0"},
    }
    for reason, payload in cases.items():
        r = post(client, payload)
        assert r.status_code == 422, (reason, r.text)
        assert r.json()["reason"] == reason
    dl = {r["reason"] for r in q(client, "SELECT reason FROM dead_letter")}
    assert dl == set(cases)


def test_three_rejections_degrade_then_recover(client: TestClient) -> None:
    msgs = replay_msgs()
    for m in msgs[:8]:
        post(client, m)
    for m in msgs[8:11]:
        assert post(client, {**m, "sensors": {**m["sensors"], "T30": 99999.0}}).status_code == 422
    assert q(client, "SELECT state FROM assets")[0]["state"] == "DEGRADED_DATA"
    for m in msgs[8:11]:
        assert post(client, m).status_code == 200
    assert q(client, "SELECT state FROM assets")[0]["state"] in ("HEALTHY", "WARNING", "CRITICAL")
    tos = [a["to_state"] for a in q(client, "SELECT to_state FROM alerts ORDER BY alert_id")]
    assert "DEGRADED_DATA" in tos


def test_duplicate_out_of_order_gap(client: TestClient) -> None:
    msgs = replay_msgs()
    for m in msgs[:10]:
        post(client, m)
    r = post(client, msgs[9])
    assert r.status_code == 200 and r.json()["status"] == "duplicate"
    post(client, msgs[12])  # cycle 13 after 10 -> gap
    post(client, msgs[11])  # cycle 12 after 13 -> out of order, stored, not inferred
    rows = {r["cycle"]: r["flags"] for r in q(client, "SELECT cycle, flags FROM telemetry")}
    assert "gap" in rows[13] and "out_of_order" in rows[12]
    preds = {r["cycle"] for r in q(client, "SELECT cycle FROM predictions")}
    assert 12 not in preds and 13 in preds
    assert q(client, "SELECT last_cycle FROM assets")[0]["last_cycle"] == 13
    assert len(q(client, "SELECT 1 FROM telemetry WHERE cycle = 10")) == 1


def test_new_life_on_cycle_restart(client: TestClient) -> None:
    msgs = replay_msgs()
    for m in msgs[:20]:
        post(client, m)
    restart = {**msgs[0], "msg_id": "restart-1", "seq": 999}
    assert post(client, restart).status_code == 200
    a = q(client, "SELECT life_id, state, last_cycle FROM assets")[0]
    assert a == {"life_id": 2, "state": "WARMING_UP", "last_cycle": 1}
    assert q(client, "SELECT count(*) AS n FROM telemetry WHERE life_id = 2")[0]["n"] == 1


def test_clock_skew_flag(client: TestClient) -> None:
    m = {**replay_msgs()[0], "ts": "2020-01-01T00:00:00Z"}
    assert post(client, m).status_code == 200
    assert "clock_skew" in q(client, "SELECT flags FROM telemetry")[0]["flags"]


def test_rate_limit(client: TestClient) -> None:
    client.app.state.ingest.rate = 3.0
    codes = [post(client, m).status_code for m in replay_msgs()[:8]]
    assert codes[:3] == [200, 200, 200] and 429 in codes


def test_inference_error_keeps_telemetry(client: TestClient, monkeypatch) -> None:
    msgs = replay_msgs()
    post(client, msgs[0])
    ctx = client.app.state.ingest.assets["FD001-T001"]

    def boom(*a, **k):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(ctx.runtime, "prepare", boom)
    r = post(client, msgs[1])
    assert r.status_code == 200
    p = q(client, "SELECT status FROM predictions WHERE cycle = 2")[0]
    assert p["status"] == "ERROR"
    assert q(client, "SELECT count(*) AS n FROM telemetry")[0]["n"] == 2


def test_model_error_on_ready_row(client: TestClient, monkeypatch) -> None:
    msgs = replay_msgs()
    for m in msgs[:19]:
        post(client, m)
    ctx = client.app.state.ingest.assets["FD001-T001"]

    def boom(*a, **k):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(ctx.runtime.bundle.model, "predict", boom)
    r = post(client, msgs[19])
    assert r.status_code == 200
    p = q(client, "SELECT status FROM predictions WHERE cycle = 20")[0]
    assert p["status"] == "ERROR"
    assert q(client, "SELECT count(*) AS n FROM telemetry")[0]["n"] == 20


def test_db_unavailable_returns_503(client: TestClient, monkeypatch) -> None:
    svc = client.app.state.ingest
    post(client, replay_msgs()[0])
    good = svc.engine
    monkeypatch.setattr(svc, "engine", sa.create_engine("postgresql+psycopg://x:y@127.0.0.1:1/none",
                                                         connect_args={"connect_timeout": 1}))
    r = post(client, replay_msgs()[1])
    assert r.status_code == 503 and r.json()["status"] == "unavailable"
    monkeypatch.setattr(svc, "engine", good)
    assert post(client, replay_msgs()[1]).status_code == 200  # not marked seen while storage was down


def test_batch_endpoint(client: TestClient) -> None:
    msgs = replay_msgs()[:5]
    r = client.post("/api/v1/ingest/batch", content=json.dumps(msgs + [msgs[0]]), headers={"X-API-Key": API_KEY})
    assert r.status_code == 200
    assert r.json()["counts"] == {"accepted": 5, "duplicate": 1}


def test_restart_rehydrates_stream(client: TestClient) -> None:
    """After a backend restart (runtimes dropped) predictions continue exactly as before."""
    msgs = replay_msgs(units=[34])
    for m in msgs[:40]:
        post(client, m)
    ref = post(client, msgs[40]).json()["rul_pred"]
    client.app.state.ingest.reset()
    with client.app.state.engine.begin() as c:
        c.execute(sa.text("DELETE FROM predictions WHERE cycle = 41"))
        c.execute(sa.text("DELETE FROM telemetry WHERE cycle = 41"))
        c.execute(sa.text("UPDATE assets SET last_cycle = 40"))
    assert abs(post(client, msgs[40]).json()["rul_pred"] - ref) < 1e-3
