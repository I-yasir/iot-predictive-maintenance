import numpy as np
from scipy.stats import ks_2samp

from pdm_ml.drift.reference import ks_statistic


def test_ks_statistic_matches_scipy() -> None:
    rng = np.random.default_rng(0)
    for _ in range(200):
        a = np.round(rng.normal(rng.normal(), 1, 50), 2)  # rounding forces ties
        b = np.round(rng.normal(0, 1, 500), 2)
        assert abs(ks_statistic(a, np.sort(b)) - ks_2samp(a, b).statistic) < 1e-12
