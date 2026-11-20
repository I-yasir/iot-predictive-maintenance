"""Alerts list + acknowledge (docs/04 §5.4)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import Engine, text

from app.api.deps import engine, rows
from app.auth import require_user

router = APIRouter(tags=["alerts"], dependencies=[Depends(require_user)])


@router.get("/alerts")
def list_alerts(e: Engine = Depends(engine), state: str | None = None, asset: str | None = None,
                ack: bool | None = None, limit: int = Query(100, le=1000)) -> dict[str, Any]:
    conds: list[str] = []
    params: dict[str, Any] = {"n": limit}
    if state:
        conds.append("to_state = ANY(:states)")
        params["states"] = state.split(",")
    if asset:
        conds.append("asset_id = :asset")
        params["asset"] = asset
    if ack is not None:
        conds.append("acknowledged_at IS " + ("NOT NULL" if ack else "NULL"))
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    items = rows(e, f"SELECT * FROM alerts {where} ORDER BY created_at DESC, alert_id DESC LIMIT :n", **params)
    return {"count": len(items), "items": items}


class Ack(BaseModel):
    by: str = "dashboard"


@router.post("/alerts/{alert_id}/ack")
def ack_alert(alert_id: int, request: Request, body: Ack | None = None, e: Engine = Depends(engine)) -> dict[str, Any]:
    with e.begin() as c:
        r = c.execute(text("""UPDATE alerts SET acknowledged_at = COALESCE(acknowledged_at, now()),
                                     acknowledged_by = COALESCE(acknowledged_by, :by)
                              WHERE alert_id = :id RETURNING *"""),
                      {"id": alert_id, "by": (body or Ack()).by[:64]}).mappings().first()
    if r is None:
        raise HTTPException(404, "alert not found")
    out = dict(r)
    request.app.state.hub.publish({"type": "alert_ack", "data": {k: str(v) if v is not None else None
                                                                 for k, v in out.items()}})
    return out
