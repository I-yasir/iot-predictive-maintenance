"""Assets, telemetry, predictions, diagnostics, report (docs/04 §5.4)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import Engine, text

from app.api.deps import engine, rows
from app.auth import require_user

router = APIRouter(tags=["assets"], dependencies=[Depends(require_user)])

ASSETS_SQL = """
SELECT a.asset_id, a.site_id, a.profile, a.source, a.display_name, a.life_id, a.state, a.last_cycle,
       a.last_seen_at, a.expected_interval_s, a.true_rul_at_end,
       p.cycle AS pred_cycle, p.status AS pred_status, p.rul_pred, p.rul_p10, p.rul_p90, p.health_index,
       p.flags, p.model_version, p.true_rul
FROM assets a
LEFT JOIN LATERAL (
  SELECT * FROM predictions q WHERE q.asset_id = a.asset_id AND q.life_id = a.life_id
  ORDER BY q.cycle DESC, q.created_at DESC LIMIT 1) p ON true
{where}
ORDER BY p.rul_pred ASC NULLS LAST, a.asset_id
"""

SPARK_SQL = """
SELECT asset_id, array_agg(rul_pred ORDER BY cycle) AS spark FROM (
  SELECT p.asset_id, p.cycle, p.rul_pred,
         row_number() OVER (PARTITION BY p.asset_id ORDER BY p.cycle DESC) AS rn
  FROM predictions p JOIN assets a ON a.asset_id = p.asset_id AND a.life_id = p.life_id
  WHERE p.status = 'OK') s
