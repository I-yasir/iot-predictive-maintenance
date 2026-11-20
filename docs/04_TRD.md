# 04 — Technical Requirements Document (TRD)

Locked stack, repository layout, protocol contracts and security/config rules. Changing a pinned version or contract requires updating this file in the same change.

---

## 1. Architecture Summary

Single-host deployment via Docker Compose: **Mosquitto** (MQTT broker) + **PostgreSQL/TimescaleDB** (storage) + **backend** (FastAPI app hosting the MQTT subscriber, HTTP ingest, inference, alerting, REST + WebSocket) + **frontend** (static React build served by nginx). The ML training pipeline runs offline as a Python package (`ml/`) producing versioned artifact bundles that the backend loads read-only.

Design principles:
1. **Adapters at the edge, canonical schema in the core.** Every source maps to `TelemetryPayload v1` (§5). The core never knows whether data came from replay, ESP32 or a real sensor.
2. **One feature implementation.** Feature engineering lives in `ml/pdm_ml/features/` and is imported by both training and the backend inference service. No re-implementation in backend code (prevents train/serve skew).
3. **Profiles, not hard-coded sensors.** A *profile* (`FD001`…`FD004`, later `real-xyz`) declares its sensor set, units, ranges, regimes and model bundle in `config/profiles/{profile}.yaml`.
4. **Fail fast at startup, degrade gracefully at runtime.**

## 2. Locked Tech Stack

### 2.1 Runtimes & infrastructure
| Component | Version |
|---|---|
| Python | 3.12.x (3.12.10 in Docker `python:3.12.10-slim-bookworm`) |
| Node.js (frontend build) | 22.16.0 LTS |
| PostgreSQL + TimescaleDB | image `timescale/timescaledb:2.20.0-pg16` |
| MQTT broker | image `eclipse-mosquitto:2.0.21` |
| Web server (frontend) | image `nginx:1.27.5-alpine` |
| Docker Compose | v2 (compose file spec, no `version:` key) |
| Package manager (Python) | `uv` 0.7.x with `uv.lock`; pip-compatible `requirements*.txt` exported |

### 2.2 ML (`ml/`)
| Library | Version | Use |
|---|---|---|
| numpy | 2.2.6 | arrays |
| pandas | 2.3.3 | data wrangling |
| pyarrow | 20.0.0 | parquet interim files |
| scikit-learn | 1.6.1 | scaling, KMeans regimes, GroupKFold, Ridge baseline, metrics |
| lightgbm | 4.6.0 | primary RUL model (+ quantile models), `pred_contrib` explanations |
| scipy | 1.15.3 | stats (KS drift tests) |
| joblib | 1.5.1 | artifact serialization |
| PyYAML | 6.0.2 | configs |
| matplotlib | 3.10.3 | evaluation plots (offline only) |
| jupyterlab | 4.4.3 | data audit notebook (dev only) |

### 2.3 Backend (`backend/`)
| Library | Version |
|---|---|
| fastapi | 0.115.12 |
| uvicorn[standard] | 0.34.3 |
| pydantic | 2.11.5 |
| pydantic-settings | 2.9.1 |
| SQLAlchemy | 2.0.41 |
| alembic | 1.16.1 |
| psycopg[binary] | 3.2.9 |
| paho-mqtt | 2.1.0 |
| httpx | 0.28.1 (tests, simulator HTTP transport) |
| structlog | 25.4.0 |
| prometheus-client | 0.22.1 |

### 2.4 Frontend (`frontend/`)
| Library | Version |
|---|---|
| react / react-dom | 18.3.1 |
| typescript | 5.8.3 |
| vite | 6.3.5 |
| @vitejs/plugin-react | 4.5.2 |
| react-router-dom | 6.30.1 |
| @tanstack/react-query | 5.80.6 |
| recharts | 2.15.3 |
| zod | 3.24.2 (runtime validation of API/WS messages) |
| lucide-react | 0.511.0 (icons) |
| @fontsource/inter, @fontsource/jetbrains-mono | 5.2.6 (self-hosted fonts) |
| vitest | 3.2.3 |
| @testing-library/react | 16.3.0 |
| @playwright/test | 1.53.0 (E2E) |
| eslint | 9.28.0 + typescript-eslint 8.34.0 |

