"""P3.9 load test: N assets over MQTT at a target total rate against a real backend process.

Starts the backend (uvicorn) with the MQTT subscriber, then `pdm-replay --continuous` publishers (4 per profile, disjoint units)
(round-robin, QoS 1). Samples backend RSS and /api/v1/stats every 10 s and writes reports/perf_p39.{json,md}.

    python backend/perf/load_test.py --rate 500 --assets 300 --duration 300
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
BIN = Path(sys.executable).parent


def rss_mb(pid: int) -> float:
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    return 0.0


def read_hist(text: str) -> dict[float, float]:
    out = {}
    for line in text.splitlines():
        if line.startswith("ingest_to_prediction_seconds_bucket"):
            le = line.split('le="')[1].split('"')[0]
            out[float("inf") if le == "+Inf" else float(le)] = float(line.rsplit(" ", 1)[1])
    return out


def hist_quantile(h: dict[float, float], q: float) -> float | None:
    """Prometheus-style quantile (linear inside the bucket) of a cumulative histogram, in ms."""
    les = sorted(h)
    total = h[les[-1]] if les else 0.0
    if not total:
        return None
    prev_le, prev_n = 0.0, 0.0
    for le in les:
        if h[le] >= q * total:
            if le == float("inf"):
                return prev_le * 1000.0
            return (prev_le + (le - prev_le) * (q * total - prev_n) / max(h[le] - prev_n, 1e-9)) * 1000.0
        prev_le, prev_n = le, h[le]
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=float, default=500)
    ap.add_argument("--assets", type=int, default=300)
    ap.add_argument("--duration", type=float, default=300)
    ap.add_argument("--profiles", default="FD001,FD002,FD004")
    ap.add_argument("--port", type=int, default=8077)
    ap.add_argument("--publishers-per-profile", type=int, default=4)
    ap.add_argument("--warmup", type=float, default=60, help="seconds excluded from the NFR verdict")
    ap.add_argument("--workers", type=int, default=2, help="backend MQTT worker threads")
    args = ap.parse_args()
    env = {**os.environ, "DASHBOARD_PASSWORD": "perf", "SESSION_SECRET": "p" * 32, "LOG_LEVEL": "WARNING",
           "MQTT_WORKERS": str(args.workers)}
    backend = subprocess.Popen([str(BIN / "uvicorn"), "app.main:create_app", "--factory", "--port", str(args.port),
                                "--log-level", "warning"], cwd=ROOT, env=env)
    base = f"http://127.0.0.1:{args.port}"
    c = httpx.Client(base_url=base, timeout=10)
    for _ in range(120):
        try:
            if c.get("/readyz").status_code == 200 and c.get("/readyz").json()["checks"]["mqtt"]:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    else:
        backend.kill()
        raise SystemExit("backend did not become ready")
    c.post("/api/v1/auth/login", json={"password": "perf"})
    profiles = args.profiles.split(",")
    per = args.assets // len(profiles)
    speed = args.rate / args.assets  # ticks per second; one message per asset per tick
    # Several publishers per profile on disjoint units: each publish waits for its PUBACK (like a real ESP32),
    # so one client serialising 100 devices would cap the offered load below the target, not the backend.
    k = args.publishers_per_profile
    pubs = [subprocess.Popen([str(BIN / "pdm-replay"), "--profile", p, "--split", "train",
                              "--units", *[str(u) for u in range(1 + j, per + 1, k)],
                              "--speed", f"{speed:.4f}", "--continuous", "--transport", "mqtt"],
                             cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for p in profiles for j in range(k)]
    samples = []
    t0 = time.time()
    hist_warm: dict[float, float] = {}
    try:
        while time.time() - t0 < args.duration:
            time.sleep(10)
            if not hist_warm and time.time() - t0 >= args.warmup:
                hist_warm = read_hist(c.get("/metrics").text)
            s = c.get("/api/v1/stats").json()
            samples.append({"t": round(time.time() - t0), "rss_mb": round(rss_mb(backend.pid), 1),
                            "rate": s["ingest"]["rate_msgs_s_10s"], "latency_ms": s["ingest"]["latency_ms"],
                            "active_assets": s["active_assets"], "counts": s["ingest"]["counts"]})
            print(json.dumps(samples[-1]), flush=True)
    finally:
        for p in pubs:
            p.send_signal(signal.SIGINT)
        time.sleep(2)
        metrics = c.get("/metrics").text
        for p in pubs:
            p.kill()
        backend.send_signal(signal.SIGINT)
        backend.wait(20)
    steady = [x for x in samples if x["t"] > args.warmup]
    warm = [x for x in samples if x["t"] <= args.warmup]
    hist = read_hist(metrics)
    total = hist.get(float("inf"), 0.0)
    h_steady = {le: n - hist_warm.get(le, 0.0) for le, n in hist.items()}
    p95_steady = hist_quantile(h_steady, 0.95)
    out = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "config": vars(args),
        "steady_rate_msgs_s_mean": round(sum(x["rate"] for x in steady) / max(1, len(steady)), 1),
        "latency_p95_ms_max_window": max((x["latency_ms"]["p95"] for x in steady if x["latency_ms"]), default=None),
        "latency_p95_ms_median_window": sorted(x["latency_ms"]["p95"] for x in steady if x["latency_ms"])[
            len(steady) // 2] if steady else None,
        "latency_p95_ms_steady": None if p95_steady is None else round(p95_steady, 1),
        "latency_p50_ms_steady": None if (p := hist_quantile(h_steady, 0.5)) is None else round(p, 1),
        "messages_steady": h_steady.get(float("inf"), 0.0),
        "warmup_s": args.warmup,
        "warmup_latency_p95_ms_max_window": max((x["latency_ms"]["p95"] for x in warm if x["latency_ms"]),
                                                default=None),
        "rss_mb_max": max((x["rss_mb"] for x in samples), default=None),
        "active_assets_max": max((x["active_assets"] for x in samples), default=None),
        "messages_total": total,
        "samples": samples,
    }
    rep = ROOT / "reports"
    rep.mkdir(exist_ok=True)
    (rep / "perf_p39.json").write_text(json.dumps(out, indent=2) + "\n")
    nfr = {"rate": out["steady_rate_msgs_s_mean"] >= 0.95 * args.rate,
           "p95": (out["latency_p95_ms_steady"] or 1e9) <= 250, "rss": (out["rss_mb_max"] or 1e9) <= 1024}
    (rep / "perf_p39.md").write_text("\n".join([
        f"# P3.9 load test: {'PASS' if all(nfr.values()) else 'FAIL'}", "",
        f"{out['generated']} · {args.assets} assets ({', '.join(profiles)} train units, `--continuous`, {len(pubs)} publisher processes) over MQTT QoS 1 · "
        f"target {args.rate:g} msg/s for {args.duration:g} s · backend with {args.workers} MQTT workers, TimescaleDB on the same host.", "",
        "| NFR (docs/04 §8) | Target | Result |", "|---|---|---|",
        f"| Throughput | ≥ {args.rate:g} msg/s | {out['steady_rate_msgs_s_mean']} msg/s {'✅' if nfr['rate'] else '❌'} |",
        f"| p95 ingest → prediction persisted | ≤ 250 ms | {out['latency_p95_ms_steady']} ms over the steady period "
        f"(p50 {out['latency_p50_ms_steady']} ms; worst 10 s window {out['latency_p95_ms_max_window']} ms) "
        f"{'✅' if nfr['p95'] else '❌'} |",
        f"| Backend memory, {out['active_assets_max']} active assets | ≤ 1 GB | max RSS {out['rss_mb_max']} MB {'✅' if nfr['rss'] else '❌'} |",
        "", f"Steady period = after the first {args.warmup:g} s. The warm-up is reported, not scored: all "
        f"{args.assets} assets register and fill their windows at the same moment, worst 10 s p95 "
        f"{out['warmup_latency_p95_ms_max_window']} ms.",
        "", f"Messages processed: {int(total)} ({int(out['messages_steady'])} in the steady period). "
        "Raw samples: `perf_p39.json`.", ""]))
    print(json.dumps({k: v for k, v in out.items() if k != "samples"}, indent=2))
    return 0 if all(nfr.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
