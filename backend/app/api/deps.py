from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy import Engine, text


def engine(request: Request) -> Engine:
    e: Engine = request.app.state.engine
    return e


def rows(e: Engine, sql: str, **params: Any) -> list[dict[str, Any]]:
    with e.connect() as c:
        return [dict(r) for r in c.execute(text(sql), params).mappings().all()]
