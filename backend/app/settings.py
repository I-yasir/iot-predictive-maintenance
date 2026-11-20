"""Environment configuration (docs/04 §4). Every value comes from the environment / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from pdm_ml.config import find_root


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://pdm:change-me-db@localhost:5432/pdm"
    mqtt_enabled: bool = True
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: str = "pdm-backend"
    mqtt_password: str = Field(default="", validation_alias="MQTT_BACKEND_PASSWORD")
    mqtt_topic_prefix: str = "pdm/v1"
    mqtt_workers: int = 2  # more threads only add GIL contention with the paho network thread (P3.9)
    ingest_api_key: str = ""
    dashboard_password: str = ""  # empty -> dashboard auth disabled (dev only, logged as a warning)
    session_secret: str = ""
    session_max_age_s: int = 12 * 3600
    model_root: str = "ml/artifacts"
    active_profiles: str = "FD001,FD002,FD003,FD004"
    alerts_config: str = "config/alerts.yaml"
    profiles_dir: str = "config/profiles"
    cors_origins: str = "http://localhost:8080,http://localhost:5173"
    log_level: str = "INFO"
    log_json: bool = True
    max_payload_bytes: int = 4096
    offline_check_s: float = 1.0
    auto_migrate: bool = True  # dev convenience: alembic upgrade head at startup

    def path(self, value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else find_root() / p

    @property
    def profiles(self) -> list[str]:
        return [p.strip() for p in self.active_profiles.split(",") if p.strip()]

    @property
    def cors(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def alerts(self) -> dict[str, Any]:
        data: dict[str, Any] = yaml.safe_load(self.path(self.alerts_config).read_text())
        return data


@lru_cache
def get_settings() -> Settings:
    return Settings()
