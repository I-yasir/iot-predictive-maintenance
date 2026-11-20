"""RUL labelling (docs/05 §4)."""

from __future__ import annotations

import pandas as pd


def train_rul(df: pd.DataFrame) -> pd.Series:
    """Run-to-failure data: RUL = last cycle of the unit - current cycle (last row = 0)."""
    return (df.groupby("unit").cycle.transform("max") - df.cycle).rename("rul")


def test_rul(df: pd.DataFrame, true_rul: pd.Series) -> pd.Series:
    """Truncated data: RUL = RUL_file[unit] + (last observed cycle - cycle)."""
    last = df.groupby("unit").cycle.transform("max")
    return (df.unit.map(true_rul) + last - df.cycle).rename("rul")


def cap(rul: pd.Series, cap_value: int) -> pd.Series:
    """Piecewise-linear target: degradation is unobservable early in life."""
    return rul.clip(upper=cap_value)
