"""Prometheus metrics (docs/04 §8). One registry per app so tests stay isolated."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram


class Metrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        r = self.registry
        self.ingested = Counter("ingest_accepted_total", "Accepted telemetry", ["transport", "profile"], registry=r)
        self.rejected = Counter("ingest_rejected_total", "Rejected telemetry", ["transport", "reason"], registry=r)
        self.duplicates = Counter("ingest_duplicate_total", "Duplicate telemetry", ["transport"], registry=r)
        self.rate_limited = Counter("ingest_rate_limited_total", "Dropped by per-asset rate limit", registry=r)
        self.latency = Histogram(
            "ingest_to_prediction_seconds", "Receive -> prediction persisted",
            buckets=(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 1.0, 2.5, 5.0, 10.0), registry=r,
        )
        self.inference_errors = Counter("inference_errors_total", "Inference exceptions", ["profile"], registry=r)
        self.alerts = Counter("alerts_total", "Alert transitions", ["to_state"], registry=r)
        self.active_assets = Gauge("active_assets", "Assets with an in-memory runtime", registry=r)
        self.drift_assets = Gauge("drift_assets", "Assets currently flagged DRIFT", registry=r)
        self.ws_clients = Gauge("ws_clients", "Connected WebSocket clients", registry=r)
        self.mqtt_connected = Gauge("mqtt_connected", "1 when the MQTT subscriber is connected", registry=r)
