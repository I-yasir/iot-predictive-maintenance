"""Build canonical TelemetryPayload v1 dicts (docs/04 §5.2) from dataset rows or synthetic values."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from pdm_contracts import SCHEMA_VERSION

SETTINGS = ("setting_1", "setting_2", "setting_3")


def now_rfc3339() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def build_payload(
    *,
    site_id: str,
    asset_id: str,
    profile: str,
    source: str,
    seq: int,
    cycle: int,
    settings: Mapping[str, float],
    sensors: Mapping[str, float],
    msg_prefix: str,
    meta: Mapping[str, Any] | None = None,
    ts: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "msg_id": f"{msg_prefix}-{seq:06d}"[:64],
        "site_id": site_id,
        "asset_id": asset_id,
        "profile": profile,
        "source": source,
        "seq": int(seq),
        "cycle": int(cycle),
        "ts": ts or now_rfc3339(),
        "settings": {k: round(float(settings[k]), 4) for k in SETTINGS},
        "sensors": {k: round(float(v), 4) for k, v in sensors.items()},
        "meta": dict(meta or {}),
    }
