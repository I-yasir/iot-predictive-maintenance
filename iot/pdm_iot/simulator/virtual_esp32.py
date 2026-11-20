"""Mode 2b — virtual ESP32 (plan P2.7).

A Python twin of the firmware: same generator (pdm_generator.h, mirrored here line for line), same payload
layout, same MQTT topics/LWT, so Mode 2 logic is testable in CI without a board. Adds scheduled fault
injection for the harness.

    pdm-virtual-esp32 --asset FD001-V001 --mode trajectory --rate 2
    pdm-virtual-esp32 --count 60 --faults malformed@10,missing@20,range@30,duplicate@40,out_of_order@45,drop@50:3
    pdm-virtual-esp32 --count 5 --transport stdout
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import math
import os
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from pdm_iot.payload import build_payload
from pdm_iot.transports import HttpTransport, MqttTransport, SendResult, Transport, encode
from pdm_ml.config import find_root

log = logging.getLogger("pdm.virtual_esp32")
FW_VERSION = "virtual-esp32/0.1.0"
TRAJECTORY, DISTRIBUTION = "trajectory", "distribution"


def _f32(values: Any) -> np.ndarray:
    """Arrays live in flash as float32 on the ESP32; mirror that exactly."""
    return np.asarray(values, dtype=np.float32).astype(np.float64)


class Generator:
    """Mirror of PdmGenerator in iot/esp32/include/pdm_generator.h. Keep the two in lock-step."""

    def __init__(self, profile: dict[str, Any], seed: int, mode: str) -> None:
        self.p = profile
        self.n = len(profile["channels"])
        self.n_settings = int(profile["n_settings"])
        self.traj = _f32(profile["trajectory"]).reshape(-1, self.n)
        self.mu = _f32(profile["healthy_mean"])
        self.sigma = _f32(profile["noise_sigma"])
        self.drift_tab = _f32(profile["drift"]).reshape(-1, self.n)
        self.step = int(profile["drift_grid"][1] - profile["drift_grid"][0])
        self.state = (seed | 1) & 0xFFFFFFFF
        self.mode = mode
        self.cycle = 0
        self.life = 0
        self._new_life()

    def _xorshift32(self) -> int:
        x = self.state
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.state = x
        return x

    def _uniform(self) -> float:
        return ((self._xorshift32() >> 8) + 1.0) / 16777216.0

    def _gauss(self) -> float:
        u1, u2 = self._uniform(), self._uniform()
        return math.sqrt(-2.0 * math.log(u1)) * math.cos(6.283185307179586 * u2)

    @staticmethod
    def _round4(v: float) -> float:
        # C round(): half away from zero
        x = v * 10000.0
        return math.copysign(math.floor(abs(x) + 0.5), x) / 10000.0

    def _drift(self, remaining: int, j: int) -> float:
        remaining = max(remaining, 0)
        max_r = (len(self.drift_tab) - 1) * self.step
        if remaining >= max_r:
            return float(self.drift_tab[-1, j])
        i = remaining // self.step
        f = (remaining - i * self.step) / self.step
        a, b = self.drift_tab[i, j], self.drift_tab[i + 1, j]
        return float(a + f * (b - a))

    def _new_life(self) -> None:
        self.cycle = 0
        if self.mode == TRAJECTORY:
            self.life = len(self.traj)
        else:
            lifetime = math.exp(self.p["life_log_mean"] + self.p["life_log_std"] * self._gauss())
            self.life = max(int(self.p["life_min"]), int(math.copysign(math.floor(abs(lifetime) + 0.5), lifetime)))

    def next(self) -> tuple[int, list[float]]:
        if self.cycle >= self.life:
            self._new_life()
        self.cycle += 1
        out = []
        for j in range(self.n):
            z = self._gauss()
            if self.mode == TRAJECTORY:
                base = float(self.traj[self.cycle - 1, j])
                noise = 0.0 if j < self.n_settings else self.p["noise_scale_trajectory"] * float(self.sigma[j]) * z
                out.append(self._round4(base + noise))
            else:
                out.append(self._round4(float(self.mu[j]) + self._drift(self.life - self.cycle, j) + float(self.sigma[j]) * z))
        return self.cycle, out

    @property
    def end_of_life(self) -> bool:
        return self.cycle >= self.life

    def true_remaining(self) -> int:
        extra = int(self.p["trajectory_true_rul_end"]) if self.mode == TRAJECTORY else 0
        return self.life - self.cycle + extra


def load_profile_json(profile: str = "FD001") -> dict[str, Any]:
    path = find_root() / "iot" / "esp32" / f"profile_{profile.lower()}.json"
    data: dict[str, Any] = json.loads(path.read_text())
    return data


@dataclass
class Fault:
    kind: str
    at_seq: int
    arg: float = 0.0


def parse_faults(spec: str | None) -> list[Fault]:
    """'malformed@10,missing@20,range@30,duplicate@40,out_of_order@45,drop@50:3'"""
    out = []
    for item in filter(None, (spec or "").split(",")):
        kind, _, rest = item.partition("@")
        at, _, arg = rest.partition(":")
        if kind not in {"malformed", "missing", "range", "duplicate", "out_of_order", "drop"}:
            raise ValueError(f"unknown fault {kind!r}")
        out.append(Fault(kind, int(at), float(arg or 0)))
    return out


@dataclass
class VirtualDevice:
    asset_id: str
    profile_name: str = "FD001"
    site_id: str = "lab"
    mode: str = TRAJECTORY
    seed: int = 12345
    source: str = "VIRTUAL_ESP32"
    faults: list[Fault] = field(default_factory=list)
    buffer_size: int = 64  # firmware ring buffer while "Wi-Fi" is down

    def __post_init__(self) -> None:
        self.profile = load_profile_json(self.profile_name)
        self.gen = Generator(self.profile, self.seed, self.mode)
        self.seq = 0
        self.device_id = f"{self.seed & 0xFFFFFF:06x}"
        self.injected: list[dict[str, Any]] = []

    def next_payload(self) -> dict[str, Any]:
        cycle, values = self.gen.next()
        self.seq += 1
        chans = self.profile["channels"]
        ns = self.profile["n_settings"]
        return build_payload(
            site_id=self.site_id, asset_id=self.asset_id, profile=self.profile_name, source=self.source,
            seq=self.seq, cycle=cycle,
            settings=dict(zip(chans[:ns], values[:ns], strict=True)),
            sensors=dict(zip(chans[ns:], values[ns:], strict=True)),
            msg_prefix=f"esp32-{self.device_id}",
            meta={"fw": FW_VERSION, "rssi": -55, "mode": self.mode, "eol": self.gen.end_of_life,
                  "true_rul": self.gen.true_remaining(), "profile_version": self.profile["version"]},
        )

    def wire_messages(self, payload: dict[str, Any]) -> list[tuple[bytes, str]]:
        """Apply any fault scheduled at this seq. Returns [(bytes, label)] to transmit (may be several)."""
        seq = payload["seq"]
        msgs: list[tuple[bytes, str]] = [(encode(payload), "ok")]
        for f in (f for f in self.faults if f.at_seq == seq and f.kind != "drop"):  # drop lives in run()
            self.injected.append({"kind": f.kind, "seq": seq})
            if f.kind == "malformed":
                msgs = [(encode(payload)[:-7] + b"#!", "malformed")]
            elif f.kind == "missing":
                p = copy.deepcopy(payload)
                p["sensors"].pop("T30", None)
                msgs = [(encode(p), "missing")]
            elif f.kind == "range":
                p = copy.deepcopy(payload)
                p["sensors"]["T30"] = 99999.0
                msgs = [(encode(p), "range")]
            elif f.kind == "duplicate":
                msgs = [(encode(payload), "ok"), (encode(payload), "duplicate")]
            elif f.kind == "out_of_order":
                p = copy.deepcopy(payload)
                p["cycle"] = max(1, p["cycle"] - 3)
                p["msg_id"] += "-ooo"
                msgs = [(encode(payload), "ok"), (encode(p), "out_of_order")]
        return msgs


def run(device: VirtualDevice, transport: Transport, count: int, rate_hz: float) -> dict[str, Any]:
    period = 1.0 / rate_hz if rate_hz > 0 else 0.0
    buffered: deque[tuple[bytes, str, dict[str, Any]]] = deque(maxlen=device.buffer_size)
    drop_until_seq = 0
    stats: dict[str, Any] = {"generated": 0, "sent": 0, "send_failures": 0, "buffer_overflow": 0}
    for _ in range(count):
        t0 = time.monotonic()
        payload = device.next_payload()
        stats["generated"] += 1
        drop = next((f for f in device.faults if f.kind == "drop" and f.at_seq == payload["seq"]), None)
        if drop:
            device.injected.append({"kind": "drop", "seq": payload["seq"], "cycles": int(drop.arg)})
            drop_until_seq = payload["seq"] + int(drop.arg)
        for raw, label in device.wire_messages(payload):
            if payload["seq"] < drop_until_seq:  # "Wi-Fi down": buffer like the firmware does
                if len(buffered) == buffered.maxlen:
                    stats["buffer_overflow"] += 1
                buffered.append((raw, label, payload))
                continue
            while buffered:  # flush in order after reconnect
                b_raw, _, b_payload = buffered.popleft()
                _count(stats, transport.send(b_payload, raw=b_raw))
            _count(stats, transport.send(payload, raw=raw))
        if period:
            time.sleep(max(0.0, period - (time.monotonic() - t0)))
    while buffered:
        b_raw, _, b_payload = buffered.popleft()
        _count(stats, transport.send(b_payload, raw=b_raw))
    stats["injected"] = device.injected
    return stats


def _count(stats: dict[str, Any], res: SendResult) -> None:
    stats["sent"] += 1
    if not res.ok:
        stats["send_failures"] += 1


class _Stdout:
    def send(self, payload: dict[str, Any], raw: bytes | None = None) -> SendResult:
        sys.stdout.write((raw or encode(payload)).decode(errors="replace") + "\n")
        return SendResult(True)

    def close(self) -> None:
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--asset", default=os.environ.get("VIRTUAL_ASSET_ID", "FD001-V001"))
    ap.add_argument("--profile", default="FD001", choices=["FD001", "FD003"])
    ap.add_argument("--mode", default=TRAJECTORY, choices=[TRAJECTORY, DISTRIBUTION])
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--rate", type=float, default=1.0, help="messages per second (0 = no delay)")
    ap.add_argument("--count", type=int, default=0, help="messages to send (0 = one full life)")
    ap.add_argument("--faults", default="", help="e.g. malformed@10,missing@20,range@30,duplicate@40,drop@50:3")
    ap.add_argument("--site", default=os.environ.get("MQTT_SITE_ID", "lab"))
    ap.add_argument("--transport", default="mqtt", choices=["mqtt", "http", "stdout"])
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    dev = VirtualDevice(args.asset, args.profile, args.site, args.mode, args.seed, faults=parse_faults(args.faults))
    transport: Transport
    if args.transport == "mqtt":
        transport = MqttTransport(os.environ.get("MQTT_HOST", "localhost"), int(os.environ.get("MQTT_PORT", "1883")),
                                  "pdm-replay", os.environ.get("MQTT_REPLAY_PASSWORD"),
                                  os.environ.get("MQTT_TOPIC_PREFIX", "pdm/v1"))
    elif args.transport == "http":
        transport = HttpTransport(os.environ.get("INGEST_URL", "http://localhost:8000/api/v1/ingest"),
                                  os.environ.get("INGEST_API_KEY", ""))
    else:
        transport = _Stdout()
    count = args.count or dev.gen.life
    try:
        stats = run(dev, transport, count, args.rate)
    finally:
        transport.close()
    print(json.dumps(stats), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
