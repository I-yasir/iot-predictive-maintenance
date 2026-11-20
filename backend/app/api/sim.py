"""Replay controls (docs/02 §4, plan P3.8)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import require_user

router = APIRouter(prefix="/sim/replay", tags=["simulation"], dependencies=[Depends(require_user)])


class ReplayStart(BaseModel):
    profile: Literal["FD001", "FD002", "FD003", "FD004"]
    split: Literal["test", "train"] = "test"
    units: list[int] | None = None
    random_n: int | None = Field(default=None, ge=1, le=260)
    speed_cps: float = Field(default=5.0, ge=0, le=1000)
    loop: bool = False
    transport: Literal["internal", "mqtt", "http"] = "internal"
    site_id: str = "lab"
    asset_prefix: str = Field(default="", max_length=16, pattern=r"^[A-Za-z0-9_-]*$")


def _ctl(request: Request) -> Any:
    return request.app.state.replay


def _push(request: Request, status: dict[str, Any]) -> dict[str, Any]:
    request.app.state.hub.publish({"type": "sim_status", "data": status})
    return status


@router.post("/start")
def start(body: ReplayStart, request: Request) -> dict[str, Any]:
    try:
        return _push(request, _ctl(request).start(body.model_dump()))
    except (RuntimeError, ValueError) as e:
        raise HTTPException(409 if isinstance(e, RuntimeError) else 422, str(e)) from e


@router.post("/pause")
def pause(request: Request) -> dict[str, Any]:
    return _push(request, _ctl(request).pause())


@router.post("/resume")
def resume(request: Request) -> dict[str, Any]:
    return _push(request, _ctl(request).resume())


@router.post("/stop")
def stop(request: Request) -> dict[str, Any]:
    return _push(request, _ctl(request).stop())


@router.get("/status")
def status(request: Request) -> dict[str, Any]:
    s: dict[str, Any] = _ctl(request).status()
    return s
