"""Load raw C-MAPSS files into named DataFrames (docs/05 §3.1-3.2).

Raw quirks handled here: no header, whitespace separated with trailing spaces, 26 columns
(the readme wrongly says 26 sensors; there are 21).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
import yaml

from pdm_ml.config import PROFILES, SETTINGS, raw_dir, reference_dir

Split = Literal["train", "test"]
N_RAW_COLUMNS = 26


@dataclass(frozen=True)
class SensorInfo:
    raw: str
    symbol: str
    description: str
    unit: str
    subsystem: str
    kind: str


@lru_cache(maxsize=1)
def sensor_catalog(path: Path | None = None) -> tuple[SensorInfo, ...]:
    path = path or reference_dir() / "sensor_catalog.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    cat = tuple(SensorInfo(**{k: str(v) for k, v in s.items()}) for s in data["sensors"])
    if len(cat) != 21 or [s.raw for s in cat] != [f"s{i}" for i in range(1, 22)]:
        raise ValueError("sensor_catalog.yaml must list s1..s21 in order")
    return cat


def sensor_symbols() -> list[str]:
    return [s.symbol for s in sensor_catalog()]


def columns() -> list[str]:
    return ["unit", "cycle", *SETTINGS, *sensor_symbols()]


def _check_profile(profile: str) -> None:
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; expected one of {PROFILES}")


def load_split(profile: str, split: Split, data_dir: Path | None = None) -> pd.DataFrame:
    """Return one row per (unit, cycle) with canonical column names."""
    _check_profile(profile)
    path = (data_dir or raw_dir()) / f"{split}_{profile}.txt"
    df = pd.read_csv(path, sep=r"\s+", header=None, engine="c")
    if df.shape[1] != N_RAW_COLUMNS:
        raise ValueError(f"{path.name}: expected {N_RAW_COLUMNS} columns, got {df.shape[1]}")
    df.columns = columns()
    df = df.astype({"unit": np.int32, "cycle": np.int32})
    return df.sort_values(["unit", "cycle"], kind="stable").reset_index(drop=True)


def load_true_rul(profile: str, data_dir: Path | None = None) -> pd.Series:
    """True RUL after the last test cycle, indexed by test unit id (1..N in file order)."""
    _check_profile(profile)
    path = (data_dir or raw_dir()) / f"RUL_{profile}.txt"
    s = pd.read_csv(path, sep=r"\s+", header=None)[0].astype(np.int32)
    s.index = pd.Index(np.arange(1, len(s) + 1, dtype=np.int32), name="unit")
    return s.rename("true_rul")


@dataclass
class ProfileData:
    profile: str
    train: pd.DataFrame
    test: pd.DataFrame
    true_rul: pd.Series


def load_profile(profile: str, data_dir: Path | None = None) -> ProfileData:
    return ProfileData(
        profile=profile,
        train=load_split(profile, "train", data_dir),
        test=load_split(profile, "test", data_dir),
        true_rul=load_true_rul(profile, data_dir),
    )