Styling: plain CSS modules + `tokens.css` (no Tailwind, no component library) to keep the design system explicit.

### 2.5 IoT (`iot/`)
| Item | Version |
|---|---|
| Board | ESP32 DevKit V1 (ESP32-WROOM-32) |
| Build system | PlatformIO Core 6.1.18, platform `espressif32@6.10.0`, framework `arduino` (arduino-esp32 core 2.0.17) |
| Arduino IDE alternative | Arduino IDE 2.3.6 + "esp32 by Espressif" 2.0.17 (sketch kept IDE-compatible) |
| MQTT client lib | `knolleary/PubSubClient@2.8` (buffer raised to 1024 B — default 256 B is too small for the payload) |
| JSON lib | `bblanchon/ArduinoJson@7.4.1` |
| Host simulator/harness | Python 3.12 + paho-mqtt 2.1.0 + httpx 0.28.1 + pyserial 3.5 |

### 2.6 Quality tooling
pytest 8.4.0, pytest-asyncio 1.0.0, pytest-cov 6.1.1, hypothesis 6.135.0 (payload fuzzing), ruff 0.11.13 (lint + format), mypy 1.16.0 (strict on `backend/` and `ml/pdm_ml/`), pre-commit 4.2.0.

## 3. Repository Structure

```
.
├── CLAUDE.md
├── README.md
├── docs/                          # 01–06 context architecture (source of truth)
├── data/
│   ├── raw/cmapss/                # ORIGINAL files moved from Dataset/ (read-only, never modified)
│   │   ├── train_FD00{1-4}.txt, test_FD00{1-4}.txt, RUL_FD00{1-4}.txt
│   │   ├── readme.txt, Damage Propagation Modeling.pdf, CMAPSSData.zip
│   ├── interim/                   # parquet with named columns + RUL labels (generated, gitignored)
│   ├── processed/                 # feature tables per profile/split (generated, gitignored)
│   └── reference/                 # small committed artifacts: data_audit.json, sensor_catalog.yaml
├── config/
│   ├── profiles/FD001.yaml … FD004.yaml   # sensors, units, ranges, regimes, model bundle path
│   ├── alerts.yaml                         # thresholds, hysteresis
│   └── mosquitto/mosquitto.conf, passwd.example
├── ml/
│   ├── pyproject.toml
│   ├── pdm_ml/
│   │   ├── io/          # loaders for raw C-MAPSS → named DataFrame
│   │   ├── audit/       # data audit checks → data/reference/data_audit.json
│   │   ├── labels/      # RUL labelling, piecewise cap
│   │   ├── features/    # regimes, normalization, windowing (SHARED with backend)
│   │   ├── models/      # baseline, lgbm point + quantile, registry/bundle writer
│   │   ├── evaluate/    # RMSE, NASA score, calibration, alert confusion, plots
│   │   ├── diagnostics/ # baselines, z-scores, subsystem scores, contributions
│   │   └── drift/       # reference stats, OOD checks
│   ├── pipelines/       # CLI entrypoints: audit.py, build_features.py, train.py, evaluate.py, export_esp32_profile.py
│   ├── notebooks/01_data_audit_and_baseline.ipynb   # documented EDA + audit + baseline (exploratory, not production)
│   ├── artifacts/{profile}/{model_version}/   # bundle, committed (~0.7 MB each, MANIFEST-verified)
│   └── tests/
├── iot/
│   ├── contracts/telemetry_v1.schema.json     # JSON Schema (generated from Pydantic, committed)
│   ├── simulator/        # replay.py (Mode 1), virtual_esp32.py (Mode 2b), transports (mqtt/http)
│   ├── esp32/
│   │   ├── platformio.ini
│   │   ├── src/main.cpp            # state machine, Wi-Fi/MQTT/HTTP, payload builder
│   │   ├── include/config.example.h # Wi-Fi/broker creds template (config.h gitignored)
│   │   ├── include/profile_fd001.h  # GENERATED by ml/pipelines/export_esp32_profile.py
│   │   └── README.md               # flashing & wiring-free setup
│   ├── harness/          # mode2_harness.py: schema/rate/gap/latency/fault-injection checks + report
│   └── tests/
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py            # FastAPI app factory, lifespan (load models, start MQTT)
│   │   ├── settings.py        # pydantic-settings
│   │   ├── schemas/           # TelemetryPayload v1, API DTOs, WS events
│   │   ├── ingest/            # mqtt_subscriber.py, http_router.py, validator.py, dead_letter.py
│   │   ├── inference/         # model_registry.py, buffer.py, service.py (imports pdm_ml.features)
│   │   ├── alerts/            # state_machine.py, engine.py
│   │   ├── api/               # assets, telemetry, predictions, alerts, diagnostics, sim, devices, stats, models
│   │   ├── ws/                # hub.py (WebSocket broadcast)
│   │   ├── sim/               # in-process replay controller (wraps iot.simulator)
│   │   ├── db/                # models.py, session.py, migrations/ (alembic)
│   │   └── observability/     # logging, /metrics
│   └── tests/
├── frontend/
│   ├── package.json, vite.config.ts, tsconfig.json
│   ├── src/
│   │   ├── styles/tokens.css
│   │   ├── api/ (client, zod schemas, ws)
│   │   ├── components/ (charts, tiles, chips, selector, states)
│   │   ├── routes/ (Overview, AssetDetail, AssetReport, Test, Alerts, ModelCard, NotFound)
│   │   └── hooks/
│   └── tests/ (vitest) , e2e/ (playwright)
├── tests/e2e/                 # cross-service Mode 1 / Mode 2 scenarios
├── docker-compose.yml
├── .env.example
└── Makefile                   # make audit | train | evaluate | up | replay | harness | test
```

