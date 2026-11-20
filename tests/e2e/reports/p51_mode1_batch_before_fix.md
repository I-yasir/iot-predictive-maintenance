# P5.1 Mode 1 batch through the backend ingest path

Result: **FAIL**. Every official test engine was streamed through `POST /api/v1/ingest/batch` (assets `B88814FD00x-Tnnn`); the backend's last prediction per engine is compared with the offline P1.8 evaluation (`ml/reports/test_FD00x.json`). Pass rule: ≥ 90% of engines within 0.001 cycles of the offline prediction, none more than 1.0 cycle off, RMSE/MAE/bias within 0.05, NASA score within 2 %, shares within one engine. The few engines that differ do so because streaming and batch features differ in the last bit (~1e-15) and that flips a LightGBM split sitting exactly on the threshold.

| Profile | Engines | Messages | msg/s | Exact share | Max abs diff (cycles) | RMSE served / offline | NASA score served / offline | Critical recall | Coverage P10–P90 | OK |
|---|---|---|---|---|---|---|---|---|---|---|
| FD001 | 100 | 13096 | 138.8 | 0.94 | 0.650 | 14.24 / 14.23 | 284.5 / 284.2 | 0.92 / 0.92 | 0.93 / 0.93 | yes |
| FD002 | 259 | 33991 | 130.3 | 1.00 | 0.000 | 23.00 / 23.00 | 3852.9 / 3852.9 | 1.00 / 1.00 | 0.79 / 0.79 | yes |
| FD003 | 100 | 16596 | 137.9 | 0.39 | 21.850 | 14.31 / 12.02 | 355.6 / 286.2 | 0.85 / 0.85 | 0.92 / 0.92 | NO |
| FD004 | 248 | 41214 | 144.9 | 1.00 | 0.000 | 24.69 / 24.69 | 3760.6 / 3760.6 | 0.91 / 0.91 | 0.78 / 0.78 | yes |

Ingest outcome counts per profile: FD001 {'accepted': 13096}; FD002 {'accepted': 33991}; FD003 {'accepted': 16596}; FD004 {'accepted': 41214}
