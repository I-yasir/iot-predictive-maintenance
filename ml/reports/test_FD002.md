# Official test evaluation — FD002

> **Run 3, post-hoc** (bundle `20261120-p3`, plan step P1.10). Third look at the official test set; changes since run 2 were selected on CV only (feature window grid {30, 50, 70, 100}). See `docs/05_ML_and_Data_Spec.md` §7.5.4.

Model `20261120-p3` · 259 test engines · last observed cycle vs `RUL_FD002.txt` (uncapped truth).
Selected config: `cap=125;n_sensors=14;W=100,a=0.3;min_child_samples=20,num_leaves=31` · conformal margin ±13.0 cycles.

| Metric | Value | Target |
|---|---|---|
| RMSE (cycles) | **23.37** | ≤ 22 ❌ |
| NASA score | **3745** | ≤ 3000 ❌ |
| MAE | 15.59 | |
| Bias (pred − true) | -7.61 | |
| Late by > 20 cycles | 6.6% | ≤ 10% |
| P10–P90 coverage | 78.8% | 75–90% |
| Mean interval width | 85.3 | |
| Critical recall | 0.98 | ≥ 0.90 |
| False Critical among healthy | 0.0% | ≤ 5% |
| CV RMSE LightGBM / Ridge | 15.82 / 20.94 | ≥ 15% better ✅ |

RMSE by true RUL: <=30: 3.4 · 31-75: 12.6 · 76-125: 16.1 · >125: 43.9

## Alert confusion (thresholds 75 / 30)

```
predicted  Healthy  Warning  Critical
true                                 
Healthy        129       10         0
Warning          9       49         1
Critical         0        1        60
```

![pred vs true](test_FD002_scatter.png)
![trajectories](test_FD002_trajectories.png)
