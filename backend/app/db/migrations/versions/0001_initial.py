"""Initial schema (docs/05 §9): assets, devices, telemetry + predictions hypertables, alerts, dead letter.

Revision ID: 0001
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

UP = """
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE assets (
  asset_id      TEXT PRIMARY KEY,
  site_id       TEXT NOT NULL,
  profile       TEXT NOT NULL,
  source        TEXT NOT NULL,
  display_name  TEXT,
  life_id       INT  NOT NULL DEFAULT 1,
  state         TEXT NOT NULL DEFAULT 'NEW',
  last_cycle    INT,
  last_seen_at  TIMESTAMPTZ,
  expected_interval_s REAL DEFAULT 1.0,
  true_rul_at_end INT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  meta          JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE devices (
  device_id TEXT PRIMARY KEY, asset_id TEXT REFERENCES assets ON DELETE SET NULL, fw TEXT, ip TEXT,
  rssi INT, online BOOLEAN, last_status_at TIMESTAMPTZ
);

CREATE TABLE telemetry (
  asset_id    TEXT NOT NULL REFERENCES assets ON DELETE CASCADE,
  life_id     INT  NOT NULL,
  cycle       INT  NOT NULL,
  received_at TIMESTAMPTZ NOT NULL,
  device_ts   TIMESTAMPTZ,
  msg_id      TEXT,
  seq         INT,
  settings    JSONB NOT NULL,
  sensors     JSONB NOT NULL,
  regime      SMALLINT,
  flags       TEXT[] NOT NULL DEFAULT '{}',
  meta        JSONB,
  PRIMARY KEY (asset_id, life_id, cycle, received_at)
);
SELECT create_hypertable('telemetry', 'received_at');
CREATE INDEX telemetry_asset_cycle ON telemetry (asset_id, life_id, cycle DESC);

CREATE TABLE predictions (
  prediction_id BIGSERIAL,
  asset_id      TEXT NOT NULL REFERENCES assets ON DELETE CASCADE,
  life_id       INT  NOT NULL,
  cycle         INT  NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  model_version TEXT NOT NULL,
  status        TEXT NOT NULL,
  rul_pred REAL, rul_p10 REAL, rul_p90 REAL, health_index REAL,
  state         TEXT NOT NULL,
  flags         TEXT[] NOT NULL DEFAULT '{}',
  contributors  JSONB,
  subsystem_scores JSONB,
  latency_ms    REAL,
  true_rul      INT,
  PRIMARY KEY (prediction_id, created_at)
);
SELECT create_hypertable('predictions', 'created_at');
CREATE INDEX predictions_asset_cycle ON predictions (asset_id, life_id, cycle DESC);

CREATE TABLE alerts (
  alert_id BIGSERIAL PRIMARY KEY,
  asset_id TEXT NOT NULL REFERENCES assets ON DELETE CASCADE,
  life_id INT NOT NULL, cycle INT NOT NULL,
  from_state TEXT NOT NULL, to_state TEXT NOT NULL, rul_pred REAL, reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), acknowledged_at TIMESTAMPTZ, acknowledged_by TEXT
);
CREATE INDEX alerts_created ON alerts (created_at DESC);
CREATE INDEX alerts_asset ON alerts (asset_id, created_at DESC);

CREATE TABLE dead_letter (
  id BIGSERIAL PRIMARY KEY, received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  transport TEXT, topic TEXT, asset_id TEXT, reason TEXT NOT NULL, detail TEXT, raw BYTEA
);
CREATE INDEX dead_letter_received ON dead_letter (received_at DESC);

CREATE TABLE model_registry (
  profile TEXT, model_version TEXT, active BOOLEAN, metrics JSONB, created_at TIMESTAMPTZ,
  PRIMARY KEY (profile, model_version)
);

SELECT add_retention_policy('telemetry', INTERVAL '30 days');
SELECT add_retention_policy('predictions', INTERVAL '90 days');
"""

DOWN = """
DROP TABLE IF EXISTS model_registry;
DROP TABLE IF EXISTS dead_letter;
DROP TABLE IF EXISTS alerts;
DROP TABLE IF EXISTS predictions;
DROP TABLE IF EXISTS telemetry;
DROP TABLE IF EXISTS devices;
DROP TABLE IF EXISTS assets;
"""


def upgrade() -> None:
    op.execute(UP)


def downgrade() -> None:
    op.execute(DOWN)
