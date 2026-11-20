"""Models, stats, devices + server-side harness checks (docs/04 §5.4, plan P3.8)."""

from __future__ import annotations

from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import Engine

from app.api.deps import engine, rows
from app.auth import require_user

router = APIRouter(tags=["system"], dependencies=[Depends(require_user)])


@router.get("/models")
def models(request: Request) -> dict[str, Any]:
    return {"items": request.app.state.registry.describe()}


@router.get("/evaluation")
def evaluation(request: Request) -> dict[str, Any]:
    """Latest Mode 1 batch evaluation (`make evaluate`, written to ml/reports/test_FD00x.{json,md}), US-11."""
    import json
    import re
    from datetime import UTC, datetime

    root = request.app.state.settings.path("ml/reports")
    items = []
    for p in sorted(root.glob("test_FD00?.json")):
        d = json.loads(p.read_text())
        md = p.with_suffix(".md")
        conf = None
        if md.exists():  # the alert confusion table is only in the markdown report
            m = re.search(r"predicted\s+Healthy\s+Warning\s+Critical\s*\ntrue\s*\n((?:\w+(?:\s+\d+){3}\s*\n){3})",
                          md.read_text())
            if m:
                conf = {ln.split()[0]: [int(x) for x in ln.split()[1:]] for ln in m.group(1).strip().splitlines()}
        items.append({"profile": p.stem.removeprefix("test_"), "generated": datetime.fromtimestamp(
            p.stat().st_mtime, UTC).isoformat(timespec="seconds"), "confusion": conf,
            "report": f"ml/reports/{md.name}", **d})
    return {"labels": ["Healthy", "Warning", "Critical"], "items": items}


@router.get("/stats")
def stats(request: Request, e: Engine = Depends(engine)) -> dict[str, Any]:
    ingest = request.app.state.ingest
    dl = rows(e, "SELECT reason, count(*) AS n FROM dead_letter WHERE received_at > now() - interval '1 day' "
                 "GROUP BY reason ORDER BY n DESC")
    drift = sum(1 for c in ingest.assets.values() if c.runtime.drift_flag)
    request.app.state.metrics.drift_assets.set(drift)
    return {"ingest": ingest.stats.snapshot(), "active_assets": len(ingest.assets), "drift_assets": drift,
            "dead_letter_24h": dl, "mqtt_connected": request.app.state.mqtt_connected(),
            "db_ok": ingest.db_ok}


@router.get("/dead-letter")
def dead_letter(e: Engine = Depends(engine), limit: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    """Latest rejected messages for the dead-letter viewer (raw payload truncated to 2 KB, decoded leniently)."""
    items = rows(e, "SELECT id, received_at, transport, topic, asset_id, reason, detail, raw FROM dead_letter "
                    "ORDER BY received_at DESC, id DESC LIMIT :n", n=limit)
    for it in items:
        raw = it.pop("raw") or b""
        it["raw"] = bytes(raw[:2048]).decode("utf-8", errors="replace")
        it["raw_truncated"] = len(raw) > 2048
    return {"items": items}


@router.get("/devices")
def devices(e: Engine = Depends(engine)) -> dict[str, Any]:
    items = rows(e, """
      SELECT a.asset_id AS device_id, a.asset_id, a.source, a.state, a.last_seen_at, a.last_cycle,
             d.fw, d.ip, d.rssi, d.online, d.last_status_at
      FROM assets a LEFT JOIN devices d ON d.device_id = a.asset_id
      WHERE a.source IN ('ESP32', 'VIRTUAL_ESP32')
      UNION ALL
      SELECT d.device_id, NULL, NULL, NULL, NULL, NULL, d.fw, d.ip, d.rssi, d.online, d.last_status_at
      FROM devices d WHERE NOT EXISTS (SELECT 1 FROM assets a WHERE a.asset_id = d.device_id)
      ORDER BY 1""")
    return {"items": items}


@router.post("/devices/{device_id}/harness-check")
def harness_check(device_id: str, e: Engine = Depends(engine), window: int = Query(200, ge=10, le=5000),
                  expected_rate_hz: float | None = None) -> dict[str, Any]:
    """Mode 2 checks on the last `window` stored messages of a device (same check names as pdm-harness)."""
    t = rows(e, """SELECT cycle, seq, received_at, device_ts, flags FROM telemetry WHERE asset_id = :a
                   ORDER BY received_at DESC LIMIT :n""", a=device_id, n=window)
    if not t:
        raise HTTPException(404, f"no telemetry for {device_id}")
    t = t[::-1]
    rej = rows(e, """SELECT reason, count(*) AS n FROM dead_letter WHERE asset_id = :a AND received_at >= :since
                     GROUP BY reason""", a=device_id, since=t[0]["received_at"])
    seqs = sorted({r["seq"] for r in t if r["seq"] is not None})
    missing = sorted(set(range(seqs[0], seqs[-1] + 1)) - set(seqs)) if seqs else []
    span = (t[-1]["received_at"] - t[0]["received_at"]).total_seconds()
    rate = round((len(t) - 1) / span, 3) if span > 0 else 0.0
    lat = [(r["received_at"] - r["device_ts"]).total_seconds() * 1000 for r in t if r["device_ts"] is not None]
    gaps = [(b["received_at"] - a["received_at"]).total_seconds() for a, b in zip(t, t[1:], strict=False)]
    flags = [f for r in t for f in r["flags"]]
    checks = [
        {"check": "schema", "ok": not rej, "detail": f"{len(t)} accepted, rejected {dict((r['reason'], r['n']) for r in rej)}"},
        {"check": "sequence", "ok": not missing, "detail": f"missing seq {missing[:20]}" if missing else "no gaps"},
        {"check": "latency", "ok": bool(lat) and float(np.percentile(lat, 95)) < 2000 if lat else False,
         "detail": {"p50": round(float(np.percentile(lat, 50)), 1), "p95": round(float(np.percentile(lat, 95)), 1)}
         if lat else "device sends no ts (NTP failed?)"},
        {"check": "reconnects", "ok": True,
         "detail": f"{sum(1 for g in gaps if g > 5)} silences > 5 s, longest {round(max(gaps, default=0), 1)} s"},
        {"check": "order", "ok": "out_of_order" not in flags,
         "detail": f"{flags.count('out_of_order')} out-of-order, {flags.count('gap')} cycle gaps"},
    ]
    if expected_rate_hz:
        checks.append({"check": "rate", "ok": abs(rate - expected_rate_hz) <= 0.2 * expected_rate_hz,
                       "detail": f"observed {rate} msg/s vs expected {expected_rate_hz}"})
    return {"device_id": device_id, "window": len(t), "rate_msgs_s": rate, "passed": all(c["ok"] for c in checks),
            "checks": checks}
