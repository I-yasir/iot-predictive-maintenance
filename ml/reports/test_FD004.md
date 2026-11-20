# Official test evaluation — FD004

> **Run 2, post-hoc** (bundle `20261120-p2`). Produced after the test set had been seen once in run 1 (archived in `run1_20261120-p1/`); only the CV validation range changed. See `docs/05_ML_and_Data_Spec.md` §7.5.3.

Model `20261120-p2` · 248 test engines · last observed cycle vs `RUL_FD004.txt` (uncapped truth).
Selected config: `cap=125;n_sensors=15;min_child_samples=50,num_leaves=31` · conformal margin ±5.8 cycles.

| Metric | Value | Target |
|---|---|---|
| RMSE (cycles) | **26.14** | ≤ 24 ❌ |
| NASA score | **4513** | ≤ 4500 ❌ |
| MAE | 18.41 | |
| Bias (pred − true) | -7.49 | |
| Late by > 20 cycles | 7.3% | ≤ 10% |
| P10–P90 coverage | 71.4% | 75–90% |
| Mean interval width | 70.0 | |
| Critical recall | 0.87 | ≥ 0.90 |
| False Critical among healthy | 0.0% | ≤ 5% |
| CV RMSE LightGBM / Ridge | 18.28 / 21.55 | ≥ 15% better ✅ |

RMSE by true RUL: <=30: 7.0 · 31-75: 17.2 · 76-125: 16.6 · >125: 44.1

## Alert confusion (thresholds 75 / 30)

```
predicted  Healthy  Warning  Critical
true                                 
Healthy        134        6         0
Warning         18       33         4
Critical         0        7        46
```

![pred vs true](test_FD004_scatter.png)
![trajectories](test_FD004_trajectories.png)
