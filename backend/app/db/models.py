"""SQLAlchemy Core table definitions mirroring docs/05 §9 (the migration is the source of truth for DDL)."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Integer,
    LargeBinary,
    MetaData,
    SmallInteger,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import REAL as Real

metadata = MetaData()

assets = Table(
    "assets", metadata,
    Column("asset_id", Text, primary_key=True),
    Column("site_id", Text, nullable=False),
    Column("profile", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("display_name", Text),
    Column("life_id", Integer, nullable=False),
    Column("state", Text, nullable=False),
    Column("last_cycle", Integer),
    Column("last_seen_at", DateTime(timezone=True)),
    Column("expected_interval_s", Real),
    Column("true_rul_at_end", Integer),
    Column("created_at", DateTime(timezone=True)),
    Column("meta", JSONB, nullable=False),
)

devices = Table(
    "devices", metadata,
    Column("device_id", Text, primary_key=True),
    Column("asset_id", Text),
    Column("fw", Text),
    Column("ip", Text),
    Column("rssi", Integer),
    Column("online", Boolean),
    Column("last_status_at", DateTime(timezone=True)),
)

telemetry = Table(
    "telemetry", metadata,
    Column("asset_id", Text, primary_key=True),
    Column("life_id", Integer, primary_key=True),
    Column("cycle", Integer, primary_key=True),
    Column("received_at", DateTime(timezone=True), primary_key=True),
    Column("device_ts", DateTime(timezone=True)),
    Column("msg_id", Text),
    Column("seq", Integer),
    Column("settings", JSONB, nullable=False),
    Column("sensors", JSONB, nullable=False),
    Column("regime", SmallInteger),
    Column("flags", ARRAY(Text), nullable=False),
    Column("meta", JSONB),
)

predictions = Table(
    "predictions", metadata,
    Column("prediction_id", BigInteger, primary_key=True, autoincrement=True),
    Column("asset_id", Text, nullable=False),
    Column("life_id", Integer, nullable=False),
    Column("cycle", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), primary_key=True),
    Column("model_version", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("rul_pred", Real),
    Column("rul_p10", Real),
    Column("rul_p90", Real),
    Column("health_index", Real),
    Column("state", Text, nullable=False),
    Column("flags", ARRAY(Text), nullable=False),
    Column("contributors", JSONB),
    Column("subsystem_scores", JSONB),
    Column("latency_ms", Real),
    Column("true_rul", Integer),
)

alerts = Table(
    "alerts", metadata,
    Column("alert_id", BigInteger, primary_key=True),
    Column("asset_id", Text, nullable=False),
    Column("life_id", Integer, nullable=False),
    Column("cycle", Integer, nullable=False),
    Column("from_state", Text, nullable=False),
    Column("to_state", Text, nullable=False),
    Column("rul_pred", Real),
    Column("reason", Text),
    Column("created_at", DateTime(timezone=True)),
    Column("acknowledged_at", DateTime(timezone=True)),
    Column("acknowledged_by", Text),
)

dead_letter = Table(
    "dead_letter", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("received_at", DateTime(timezone=True)),
    Column("transport", Text),
    Column("topic", Text),
    Column("asset_id", Text),
    Column("reason", Text, nullable=False),
    Column("detail", Text),
    Column("raw", LargeBinary),
)

model_registry = Table(
    "model_registry", metadata,
    Column("profile", Text, primary_key=True),
    Column("model_version", Text, primary_key=True),
    Column("active", Boolean),
    Column("metrics", JSONB),
    Column("created_at", DateTime(timezone=True)),
)