WHERE rn <= 50 GROUP BY asset_id
"""


def _asset(e: Engine, asset_id: str) -> dict[str, Any]:
    r = rows(e, ASSETS_SQL.format(where="WHERE a.asset_id = :a"), a=asset_id)
    if not r:
        raise HTTPException(404, f"asset {asset_id} not found")
    return r[0]


@router.get("/assets")
def list_assets(e: Engine = Depends(engine), state: str | None = None, profile: str | None = None,
                source: str | None = None) -> dict[str, Any]:
    conds, params = [], {}
    for col, val in (("state", state), ("profile", profile), ("source", source)):
        if val:
            conds.append(f"a.{col} = ANY(:{col})")
            params[col] = val.split(",")
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    items = rows(e, ASSETS_SQL.format(where=where), **params)
    spark = {r["asset_id"]: r["spark"] for r in rows(e, SPARK_SQL)}
    for it in items:
        it["sparkline"] = spark.get(it["asset_id"], [])
    counts: dict[str, int] = {}
    for it in items:
        counts[it["state"]] = counts.get(it["state"], 0) + 1
    return {"count": len(items), "by_state": counts, "items": items}


@router.get("/assets/{asset_id}")
def get_asset(asset_id: str, e: Engine = Depends(engine)) -> dict[str, Any]:
    a = _asset(e, asset_id)
    a["lives"] = [r["life_id"] for r in rows(
        e, "SELECT DISTINCT life_id FROM telemetry WHERE asset_id = :a ORDER BY life_id", a=asset_id)]
    last = rows(e, "SELECT reason, detail, received_at FROM dead_letter WHERE asset_id = :a "
                   "ORDER BY received_at DESC LIMIT 1", a=asset_id)
    a["last_rejection"] = last[0] if last else None
    return a


@router.get("/assets/{asset_id}/telemetry")
def telemetry(asset_id: str, e: Engine = Depends(engine), from_cycle: int | None = None,
              to_cycle: int | None = None, sensors: str | None = None, life_id: int | None = None,
              limit: int = Query(500, le=5000)) -> dict[str, Any]:
    a = _asset(e, asset_id)
    life = life_id or a["life_id"]
    r = rows(e, """SELECT cycle, received_at, device_ts, seq, settings, sensors, regime, flags FROM telemetry
                   WHERE asset_id = :a AND life_id = :l AND cycle >= :f AND cycle <= :t
                   ORDER BY cycle DESC, received_at DESC LIMIT :n""",
             a=asset_id, l=life, f=from_cycle or 0, t=to_cycle or 10**9, n=limit)
    if sensors:
        keep = set(sensors.split(","))
        for x in r:
            x["sensors"] = {k: v for k, v in x["sensors"].items() if k in keep}
    return {"asset_id": asset_id, "life_id": life, "items": r[::-1]}


@router.get("/assets/{asset_id}/predictions")
def predictions(asset_id: str, e: Engine = Depends(engine), limit: int = Query(500, le=5000),
                life_id: int | None = None) -> dict[str, Any]:
    a = _asset(e, asset_id)
    life = life_id or a["life_id"]
    r = rows(e, """SELECT prediction_id, cycle, created_at, model_version, status, rul_pred, rul_p10, rul_p90,
                          health_index, state, flags, latency_ms, true_rul FROM predictions
                   WHERE asset_id = :a AND life_id = :l ORDER BY cycle DESC, created_at DESC LIMIT :n""",
             a=asset_id, l=life, n=limit)
    return {"asset_id": asset_id, "life_id": life, "items": r[::-1]}


@router.get("/assets/{asset_id}/diagnostics")
def diagnostics(asset_id: str, request: Request, e: Engine = Depends(engine)) -> dict[str, Any]:
    a = _asset(e, asset_id)
    p = rows(e, """SELECT cycle, rul_pred, rul_p10, rul_p90, health_index, flags, contributors, subsystem_scores,
                          model_version FROM predictions WHERE asset_id = :a AND life_id = :l AND status = 'OK'
                   ORDER BY cycle DESC LIMIT 1""", a=asset_id, l=a["life_id"])
    t = rows(e, """SELECT cycle, sensors, settings, regime FROM telemetry WHERE asset_id = :a AND life_id = :l
                   ORDER BY cycle DESC LIMIT 1""", a=asset_id, l=a["life_id"])
    bundle = request.app.state.registry.get(a["profile"])
    units = {}
    subsystem_of = {}
    if bundle is not None:
        subsystem_of = {s: bundle.subsystem_of.get(s) for s in bundle.pipeline.sensors_used}
        from pdm_ml.io.loader import sensor_catalog
        units = {c.symbol: c.unit for c in sensor_catalog()}
    return {"asset_id": asset_id, "note": "Indicative: C-MAPSS has no fault-mode labels (PRD non-goal 3).",
            "latest": p[0] if p else None, "latest_telemetry": t[0] if t else None,
            "sensor_subsystem": subsystem_of, "units": units}


@router.get("/assets/{asset_id}/report")
def report(asset_id: str, request: Request, e: Engine = Depends(engine)) -> dict[str, Any]:
    a = get_asset(asset_id, e)
    reg = request.app.state.registry
    model = next((m for m in reg.describe() if m["profile"] == a["profile"]), None)
    return {"asset": a, "diagnostics": diagnostics(asset_id, request, e),
            "predictions": predictions(asset_id, e, limit=1000)["items"],
            "alerts": rows(e, "SELECT * FROM alerts WHERE asset_id = :a ORDER BY created_at DESC LIMIT 100",
                           a=asset_id),
            "model": None if model is None else {k: model[k] for k in
                                                 ("model_version", "point_estimate", "cv", "test", "cap")}}


class GroundTruth(BaseModel):
    true_rul_at_end: int


@router.post("/assets/{asset_id}/ground-truth")
def ground_truth(asset_id: str, body: GroundTruth, e: Engine = Depends(engine)) -> dict[str, Any]:
    _asset(e, asset_id)
    with e.begin() as c:
        c.execute(text("UPDATE assets SET true_rul_at_end = :v WHERE asset_id = :a"),
                  {"v": body.true_rul_at_end, "a": asset_id})
    return {"asset_id": asset_id, "true_rul_at_end": body.true_rul_at_end}
