"""P3.8 replay controller via API + device harness checks; MQTT end to end (broker marker)."""

from __future__ import annotations

import os
import socket
import time

import pytest
import sqlalchemy as sa
from conftest import make_settings
from fastapi.testclient import TestClient

from app.main import create_app
from pdm_iot.simulator.virtual_esp32 import VirtualDevice, parse_faults, run
from pdm_iot.transports import MemoryTransport, MqttTransport


def _wait(client: TestClient, states: set[str], timeout: float = 30) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = client.get("/api/v1/sim/replay/status").json()
        if s["state"] in states:
            return s
        time.sleep(0.05)
    raise AssertionError(f"replay never reached {states}: {s}")


def test_replay_start_pause_resume_stop(client: TestClient) -> None:
    assert client.get("/api/v1/sim/replay/status").json()["state"] == "IDLE"
    r = client.post("/api/v1/sim/replay/start", json={"profile": "FD001", "units": [34, 35], "speed_cps": 50})
    assert r.status_code == 200 and r.json()["state"] == "RUNNING"
    assert client.post("/api/v1/sim/replay/start", json={"profile": "FD001"}).status_code == 409
    time.sleep(0.3)
    assert client.post("/api/v1/sim/replay/pause").json()["state"] == "PAUSED"
    sent = client.get("/api/v1/sim/replay/status").json()["stats"]["sent"]
    time.sleep(0.3)
    assert client.get("/api/v1/sim/replay/status").json()["stats"]["sent"] <= sent + 2
    assert client.post("/api/v1/sim/replay/resume").json()["state"] == "RUNNING"
    assert client.post("/api/v1/sim/replay/stop").json()["state"] == "STOPPED"
    assert client.get("/api/v1/assets").json()["count"] == 2


def test_replay_completes_through_ingest(client: TestClient) -> None:
    client.post("/api/v1/sim/replay/start", json={"profile": "FD003", "units": [1], "speed_cps": 0})
    s = _wait(client, {"COMPLETED", "ERROR"})
    assert s["state"] == "COMPLETED" and s["stats"]["failed"] == 0
    a = client.get("/api/v1/assets/FD003-T001").json()
    assert a["last_cycle"] == s["stats"]["sent"]


def test_harness_check_on_virtual_device(client: TestClient) -> None:
    dev = VirtualDevice("FD001-V001", faults=parse_faults("range@30"))
    t = MemoryTransport()
    run(dev, t, 60, 0)
    for raw in t.sent:
        client.post("/api/v1/ingest", content=raw, headers={"X-API-Key": "k" * 40})
    r = client.post("/api/v1/devices/FD001-V001/harness-check?window=100").json()
    by = {c["check"]: c for c in r["checks"]}
    assert r["window"] == 59 and not by["schema"]["ok"] and "range:T30" in by["schema"]["detail"]
    assert by["sequence"]["ok"] is False  # seq 30 was rejected -> gap visible to the device check
    devs = client.get("/api/v1/devices").json()["items"]
    assert any(d["device_id"] == "FD001-V001" for d in devs)
    assert client.post("/api/v1/devices/NOPE/harness-check").status_code == 404


def _broker() -> bool:
    try:
        with socket.create_connection(("localhost", 1883), 1):
            return bool(os.environ.get("MQTT_BACKEND_PASSWORD"))
    except OSError:
        return False


@pytest.mark.broker
@pytest.mark.skipif(not _broker(), reason="no broker / .env")
def test_mqtt_end_to_end_with_acks(db_url: str) -> None:
    """Virtual ESP32 -> Mosquitto -> backend subscriber -> DB, with acks back on the ack topic."""
    s = make_settings(db_url, mqtt_enabled=True, mqtt_password=os.environ["MQTT_BACKEND_PASSWORD"])
    site = f"t{int(time.time())}"
    with TestClient(create_app(s, start_background=True)) as c:
        sub = c.app.state  # noqa: F841
        t0 = time.time()
        while not c.app.state.mqtt_connected() and time.time() - t0 < 10:
            time.sleep(0.1)
        assert c.app.state.mqtt_connected()
        acks: list[bytes] = []
        obs = MqttTransport("localhost", 1883, "pdm-harness", os.environ.get("MQTT_HARNESS_PASSWORD"))
        obs.subscribe(f"pdm/v1/{site}/+/ack", lambda tp, raw: acks.append(raw))
        pub = MqttTransport("localhost", 1883, "pdm-replay", os.environ.get("MQTT_REPLAY_PASSWORD"))
        time.sleep(0.3)
        run(VirtualDevice("FD001-V009", site_id=site, faults=parse_faults("malformed@5")), pub, 20, 0)
        t0 = time.time()
        while len(acks) < 20 and time.time() - t0 < 10:
            time.sleep(0.1)
        pub.close()
        obs.close()
        with c.app.state.engine.connect() as conn:
            n = conn.execute(sa.text("SELECT count(*) FROM telemetry WHERE asset_id = 'FD001-V009'")).scalar()
        assert n == 19 and len(acks) == 20  # 19 accepted + 1 rejected ack
