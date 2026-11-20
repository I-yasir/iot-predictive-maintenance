"""Backend tests run against the docker-compose TimescaleDB (a fresh database per session)."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from pdm_iot.simulator.replay import ReplayConfig, build_messages

ROOT = Path(__file__).resolve().parents[2]
for line in (ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []:
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://pdm:change-me-db@localhost:5432/pdm")
API_KEY = "k" * 40
PASSWORD = "test-password"


def _admin() -> sa.Engine:
    return sa.create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")


@pytest.fixture(scope="session")
def db_url() -> Iterator[str]:
    name = f"pdm_test_{uuid.uuid4().hex[:8]}"
    try:
        with _admin().connect() as c:
            c.execute(sa.text(f"CREATE DATABASE {name}"))
    except sa.exc.OperationalError:
        pytest.skip("TimescaleDB not reachable (docker compose up -d db)")
    url = ADMIN_URL.rsplit("/", 1)[0] + "/" + name
    yield url
    with _admin().connect() as c:
        c.execute(sa.text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))


def make_settings(db_url: str, **kw: Any) -> Settings:
    base = dict(database_url=db_url, mqtt_enabled=False, ingest_api_key=API_KEY, dashboard_password=PASSWORD,
                session_secret="s" * 32, log_json=False, log_level="WARNING")
    base.update(kw)
    return Settings(**base)


@pytest.fixture(scope="session")
def app_client(db_url: str) -> Iterator[TestClient]:
    app = create_app(make_settings(db_url), start_background=False)
    with TestClient(app) as c:
        assert c.post("/api/v1/auth/login", json={"password": PASSWORD}).status_code == 200
        yield c


@pytest.fixture
def client(app_client: TestClient) -> Iterator[TestClient]:
    """Clean tables + in-memory runtimes for every test."""
    app = app_client.app
    with app.state.engine.begin() as c:  # type: ignore[attr-defined]
        c.execute(sa.text("TRUNCATE alerts, predictions, telemetry, dead_letter, devices, assets CASCADE"))
    app.state.ingest.reset()  # type: ignore[attr-defined]
    app.state.ingest.rate = 0.0  # type: ignore[attr-defined]  # tests post faster than 50 msg/s
    yield app_client


def replay_msgs(profile: str = "FD001", units: list[int] | None = None, split: str = "test",
                prefix: str = "") -> list[dict[str, Any]]:
    cfg = ReplayConfig(profile, split, units or [1], speed_cps=0, asset_prefix=prefix)
    return [m for tick in build_messages(cfg) for m in tick]


def post(client: TestClient, payload: dict[str, Any] | bytes | str, key: str | None = API_KEY) -> Any:
    data = payload if isinstance(payload, bytes | str) else json.dumps(payload)
    headers = {"X-API-Key": key} if key else {}
    return client.post("/api/v1/ingest", content=data, headers=headers)
