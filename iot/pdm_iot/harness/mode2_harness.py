"""Mode 2 test harness (plan P2.8, docs/05 §10).

Observes the MQTT telemetry of one site, optionally drives a virtual ESP32 with scheduled faults, and
checks what a Mode 2 device must guarantee before the backend trusts it:

  schema     every clean message passes the TelemetryPayload v1 contract
  rate       observed msgs/s is within 20 % of the configured rate
  sequence   no permanent seq gaps (buffered messages after a Wi-Fi drop must arrive late, in order)
  latency    receive time - payload ts (p50/p95/max), so a buffered flush is visible
  faults     every injected fault is caught with the expected reason
  acks       the echo-ack stub (a stand-in for the backend) acked every accepted message

    pdm-harness --virtual --count 60 --rate 10 --faults malformed@10,missing@20,range@30,duplicate@40,out_of_order@45,drop@50:3
    pdm-harness --listen 120 --asset FD001-E001 --rate 1      # a physical ESP32 on the same broker

Writes reports/mode2_<UTC timestamp>.md and .json.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from pdm_contracts import Accepted, Profile, Rejection, load_profiles, parse_topic, validate_message
from pdm_iot.simulator.virtual_esp32 import VirtualDevice, parse_faults, run
from pdm_iot.transports import MqttTransport
from pdm_ml.config import find_root

log = logging.getLogger("pdm.harness")

# what the backend must say for each injected fault
EXPECTED = {
    "malformed": "parse_error",
    "missing": "schema:sensors.T30",
    "range": "range:T30",
    "duplicate": "duplicate_msg_id",
    "out_of_order": "cycle_regression",
    "drop": "buffered_then_flushed",
}


@dataclass
class Received:
    t_recv: float
    topic: str
    raw: bytes


@dataclass
class Analysis:
    total: int = 0
    accepted: int = 0
    rejected: Counter[str] = field(default_factory=Counter)
    flags: Counter[str] = field(default_factory=Counter)
    duplicates: list[str] = field(default_factory=list)
    regressions: list[int] = field(default_factory=list)  # seq of messages whose cycle went backwards
    late: list[int] = field(default_factory=list)  # seq that arrived after a higher seq (buffered flush)
    missing_seq: list[int] = field(default_factory=list)
    rate_hz: float = 0.0
    latency_ms: dict[str, float] = field(default_factory=dict)
    rejected_seq: dict[int, str] = field(default_factory=dict)
    status: list[dict[str, Any]] = field(default_factory=list)


class Observer:
    """Records telemetry + status for a site. Optionally acks like the backend will (echo-ack stub)."""

    def __init__(self, transport: MqttTransport, site: str, prefix: str, profiles: dict[str, Profile],
                 ack_transport: MqttTransport | None = None) -> None:
        self.records: list[Received] = []
        self.acks: list[dict[str, Any]] = []
        self.profiles, self.prefix, self.ack = profiles, prefix, ack_transport
        self._lock = threading.Lock()
        transport.subscribe(f"{prefix}/{site}/+/telemetry", self._on_msg)
        transport.subscribe(f"{prefix}/{site}/+/status", self._on_msg)
        transport.subscribe(f"{prefix}/{site}/+/ack", self._on_ack)

    def _on_msg(self, topic: str, raw: bytes) -> None:
        with self._lock:
            self.records.append(Received(time.time(), topic, raw))
        parsed = parse_topic(topic, self.prefix)
        if self.ack is None or parsed is None or parsed[2] != "telemetry":
            return
        res = validate_message(raw, self.profiles, (parsed[0], parsed[1]))
        body: dict[str, Any] = {"status": "accepted" if isinstance(res, Accepted) else "rejected"}
        if isinstance(res, Accepted):
            body["msg_id"] = res.payload.msg_id
        else:
            body["reason"] = res.reason
        self.ack.publish(f"{self.prefix}/{parsed[0]}/{parsed[1]}/ack", json.dumps(body).encode())

    def _on_ack(self, topic: str, raw: bytes) -> None:
        with self._lock:
            self.acks.append(json.loads(raw))

    def snapshot(self) -> tuple[list[Received], list[dict[str, Any]]]:
        with self._lock:
            return list(self.records), list(self.acks)


def analyse(records: list[Received], profiles: dict[str, Profile], prefix: str = "pdm/v1") -> Analysis:
    a = Analysis()
    seen_ids: set[str] = set()
    last_cycle: dict[str, tuple[int, bool]] = {}
    max_seq: dict[str, int] = {}
    seqs: dict[str, set[int]] = {}
    times: list[float] = []
    lat: list[float] = []
    for r in records:
        parsed = parse_topic(r.topic, prefix)
        if parsed is None:
            continue
        site, asset, kind = parsed
        if kind == "status":
            try:
                a.status.append({"t": r.t_recv, "asset": asset, **json.loads(r.raw)})
            except (json.JSONDecodeError, TypeError):
                a.status.append({"t": r.t_recv, "asset": asset, "raw": r.raw[:80].decode(errors="replace")})
            continue
        if kind != "telemetry":
            continue
        a.total += 1
        times.append(r.t_recv)
        res = validate_message(r.raw, profiles, (site, asset))
        if isinstance(res, Rejection):
            a.rejected[res.reason] += 1
            seq = _peek_seq(r.raw)
            if seq is not None:
                a.rejected_seq[seq] = res.reason
                seqs.setdefault(asset, set()).add(seq)
                max_seq[asset] = max(max_seq.get(asset, 0), seq)
            continue
        p = res.payload
        a.flags.update(res.flags)
        if p.msg_id in seen_ids:
            a.duplicates.append(p.msg_id)
            a.rejected["duplicate_msg_id"] += 1
            continue
        seen_ids.add(p.msg_id)
        a.accepted += 1
        prev = last_cycle.get(asset)
        if prev and p.cycle < prev[0] and not prev[1]:  # cycle went back without an end-of-life reset
            a.regressions.append(p.seq)
        if p.seq < max_seq.get(asset, 0):
            a.late.append(p.seq)
        max_seq[asset] = max(max_seq.get(asset, 0), p.seq)
        seqs.setdefault(asset, set()).add(p.seq)
        last_cycle[asset] = (max(p.cycle, prev[0]) if prev and not prev[1] else p.cycle, bool(p.meta.get("eol")))
        if p.ts is not None:  # an ESP32 without NTP omits ts
            lat.append((r.t_recv - p.ts.timestamp()) * 1000.0)
    for s in seqs.values():
        a.missing_seq += sorted(set(range(min(s), max(s) + 1)) - s)
    if len(times) > 1 and times[-1] > times[0]:
        a.rate_hz = round((len(times) - 1) / (times[-1] - times[0]), 2)
    if lat:
        arr = np.asarray(lat)
        a.latency_ms = {"p50": round(float(np.percentile(arr, 50)), 1), "p95": round(float(np.percentile(arr, 95)), 1),
                        "max": round(float(arr.max()), 1)}
    return a


def _peek_seq(raw: bytes) -> int | None:
    try:
        v = json.loads(raw).get("seq")
        return int(v) if isinstance(v, int) else None
    except (json.JSONDecodeError, AttributeError, UnicodeDecodeError):
        return None


def check(a: Analysis, rate_hz: float, injected: list[dict[str, Any]], acks: list[dict[str, Any]] | None,
          drop_buffered: int = 0) -> list[dict[str, Any]]:
    """Turn an Analysis into pass/fail checks."""
    out: list[dict[str, Any]] = []
    injected_reject = sum(1 for f in injected if f["kind"] in ("malformed", "missing", "range"))
    clean_rejects = sum(n for k, n in a.rejected.items() if k != "duplicate_msg_id") - injected_reject
    out.append({"check": "schema", "ok": a.total > 0 and clean_rejects == 0,
                "detail": f"{a.accepted} accepted, {sum(a.rejected.values())} rejected ({dict(a.rejected)}), "
                          f"{injected_reject} of those were injected"})
    if rate_hz > 0:
        # a drop buffers then flushes in a burst, which inflates the average; allow for it
        ok = a.rate_hz >= 0.8 * rate_hz and (a.rate_hz <= 1.2 * rate_hz or drop_buffered > 0)
        out.append({"check": "rate", "ok": ok, "detail": f"observed {a.rate_hz} msg/s vs configured {rate_hz}"})
    # a malformed message cannot be read back, so its seq is legitimately "missing"
    unreadable = {f["seq"] for f in injected if f["kind"] == "malformed"}
    gaps = [s for s in a.missing_seq if s not in unreadable]
    out.append({"check": "sequence", "ok": not gaps,
                "detail": ("no permanent gaps" if not gaps else f"missing seq {gaps[:20]}")
                + (f" (seq {sorted(unreadable)} unreadable by design)" if unreadable else "")})
    out.append({"check": "latency", "ok": bool(a.latency_ms), "detail": json.dumps(a.latency_ms)})
    for f in injected:
        kind, seq = f["kind"], f["seq"]
        if kind in ("malformed", "missing", "range"):
            if kind == "malformed":  # unparseable, so match on count rather than seq
                n_bad = sum(1 for x in injected if x["kind"] == "malformed")
                ok = a.rejected.get("parse_error", 0) == n_bad
                got = f"{a.rejected.get('parse_error', 0)} parse_error for {n_bad} injected"
            else:
                got = a.rejected_seq.get(seq, "accepted")
                ok = got == EXPECTED[kind]
        elif kind == "duplicate":
            ok, got = bool(a.duplicates), f"{len(a.duplicates)} duplicate msg_id"
        elif kind == "out_of_order":
            ok, got = seq in a.regressions, f"regressions at seq {a.regressions}"
        else:  # drop: the buffered seqs must all arrive (flushed in order on reconnect) and show the delay
            n = int(f.get("cycles", 0))
            want = set(range(seq, seq + n))
            min_delay_ms = 0.5 * (n - 1) * 1000.0 / rate_hz if rate_hz > 0 else 0.0
            ok = not (want & set(a.missing_seq)) and a.latency_ms.get("max", 0.0) >= min_delay_ms
            got = f"{n} buffered and flushed, none lost; max latency {a.latency_ms.get('max')} ms"
        out.append({"check": f"fault:{kind}@{seq}", "ok": ok, "detail": f"expected {EXPECTED[kind]}, got {got}"})
    if acks is not None:
        acked = sum(1 for x in acks if x.get("status") == "accepted")
        out.append({"check": "acks", "ok": acked == a.accepted + len(a.duplicates),
                    "detail": f"{acked} accepted acks for {a.accepted} accepted (+{len(a.duplicates)} duplicates, "
                              f"which the stub does not de-duplicate)"})
    return out


def render_markdown(meta: dict[str, Any], a: Analysis, checks: list[dict[str, Any]]) -> str:
    passed = all(c["ok"] for c in checks)
    lines = [f"# Mode 2 harness report: {'PASS' if passed else 'FAIL'}", "",
             f"Generated {meta['generated']} by `pdm-harness` ({meta['mode']}).", "",
             "| Setting | Value |", "|---|---|"]
    lines += [f"| {k} | `{v}` |" for k, v in meta.items() if k not in ("generated",)]
    lines += ["", "## Checks", "", "| Check | Result | Detail |", "|---|---|---|"]
    lines += [f"| {c['check']} | {'PASS' if c['ok'] else '**FAIL**'} | {c['detail']} |" for c in checks]
    lines += ["", "## Traffic", "",
              f"- telemetry messages received: {a.total} (accepted {a.accepted})",
              f"- rejections: {dict(a.rejected) or 'none'}",
              f"- soft out-of-distribution flags: {dict(a.flags) or 'none'}",
              f"- late (buffered) seqs: {a.late or 'none'}",
              f"- status messages: {len(a.status)}", ""]
    return "\n".join(lines)


def _mqtt(user: str, password_env: str, client_id: str) -> MqttTransport:
    return MqttTransport(os.environ.get("MQTT_HOST", "localhost"), int(os.environ.get("MQTT_PORT", "1883")), user,
                         os.environ.get(password_env), os.environ.get("MQTT_TOPIC_PREFIX", "pdm/v1"),
                         client_id=client_id)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--virtual", action="store_true", help="drive an in-process virtual ESP32")
    g.add_argument("--listen", type=float, metavar="SECONDS", help="only observe (physical device)")
    ap.add_argument("--asset", default="FD001-V001")
    ap.add_argument("--site", default=os.environ.get("MQTT_SITE_ID", "lab"))
    ap.add_argument("--mode", default="trajectory", choices=["trajectory", "distribution"])
    ap.add_argument("--count", type=int, default=60)
    ap.add_argument("--rate", type=float, default=10.0)
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--faults", default="")
    ap.add_argument("--no-ack", action="store_true", help="do not run the echo-ack backend stub")
    ap.add_argument("--out", default=str(find_root() / "reports"))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(message)s")

    prefix = os.environ.get("MQTT_TOPIC_PREFIX", "pdm/v1")
    profiles = load_profiles(find_root() / "config" / "profiles")
    watcher = _mqtt("pdm-harness", "MQTT_HARNESS_PASSWORD", "pdm-harness-observer")
    acker = None if args.no_ack else _mqtt("pdm-backend", "MQTT_BACKEND_PASSWORD", "pdm-harness-ackstub")
    obs = Observer(watcher, args.site, prefix, profiles, acker)
    time.sleep(0.5)  # let subscriptions settle
    injected: list[dict[str, Any]] = []
    drop_buffered = 0
    try:
        if args.virtual:
            dev = VirtualDevice(args.asset, site_id=args.site, mode=args.mode, seed=args.seed,
                                faults=parse_faults(args.faults))
            pub = _mqtt("pdm-replay", "MQTT_REPLAY_PASSWORD", f"pdm-virtual-{args.asset}")
            try:
                stats = run(dev, pub, args.count, args.rate)
            finally:
                pub.close()
            injected = stats["injected"]
            drop_buffered = sum(int(f.get("cycles", 0)) for f in injected if f["kind"] == "drop")
        else:
            time.sleep(args.listen or 0)
        time.sleep(1.0)  # drain in-flight messages and acks
    finally:
        watcher.close()
        if acker:
            acker.close()
    records, acks = obs.snapshot()
    a = analyse(records, profiles, prefix)
    checks = check(a, args.rate, injected, None if args.no_ack else acks, drop_buffered)
    meta = {"generated": datetime.now(UTC).isoformat(timespec="seconds"),
            "mode": "virtual ESP32" if args.virtual else f"listen {args.listen}s",
            "asset": args.asset, "site": args.site, "rate_hz": args.rate, "count": args.count,
            "faults": args.faults or "none", "generator_mode": args.mode, "seed": args.seed}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (out / f"mode2_{stamp}.md").write_text(render_markdown(meta, a, checks))
    (out / f"mode2_{stamp}.json").write_text(json.dumps(
        {"meta": meta, "checks": checks, "injected": injected, "rejected": dict(a.rejected),
         "late": a.late, "latency_ms": a.latency_ms, "rate_hz": a.rate_hz}, indent=2) + "\n")
    passed = all(c["ok"] for c in checks)
    print(f"{'PASS' if passed else 'FAIL'}: reports/mode2_{stamp}.md", file=sys.stderr)
    for c in checks:
        print(f"  {'ok  ' if c['ok'] else 'FAIL'} {c['check']}: {c['detail']}", file=sys.stderr)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
