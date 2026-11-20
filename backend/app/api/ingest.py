"""HTTP ingest (docs/04 §5.1, §5.3): POST /ingest and /ingest/batch with X-API-Key."""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app.auth import check_api_key
from app.ingest.service import IngestService

router = APIRouter(tags=["ingest"])
MAX_BATCH = 500


def _auth(request: Request, key: str | None) -> IngestService:
    if not check_api_key(request.app.state.settings, key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad or missing X-API-Key")
    svc: IngestService = request.app.state.ingest
    return svc


@router.post("/ingest", summary="Ingest one TelemetryPayload v1")
async def ingest(request: Request, x_api_key: str | None = Header(default=None)) -> JSONResponse:
    svc = _auth(request, x_api_key)
    t = time.time()
    raw = await request.body()
    r = await run_in_threadpool(svc.process, raw, "http", None, t)
    return JSONResponse(r.body, status_code=r.http_code)


@router.post("/ingest/batch", summary="Ingest a JSON array of payloads (in order)")
async def ingest_batch(request: Request, x_api_key: str | None = Header(default=None)) -> JSONResponse:
    svc = _auth(request, x_api_key)
    t = time.time()
    raw = await request.body()
    if len(raw) > svc.max_payload_bytes * MAX_BATCH:
        return JSONResponse({"status": "rejected", "reason": "too_large"}, status_code=413)
    try:
        items = json.loads(raw)
    except ValueError:
        return JSONResponse({"status": "rejected", "reason": "parse_error"}, status_code=422)
    if not isinstance(items, list) or len(items) > MAX_BATCH:
        return JSONResponse({"status": "rejected", "reason": f"schema:batch (array of <= {MAX_BATCH})"},
                            status_code=422)

    def run() -> list[dict[str, Any]]:
        return [svc.process(json.dumps(i).encode(), "http", None, t).body for i in items]

    results = await run_in_threadpool(run)
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return JSONResponse({"status": "ok", "counts": counts, "results": results})
