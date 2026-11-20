"""Engine + migrations. `pdm-backend migrate` / alembic both use `migrate()`."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text

MIGRATIONS = Path(__file__).parent / "migrations"


def make_engine(url: str, synchronous_commit: bool = False) -> Engine:
    """synchronous_commit=off (default for the service): a commit returns before the WAL fsync, so a
    crash can lose the last ~0.6 s of telemetry but never corrupts data; cuts per-message latency ~2x."""
    opts = {} if synchronous_commit else {"options": "-c synchronous_commit=off"}
    return create_engine(url, pool_size=16, max_overflow=8, pool_pre_ping=True, future=True, connect_args=opts)


def alembic_config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def migrate(url: str, revision: str = "head") -> None:
    command.upgrade(alembic_config(url), revision)


def downgrade(url: str, revision: str = "base") -> None:
    command.downgrade(alembic_config(url), revision)


def ping(engine: Engine) -> bool:
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
