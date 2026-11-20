# 02 — Application Flow & State Machines

Defines every data path and UI state. Contracts referenced here are specified in `04_TRD.md` (payloads, APIs) and `05_ML_and_Data_Spec.md` (features, thresholds).

---

## 1. End-to-End Data Flow

```
 ┌──────────────────────── SOURCES (adapters) ─────────────────────────┐
 │ Mode 1: Replay Simulator (iot/simulator)  — reads data/raw/cmapss    │
 │ Mode 2: ESP32 firmware (iot/esp32)        — synthetic over Wi-Fi     │
 │ Mode 2b: Virtual ESP32 (iot/simulator)    — same bytes, no hardware  │
 │ Future: Real-sensor gateway adapter       — maps to canonical schema │
 └───────────────┬──────────────────────────────┬──────────────────────┘
                 │ MQTT pdm/v1/{site}/{asset}/telemetry (QoS 1)
                 │ or HTTP POST /api/v1/ingest (fallback)
                 ▼
        ┌──────────────────┐   invalid   ┌───────────────────┐
        │ Ingestion Gateway │──────────▶ │ Dead-letter table  │
        │ (backend/ingest)  │            │ + reject counter   │
        └────────┬─────────┘            └───────────────────┘
                 │ validated TelemetryRecord (canonical)
                 ▼
        ┌──────────────────┐
        │ Telemetry Store   │  telemetry table (asset_id, cycle)
        └────────┬─────────┘
                 ▼
        ┌──────────────────┐  per-asset rolling buffer (last W=30 cycles)
        │ Feature Service   │  regime assignment → normalization → window features
        └────────┬─────────┘
                 ▼
        ┌──────────────────┐  model registry: profile → artifact bundle
        │ Inference Service │  RUL point + P10/P90, health index, contributions
        └────────┬─────────┘
                 ▼
        ┌──────────────────┐  state machine (§3) + drift/confidence rules
        │ Alert Engine      │
        └────────┬─────────┘
                 ▼
        ┌──────────────────┐  predictions, alerts tables
        │ Prediction Store  │
        └────────┬─────────┘
                 ▼
        ┌──────────────────┐  WebSocket /ws/v1/stream  +  REST /api/v1/*
        │ API / Push Hub    │
        └────────┬─────────┘
                 ▼
            Dashboard (frontend)
```

Processing is **synchronous per message** inside the backend process (no external queue in MVP): validate → persist → features → infer → alert → persist → broadcast. Target p95 ≤ 250 ms.

## 2. Ingestion & Inference Sequence (per message)

1. **Receive** on MQTT subscriber (`pdm/v1/+/+/telemetry`) or HTTP.
2. **Authenticate**: MQTT broker credentials, or `X-API-Key` header for HTTP. Fail → HTTP 401 / broker reject.
3. **Validate** against `TelemetryPayload` (Pydantic): schema version, required fields, types, physical range checks (`05` §3.3). Fail → dead-letter with `reason`, HTTP 422, counter `ingest_rejected_total{reason}`.
4. **Dedupe/order**: key `(asset_id, cycle)`. Duplicate → ignore (idempotent, return 200 `duplicate`). `cycle < last_cycle` → store, flag `out_of_order`, do not re-infer past cycles. Gap (`cycle > last_cycle+1`) → store, flag `gap`, continue.
5. **Auto-register** asset on first message (status `NEW`), using `profile` and `source` from the payload.
6. **Persist** raw telemetry.
7. **Feature build**: append to rolling buffer; if buffer length < `MIN_CYCLES` (=5) → prediction status `WARMING_UP` (no RUL shown).
8. **Infer**: load model for `profile`; output `rul_pred`, `rul_p10`, `rul_p90`, `health_index`, `top_contributors`, `subsystem_scores`.
9. **Confidence & drift checks** (`05` §8) → flags `LOW_CONFIDENCE`, `OOD`, `DRIFT`.
10. **Alert engine** → new state; on transition emit `alert` event.
11. **Persist** prediction + alert; **broadcast** `prediction` (and `alert`) on WebSocket.
12. **Ack**: HTTP 200 body `{status, asset_id, cycle, prediction_id}`; MQTT: optional ack on `pdm/v1/{site}/{asset}/ack` (used by the Mode 2 harness to measure latency).

