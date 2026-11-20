"""Integration tests against the docker-compose Mosquitto (marker: broker). Skipped when it is not running."""

import os
import threading
import time
import uuid

import pytest

from pdm_iot.simulator.virtual_esp32 import VirtualDevice, run
from pdm_iot.transports import MqttTransport

pytestmark = pytest.mark.broker
HOST, PORT = os.environ.get("MQTT_HOST", "localhost"), int(os.environ.get("MQTT_PORT", "1883"))


def _client(user, pw_env):
    return MqttTransport(HOST, PORT, user, os.environ.get(pw_env), client_id=f"test-{uuid.uuid4().hex[:6]}")


def test_100_published_100_received():
    site = f"t{uuid.uuid4().hex[:6]}"
    got, done = [], threading.Event()
    sub = _client("pdm-harness", "MQTT_HARNESS_PASSWORD")

    def on(topic, raw):
        got.append(raw)
        if len(got) == 100:
            done.set()

    sub.subscribe(f"pdm/v1/{site}/+/telemetry", on)
    time.sleep(0.3)
    pub = _client("pdm-replay", "MQTT_REPLAY_PASSWORD")
    try:
        stats = run(VirtualDevice("FD001-V001", site_id=site), pub, 100, 0)
        assert stats["send_failures"] == 0
        assert done.wait(10), f"only {len(got)} of 100 received"
    finally:
        pub.close()
        sub.close()


def test_anonymous_refused():
    with pytest.raises(ConnectionError):
        MqttTransport(HOST, PORT, None, None, connect_timeout_s=3)


def test_wrong_password_refused():
    with pytest.raises(ConnectionError):
        MqttTransport(HOST, PORT, "pdm-replay", "wrong", connect_timeout_s=3)


def test_acl_blocks_harness_publishing():
    """pdm-harness is read-only: Mosquitto silently drops its publishes, so a subscriber sees nothing."""
    site = f"t{uuid.uuid4().hex[:6]}"
    got = []
    sub = _client("pdm-backend", "MQTT_BACKEND_PASSWORD")
    sub.subscribe(f"pdm/v1/{site}/+/telemetry", lambda t, r: got.append(r))
    time.sleep(0.3)
    bad = _client("pdm-harness", "MQTT_HARNESS_PASSWORD")
    try:
        bad.publish(f"pdm/v1/{site}/FD001-X/telemetry", b"{}")
        time.sleep(1.0)
        assert got == []
    finally:
        bad.close()
        sub.close()
