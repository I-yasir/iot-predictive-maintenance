"""P3.8 in-process replay controller wrapping the Mode 1 simulator (pdm_iot.simulator.replay)."""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from app.ingest.service import IngestService
from app.settings import Settings
from pdm_iot.simulator.replay import ReplayConfig, ReplaySimulator, ReplayState, make_transport
from pdm_iot.transports import SendResult, Transport, encode


class InternalTransport:
    """Hands messages straight to the ingest service: same validation/inference path, no broker hop."""

    def __init__(self, ingest: IngestService) -> None:
        self.ingest = ingest

    def send(self, payload: dict[str, Any], raw: bytes | None = None) -> SendResult:
        r = self.ingest.process(raw or encode(payload), "internal", None, time.time())
        return SendResult(r.status in ("accepted", "duplicate"), json.dumps(r.body)[:300], r.http_code)

    def close(self) -> None:
        pass


class ReplayController:
    def __init__(self, ingest: IngestService, settings: Settings) -> None:
        self.ingest, self.settings = ingest, settings
        self.sim: ReplaySimulator | None = None
        self.transport: Transport | None = None
        self.cfg: dict[str, Any] = {}
        self.lock = threading.Lock()

    def start(self, cfg: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            if self.sim and self.sim.state in (ReplayState.RUNNING, ReplayState.PAUSED):
                raise RuntimeError("a replay is already running; stop it first")
            kind = cfg.get("transport", "internal")
            self.transport = InternalTransport(self.ingest) if kind == "internal" else make_transport(kind)
            rc = ReplayConfig(profile=cfg["profile"], split=cfg.get("split", "test"), units=cfg.get("units"),
                              random_n=cfg.get("random_n"), speed_cps=float(cfg.get("speed_cps", 5.0)),
                              loop=bool(cfg.get("loop", False)), site_id=cfg.get("site_id", "lab"),
                              asset_prefix=cfg.get("asset_prefix", ""))
            self.cfg = {**cfg, "transport": kind}
            self.sim = ReplaySimulator(rc, self.transport)
            self.sim.start()
            return self.status()

    def pause(self) -> dict[str, Any]:
        if self.sim:
            self.sim.pause()
        return self.status()

    def resume(self) -> dict[str, Any]:
        if self.sim:
            self.sim.resume()
        return self.status()

    def stop(self) -> dict[str, Any]:
        if self.sim:
            self.sim.stop()
            if self.transport:
                self.transport.close()
        return self.status()

    def status(self) -> dict[str, Any]:
        if self.sim is None:
            return {"state": ReplayState.IDLE.value, "config": None, "stats": None}
        return {"state": self.sim.state.value, "config": self.cfg, "stats": self.sim.stats.as_dict()}
