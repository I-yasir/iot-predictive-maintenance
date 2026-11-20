# PdM-Live — IoT Real-Time Predictive Maintenance

Predicts the Remaining Useful Life (RUL) of monitored assets from streamed sensor telemetry and shows a live fleet overview with per-component diagnostic reports. Built and tested on the NASA C-MAPSS turbofan dataset (in `data/raw/cmapss/`), with two test modes: dataset replay and an ESP32 streaming synthetic telemetry over Wi-Fi.

**Status:** Phase 1 ML pipeline done: data audit, causal features, grouped CV, LightGBM RUL models with conformal intervals, and versioned bundles in `ml/artifacts/`. Results are in `ml/reports/` and `docs/05_ML_and_Data_Spec.md` §7.5.4 (official test RMSE: FD001 14.2, FD002 23.4, FD003 12.0, FD004 26.0). Next up is Phase 2 (IoT ingestion contract, replay simulator, ESP32).

```bash
make venv && source .venv/bin/activate
make audit      # data audit + profile configs
make train      # CV model selection + bundles (~6 min on 4 cores)
make evaluate   # official test evaluation
make test       # 21 tests
```

| Start here | What it is |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Working rules for contributors and agents |
| [`docs/01_PRD.md`](docs/01_PRD.md) | Problem, personas, user stories, metrics, non-goals |
| [`docs/02_AppFlow.md`](docs/02_AppFlow.md) | Data flow, state machines, routes, UI states |
| [`docs/03_UI_Spec.md`](docs/03_UI_Spec.md) | Design tokens and dashboard views |
| [`docs/04_TRD.md`](docs/04_TRD.md) | Locked stack, repo layout, MQTT/HTTP payload contract, security |
| [`docs/05_ML_and_Data_Spec.md`](docs/05_ML_and_Data_Spec.md) | Dataset findings, features, validation, models, storage, drift |
| [`docs/06_Plan.md`](docs/06_Plan.md) | Implementation checklist |
| [`ml/notebooks/01_data_audit_and_baseline.ipynb`](ml/notebooks/01_data_audit_and_baseline.ipynb) | Documented data audit, EDA and baseline model |

## Dataset

The data is A. Saxena, K. Goebel, D. Simon and N. Eklund, "Damage Propagation Modeling for Aircraft Engine Run-to-Failure Simulation", PHM08. It comes from the NASA Prognostics Center of Excellence Data Repository. The original files are kept unchanged in `data/raw/cmapss/`, with checksums in `data/reference/raw_checksums.txt`.
