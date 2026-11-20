"""Mode 1 — dataset replay simulator (docs/02 §4, plan P2.4).

Streams C-MAPSS rows through the SAME ingestion path real devices use (MQTT or HTTP), one cycle per
unit per tick, round-robin across units. Test-split messages carry `meta.true_rul` so the dashboard can
plot predicted vs. true RUL.

    pdm-replay --profile FD001 --split test --units 34 --speed 5
    pdm-replay --profile FD002 --split test --random 10 --speed 20 --transport http
    pdm-replay --profile FD001 --split test --units 34 --transport stdout   # dry run, no broker
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import sys
import threading
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np
import pandas as pd

from pdm_iot.payload import SETTINGS, build_payload
from pdm_iot.transports import HttpTransport, MemoryTransport, MqttTransport, SendResult, Transport, encode
from pdm_ml.io.loader import load_split, load_true_rul, sensor_symbols
from pdm_ml.labels.rul import test_rul

log = logging.getLogger("pdm.replay")
MAX_CONSECUTIVE_FAILURES = 3


class ReplayState(StrEnum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


def asset_id_for(profile: str, split: str, unit: int, prefix: str = "") -> str:
    """FD001 test unit 34 -> 'FD001-T034'; train (run-to-failure) unit 7 -> 'FD001-R007'."""
    tag = "T" if split == "test" else "R"
    return f"{prefix}{profile}-{tag}{unit:03d}"


@dataclass
class ReplayConfig:
    profile: str
    split: str = "test"
    units: Sequence[int] | None = None  # None = all
    random_n: int | None = None
    speed_cps: float = 5.0  # cycles per second per unit (ticks per second)
    loop: bool = False
    site_id: str = "lab"
    asset_prefix: str = ""
    seed: int = 42
    continuous: bool = False  # every unit restarts (new life) as soon as it ends: constant fleet size, never stops


@dataclass
class ReplayStats:
    sent: int = 0
    accepted: int = 0
    failed: int = 0
    started_at: float | None = None
    finished_at: float | None = None
    per_unit_progress: dict[str, tuple[int, int]] = field(default_factory=dict)
    last_error: str = ""

    def as_dict(self) -> dict[str, Any]:
        elapsed = ((self.finished_at or time.time()) - self.started_at) if self.started_at else 0.0
        return {"sent": self.sent, "accepted": self.accepted, "failed": self.failed,
                "rate_msgs_s": round(self.sent / elapsed, 2) if elapsed > 0 else 0.0,
                "last_error": self.last_error,
                "progress": {k: {"cycle": c, "of": n} for k, (c, n) in self.per_unit_progress.items()}}


def select_units(df: pd.DataFrame, cfg: ReplayConfig) -> list[int]:
    all_units = sorted(int(u) for u in df.unit.unique())
    if cfg.units:
        missing = sorted(set(cfg.units) - set(all_units))
        if missing:
            raise ValueError(f"units not in {cfg.profile} {cfg.split}: {missing}")
        return list(cfg.units)
    if cfg.random_n:
        rng = np.random.default_rng(cfg.seed)
        return sorted(int(u) for u in rng.choice(all_units, size=min(cfg.random_n, len(all_units)), replace=False))
    return all_units


def build_messages(cfg: ReplayConfig, run_tag: str = "") -> Iterator[list[dict[str, Any]]]:
    """Yield one tick at a time: a list with the next cycle of every still-active unit.

    ``run_tag`` goes into every msg_id so that a looped lap or a new run is not mistaken
    for a re-delivery of the previous one (ingest dedups on msg_id).
    """
    df = load_split(cfg.profile, "test" if cfg.split == "test" else "train")
    units = select_units(df, cfg)
    df = df[df.unit.isin(units)]
    if cfg.split == "test":
        df = df.assign(true_rul=test_rul(df, load_true_rul(cfg.profile)).to_numpy())
    else:
        df = df.assign(true_rul=(df.groupby("unit").cycle.transform("max") - df.cycle).to_numpy())
    sensors = sensor_symbols()
    groups = {u: g.to_dict("records") for u, g in df.groupby("unit")}
    seq = {u: 0 for u in units}
    max_len = max(len(g) for g in groups.values())
    i = 0
    while cfg.continuous or i < max_len:
        tick = []
        for u in units:
            rows = groups[u]
            if i >= len(rows) and not cfg.continuous:
                continue
            j = i % len(rows)
            r = rows[j]
            seq[u] += 1
            aid = asset_id_for(cfg.profile, cfg.split, u, cfg.asset_prefix)
            tick.append(build_payload(
                site_id=cfg.site_id, asset_id=aid, profile=cfg.profile, source="REPLAY",
                seq=seq[u], cycle=int(r["cycle"]),
                settings={k: r[k] for k in SETTINGS}, sensors={k: r[k] for k in sensors},
                msg_prefix=f"replay-{run_tag}-{aid}" if run_tag else f"replay-{aid}",
                meta={"true_rul": int(r["true_rul"]), "split": cfg.split, "unit": u, "len": len(rows),
                      "eol": j == len(rows) - 1},
            ))
        yield tick
        i += 1


class ReplaySimulator:
    """Thread-based controller with the state machine from docs/02 §4."""

    def __init__(self, cfg: ReplayConfig, transport: Transport) -> None:
        self.cfg, self.transport = cfg, transport
        self.state = ReplayState.IDLE
        self.stats = ReplayStats()
        self._resume = threading.Event()
        self._resume.set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # controls
    def start(self, block: bool = False) -> None:
        if self.state in (ReplayState.RUNNING, ReplayState.PAUSED):
            raise RuntimeError("replay already running")
        self.state, self.stats = ReplayState.RUNNING, ReplayStats(started_at=time.time())
        self._stop.clear()
        self._resume.set()
        if block:
            self._run()
        else:
            self._thread = threading.Thread(target=self._run, name="replay", daemon=True)
            self._thread.start()

    def pause(self) -> None:
        if self.state == ReplayState.RUNNING:
            self._resume.clear()
            self.state = ReplayState.PAUSED

    def resume(self) -> None:
        if self.state == ReplayState.PAUSED:
            self.state = ReplayState.RUNNING
            self._resume.set()

    def stop(self) -> None:
        self._stop.set()
        self._resume.set()
        if self._thread:
            self._thread.join(timeout=10)

    def wait(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def _send(self, msg: dict[str, Any]) -> SendResult:
        res = self.transport.send(msg)
        self.stats.sent += 1
        if res.ok:
            self.stats.accepted += 1
        else:
            self.stats.failed += 1
            self.stats.last_error = res.detail
        return res

    def _run(self) -> None:
        period = 1.0 / self.cfg.speed_cps if self.cfg.speed_cps > 0 else 0.0
        consecutive_fail = 0
        try:
            run = secrets.token_hex(3)
            lap = 0
            while True:
                lap += 1
                for tick in build_messages(self.cfg, run_tag=f"{run}{lap}"):
                    t0 = time.monotonic()
                    for msg in tick:
                        self._resume.wait()
                        if self._stop.is_set():
                            self.state = ReplayState.STOPPED
                            return
                        res = self._send(msg)
                        consecutive_fail = 0 if res.ok else consecutive_fail + 1
                        if consecutive_fail >= MAX_CONSECUTIVE_FAILURES:
                            self.state = ReplayState.ERROR
                            log.error("ingest unreachable %d times in a row: %s", consecutive_fail, res.detail)
                            return
                        self.stats.per_unit_progress[msg["asset_id"]] = (msg["cycle"], msg["meta"]["len"])
                    if period:
                        time.sleep(max(0.0, period - (time.monotonic() - t0)))
                if not self.cfg.loop:
                    break
            self.state = ReplayState.COMPLETED
        except Exception as e:  # surfaced in state, never kills the host process
            self.stats.last_error = f"{type(e).__name__}: {e}"
            self.state = ReplayState.ERROR
            log.exception("replay crashed")
        finally:
            self.stats.finished_at = time.time()


class StdoutTransport(MemoryTransport):
    def send(self, payload: dict[str, Any], raw: bytes | None = None) -> SendResult:
        sys.stdout.write((raw or encode(payload)).decode() + "\n")
        return SendResult(True)


def make_transport(kind: str) -> Transport:
    if kind == "mqtt":
        return MqttTransport(os.environ.get("MQTT_HOST", "localhost"), int(os.environ.get("MQTT_PORT", "1883")),
                             "pdm-replay", os.environ.get("MQTT_REPLAY_PASSWORD"),
                             os.environ.get("MQTT_TOPIC_PREFIX", "pdm/v1"))
    if kind == "http":
        return HttpTransport(os.environ.get("INGEST_URL", "http://localhost:8000/api/v1/ingest"),
                             os.environ.get("INGEST_API_KEY", ""))
    if kind == "stdout":
        return StdoutTransport()
    raise ValueError(kind)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True, choices=["FD001", "FD002", "FD003", "FD004"])
    ap.add_argument("--split", default="test", choices=["test", "train"])
    ap.add_argument("--units", type=int, nargs="*", help="unit ids (default: all)")
    ap.add_argument("--random", type=int, dest="random_n", help="replay N random units")
    ap.add_argument("--speed", type=float, default=5.0, help="cycles per second (0 = as fast as possible)")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--continuous", action="store_true",
                    help="restart each unit as soon as it ends (constant load; used by the P3.9 load test)")
    ap.add_argument("--site", default=os.environ.get("MQTT_SITE_ID", "lab"))
    ap.add_argument("--transport", default="mqtt", choices=["mqtt", "http", "stdout"])
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    cfg = ReplayConfig(args.profile, args.split, args.units, args.random_n, args.speed, args.loop, args.site,
                       continuous=args.continuous)
    transport = make_transport(args.transport)
    sim = ReplaySimulator(cfg, transport)
    try:
        sim.start(block=True)
    except KeyboardInterrupt:
        sim.stop()
    finally:
        transport.close()
    print(json.dumps({"state": sim.state, **{k: v for k, v in sim.stats.as_dict().items() if k != "progress"}}),
          file=sys.stderr)
    return 0 if sim.state == ReplayState.COMPLETED else 1


if __name__ == "__main__":
    sys.exit(main())
