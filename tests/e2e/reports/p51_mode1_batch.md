# P5.1 Mode 1 batch through the backend ingest path

Result: **PASS**. Every official test engine was streamed through `POST /api/v1/ingest/batch` (assets `B25229FD00x-Tnnn`); the backend's last prediction per engine is compared with the offline P1.8 evaluation (`ml/reports/test_FD00x.json`). Pass rule: ≥ 90% of engines within 0.001 cycles of the offline prediction, none more than 1.0 cycle off, RMSE/MAE/bias within 0.05, NASA score within 2 %, shares within one engine. The few engines that differ do so because streaming and batch features differ in the last bit (~1e-15) and that flips a LightGBM split sitting exactly on the threshold.

| Profile | Engines | Messages | msg/s | Exact share | Max abs diff (cycles) | RMSE served / offline | NASA score served / offline | Critical recall | Coverage P10–P90 | OK |
|---|---|---|---|---|---|---|---|---|---|---|
| FD001 | 100 | 13096 | 184.9 | 1.00 | 0.000 | 13.81 / 13.81 | 268.3 / 268.3 | 0.88 / 0.88 | 0.91 / 0.91 | yes |
| FD002 | 259 | 33991 | 185.5 | 1.00 | 0.000 | 23.04 / 23.04 | 3896.7 / 3896.7 | 1.00 / 1.00 | 0.79 / 0.79 | yes |
| FD003 | 100 | 16596 | 193.9 | 1.00 | 0.000 | 13.29 / 13.29 | 332.8 / 332.8 | 0.90 / 0.90 | 0.93 / 0.93 | yes |
| FD004 | 248 | 41214 | 187.1 | 1.00 | 0.000 | 24.61 / 24.61 | 3710.1 / 3710.1 | 0.91 / 0.91 | 0.79 / 0.79 | yes |

Ingest outcome counts per profile: FD001 {'accepted': 13096}; FD002 {'accepted': 33991}; FD003 {'accepted': 16596}; FD004 {'accepted': 41214}
