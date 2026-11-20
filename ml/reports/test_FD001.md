# Official test evaluation — FD001

Model `20261120-p3` · 100 test engines · last observed cycle vs `RUL_FD001.txt` (uncapped truth).
Selected config: `cap=125;n_sensors=14;W=50,a=0.3;min_child_samples=20,num_leaves=31` · conformal margin ±12.4 cycles.

| Metric | Value | Target |
|---|---|---|
| RMSE, uncapped truth | **14.23** | ≤ 16 ✅ |
| RMSE, truth capped at 125 | 13.16 |  |
| NASA score, uncapped | 284 | ≤ 500 ✅ |
| NASA score, capped at 125 | 255 |  |
| MAE | 10.72 | |
| Bias (pred − true) | -1.10 | |
| Late by > 20 cycles | 6.0% | ≤ 10% |
| P10–P90 coverage | 93.0% | 75–90% |
| Mean interval width | 82.0 | |
| Critical recall | 0.92 | ≥ 0.90 |
| False Critical among healthy | 0.0% | ≤ 5% |
| CV RMSE model / Ridge | 14.29 / 20.29 | ≥ 15% better ✅ |

RMSE by true RUL: <=30: 4.1 · 31-75: 9.8 · 76-125: 17.2 · >125: 20.2

## Alert confusion (thresholds 75 / 30)

```
predicted  Healthy  Warning  Critical
true                                 
Healthy         54        3         0
Warning          1       16         1
Critical         0        2        23
```

![pred vs true](test_FD001_scatter.png)
![trajectories](test_FD001_trajectories.png)
