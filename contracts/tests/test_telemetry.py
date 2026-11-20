"""P2.1: TelemetryPayload v1 accepts valid messages and rejects bad ones with the documented reason codes."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pdm_contracts import Accepted, Rejection, json_schema, load_profiles, parse_topic, validate_message

ROOT = Path(__file__).resolve().parents[2]
PROFILES = load_profiles(ROOT / "config" / "profiles")
EXAMPLE = json.loads((ROOT / "iot" / "contracts" / "example_payload.json").read_text())


def check(obj: Any, **kw: Any) -> Accepted | Rejection:
    return validate_message(json.dumps(obj), PROFILES, **kw)


def mutate(path: str, value: Any = ..., delete: bool = False) -> dict[str, Any]:
    obj = copy.deepcopy(EXAMPLE)
    *parents, last = path.split(".")
    node = obj
    for p in parents:
        node = node[p]
    if delete:
        del node[last]
    else:
        node[last] = value
    return obj


def test_example_is_valid() -> None:
    r = check(EXAMPLE)
    assert isinstance(r, Accepted), r
    assert r.flags == []
    assert r.payload.cycle == 1 and r.payload.source == "ESP32"


def test_all_profiles_loaded() -> None:
    assert set(PROFILES) == {"FD001", "FD002", "FD003", "FD004"}
    assert "epr" in PROFILES["FD003"].required_sensors


@pytest.mark.parametrize(
    "obj,reason",
    [
        (mutate("cycle", delete=True), "schema:cycle"),
        (mutate("cycle", 0), "schema:cycle"),
        (mutate("cycle", "12"), "schema:cycle"),
        (mutate("cycle", True), "schema:cycle"),
        (mutate("asset_id", "bad id!"), "schema:asset_id"),
        (mutate("source", "PLC"), "schema:source"),
        (mutate("schema_version", "2.0"), "unsupported_version"),
        (mutate("profile", "FD009"), "unknown_profile"),
        (mutate("sensors.T30", delete=True), "schema:sensors.T30"),
        (mutate("sensors.T30", 99999.0), "range:T30"),
        (mutate("settings.setting_3", delete=True), "schema:settings.setting_3"),
        (mutate("extra_field", 1), "schema:extra_field"),
        (mutate("meta", {"blob": "x" * 2000}), "schema:meta"),
    ],
)
def test_rejections(obj: dict[str, Any], reason: str) -> None:
    r = check(obj)
    assert isinstance(r, Rejection), r
    assert r.reason == reason, r


def test_nan_and_inf_rejected() -> None:
    for bad in ("NaN", "Infinity", "-Infinity"):
        raw = json.dumps(EXAMPLE).replace('"T30": 1589.7', f'"T30": {bad}')
        r = validate_message(raw, PROFILES)
        assert isinstance(r, Rejection) and r.reason == "schema:sensors", r


def test_parse_error_and_size() -> None:
    r1 = validate_message(b"{not json", PROFILES)
    assert isinstance(r1, Rejection) and r1.reason == "parse_error"
    r2 = validate_message(b"[1,2]", PROFILES)
    assert isinstance(r2, Rejection) and r2.reason == "schema:payload"
    r3 = validate_message(b" " * 5000, PROFILES)
    assert isinstance(r3, Rejection) and r3.reason == "too_large"


def test_soft_ood_flag_is_not_rejection() -> None:
    r = check(mutate("sensors.T30", 1625.0))  # above FD001 train max 1616.91, inside hard limit
    assert isinstance(r, Accepted) and r.flags == ["OOD:T30"]


def test_extra_sensor_allowed_and_topic_match() -> None:
    assert isinstance(check(mutate("sensors.vibration_rms", 0.12)), Accepted)
    assert isinstance(check(EXAMPLE, topic_ids=("lab", "FD001-E001")), Accepted)
    r = check(EXAMPLE, topic_ids=("lab", "OTHER"))
    assert isinstance(r, Rejection) and r.reason == "topic_mismatch"


def test_parse_topic() -> None:
    assert parse_topic("pdm/v1/lab/FD001-E001/telemetry") == ("lab", "FD001-E001", "telemetry")
    assert parse_topic("pdm/v1/lab/bad id/telemetry") is None
    assert parse_topic("other/lab/x/telemetry") is None


def test_schema_file_is_current() -> None:
    committed = json.loads((ROOT / "iot" / "contracts" / "telemetry_v1.schema.json").read_text())
    assert committed == json_schema(), "run: python -m pdm_contracts.export_schema"


@settings(max_examples=300, deadline=None)
@given(
    st.dictionaries(
        st.text(max_size=12),
        st.one_of(st.none(), st.integers(), st.floats(), st.text(max_size=8)),
        max_size=8,
    )
)
def test_fuzz_never_crashes(obj: dict[str, Any]) -> None:
    r = validate_message(json.dumps(obj), PROFILES)
    assert isinstance(r, Rejection) and r.reason


@settings(max_examples=200, deadline=None)
@given(
    st.sampled_from(sorted(EXAMPLE["sensors"])),
    st.one_of(st.text(max_size=5), st.none(), st.lists(st.integers())),
)
def test_fuzz_bad_sensor_types(key: str, value: Any) -> None:
    r = check(mutate(f"sensors.{key}", value))
    assert isinstance(r, Rejection) and r.reason.startswith("schema:sensors")
