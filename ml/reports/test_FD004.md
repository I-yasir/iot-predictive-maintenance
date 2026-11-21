# Official test evaluation — FD004

Model `20261120-p6` · 248 test engines · last observed cycle vs `RUL_FD004.txt` (uncapped truth).
Selected config: `cap=125;n_sensors=15;W=70,a=0.3;min_child_samples=50,num_leaves=31` + M2 sequence model (point = mean) · conformal margin ±18.2 cycles.

| Metric | Value | Target |
|---|---|---|
| RMSE, uncapped truth | 24.61 |  |
| RMSE, truth capped at 125 | **11.86** | ≤ 24 ✅ |
| NASA score, uncapped | 3710 |  |
| NASA score, capped at 125 | 756 | ≤ 4500 ✅ |
| MAE | 16.49 | |
| Bias (pred − true) | -8.13 | |
| Late by > 20 cycles | 5.6% | ≤ 10% |
| P10–P90 coverage | 78.6% | 75–90% |
| Mean interval width | 91.1 | |
| Critical recall | 0.91 | ≥ 0.90 |
| False Critical among healthy | 0.0% | ≤ 5% |
| CV RMSE model / Ridge | 15.79 / 21.47 | ≥ 15% better ✅ |

RMSE by true RUL: <=30: 5.7 · 31-75: 13.5 · 76-125: 15.3 · >125: 42.5

## Alert confusion (thresholds 75 / 30)

```
predicted  Healthy  Warning  Critical
true                                 
Healthy        134        6         0
Warning         10       43         2
Critical         0        5        48
```

![pred vs true](test_FD004_scatter.png)
![trajectories](test_FD004_trajectories.png)
