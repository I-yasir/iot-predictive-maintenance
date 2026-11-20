"""TelemetryPayload v1 — the canonical message every source must emit (docs/04 §5.2).

Two layers:
  1. `TelemetryPayload` — structural schema (types, ids, finite numbers). Profile-agnostic.
  2. `validate_message` — full ingestion check: size, JSON parse, schema, profile, required sensors,
     hard ranges, topic/payload id match. Returns either an accepted payload or a `Rejection` whose
     `reason` is one of the codes listed in docs/04 §5.3 / docs/02 §8.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

SCHEMA_VERSION = "1.0"
MAX_PAYLOAD_BYTES = 4096
MAX_META_BYTES = 1024
ID_PATTERN = r"^[A-Za-z0-9_-]{1,48}$"
_ID_RE = re.compile(ID_PATTERN)

Id = Annotated[str, Field(pattern=ID_PATTERN)]


class Source(StrEnum):
    REPLAY = "REPLAY"
    ESP32 = "ESP32"
    VIRTUAL_ESP32 = "VIRTUAL_ESP32"
    LIVE = "LIVE"


def _finite(v: float, name: str) -> float:
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(float(v)):
        raise ValueError(f"{name} must be a finite number")
    return float(v)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    setting_1: float
    setting_2: float
    setting_3: float

    @field_validator("setting_1", "setting_2", "setting_3", mode="before")
    @classmethod
    def _check(cls, v: Any) -> float:
        return _finite(v, "setting")


class TelemetryPayload(BaseModel):
    """One operating cycle from one asset."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: str
    msg_id: Annotated[str, Field(min_length=1, max_length=64)]
    site_id: Id
    asset_id: Id
    profile: Id
    source: Source
    seq: Annotated[int, Field(ge=0)]
    cycle: Annotated[int, Field(ge=1)]
    ts: datetime | None = None
    settings: Settings
    sensors: dict[str, float]
    meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source", mode="before")
    @classmethod
    def _source(cls, v: Any) -> Source:
        return Source(v)

    @field_validator("ts", mode="before")
    @classmethod
    def _ts(cls, v: Any) -> datetime | None:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("ts must be an RFC 3339 string")
        return datetime.fromisoformat(v.replace("Z", "+00:00"))

    @field_validator("sensors", mode="before")
    @classmethod
    def _sensors(cls, v: Any) -> dict[str, float]:
        if not isinstance(v, dict) or not v:
            raise ValueError("sensors must be a non-empty object")
        out = {}
        for k, val in v.items():
            if not isinstance(k, str) or not 1 <= len(k) <= 32:
                raise ValueError("sensor keys must be 1-32 char strings")
            out[k] = _finite(val, f"sensors.{k}")
        return out

    @field_validator("meta")
    @classmethod
    def _meta(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(v)) > MAX_META_BYTES:
            raise ValueError("meta larger than 1 KB")
        return v

    @model_validator(mode="after")
    def _version(self) -> TelemetryPayload:
        if self.schema_version.split(".")[0] != SCHEMA_VERSION.split(".")[0]:
            raise ValueError("unsupported_version")
        return self


# ---------------------------------------------------------------- profile-aware validation


@dataclass(frozen=True)
class Range:
    hard_min: float
    hard_max: float
    soft_min: float
    soft_max: float


@dataclass(frozen=True)
class Profile:
    name: str
    required_settings: tuple[str, ...]
    required_sensors: tuple[str, ...]
    ranges: dict[str, Range]
    expected_interval_s: float = 1.0

    @classmethod
    def from_yaml(cls, path: Path) -> Profile:
        d = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(
            name=d["profile"],
            required_settings=tuple(d["required_settings"]),
            required_sensors=tuple(d["required_sensors"]),
            ranges={k: Range(**v) for k, v in d["ranges"].items()},
            expected_interval_s=float(d.get("expected_interval_s", 1.0)),
        )


def load_profiles(directory: Path) -> dict[str, Profile]:
    return {p.stem: Profile.from_yaml(p) for p in sorted(directory.glob("*.yaml"))}


@dataclass
class Rejection:
    reason: str
    detail: str = ""


@dataclass
class Accepted:
    payload: TelemetryPayload
    flags: list[str] = field(default_factory=list)  # soft issues, e.g. "OOD:T30"


def _schema_reason(err: ValidationError) -> str:
    first = err.errors()[0]
    if "unsupported_version" in str(first.get("msg", "")):
        return "unsupported_version"
    loc = ".".join(str(p) for p in first["loc"]) or "payload"
    return f"schema:{loc}"


def validate_message(
    raw: bytes | str,
    profiles: dict[str, Profile],
    topic_ids: tuple[str, str] | None = None,
) -> Accepted | Rejection:
    """Full ingestion validation. `topic_ids` = (site_id, asset_id) parsed from the MQTT topic, if any."""
    data = raw.encode() if isinstance(raw, str) else raw
    if len(data) > MAX_PAYLOAD_BYTES:
        return Rejection("too_large", f"{len(data)} bytes > {MAX_PAYLOAD_BYTES}")
    try:
        obj = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        return Rejection("parse_error", str(e)[:200])
    if not isinstance(obj, dict):
        return Rejection("schema:payload", "top-level JSON must be an object")
    try:
        p = TelemetryPayload.model_validate(obj)
    except ValidationError as e:
        return Rejection(_schema_reason(e), str(e.errors()[0].get("msg", ""))[:200])
    if topic_ids is not None and (p.site_id, p.asset_id) != topic_ids:
        return Rejection("topic_mismatch", f"topic {topic_ids} != payload ({p.site_id}, {p.asset_id})")
    prof = profiles.get(p.profile)
    if prof is None:
        return Rejection("unknown_profile", p.profile)
    for s in prof.required_sensors:
        if s not in p.sensors:
            return Rejection(f"schema:sensors.{s}", "required sensor missing")
    flags: list[str] = []
    values = {**p.settings.model_dump(), **p.sensors}
    for name, v in values.items():
        r = prof.ranges.get(name)
        if r is None:
            continue  # extra sensors are stored but not range-checked
        if not r.hard_min <= v <= r.hard_max:
            return Rejection(f"range:{name}", f"{v} outside [{r.hard_min}, {r.hard_max}]")
        if not r.soft_min <= v <= r.soft_max:
            flags.append(f"OOD:{name}")
    return Accepted(p, flags)


def parse_topic(topic: str, prefix: str = "pdm/v1") -> tuple[str, str, str] | None:
    """'pdm/v1/{site}/{asset}/{kind}' -> (site, asset, kind) or None."""
    parts = topic.split("/")
    pre = prefix.split("/")
    if len(parts) != len(pre) + 3 or parts[: len(pre)] != pre:
        return None
    site, asset, kind = parts[len(pre) :]
    if not (_ID_RE.match(site) and _ID_RE.match(asset)):
        return None
    return site, asset, kind


def telemetry_topic(site_id: str, asset_id: str, prefix: str = "pdm/v1") -> str:
    return f"{prefix}/{site_id}/{asset_id}/telemetry"


def json_schema() -> dict[str, Any]:
    s = TelemetryPayload.model_json_schema()
    s["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    s["$id"] = "https://github.com/I-yasir/iot-predictive-maintenance/iot/contracts/telemetry_v1.schema.json"
    s["description"] = (
        "PdM-Live TelemetryPayload v1. Profile-specific required sensors and ranges are in "
        "config/profiles/{profile}.yaml and are enforced by the ingestion gateway."
    )
    return s
