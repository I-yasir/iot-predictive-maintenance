"""P3.1 ops endpoints + P3.3 registry fail-fast."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from conftest import ROOT, make_settings
from fastapi.testclient import TestClient

from app.main import create_app
from app.registry import ModelRegistry, RegistryError


def test_health_ready_metrics(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    r = client.get("/readyz")
    assert r.status_code == 200 and r.json()["checks"]["db"] and r.json()["checks"]["models"]
    m = client.get("/metrics")
    assert m.status_code == 200 and "ingest_accepted_total" in m.text
    assert "/api/v1/assets" in client.get("/openapi.json").json()["paths"]


def test_readyz_fails_without_db(db_url: str) -> None:
    s = make_settings("postgresql+psycopg://x:y@127.0.0.1:1/none", auto_migrate=False)
    with TestClient(create_app(s, start_background=False)) as c:
        r = c.get("/readyz")
        assert r.status_code == 503 and r.json()["checks"] == {"models": True, "db": False, "mqtt": False}


def test_missing_bundle_fails_fast(tmp_path: Path, db_url: str) -> None:
    with pytest.raises(RegistryError, match="FD001"):
        ModelRegistry.load(tmp_path, ["FD001"])
    s = make_settings(db_url, model_root=str(tmp_path))
    with pytest.raises(RegistryError), TestClient(create_app(s, start_background=False)):
        pass


def test_corrupt_bundle_fails_fast(tmp_path: Path) -> None:
    src = ROOT / "ml" / "artifacts" / "FD002"
    dst = tmp_path / "FD002"
    shutil.copytree(src, dst)
    version = (dst / "CURRENT").read_text().strip()
    with (dst / version / "seq_model.pt").open("ab") as f:
        f.write(b"x")
    with pytest.raises(RegistryError, match="checksum mismatch"):
        ModelRegistry.load(tmp_path, ["FD002"])


def test_registry_describe(client: TestClient) -> None:
    items = client.app.state.registry.describe()
    by = {i["profile"]: i for i in items}
    assert set(by) == {"FD001", "FD002", "FD003", "FD004"}
    assert by["FD002"]["has_sequence_model"] and not by["FD001"]["has_sequence_model"]
