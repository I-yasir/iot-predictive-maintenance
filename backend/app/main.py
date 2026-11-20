"""FastAPI app factory (plan P3.1). `pdm-backend` runs it with uvicorn; `pdm-backend migrate` upgrades the DB."""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from app import auth
from app import logging as applog
from app.api import alerts, assets, ingest, sim, system
from app.db.session import make_engine, migrate, ping
from app.ingest.mqtt import MqttSubscriber
from app.ingest.service import IngestService
from app.metrics import Metrics
from app.registry import ModelRegistry
from app.settings import Settings, get_settings
from app.sim.controller import ReplayController
from app.ws.hub import Hub
from pdm_contracts import load_profiles

log = applog.get("pdm.app")
HEARTBEAT_S = 15.0


class Login(BaseModel):
    password: str


def create_app(settings: Settings | None = None, *, start_background: bool = True) -> FastAPI:
    s = settings or get_settings()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        applog.configure(s.log_level, s.log_json)
        if not s.dashboard_password:
            log.warning("dashboard_auth_disabled", hint="set DASHBOARD_PASSWORD")
        if not s.ingest_api_key:
            log.warning("http_ingest_disabled", hint="set INGEST_API_KEY (>= 32 chars)")
        registry = ModelRegistry.load(s.path(s.model_root), s.profiles)  # fail fast (docs/02 §8)
        log.info("models_loaded", models={p: b.version for p, b in registry.bundles.items()})
        engine = make_engine(s.database_url)
        if s.auto_migrate:
            await run_in_threadpool(migrate, s.database_url)
        metrics = Metrics()
        hub = Hub(metrics)
        hub.bind(asyncio.get_running_loop())
        svc = IngestService(engine, registry, load_profiles(s.path(s.profiles_dir)), s.alerts(), metrics,
                            hub.publish, s.max_payload_bytes)
        for k, v in dict(settings=s, registry=registry, engine=engine, metrics=metrics, hub=hub, ingest=svc,
                         replay=ReplayController(svc, s), started=time.time()).items():
            setattr(app.state, k, v)
        sub = None
        if s.mqtt_enabled and start_background:
            sub = MqttSubscriber(s, svc)
            sub.start()
        app.state.mqtt_connected = (lambda: sub is not None and sub.connected.is_set())
        tasks = [asyncio.create_task(_watchdog(app)), asyncio.create_task(_heartbeat(app))] if start_background else []
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            app.state.replay.stop()
            if sub:
                sub.stop()
            engine.dispose()

    app = FastAPI(title="PdM-Live API", version="0.1.0", lifespan=lifespan,
                  docs_url="/docs", openapi_url="/openapi.json")
    app.state.settings = s
    app.add_middleware(CORSMiddleware, allow_origins=s.cors, allow_credentials=True,
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-API-Key"])

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict[str, Any]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["ops"])
    def readyz(request: Request) -> JSONResponse:
        st = request.app.state
        checks = {"models": bool(getattr(st, "registry", None) and st.registry.bundles),
                  "db": bool(getattr(st, "engine", None) and ping(st.engine)),
                  "mqtt": st.mqtt_connected() if hasattr(st, "mqtt_connected") else False}
        ok = checks["models"] and checks["db"]
        return JSONResponse({"ready": ok, "checks": checks}, status_code=200 if ok else 503)

    @app.get("/metrics", tags=["ops"])
    def metrics(request: Request) -> Response:
        return Response(generate_latest(request.app.state.metrics.registry), media_type=CONTENT_TYPE_LATEST)

    api = APIRouter(prefix="/api/v1")

    @api.post("/auth/login", tags=["auth"])
    def login(body: Login, request: Request, response: Response) -> dict[str, Any]:
        st: Settings = request.app.state.settings
        if not auth.check_password(st, body.password):
            raise HTTPException(401, "wrong password")
        response.set_cookie(auth.COOKIE, auth.make_token(st), max_age=st.session_max_age_s, httponly=True,
                            samesite="strict", secure=request.url.scheme == "https")
        return {"ok": True}

    @api.post("/auth/logout", tags=["auth"])
    def logout(response: Response) -> dict[str, Any]:
        response.delete_cookie(auth.COOKIE)
        return {"ok": True}

    @api.get("/auth/me", tags=["auth"])
    def me(request: Request) -> dict[str, Any]:
        st: Settings = request.app.state.settings
        return {"authenticated": auth.valid_token(st, request.cookies.get(auth.COOKIE)),
                "auth_enabled": bool(st.dashboard_password)}

    for r in (ingest.router, assets.router, alerts.router, system.router, sim.router):
        api.include_router(r)
    app.include_router(api)

    @app.websocket("/ws/v1/stream")
    async def stream(ws: WebSocket, asset: str | None = None) -> None:
        if not auth.ws_allowed(ws):
            await ws.close(code=4401)
            return
        await ws.accept()
        hub: Hub = ws.app.state.hub
        client = hub.connect(asset)
        try:
            await ws.send_json({"type": "hello", "ts": time.time(), "asset": asset})
            while True:
                msg = await client.queue.get()
                await ws.send_text(msg)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            hub.disconnect(client)

    return app


async def _watchdog(app: FastAPI) -> None:
    s: Settings = app.state.settings
    last_sim: str | None = None
    while True:
        await asyncio.sleep(s.offline_check_s)
        try:
            await run_in_threadpool(app.state.ingest.check_offline)
            st = app.state.replay.status()
            if st["state"] in ("RUNNING", "PAUSED") or st["state"] != last_sim:
                app.state.hub.publish({"type": "sim_status", "data": st})
                last_sim = st["state"]
        except Exception:
            log.exception("watchdog_failed")


async def _heartbeat(app: FastAPI) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_S)
        app.state.hub.publish({"type": "heartbeat", "ts": time.time()})


def run() -> None:
    import uvicorn

    if len(sys.argv) > 1 and sys.argv[1] == "migrate":
        migrate(get_settings().database_url)
        print("database migrated to head")
        return
    uvicorn.run("app.main:create_app", factory=True, host="0.0.0.0", port=8000, log_level="warning")
