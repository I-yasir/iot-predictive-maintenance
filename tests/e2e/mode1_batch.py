"""P5.1 Mode 1 batch: stream every official test engine through the backend's HTTP batch ingest and check
that the backend's final prediction per engine reproduces the offline P1.8 evaluation.

This is a verification of the serving path, not another model evaluation: no model or config is changed
based on its output (the test set must not be used for tuning, see docs/06 P1.8 notes).

    python tests/e2e/mode1_batch.py [--profiles FD001 ...] [--url http://localhost:8000]

Needs INGEST_API_KEY and DASHBOARD_PASSWORD in the environment (`set -a; . ./.env; set +a`).
Writes tests/e2e/reports/p51_mode1_batch.{json,md}. Exit code 0 only if every profile matches.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from pdm_iot.simulator.replay import ReplayConfig, build_messages
from pdm_ml.config import PROFILES, artifacts_dir, reports_dir
from pdm_ml.evaluate.metrics import summarize
from pdm_ml.io.loader import load_profile
from pdm_ml.models.bundle import load_bundle

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tests" / "e2e" / "reports"
BATCH = 500
# Streaming features (rolling sums updated per cycle) and batch features (vectorised over the whole history)
# agree to ~1e-15 but are not bit-identical. When a feature sits exactly on a LightGBM split threshold that
# last-bit difference sends the row down the other branch, moving that engine's prediction by up to ~1 cycle.
# So: most engines must match exactly, none may be off by more than MAX_DIFF, and the fleet metrics must agree.
EXACT_TOL = 1e-3  # cycles
MIN_EXACT_SHARE = 0.9
MAX_DIFF = 1.0  # cycles
METRICS = ("rmse", "nasa_score", "mae", "bias", "critical_recall", "false_critical_rate", "coverage_p10_p90")


def offline(profile: str) -> dict[int, tuple[float, float, float]]:
    b = load_bundle(artifacts_dir(), profile)
    F = b.predict_history(load_profile(profile).test)
    last = F.loc[F.groupby("unit").cycle.idxmax()]
    return {int(r.unit): (float(r.pred), float(r.lo), float(r.hi)) for r in last.itertuples()}


def stream(client: httpx.Client, profile: str, prefix: str, key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    buf: list[dict[str, Any]] = []

    def flush() -> None:
        while buf:
            send(buf[:BATCH])
            del buf[:BATCH]

    def send(pending: list[dict[str, Any]]) -> None:
        for _attempt in range(20):
            r = client.post("/api/v1/ingest/batch", json=pending, headers={"X-API-Key": key}, timeout=120)
            r.raise_for_status()
            results = r.json()["results"]
            retry = [m for m, res in zip(pending, results, strict=True) if res["status"] in ("rate_limited", "unavailable")]
            for res in results:
                if res["status"] not in ("rate_limited", "unavailable"):
                    counts[res["status"]] = counts.get(res["status"], 0) + 1
            if not retry:
                return
            pending = retry
            time.sleep(0.5)
        raise RuntimeError(f"{len(pending)} messages still rate limited after retries")

    cfg = ReplayConfig(profile, "test", speed_cps=0, asset_prefix=prefix)
    for tick in build_messages(cfg, run_tag=prefix.lower()):
        buf.extend(tick)
        if len(buf) >= BATCH:
            flush()
    if buf:
        flush()
    return counts


def served(client: httpx.Client, prefix: str, profile: str) -> dict[int, dict[str, Any]]:
    items = client.get("/api/v1/assets", timeout=60).json()["items"]
    out = {}
    tag = f"{prefix}{profile}-T"
    for a in items:
        if a["asset_id"].startswith(tag):
            out[int(a["asset_id"][len(tag):])] = a
    return out


def run(url: str, profiles: list[str]) -> dict[str, Any]:
    key, pw = os.environ["INGEST_API_KEY"], os.environ["DASHBOARD_PASSWORD"]
    prefix = f"B{int(time.time()) % 100000:05d}"  # fresh assets for every run
    report: dict[str, Any] = {"url": url, "asset_prefix": prefix, "profiles": {}}
    with httpx.Client(base_url=url) as client:
        client.post("/api/v1/auth/login", json={"password": pw}).raise_for_status()
        for p in profiles:
            t0 = time.time()
            exp = offline(p)
            counts = stream(client, p, prefix, key)
            elapsed = time.time() - t0
            got = served(client, prefix, p)
            ref = json.loads((reports_dir() / f"test_{p}.json").read_text())
            truth = load_profile(p).true_rul
            units = sorted(exp)
            missing = [u for u in units if u not in got or got[u]["rul_pred"] is None]
            diffs = [abs(got[u]["rul_pred"] - exp[u][0]) for u in units if u not in missing]
            cycle_ok = all(got[u]["pred_cycle"] == got[u]["last_cycle"] for u in units if u not in missing)
            m_srv = {}
            if not missing:
                y = truth.loc[units].to_numpy(float)
                m_srv = summarize(y, [got[u]["rul_pred"] for u in units], [got[u]["rul_p10"] for u in units],
                                  [got[u]["rul_p90"] for u in units])
            metric_rows = {k: {"offline_p18": ref[k], "served": m_srv.get(k)} for k in METRICS}
            n = len(units)

            def close(k: str, srv: float, off: float) -> bool:
                if k in ("rmse", "mae", "bias"):
                    return abs(srv - off) <= 0.05
                if k == "nasa_score":
                    return abs(srv - off) <= 0.02 * off
                return abs(srv - off) <= 1.0 / n + 1e-9  # shares: at most one engine changes bucket

            metrics_ok = bool(m_srv) and all(close(k, v["served"], v["offline_p18"]) for k, v in metric_rows.items()
                                             if not (isinstance(v["offline_p18"], float) and np.isnan(v["offline_p18"])))
            exact_share = float(np.mean([x <= EXACT_TOL for x in diffs])) if diffs else 0.0
            ok = (not missing and cycle_ok and exact_share >= MIN_EXACT_SHARE and max(diffs, default=0) <= MAX_DIFF
                  and metrics_ok)
            report["profiles"][p] = {
                "ok": ok, "units": len(units), "messages": sum(counts.values()), "ingest_counts": counts,
                "seconds": round(elapsed, 1), "msgs_per_s": round(sum(counts.values()) / elapsed, 1),
                "missing_predictions": missing, "pred_at_last_cycle": cycle_ok,
                "max_abs_pred_diff": max(diffs, default=None), "exact_share": exact_share,
                "engines_off": {u: round(abs(got[u]["rul_pred"] - exp[u][0]), 4) for u in units
                                if u not in missing and abs(got[u]["rul_pred"] - exp[u][0]) > EXACT_TOL}, "model_version": ref["model_version"],
                "metrics": metric_rows,
            }
            print(f"{p}: ok={ok} max|diff|={max(diffs, default=float('nan')):.5f} "
                  f"rmse served {m_srv.get('rmse', float('nan')):.3f} vs {ref['rmse']:.3f} ({elapsed:.0f}s)", flush=True)
    report["ok"] = all(v["ok"] for v in report["profiles"].values())
    return report


def write(report: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "p51_mode1_batch.json").write_text(json.dumps(report, indent=2, default=float))
    lines = ["# P5.1 Mode 1 batch through the backend ingest path", "",
             f"Result: **{'PASS' if report['ok'] else 'FAIL'}**. Every official test engine was streamed through "
             f"`POST /api/v1/ingest/batch` (assets `{report['asset_prefix']}FD00x-Tnnn`); the backend's last prediction "
             f"per engine is compared with the offline P1.8 evaluation (`ml/reports/test_FD00x.json`). "
             f"Pass rule: ≥ {MIN_EXACT_SHARE:.0%} of engines within {EXACT_TOL} cycles of the offline prediction, none more "
             f"than {MAX_DIFF} cycle off, RMSE/MAE/bias within 0.05, NASA score within 2 %, shares within one engine. "
             "The few engines that differ do so because streaming and batch features differ in the last bit (~1e-15) "
             "and that flips a LightGBM split sitting exactly on the threshold.", "",
             "| Profile | Engines | Messages | msg/s | Exact share | Max abs diff (cycles) | RMSE served / offline | NASA score served / offline | Critical recall | Coverage P10–P90 | OK |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for p, r in report["profiles"].items():
        m = r["metrics"]
        def f(k: str, d: int = 2) -> str:
            s = m[k]["served"]
            return f"{s:.{d}f} / {m[k]['offline_p18']:.{d}f}" if s is not None else "n/a"
        lines.append(f"| {p} | {r['units']} | {r['messages']} | {r['msgs_per_s']} | {r['exact_share']:.2f} | {r['max_abs_pred_diff']:.3f} | "
                     f"{f('rmse')} | {f('nasa_score', 1)} | {f('critical_recall')} | {f('coverage_p10_p90')} | {'yes' if r['ok'] else 'NO'} |")
    lines += ["", "Ingest outcome counts per profile: " + "; ".join(f"{p} {r['ingest_counts']}" for p, r in report["profiles"].items()), ""]
    (OUT / "p51_mode1_batch.md").write_text("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=os.environ.get("PDM_BACKEND", "http://localhost:8000"))
    ap.add_argument("--profiles", nargs="+", default=list(PROFILES))
    a = ap.parse_args()
    rep = run(a.url, a.profiles)
    write(rep)
    sys.exit(0 if rep["ok"] else 1)


if __name__ == "__main__":
    main()