## 4. Services, Ports & Config

| Service | Port | Notes |
|---|---|---|
| mosquitto | 1883 (MQTT), 9001 (WS, disabled by default) | password file required; anonymous disabled |
| db | 5432 | volume `pgdata` |
| backend | 8000 | `/api/v1/*`, `/ws/v1/stream`, `/metrics`, `/healthz`, `/readyz` |
| frontend | 8080 | nginx proxies `/api` and `/ws` to backend |

All config via environment (`.env`, never committed): `DATABASE_URL`, `MQTT_HOST`, `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_TOPIC_PREFIX=pdm/v1`, `INGEST_API_KEY`, `DASHBOARD_PASSWORD`, `MODEL_ROOT=ml/artifacts`, `ACTIVE_PROFILES=FD001,FD002,FD003,FD004`, `ALERTS_CONFIG=config/alerts.yaml`, `DATA_RAW_DIR=data/raw/cmapss`, `CORS_ORIGINS`, `LOG_LEVEL`.

## 5. IoT Protocol & Payload Contract

### 5.1 Transports
- **Primary — MQTT 3.1.1**, QoS 1, `retain=false`, keepalive 30 s, clean session true.
  - Telemetry: `pdm/v1/{site_id}/{asset_id}/telemetry`
  - Device status (LWT + online msg): `pdm/v1/{site_id}/{asset_id}/status` payload `{"online":true|false,"fw":"...","ip":"...","rssi":-60}` retained
  - Ack (optional, backend → device/harness): `pdm/v1/{site_id}/{asset_id}/ack`
  - `site_id` and `asset_id` charset `[A-Za-z0-9_-]{1,48}`; topic ids must equal payload ids or the message is rejected (`topic_mismatch`).
- **Fallback — HTTP** `POST /api/v1/ingest` (single) and `POST /api/v1/ingest/batch` (≤ 500 records), header `X-API-Key`, `Content-Type: application/json`.
- **Dashboard push — WebSocket** `GET /ws/v1/stream?assets=*|id1,id2` (auth via session cookie).

