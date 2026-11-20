"""MQTT (primary) and HTTP (fallback) transports with retry/backoff (docs/04 §5.1, plan P2.3)."""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from pdm_contracts import telemetry_topic

log = logging.getLogger(__name__)
BACKOFF_S = (1.0, 2.0, 4.0)


@dataclass
class SendResult:
    ok: bool
    detail: str = ""
    status: int | None = None


class Transport(Protocol):
    def send(self, payload: dict[str, Any], raw: bytes | None = None) -> SendResult: ...
    def close(self) -> None: ...


def encode(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()


class MqttTransport:
    """QoS 1 publisher. `send` blocks until PUBACK (or timeout), so callers get real delivery feedback."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 1883,
        username: str | None = None,
        password: str | None = None,
        prefix: str = "pdm/v1",
        client_id: str | None = None,
        qos: int = 1,
        publish_timeout_s: float = 5.0,
        connect_timeout_s: float = 10.0,
    ) -> None:
        self.prefix, self.qos, self.publish_timeout_s = prefix, qos, publish_timeout_s
        self.client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=client_id or f"pdm-{uuid.uuid4().hex[:8]}",
                                  clean_session=True)
        if username:
            self.client.username_pw_set(username, password)
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._connected = threading.Event()
        self._refused: str | None = None
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.connect_async(host, port, keepalive=30)
        self.client.loop_start()
        if not self._connected.wait(connect_timeout_s):
            self.close()
            raise ConnectionError(self._refused or f"MQTT broker {host}:{port} not reachable")

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Any, rc: Any, props: Any = None) -> None:
        if rc.is_failure:
            self._refused = f"MQTT connect refused: {rc}"
            log.error(self._refused)
        else:
            self._connected.set()

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, flags: Any, rc: Any, props: Any = None) -> None:
        self._connected.clear()
        if rc.is_failure:
            log.warning("MQTT disconnected (%s); paho will reconnect", rc)

    def publish(self, topic: str, data: bytes, retain: bool = False) -> SendResult:
        if not self._connected.wait(self.publish_timeout_s):
            return SendResult(False, "not connected")
        info = self.client.publish(topic, data, qos=self.qos, retain=retain)
        try:
            info.wait_for_publish(self.publish_timeout_s)
        except (RuntimeError, ValueError) as e:
            return SendResult(False, f"publish failed: {e}")
        return SendResult(info.is_published(), "" if info.is_published() else "PUBACK timeout")

    def send(self, payload: dict[str, Any], raw: bytes | None = None) -> SendResult:
        topic = telemetry_topic(str(payload.get("site_id", "x")), str(payload.get("asset_id", "x")), self.prefix)
        return self.publish(topic, raw if raw is not None else encode(payload))

    def subscribe(self, topic: str, on_message: Callable[[str, bytes], None]) -> None:
        self.client.message_callback_add(topic, lambda c, u, m: on_message(m.topic, m.payload))
        self.client.subscribe(topic, qos=1)

    def close(self) -> None:
        try:
            self.client.disconnect()
        finally:
            self.client.loop_stop()


class HttpTransport:
    """POST /api/v1/ingest with X-API-Key. Retries connection errors and 5xx with 1/2/4 s backoff."""

    def __init__(self, url: str, api_key: str, timeout_s: float = 5.0, backoff: tuple[float, ...] = BACKOFF_S) -> None:
        self.url, self.backoff = url, backoff
        self.client = httpx.Client(timeout=timeout_s, headers={"X-API-Key": api_key, "Content-Type": "application/json"})

    def send(self, payload: dict[str, Any], raw: bytes | None = None) -> SendResult:
        data = raw if raw is not None else encode(payload)
        last = ""
        for attempt in range(len(self.backoff) + 1):
            try:
                r = self.client.post(self.url, content=data)
                if r.status_code < 500:
                    return SendResult(r.status_code == 200, r.text[:300], r.status_code)
                last = f"HTTP {r.status_code}"
            except httpx.HTTPError as e:
                last = f"{type(e).__name__}: {e}"
            if attempt < len(self.backoff):
                time.sleep(self.backoff[attempt])
        return SendResult(False, last)

    def close(self) -> None:
        self.client.close()


class MemoryTransport:
    """In-process transport for tests and dry runs."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []

    def send(self, payload: dict[str, Any], raw: bytes | None = None) -> SendResult:
        self.sent.append(raw if raw is not None else encode(payload))
        return SendResult(True)

    def close(self) -> None:
        pass