## 3. Asset Health State Machine

States: `NEW`, `WARMING_UP`, `HEALTHY`, `WARNING`, `CRITICAL`, `OFFLINE`, `DEGRADED_DATA`.

```
NEW ──first msg──▶ WARMING_UP ──buffer ≥ MIN_CYCLES──▶ (classify by RUL)

classify: rul_pred > 75 → HEALTHY ; 30 < rul_pred ≤ 75 → WARNING ; rul_pred ≤ 30 → CRITICAL

HEALTHY ⇄ WARNING ⇄ CRITICAL    (with hysteresis, below)
any ──no data for 3× expected interval──▶ OFFLINE ──next valid msg──▶ previous state
any ──≥ 3 consecutive rejected/OOD msgs──▶ DEGRADED_DATA ──3 consecutive valid──▶ classify
replay reset / unit restarts at cycle 1 ──▶ WARMING_UP (new life, history archived)
```

**Hysteresis / debounce (avoid flapping on noisy predictions):**
- Escalate (towards CRITICAL) when the condition holds for **2 consecutive** predictions.
- De-escalate only when the condition holds for **5 consecutive** predictions AND `rul_pred` exceeds the threshold by ≥ 5 cycles.
- A single prediction with `rul_p10 ≤ 15` escalates directly to CRITICAL (safety override).

**Alert events** are created on every state transition except `NEW→WARMING_UP`. Alert record: `id, asset_id, from_state, to_state, cycle, rul_pred, created_at, acknowledged_at, acknowledged_by`. Severity = target state.

## 4. Replay Simulator State Machine (Mode 1)

```
IDLE ──start(cfg)──▶ RUNNING ──pause──▶ PAUSED ──resume──▶ RUNNING
RUNNING ──all units exhausted──▶ COMPLETED ──▶ IDLE
RUNNING/PAUSED ──stop──▶ STOPPED ──▶ IDLE
RUNNING ──ingest unreachable 3× (backoff 1s,2s,4s)──▶ ERROR ──retry/stop──▶ RUNNING/IDLE
```

`cfg = {profile, split: train|test, units: [ids]|"all"|N random, speed_cps, transport: mqtt|http, loop: bool, asset_prefix}`.
Replay sends rows in cycle order; multiple units interleave round-robin per tick. Asset ID = `{profile}-{split[0].upper()}{unit:03d}` (e.g., `FD001-T034`). For test-split units the simulator also posts ground-truth RUL metadata (`true_rul_at_end`) to `/api/v1/assets/{id}/ground-truth` so the detail view can plot true vs. predicted RUL.

Controlled from the dashboard (Test page) via `/api/v1/sim/*` or from CLI (`python -m iot.simulator.replay ...`).

## 5. ESP32 Firmware State Machine (Mode 2)

```
BOOT → LOAD_CONFIG → WIFI_CONNECTING ─ok─▶ NTP_SYNC (optional, 5 s timeout) → BROKER_CONNECTING ─ok─▶ STREAMING
WIFI_CONNECTING ─fail─▶ backoff (1,2,4,8, max 30 s) ─▶ WIFI_CONNECTING
BROKER_CONNECTING ─fail ×5─▶ HTTP_FALLBACK (POST /api/v1/ingest) ; retry MQTT every 60 s
STREAMING ─wifi lost─▶ BUFFERING (ring buffer 64 msgs) ─reconnect─▶ FLUSH → STREAMING
STREAMING ─trajectory end─▶ END_OF_LIFE (send final msg with "eol":true) → loop? RESTART(cycle=1) : IDLE
```

The on-board LED encodes state (solid = streaming, slow blink = Wi-Fi connecting, fast blink = broker connecting, double blink = buffering). Serial log at 115200 baud prints every state change and every 10th message.

## 6. Dashboard Navigation & Routes

