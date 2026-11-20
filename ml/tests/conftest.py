from __future__ import annotations

import pandas as pd
import pytest

from pdm_ml.io.loader import ProfileData, load_profile


@pytest.fixture(scope="session")
def fd001() -> ProfileData:
    return load_profile("FD001")


@pytest.fixture(scope="session")
def fd002() -> ProfileData:
    return load_profile("FD002")


@pytest.fixture(scope="session")
def fd003() -> ProfileData:
    return load_profile("FD003")


@pytest.fixture(scope="session")
def fd001_small(fd001: ProfileData) -> pd.DataFrame:
    return fd001.train[fd001.train.unit <= 20].reset_index(drop=True)
