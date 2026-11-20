"""P5.5 edge and failure cases against the full local stack (broker + DB in docker, backend from `make backend`).

    set -a; . ./.env; set +a
    python tests/e2e/edge_cases.py            # all cases
    python tests/e2e/edge_cases.py --only db_down broker_down

Cases that stop services (backend_restart, db_down, broker_down) restart them before returning. The backend
restart case sends SIGTERM to the running `uvicorn app.main` process and starts it again with `make backend`
(log: tests/e2e/reports/backend_restart.log), so run this only against a dev stack.

Writes tests/e2e/reports/p55_edge_cases.{json,md}. Cases already covered by unit/integration tests are listed
in the report with the test that covers them.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from pdm_iot.simulator.replay import ReplayConfig, ReplaySimulator, ReplayState
from pdm_iot.simulator.virtual_esp32 import VirtualDevice
from pdm_iot.simulator.virtual_esp32 import run as run_device
from pdm_iot.transports import FallbackTransport, HttpTransport, MqttTransport

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tests" / "e2e" / "reports"
URL = os.environ.get("PDM_BACKEND", "http://localhost:8000")
DB, BROKER = "pdm-live-db-1", "pdm-live-mosquitto-1"
TAG = f"E{int(time.time()) % 100000:05d}"  # fresh asset ids per run

COVERED_ELSEWHERE = {
    "duplicate_and_out_of_order": "backend/tests/test_ingest.py::test_duplicate_out_of_order_gap; Mode 2 harness "
                                  "fault types duplicate/out_of_order (P5.3 report)",
    "unit_restart_new_life": "backend/tests/test_ingest.py::test_new_life_on_cycle_restart",
    "short_unit_fd004": "P5.1: every FD004 test engine, including the shortest (19 cycles), gets a served "
                        "prediction equal to the offline one (tests/e2e/reports/p51_mode1_batch.md)",
    "ws_disconnect_ui": "frontend/src/api/ws.test.ts (backoff, resync) and frontend/e2e/edge.spec.ts "
                        "(socket dropped -> Reconnecting -> Live)",
    "restart_rehydrates_stream": "backend/tests/test_ingest.py::test_restart_rehydrates_stream",
}


def env(k: str) -> str:
    v = os.environ.get(k)
    if not v:
        sys.exit(f"{k} not set: run `set -a; . ./.env; set +a` first")
    return v


def client() -> httpx.Client:
    c = httpx.Client(base_url=URL, timeout=15)
    c.post("/api/v1/auth/login", json={"password": env("DASHBOARD_PASSWORD")}).raise_for_status()
    return c


def wait(pred: Callable[[], bool], timeout: float, step: float = 0.5) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            if pred():
                return True
        except (httpx.HTTPError, KeyError, ValueError):
            pass
        time.sleep(step)
    return False


def docker(*args: str) -> None:
    subprocess.run(["docker", *args], check=True, capture_output=True)


def healthy(name: str) -> bool:
    out = subprocess.run(["docker", "inspect", "-f", "{{.State.Health.Status}}", name], capture_output=True, text=True)
    return out.stdout.strip() == "healthy"


def ready() -> bool:
    return httpx.get(f"{URL}/readyz", timeout=3).json().get("ready") is True


def asset(c: httpx.Client, aid: str) -> dict[str, Any]:
    r = c.get(f"/api/v1/assets/{aid}")
    r.raise_for_status()
    return r.json()


def mqtt_t(**kw: Any) -> MqttTransport:
    return MqttTransport(os.environ.get("MQTT_HOST", "localhost"), int(os.environ.get("MQTT_PORT", "1883")),
                         "pdm-replay", env("MQTT_REPLAY_PASSWORD"), os.environ.get("MQTT_TOPIC_PREFIX", "pdm/v1"),
                         **kw)


def http_t() -> HttpTransport:
    return HttpTransport(f"{URL}/api/v1/ingest", env("INGEST_API_KEY"), backoff=(0.5, 1.0))


EXAMPLE = json.loads((ROOT / "iot" / "contracts" / "example_payload.json").read_text())


def payload(aid: str, cycle: int, seq: int) -> dict[str, Any]:
    p = json.loads(json.dumps(EXAMPLE))
    p.update(msg_id=f"{aid}-{seq:06d}", asset_id=aid, source="LIVE", seq=seq, cycle=cycle,
             ts=time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()), meta={})
    return p


# ---------------------------------------------------------------------------------------------------- cases
def backend_restart(c: httpx.Client) -> dict[str, Any]:
    """Graceful backend restart mid-stream over MQTT: every QoS 1 message published while it is down is queued
    by the broker for the backend's persistent session and ingested after restart."""
    pids = subprocess.run(["pgrep", "-f", "uvicorn app.main"], capture_output=True, text=True).stdout.split()
    if not pids:
        return {"ok": False, "detail": "no running backend (`make backend`) found"}
    aid_unit = 34
    cfg = ReplayConfig("FD001", "test", units=[aid_unit], speed_cps=10, asset_prefix=TAG + "R")
    aid = f"{TAG}RFD001-T034"
    sim = ReplaySimulator(cfg, mqtt_t())
    sim.start()
    assert wait(lambda: sim.stats.sent >= 30, 30)
    t_down = time.time()
    for p in pids:
        os.kill(int(p), signal.SIGTERM)
    assert wait(lambda: not subprocess.run(["pgrep", "-f", "uvicorn app.main"], capture_output=True).stdout, 30)
    sent_at_down = sim.stats.sent
    log = open(OUT / "backend_restart.log", "w")  # noqa: SIM115 - handed to the child process
    subprocess.Popen(["make", "backend"], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    back = wait(ready, 180, 1)
    t_up = time.time()
    sim_done = wait(lambda: sim.state == ReplayState.COMPLETED, 120)
    sim.transport.close()  # type: ignore[attr-defined]
    total = sim.stats.sent
    c2 = client()
    complete = wait(lambda: asset(c2, aid)["last_cycle"] == 203, 60)
    tel = c2.get(f"/api/v1/assets/{aid}/telemetry", params={"from_cycle": 1, "to_cycle": 203}).json()
    cycles = sorted({row["cycle"] for row in tel["items"]})
    ok = back and sim_done and complete and sim.stats.failed == 0 and cycles == list(range(1, 204))
    return {"ok": ok, "asset": aid, "published": total, "publish_failures": sim.stats.failed,
            "published_before_shutdown": sent_at_down, "backend_down_s": round(t_up - t_down, 1),
            "stored_cycles": len(cycles), "missing_cycles": sorted(set(range(1, 204)) - set(cycles))[:20]}


def db_down(c: httpx.Client) -> dict[str, Any]:
    """DB stopped: ingest answers 503 (device keeps its data and retries), /readyz is false; after the DB is back
    ingest works again without a backend restart."""
    aid, key = f"{TAG}D-DB", env("INGEST_API_KEY")
    h = {"X-API-Key": key}
    first = httpx.post(f"{URL}/api/v1/ingest", json=payload(aid, 1, 1), headers=h, timeout=10)
    docker("stop", DB)
    try:
        t0 = time.time()
        r = httpx.post(f"{URL}/api/v1/ingest", json=payload(aid, 2, 2), headers=h, timeout=30)
        down_status, down_s = r.status_code, round(time.time() - t0, 2)
        ready_down = httpx.get(f"{URL}/readyz", timeout=10).json()
    finally:
        docker("start", DB)
    assert wait(lambda: healthy(DB), 90, 1)
    t1 = time.time()
    recovered = wait(lambda: httpx.post(f"{URL}/api/v1/ingest", json=payload(aid, 2, 2), headers=h,
                                        timeout=10).status_code == 200, 60, 1)
    recover_s = round(time.time() - t1, 1)
    rdy = wait(ready, 30)
    state = asset(c, aid)
    ok = first.status_code == 200 and down_status == 503 and not ready_down.get("ready") and recovered and rdy \
        and state["last_cycle"] == 2
    return {"ok": ok, "status_while_down": down_status, "answer_time_s": down_s, "readyz_while_down": ready_down,
            "recovered_after_s": recover_s, "last_cycle_after": state["last_cycle"]}


def db_down_mqtt(c: httpx.Client) -> dict[str, Any]:
    """DB stopped while a device streams over MQTT: the backend holds what it has received and retries, so
    once the DB is back every cycle is stored exactly once and the stream carries on."""
    cfg = ReplayConfig("FD001", "test", units=[31], speed_cps=5, asset_prefix=TAG + "M")
    aid = f"{TAG}MFD001-T031"
    sim = ReplaySimulator(cfg, mqtt_t())
    sim.start()
    assert wait(lambda: sim.stats.sent >= 15, 30)
    docker("stop", DB)
    sent_before = sim.stats.sent
    time.sleep(8)
    docker("start", DB)
    assert wait(lambda: healthy(DB), 90, 1)
    done = wait(lambda: sim.state == ReplayState.COMPLETED, 120)
    sim.transport.close()  # type: ignore[attr-defined]
    total = sim.stats.sent
    c2 = client()
    complete = wait(lambda: asset(c2, aid)["last_cycle"] == total, 90, 1)
    tel = c2.get(f"/api/v1/assets/{aid}/telemetry", params={"limit": 5000}).json()["items"]
    cycles = [row["cycle"] for row in tel]
    ok = done and complete and sorted(cycles) == list(range(1, total + 1))
    return {"ok": ok, "published": total, "published_before_db_stop": sent_before, "db_down_s": 8,
            "stored_rows": len(cycles), "distinct_cycles": len(set(cycles)),
            "missing": sorted(set(range(1, total + 1)) - set(cycles))[:20]}


def broker_down(c: httpx.Client) -> dict[str, Any]:
    """Broker stopped mid-run: the virtual ESP32 (firmware behaviour) falls back to HTTP and nothing is lost."""
    aid = f"{TAG}V-BRK"
    dev = VirtualDevice(aid, "FD001", seed=7)
    tr = FallbackTransport(mqtt_t(require_connection=False, connect_timeout_s=3, publish_timeout_s=2), http_t(),
                           fails_before_http=3, retry_mqtt_s=10)
    n = 60
    out: dict[str, Any] = {}
    th = threading.Thread(target=lambda: out.update(run_device(dev, tr, n, 4.0)))
    th.start()
    time.sleep(4)
    docker("stop", BROKER)
    time.sleep(10)
    docker("start", BROKER)
    th.join(120)
    tr.close()
    assert wait(lambda: healthy(BROKER), 60, 1)
    st = asset(c, aid)
    modes = [m for _, m in tr.switches]
    ok = out.get("send_failures") == 0 and st["last_cycle"] == n and "http" in modes
    return {"ok": ok, "messages": n, "send_failures": out.get("send_failures"), "transport_switches": modes,
            "last_cycle": st["last_cycle"], "backend_mqtt_reconnected": wait(ready, 60)}


def ood_values(c: httpx.Client) -> dict[str, Any]:
    """Physically possible but out-of-training-range sensor values (between the profile's soft and hard
    limits) are accepted and flagged OOD, never dropped; >= 3 in a row put the asset in DEGRADED_DATA."""
    import yaml

    rng = yaml.safe_load((ROOT / "config" / "profiles" / "FD001.yaml").read_text())["ranges"]["T30"]
    value = round(rng["soft_max"] + 0.5 * (rng["hard_max"] - rng["soft_max"]), 2)
    aid, h = f"{TAG}O-OOD", {"X-API-Key": env("INGEST_API_KEY")}
    res = []
    for cyc in range(1, 13):
        p = payload(aid, cyc, cyc)
        if cyc >= 7:
            p["sensors"]["T30"] = value
        res.append(httpx.post(f"{URL}/api/v1/ingest", json=p, headers=h, timeout=10).json())
    preds = c.get(f"/api/v1/assets/{aid}/predictions", params={"limit": 20}).json()["items"]
    flags = sorted({f for p in preds for f in (p.get("flags") or [])})
    state = asset(c, aid)["state"]
    ok = all(r["status"] == "accepted" for r in res) and "OOD" in flags and state == "DEGRADED_DATA"
    return {"ok": ok, "T30_sent": value, "soft_max": rng["soft_max"], "hard_max": rng["hard_max"],
            "statuses": sorted({r["status"] for r in res}), "flags_seen": flags, "state": state}


def offline_detection(c: httpx.Client) -> dict[str, Any]:
    """An asset that stops sending is marked OFFLINE after offline_factor x its expected interval."""
    aid, h = f"{TAG}F-OFF", {"X-API-Key": env("INGEST_API_KEY")}
    for cyc in range(1, 11):
        httpx.post(f"{URL}/api/v1/ingest", json=payload(aid, cyc, cyc), headers=h, timeout=10)
        time.sleep(0.5)
    t0 = time.time()
    went = wait(lambda: asset(c, aid)["state"] == "OFFLINE", 30, 0.25)
    after = round(time.time() - t0, 1)
    alerts = c.get("/api/v1/alerts", params={"asset": aid}).json()["items"]
    ok = went and any(a["to_state"] == "OFFLINE" for a in alerts)
    return {"ok": ok, "expected_interval_s": asset(c, aid)["expected_interval_s"], "offline_after_s": after,
            "offline_alert": any(a["to_state"] == "OFFLINE" for a in alerts)}


CASES: dict[str, Callable[[httpx.Client], dict[str, Any]]] = {
    "ood_values": ood_values, "offline_detection": offline_detection, "db_down": db_down,
    "db_down_mqtt": db_down_mqtt,
    "broker_down": broker_down, "backend_restart": backend_restart,
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", nargs="*", choices=list(CASES))
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}
    for name in a.only or list(CASES):
        t0 = time.time()
        try:
            results[name] = CASES[name](client())
        except Exception as e:  # a crashed case is a failed case, the rest still run
            results[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        results[name]["seconds"] = round(time.time() - t0, 1)
        print(f"{name}: {'PASS' if results[name]['ok'] else 'FAIL'} {json.dumps(results[name], default=str)[:300]}",
              flush=True)
    rep = {"tag": TAG, "ok": all(r["ok"] for r in results.values()), "cases": results,
           "covered_elsewhere": COVERED_ELSEWHERE}
    (OUT / "p55_edge_cases.json").write_text(json.dumps(rep, indent=2, default=str))
    lines = ["# P5.5 edge and failure cases (full stack)", "", f"Result: **{'PASS' if rep['ok'] else 'FAIL'}** "
             f"(run tag `{TAG}`, `python tests/e2e/edge_cases.py`).", "", "| Case | Result | Key numbers |", "|---|---|---|"]
    for k, r in results.items():
        nums = ", ".join(f"{x}={v}" for x, v in r.items() if x not in ("ok",) and not isinstance(v, dict | list))
        lines.append(f"| {k} | {'pass' if r['ok'] else 'FAIL'} | {nums} |")
    lines += ["", "Covered by other automated tests:", ""] + [f"- **{k}**: {v}" for k, v in COVERED_ELSEWHERE.items()]
    (OUT / "p55_edge_cases.md").write_text("\n".join(lines) + "\n")
    sys.exit(0 if rep["ok"] else 1)


if __name__ == "__main__":
    main()
