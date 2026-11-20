# Official test evaluation — FD003

> **Run 3, post-hoc** (bundle `20261120-p3`, plan step P1.10). Third look at the official test set; changes since run 2 were selected on CV only (feature window grid {30, 50, 70, 100}). See `docs/05_ML_and_Data_Spec.md` §7.5.4.

Model `20261120-p3` · 100 test engines · last observed cycle vs `RUL_FD003.txt` (uncapped truth).
Selected config: `cap=125;n_sensors=15;W=70,a=0.3;min_child_samples=50,num_leaves=31` · conformal margin ±17.3 cycles.

| Metric | Value | Target |
|---|---|---|
| RMSE (cycles) | **12.02** | ≤ 16 ✅ |
| NASA score | **286** | ≤ 600 ✅ |
| MAE | 8.35 | |
| Bias (pred − true) | +0.21 | |
| Late by > 20 cycles | 5.0% | ≤ 10% |
| P10–P90 coverage | 92.0% | 75–90% |
| Mean interval width | 88.8 | |
| Critical recall | 0.85 | ≥ 0.90 |
| False Critical among healthy | 0.0% | ≤ 5% |
| CV RMSE LightGBM / Ridge | 14.49 / 19.50 | ≥ 15% better ✅ |

RMSE by true RUL: <=30: 2.7 · 31-75: 10.3 · 76-125: 13.9 · >125: 16.8

## Alert confusion (thresholds 75 / 30)

```
predicted  Healthy  Warning  Critical
true                                 
Healthy         48        3         0
Warning          4       24         1
Critical         0        3        17
```

![pred vs true](test_FD003_scatter.png)
![trajectories](test_FD003_trajectories.png)
