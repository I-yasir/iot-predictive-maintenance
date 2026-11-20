"""MQTT subscriber (docs/04 §5.1): pdm/v1/+/+/telemetry and /status, per-asset ordered worker pool, acks."""

from __future__ import annotations

import json
import queue
import threading
import time
import zlib
from datetime import UTC, datetime
from typing import Any

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app import logging as applog
from app.db import models as m
from app.ingest.service import IngestService
from app.settings import Settings
from pdm_contracts import parse_topic

BATCH_MAX = 128
log = applog.get("pdm.mqtt")


class MqttSubscriber:
    def __init__(self, settings: Settings, ingest: IngestService) -> None:
        self.s, self.ingest = settings, ingest
        self.prefix = settings.mqtt_topic_prefix
        self.client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="pdm-backend", clean_session=True)
        self.client.username_pw_set(settings.mqtt_username, settings.mqtt_password or None)
        self.client.reconnect_delay_set(1, 30)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.queues: list[queue.Queue[tuple[str, bytes, float] | None]] = [
            queue.Queue(maxsize=10000) for _ in range(max(1, settings.mqtt_workers))]
        self.workers = [threading.Thread(target=self._work, args=(q,), daemon=True, name=f"mqtt-worker-{i}")
                        for i, q in enumerate(self.queues)]
        self.connected = threading.Event()
        ingest.ack = self.publish_ack

    def start(self) -> None:
        for w in self.workers:
            w.start()
        self.client.connect_async(self.s.mqtt_host, self.s.mqtt_port, keepalive=30)
        self.client.loop_start()

    def stop(self) -> None:
        self.client.disconnect()
        self.client.loop_stop()
        for q in self.queues:
            q.put(None)

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Any, rc: Any, props: Any = None) -> None:
        if rc.is_failure:
            log.error("mqtt_connect_refused", rc=str(rc))
            return
        client.subscribe([(f"{self.prefix}/+/+/telemetry", 1), (f"{self.prefix}/+/+/status", 1)])
        self.connected.set()
        self.ingest.metrics.mqtt_connected.set(1)
        log.info("mqtt_connected", host=self.s.mqtt_host)

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, flags: Any, rc: Any, props: Any = None) -> None:
        self.connected.clear()
        self.ingest.metrics.mqtt_connected.set(0)
        log.warning("mqtt_disconnected", rc=str(rc))

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        t = time.time()
        parsed = parse_topic(msg.topic, self.prefix)
        if parsed is None:
            return
        if parsed[2] == "status":
            self._status(parsed[0], parsed[1], msg.payload)
            return
        q = self.queues[zlib.crc32(parsed[1].encode()) % len(self.queues)]  # same asset -> same worker
        try:
            q.put_nowait((msg.topic, msg.payload, t))
        except queue.Full:
            self.ingest.metrics.rejected.labels("mqtt", "backpressure").inc()

    def _work(self, q: queue.Queue[tuple[str, bytes, float] | None]) -> None:
        """Drain the queue into batches: block for the first message, then take whatever else is already
        waiting (up to BATCH_MAX). Under light load a batch is one message, so latency is unchanged."""
        stop = False
        while not stop:
            first = q.get()
            if first is None:
                return
            items = [first]
            while len(items) < BATCH_MAX:
                try:
                    nxt = q.get_nowait()
                except queue.Empty:
                    break
                if nxt is None:
                    stop = True
                    break
                items.append(nxt)
            batch: list[tuple[bytes, str, tuple[str, str] | None, float | None]] = []
            for topic, raw, t in items:
                parsed = parse_topic(topic, self.prefix)
                if parsed is not None:
                    batch.append((raw, "mqtt", (parsed[0], parsed[1]), t))
            try:
                self.ingest.process_batch(batch)
            except Exception:
                log.exception("mqtt_ingest_crashed", n=len(batch))

    def publish_ack(self, site: str, asset: str, body: dict[str, Any]) -> None:
        self.client.publish(f"{self.prefix}/{site}/{asset}/ack", json.dumps(body, default=str), qos=0)

    def _status(self, site: str, asset: str, raw: bytes) -> None:
        try:
            d = json.loads(raw)
            if not isinstance(d, dict):
                return
            now = datetime.now(UTC)
            row: dict[str, Any] = {"device_id": asset, "fw": d.get("fw"), "ip": d.get("ip"), "rssi": d.get("rssi"),
                   "online": bool(d.get("online")), "last_status_at": now}
            with self.ingest.engine.begin() as c:
                c.execute(pg_insert(m.devices).values(**row).on_conflict_do_update(
                    index_elements=["device_id"], set_={k: v for k, v in row.items() if v is not None}))
            self.ingest.publish({"type": "device_status", "data": {**row, "site_id": site,
                                                                   "last_status_at": now.isoformat()}})
        except Exception as e:  # status is best effort
            log.warning("device_status_failed", asset=asset, error=str(e)[:200])
