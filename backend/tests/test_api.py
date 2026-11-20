"""P3.7 REST API, auth, WebSocket push."""

from __future__ import annotations

import json
import threading
import time

from conftest import PASSWORD, post, replay_msgs
from fastapi.testclient import TestClient


def test_dashboard_requires_login(client: TestClient) -> None:
    anon = TestClient(client.app)
    assert anon.get("/api/v1/assets").status_code == 401
    assert anon.get("/api/v1/auth/me").json() == {"authenticated": False, "auth_enabled": True}
    assert anon.post("/api/v1/auth/login", json={"password": "nope"}).status_code == 401
    r = anon.post("/api/v1/auth/login", json={"password": PASSWORD})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert anon.get("/api/v1/assets").status_code == 200


def test_asset_views(client: TestClient) -> None:
    msgs = replay_msgs(units=[34])
    for m in msgs:
        post(client, m)
    assets = client.get("/api/v1/assets").json()
    assert assets["count"] == 1
    a = assets["items"][0]
    assert a["asset_id"] == "FD001-T034" and a["true_rul_at_end"] == 7 and len(a["sparkline"]) == 50
    assert a["state"] == "CRITICAL" and a["rul_pred"] < 30
    assert client.get("/api/v1/assets?state=HEALTHY").json()["count"] == 0
    d = client.get("/api/v1/assets/FD001-T034").json()
    assert d["lives"] == [1] and d["last_cycle"] == len(msgs)
    t = client.get("/api/v1/assets/FD001-T034/telemetry?from_cycle=10&to_cycle=19&sensors=T30,T50").json()
    assert [x["cycle"] for x in t["items"]] == list(range(10, 20)) and set(t["items"][0]["sensors"]) == {"T30", "T50"}
    p = client.get("/api/v1/assets/FD001-T034/predictions?limit=20").json()["items"]
    assert len(p) == 20 and p[-1]["true_rul"] == 7
    diag = client.get("/api/v1/assets/FD001-T034/diagnostics").json()
    assert len(diag["latest"]["contributors"]) == 3 and diag["latest"]["subsystem_scores"]
    rep = client.get("/api/v1/assets/FD001-T034/report").json()
    assert rep["model"]["model_version"] and rep["alerts"]
    assert client.get("/api/v1/assets/NOPE-1").status_code == 404
    gt = client.post("/api/v1/assets/FD001-T034/ground-truth", json={"true_rul_at_end": 9})
    assert gt.status_code == 200


def test_alerts_and_ack(client: TestClient) -> None:
    for m in replay_msgs(units=[34]):
        post(client, m)
    alerts = client.get("/api/v1/alerts?asset=FD001-T034").json()["items"]
    states = [a["to_state"] for a in alerts]
    assert "CRITICAL" in states and "WARNING" in states
    aid = alerts[0]["alert_id"]
    r = client.post(f"/api/v1/alerts/{aid}/ack", json={"by": "tester"})
    assert r.status_code == 200 and r.json()["acknowledged_by"] == "tester"
    assert client.get("/api/v1/alerts?ack=false").json()["count"] == len(alerts) - 1
    assert client.post("/api/v1/alerts/999999/ack").status_code == 404


def test_models_and_stats(client: TestClient) -> None:
    post(client, replay_msgs()[0])
    assert len(client.get("/api/v1/models").json()["items"]) == 4
    s = client.get("/api/v1/stats").json()
    assert s["ingest"]["counts"]["accepted"] >= 1 and s["db_ok"] is True


def test_websocket_prediction_within_500ms(client: TestClient) -> None:
    msgs = replay_msgs(units=[34])
    for m in msgs[:10]:
        post(client, m)
    with client.websocket_connect("/ws/v1/stream?asset=FD001-T034") as ws:
        assert ws.receive_json()["type"] == "hello"
        t0 = time.time()
        threading.Thread(target=post, args=(client, msgs[10])).start()
        while True:
            ev = json.loads(ws.receive_text())
            if ev["type"] == "prediction":
                break
        assert time.time() - t0 < 0.5
        assert ev["data"]["asset_id"] == "FD001-T034" and ev["data"]["cycle"] == 11


def test_websocket_requires_login(client: TestClient) -> None:
    anon = TestClient(client.app)
    try:
        with anon.websocket_connect("/ws/v1/stream") as ws:
            ws.receive_json()
        raise AssertionError("expected close")
    except Exception as e:
        assert "4401" in repr(e) or "WebSocketDisconnect" in type(e).__name__


def test_sensor_history_and_evaluation(client: TestClient) -> None:
    from conftest import post, replay_msgs
    msgs = replay_msgs("FD001", [34])
    for m in msgs[:30]:
        post(client, m)
    d = client.get("/api/v1/assets/FD001-T034/sensors?limit=25").json()
    assert len(d["items"]) == 25 and d["baseline_source"] == "asset"
    assert len(d["sensors"]) == 21 and "T50" in d["model_sensors"] and "T2" in d["constant_sensors"]
    row = d["items"][-1]
    assert set(row["dev_z"]) == set(d["model_sensors"]) and row["raw"]["T50"] > 0
    lo, hi = row["band"]["T50"]
    assert lo < hi
    first = client.get("/api/v1/assets/FD001-T034/sensors?limit=30").json()["items"][:20]
    assert sum(abs(r["dev_z"]["T50"]) > 3 for r in first) <= 1  # baseline cycles sit inside their own band
    ev = client.get("/api/v1/evaluation").json()
    fd1 = next(x for x in ev["items"] if x["profile"] == "FD001")
    assert fd1["rmse"] > 0 and sum(map(sum, fd1["confusion"].values())) == fd1["n"]


def test_dead_letter_viewer(client: TestClient) -> None:
    from conftest import post
    post(client, b"{not json")
    d = client.get("/api/v1/dead-letter?limit=5").json()["items"]
    assert d and d[0]["reason"] and d[0]["raw"].startswith("{not json") and d[0]["raw_truncated"] is False
