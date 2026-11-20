# CLAUDE.md — PdM-Live (IoT Real-Time Predictive Maintenance)

Instructions for any agent working in this repository. Read this file fully before every task.

## 1. Mandatory reading before ANY task

1. The dataset description files:
   - `data/raw/cmapss/readme.txt`
   - `data/raw/cmapss/Damage Propagation Modeling.pdf` — at minimum Table 2 (sensor names/units) and the scoring function
   - `data/reference/data_audit.json` and `data/reference/sensor_catalog.yaml` once they exist
   - `ml/notebooks/01_data_audit_and_baseline.ipynb` — the documented walkthrough of the data and baseline results
2. All six architecture documents, in order:
   - `docs/01_PRD.md` — problem, personas, user stories, metrics, **non-goals**
   - `docs/02_AppFlow.md` — data flow, state machines, routes, UI/error states
   - `docs/03_UI_Spec.md` — design tokens and view specs
   - `docs/04_TRD.md` — locked stack/versions, repo layout, payload contract, security
   - `docs/05_ML_and_Data_Spec.md` — dataset findings, features, splits, models, storage, drift
   - `docs/06_Plan.md` — the implementation checklist (find the next unchecked step)

Do not start coding until you have identified the exact `06_Plan.md` step ID(s) your task belongs to.

## 2. Ground rules

- **The dataset is the source of truth.** Schemas, units, ranges and preprocessing come from the C-MAPSS files and their documentation, not from assumptions. The readme has known errors (21 sensors not 26; FD004 counts swapped) — trust the files and `05` §11.
- **Never modify `data/raw/`.** Generated data goes to `data/interim/`, `data/processed/`, `data/reference/`; models to `ml/artifacts/`.
- **No data leakage.** Split by engine unit (GroupKFold); fit every scaler/cluster/baseline on training-fold units only; never tune on the official `test_FD00x`/`RUL_FD00x` files (`05` §6).
- **One feature implementation.** Backend inference must import `ml/pdm_ml/features`; never re-implement features elsewhere.
- **Sensor-agnostic core.** Sources are adapters that emit `TelemetryPayload v1` (`04` §5). Do not add source-specific logic to ingestion, inference, storage or UI.
- **Respect the locked stack.** Use the exact versions in `04_TRD.md` §2. Adding/upgrading a dependency requires updating `04` in the same change with a reason.
- **Respect non-goals** (`01` §6). If a task drifts into one, stop and ask.
- **No secrets in git** (`04` §7). Use `.env` / `config.h` from the `*.example` templates.
- Small, test-backed changes; run `ruff`, `mypy` and the relevant tests before declaring a step done.

## 3. Keep the docs alive

- If dataset inspection, training or testing reveals a schema quirk, edge case, range, metric or threshold that differs from the docs, **update `docs/05_ML_and_Data_Spec.md` (and `docs/04_TRD.md` if it affects contracts, config, stack or engineering)** in the same change. Add the quirk to `05` §11 and, if relevant, `04` §9.
- If a flow, route or UI state changes, update `02_AppFlow.md` / `03_UI_Spec.md` likewise.
- Docs and code must never disagree at the end of a task.

## 4. Update `docs/06_Plan.md` after every completed step

After finishing each step:
1. Change `[ ]` to `[x]`, append the date (YYYY-MM-DD) and a one-line note (result, metric, key file, or deviation).
2. Mark partially done work `[~]` and blocked work `[!]` with the reason.
3. If you discovered missing work, add a new step with the next free ID in the right phase (don't renumber existing IDs).
4. Reference step IDs in commit messages, e.g. `P1.5: causal window features + streaming parity test`.

## 5. Useful commands (available once scaffolded)

```
make audit       # P1.4 — regenerate data_audit.json and profile configs
make train       # P1.6–P1.9 — CV, final fit, bundles
make evaluate    # official test evaluation / Mode 1 batch
make up          # docker compose: mosquitto + db (backend/frontend join in Phase 3/4)
make replay-demo # Mode 1: FD001 test unit 34 (or: pdm-replay --profile FD001 --split test --units 10 --speed 20)
make harness     # Mode 2 harness against virtual ESP32 (or real board)
make test        # ML tests; make test-iot for contracts + IoT (broker tests need make up)
make esp32-build # PlatformIO build of iot/esp32 (flashing: iot/esp32/README.md)
make backend     # Phase 3 API + MQTT subscriber on :8000 (make migrate, make test-backend, make lint-backend)
make perf        # P3.9 load test (500 msg/s, 300 assets, 5 min) -> reports/perf_p39.md
make frontend-install  # P4 dashboard deps (npm ci), then make frontend-dev (:5173) or make frontend-build + frontend-preview (:8080)
make test-frontend     # eslint + tsc + vitest component tests
make e2e               # Playwright at 375/768/1280/1920 px, dark + light, axe (needs backend, preview and a replay running)
```
