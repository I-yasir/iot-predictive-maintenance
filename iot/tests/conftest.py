import os
import socket
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _broker_up() -> bool:
    try:
        with socket.create_connection((os.environ.get("MQTT_HOST", "localhost"), int(os.environ.get("MQTT_PORT", "1883"))), 1):
            return True
    except OSError:
        return False


_load_env()


def pytest_collection_modifyitems(config, items):
    if _broker_up() and os.environ.get("MQTT_REPLAY_PASSWORD"):
        return
    skip = pytest.mark.skip(reason="no Mosquitto on localhost:1883 or no .env (docker compose up -d mosquitto)")
    for it in items:
        if "broker" in it.keywords:
            it.add_marker(skip)
