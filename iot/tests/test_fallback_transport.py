"""MQTT -> HTTP fallback mirrors the firmware: no message lost while the broker is down, back to MQTT later."""

from __future__ import annotations

from typing import Any

from pdm_iot.transports import FallbackTransport, SendResult


class FakeMqtt:
    def __init__(self) -> None:
        self.up, self.sent = True, []

    @property
    def connected(self) -> bool:
        return self.up

    def send(self, payload: dict[str, Any], raw: bytes | None = None) -> SendResult:
        if not self.up:
            return SendResult(False, "not connected")
        self.sent.append(payload["seq"])
        return SendResult(True)

    def close(self) -> None:
        pass


class FakeHttp(FakeMqtt):
    pass


def test_fallback_and_recovery(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("pdm_iot.transports.time.monotonic", lambda: clock[0])
    m, h = FakeMqtt(), FakeHttp()
    t = FallbackTransport(m, h, fails_before_http=3, retry_mqtt_s=30)  # type: ignore[arg-type]
    seq = iter(range(1, 1000))

    def send() -> None:
        assert t.send({"seq": next(seq)}).ok

    send()
    m.up = False
    for _ in range(5):
        send()
    assert t.mode == "http"
    assert m.sent == [1] and h.sent == [2, 3, 4, 5, 6]  # every failed MQTT publish went over HTTP
    m.up = True
    clock[0] = 10
    send()
    assert t.mode == "http"  # not yet time to retry MQTT
    clock[0] = 31
    send()
    assert t.mode == "mqtt" and m.sent[-1] == 8
    assert sorted(m.sent + h.sent) == list(range(1, 9))


def test_starts_on_http_when_broker_down_at_boot():
    m, h = FakeMqtt(), FakeHttp()
    m.up = False
    t = FallbackTransport(m, h)  # type: ignore[arg-type]
    assert t.mode == "http"
    assert t.send({"seq": 1}).ok and h.sent == [1]