| Route | View | Data |
|---|---|---|
| `/` → redirect `/overview` | — | — |
| `/overview` | System Overview: KPIs, asset grid/table, lowest-RUL list, alert feed | `GET /api/v1/assets`, `GET /api/v1/alerts?limit=50`, WS |
| `/assets/:assetId` | Component Detail Report (tabs: Summary, Sensors, Subsystems, Alerts, Model) | `GET /api/v1/assets/{id}`, `/telemetry`, `/predictions`, `/diagnostics`, WS filtered |
| `/assets/:assetId/report` | Printable diagnostic report | `GET /api/v1/assets/{id}/report` |
| `/test` | Test & Simulation Controls: Replay panel, ESP32 device panel, batch eval results, ingest stats | `/api/v1/sim/*`, `/api/v1/devices`, `/api/v1/stats` |
| `/alerts` | Full alert log with filters, acknowledge | `GET /api/v1/alerts` |
| `/about/model` | Model card: versions, metrics, feature list | `GET /api/v1/models` |
| `*` | 404 page with link to overview | — |

Query params persist UI state: `/overview?state=CRITICAL&profile=FD001&source=ESP32&sort=rul`; `/assets/X?tab=sensors&range=last100`.

### 6.1 Key interactions
- Click asset tile/row → `/assets/:id`. Keyboard: arrow keys move focus in grid, Enter opens.
- Component selector (top of detail view): searchable combobox of all assets, sorted by RUL ascending; switching keeps the current tab.
- Alert feed item click → asset detail at the alert's cycle (chart cursor placed at that cycle).
- Acknowledge alert → `POST /api/v1/alerts/{id}/ack` (optimistic update, rollback on error).
- Replay panel: Start / Pause / Resume / Stop; speed slider; unit picker; live counters (sent, accepted, rejected, rate).
- ESP32 panel: lists devices seen (`source=ESP32`), last message, RSSI, firmware version, msg rate, sequence-gap count, latency p50/p95; "Run harness checks" button triggers server-side checks for the selected device window.

## 7. UI States (every data view implements all of these)

| State | Trigger | Behavior |
|---|---|---|
| **Loading** | initial fetch pending | skeleton placeholders matching final layout; no spinners longer than 300 ms without skeleton |
| **Empty — no assets** | `assets.length == 0` | illustration + "No telemetry yet" + buttons "Start dataset replay" (→ `/test`) and "Connect an ESP32" (setup steps) |
| **Empty — filter** | filters exclude all | "No assets match these filters" + Clear filters |
| **Warming up** | asset has < 5 cycles | tile shows grey "Warming up (n/5)"; detail shows sensors but RUL area says "Collecting baseline" |
| **Live / connected** | WS open | header indicator green "Live" |
| **Reconnecting** | WS closed | header amber "Reconnecting…"; exponential backoff 1→30 s; data stays visible, marked stale after 10 s; on reconnect refetch REST snapshot then resume WS |
| **Disconnected (backend down)** | REST 5xx/timeouts ×3 | full-width red banner "Backend unreachable — showing last known data from HH:MM:SS"; actions disabled |
| **Asset offline** | state OFFLINE | tile desaturated, "Offline · last seen 2m ago"; RUL shown greyed with "stale" label |
| **Degraded data** | state DEGRADED_DATA | amber hatched border + "Data quality issue" with latest rejection reason |
| **Low confidence / OOD / Drift** | prediction flags | info icon + tooltip text from `05` §8; RUL shown with wider band, never hidden |
| **Not found** | `GET /assets/{id}` 404 | "Asset not found" + selector to choose another |
| **Error (view)** | unexpected exception | error boundary card with Retry; error logged to console + `/api/v1/client-errors` (optional) |

## 8. Error Handling Matrix (backend)

| Failure | Detection | Response |
|---|---|---|
| Malformed JSON | parse error | 422 / dead-letter `parse_error` |
| Schema violation / missing field | Pydantic | 422 / dead-letter `schema:<field>` |
| Out-of-range value | range check | 422 / dead-letter `range:<field>`; ≥3 in a row → DEGRADED_DATA |
| Unknown profile | registry lookup | 422 `unknown_profile` |
| Model artifact missing/corrupt | startup check | backend refuses to start (fail fast) with clear log |
| Inference exception | try/except | telemetry kept, prediction status `ERROR`, asset keeps last state, metric incremented |
| DB unavailable | connection error | HTTP 503; MQTT messages are not acked (QoS 1 redelivery) |
| Broker down | paho on_disconnect | reconnect with backoff; HTTP ingest remains available |
| Clock skew on device | `ts` vs server time > 5 min | accept, flag `clock_skew`; server time used for latency stats |