### 5.2 `TelemetryPayload` v1 (canonical)

```json
{
  "schema_version": "1.0",
  "msg_id": "esp32-a1b2c3-000123",
  "site_id": "lab",
  "asset_id": "FD001-E001",
  "profile": "FD001",
  "source": "ESP32",
  "seq": 123,
  "cycle": 123,
  "ts": "2026-11-20T02:45:00.123Z",
  "settings": { "setting_1": -0.0007, "setting_2": -0.0004, "setting_3": 100.0 },
  "sensors": {
    "T2": 518.67, "T24": 641.82, "T30": 1589.70, "T50": 1400.60,
    "P2": 14.62, "P15": 21.61, "P30": 554.36, "Nf": 2388.06, "Nc": 9046.19,
    "epr": 1.30, "Ps30": 47.47, "phi": 521.66, "NRf": 2388.02, "NRc": 8138.62,
    "BPR": 8.4195, "farB": 0.03, "htBleed": 392, "Nf_dmd": 2388, "PCNfR_dmd": 100.00,
    "W31": 39.06, "W32": 23.4190
  },
  "meta": { "fw": "esp32-pdm/0.1.0", "rssi": -58, "mode": "trajectory", "eol": false, "true_rul": null }
}
```

| Field | Type | Rules |
|---|---|---|
| `schema_version` | string | must be `"1.0"`; unknown major → reject `unsupported_version` |
| `msg_id` | string ≤ 64 | unique per device; used for idempotency together with `(asset_id, cycle)` |
| `site_id`, `asset_id` | string | charset above |
| `profile` | enum | one of `ACTIVE_PROFILES` |
| `source` | enum | `REPLAY`, `ESP32`, `VIRTUAL_ESP32`, `LIVE` |
| `seq` | int ≥ 0 | monotonically increasing per device boot; gaps counted, not rejected |
| `cycle` | int ≥ 1 | operating cycle index — the model's time axis |
| `ts` | RFC 3339 UTC, optional | device time; if absent server time used |
| `settings` | object | `setting_1..3` floats, all required (operating condition) |
| `sensors` | object | keys = sensor symbols from the profile; all **required** sensors of the profile must be present; extra keys allowed and stored but ignored by the model; values finite floats (NaN/Inf → reject) and inside profile hard range (`05` §3.3) |
| `meta` | object, optional | free-form ≤ 1 KB; `true_rul` only honoured from `REPLAY` source |

Max payload size 4 KB. Sensor keys use C-MAPSS symbols (Table 2 of the PDF) — not `s1..s21` — so a real sensor adapter maps physical tags to meaningful names. Mapping `s{n}` ↔ symbol lives in `data/reference/sensor_catalog.yaml` (`05` §3.2).

### 5.3 Responses
- `200 {"status":"accepted","asset_id","cycle","prediction_id"}`
- `200 {"status":"duplicate"}`
- `401` bad/missing key · `413` too large · `422 {"status":"rejected","reason":"range:T30","detail":"..."}` · `503` storage unavailable.

### 5.4 Core REST API (all under `/api/v1`)
`GET /assets` · `GET /assets/{id}` · `GET /assets/{id}/telemetry?from_cycle&to_cycle&sensors=` · `GET /assets/{id}/predictions?limit` · `GET /assets/{id}/diagnostics` · `GET /assets/{id}/report` · `POST /assets/{id}/ground-truth` · `GET /alerts?state&asset&ack&limit` · `POST /alerts/{id}/ack` · `GET /models` · `POST /sim/replay/start|pause|resume|stop` · `GET /sim/replay/status` · `GET /devices` · `POST /devices/{id}/harness-check` · `GET /stats` · `POST /ingest` · `POST /ingest/batch`. OpenAPI generated at `/docs` (dev only).

### 5.5 WebSocket events
`{"type":"prediction","data":{asset_id,cycle,rul_pred,rul_p10,rul_p90,health_index,state,flags,ts}}`, `{"type":"alert","data":{...}}`, `{"type":"asset_status","data":{asset_id,state,last_seen}}`, `{"type":"sim_status","data":{...}}`, `{"type":"heartbeat","ts":...}` every 15 s.

