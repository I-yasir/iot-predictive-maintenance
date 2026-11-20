import uuid

import pytest
import sqlalchemy as sa
from conftest import ADMIN_URL, _admin

from app.db.session import downgrade, migrate


def test_upgrade_downgrade_upgrade_on_fresh_db() -> None:
    name = f"pdm_mig_{uuid.uuid4().hex[:8]}"
    try:
        with _admin().connect() as c:
            c.execute(sa.text(f"CREATE DATABASE {name}"))
    except sa.exc.OperationalError:
        pytest.skip("TimescaleDB not reachable (docker compose up -d db)")
    url = ADMIN_URL.rsplit("/", 1)[0] + "/" + name
    eng = sa.create_engine(url)
    tables = "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name <> 'alembic_version'"
    hyper = "SELECT count(*) FROM timescaledb_information.hypertables"
    try:
        migrate(url)
        with eng.connect() as c:
            assert c.execute(sa.text(tables)).scalar() >= 6
            assert c.execute(sa.text(hyper)).scalar() == 2
        downgrade(url)
        with eng.connect() as c:
            assert c.execute(sa.text(tables)).scalar() == 0
        migrate(url)
        with eng.connect() as c:
            assert c.execute(sa.text(hyper)).scalar() == 2
    finally:
        eng.dispose()
        with _admin().connect() as c:
            c.execute(sa.text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
