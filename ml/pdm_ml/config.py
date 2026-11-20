"""Project-wide constants and paths. Values mirror docs/05_ML_and_Data_Spec.md; change both together."""

from __future__ import annotations

import os
from pathlib import Path

SEED = 42
PROFILES: tuple[str, ...] = ("FD001", "FD002", "FD003", "FD004")
MULTI_REGIME: frozenset[str] = frozenset({"FD002", "FD004"})
N_REGIMES_MULTI = 6

RUL_CAP_DEFAULT = 125
WINDOW = 30
MIN_CYCLES = 5
EWM_ALPHA = 0.3
BASELINE_CYCLES = 20  # diagnostics: per-asset healthy baseline length

SETTINGS: tuple[str, ...] = ("setting_1", "setting_2", "setting_3")

BASE_INPUTS: tuple[str, ...] = (
    "T24",
    "T30",
    "T50",
    "P30",
    "Nf",
    "Nc",
    "Ps30",
    "phi",
    "NRf",
    "NRc",
    "BPR",
    "htBleed",
    "W31",
    "W32",
)
DEFAULT_INPUTS: dict[str, tuple[str, ...]] = {
    "FD001": BASE_INPUTS,
    "FD002": BASE_INPUTS,
    "FD003": (*BASE_INPUTS, "epr"),
    "FD004": (*BASE_INPUTS, "epr"),
}

# Alert thresholds (docs/05 §8.1) - used for offline alert-quality metrics.
WARNING_RUL = 75
CRITICAL_RUL = 30


def find_root(start: Path | None = None) -> Path:
    """Repository root = first ancestor containing data/raw/cmapss (override with PDM_ROOT)."""
    env = os.environ.get("PDM_ROOT")
    if env:
        return Path(env).resolve()
    start = (start or Path(__file__)).resolve()
    for p in [start, *start.parents]:
        if (p / "data" / "raw" / "cmapss").is_dir():
            return p
    raise FileNotFoundError(f"data/raw/cmapss not found above {start}; set PDM_ROOT")


def raw_dir() -> Path:
    return Path(os.environ.get("DATA_RAW_DIR", find_root() / "data" / "raw" / "cmapss"))


def reference_dir() -> Path:
    return find_root() / "data" / "reference"


def artifacts_dir() -> Path:
    return Path(os.environ.get("MODEL_ROOT", find_root() / "ml" / "artifacts"))


def reports_dir() -> Path:
    return find_root() / "ml" / "reports"


def profiles_config_dir() -> Path:
    return find_root() / "config" / "profiles"