## 6. Model Artifact Bundle

`ml/artifacts/{profile}/{model_version}/` where `model_version = {YYYYMMDD}-{git_short_sha}`:
`model_point.txt` (LightGBM), `model_q10.txt`, `model_q90.txt`, `preprocessor.joblib` (regime KMeans + per-regime scalers + feature list), `baselines.joblib` (diagnostic healthy baselines), `drift_reference.json`, `model_card.json` (metrics, data hashes, feature list, training config, library versions), `MANIFEST.sha256`. Backend verifies the manifest at startup and refuses unknown/mismatched bundles. `ml/artifacts/{profile}/CURRENT` holds the active version string.

## 7. Security & Configuration Constraints

1. **No secrets in git.** `.env`, `iot/esp32/include/config.h`, `config/mosquitto/passwd` gitignored; `*.example` templates committed. Pre-commit runs a secret scan (`detect-secrets` 1.5.0).
2. MQTT anonymous access disabled; per-device username/password; ACL restricts each device to `pdm/v1/{site}/{its asset_id}/#`. Backend user can subscribe to `pdm/v1/#`.
3. HTTP ingest requires `X-API-Key` (≥ 32 random chars), compared in constant time.
4. Dashboard protected by a single shared password → HTTP-only, `SameSite=Strict` session cookie (MVP). CORS restricted to `CORS_ORIGINS`.
5. Input hardening: max payload 4 KB, Pydantic strict types, finite-float checks, topic/payload ID match, rate limit 50 msg/s per asset (excess → 429 / dropped with metric).
6. Model bundles loaded only from `MODEL_ROOT` with manifest hash check; joblib files never loaded from user input.
7. TLS: dev runs plain MQTT/HTTP on a trusted LAN. Production path (documented, not MVP): Mosquitto TLS on 8883, nginx TLS; ESP32 uses `WiFiClientSecure` with pinned CA.
8. Logs are structured JSON; never log full API keys or passwords; payloads logged only at DEBUG.
9. Raw data in `data/raw/` is read-only; pipelines write only to `data/interim`, `data/processed`, `data/reference`, `ml/artifacts`.

## 8. Non-Functional Requirements
- p95 ingest→prediction ≤ 250 ms; ≥ 500 msg/s replay throughput; dashboard update ≤ 2 s.
- Backend memory ≤ 1 GB with 300 active assets (rolling buffers bounded to the profile's feature window, ≤ 100 cycles/asset).
- Test coverage ≥ 80 % lines for `ml/pdm_ml` and `backend/app`.
- Reproducibility: fixed seeds (`SEED=42`), data file SHA-256 recorded in `model_card.json`.

## 9. Dataset Quirks Affecting Engineering (keep in sync with `05`)
- Raw files are whitespace-separated with **trailing spaces** → parse with `sep=r"\s+"`, `header=None`; expect exactly 26 columns.
- `readme.txt` says columns go up to "sensor measurement 26" but there are **21 sensors** (26 columns = unit + cycle + 3 settings + 21 sensors).
- `readme.txt` FD004 counts are **swapped**: actual train = 249 units, test = 248 units (`RUL_FD004.txt` has 248 rows).
- Readme contains non-UTF-8 bytes (Windows-1252 quotes) → read with `encoding="cp1252"` if parsed.
- Model bundles are small (~0.7 MB per profile) so they are committed; the backend can start without retraining.
- `make test` takes ~2 min (loads all four subsets); run it alone, CPU contention with training slows both.
- The owner's laptop currently has system Python 3.10 (pandas 2.3.3, numpy 2.2.6). Use `uv` to install Python 3.12 for the project venv; do not rely on system Python.
- Data was delivered in `Dataset/`; moved to `data/raw/cmapss/` on 2026-11-20 (SHA-256 in `data/reference/raw_checksums.txt`, verified identical to the files inside `CMAPSSData.zip`).
