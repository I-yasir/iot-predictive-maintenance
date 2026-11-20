# PdM-Live demo script (about 10 minutes)

A walk-through for showing the MVP to someone new. Everything runs on one machine with Docker.

## 0. Before the audience arrives (once, ~5 min)

```bash
cp .env.example .env          # then set every change-me value (passwords, INGEST_API_KEY, SESSION_SECRET)
make passwd                   # broker password file from .env
make up                       # broker, TimescaleDB, backend :8000, dashboard :8080
```

Open http://localhost:8080 and sign in with `DASHBOARD_PASSWORD`. An empty fleet shows "No assets yet".

## 1. The problem (1 min)

Turbofan engines degrade until they fail. Each engine streams 21 sensors once per flight cycle. The system predicts the
**remaining useful life (RUL)** in cycles, with an 80 % interval, and turns it into a health state:
Healthy (> 75), Warning (31–75), Critical (≤ 30). Models were trained on NASA C-MAPSS (4 fleets, FD001–FD004).

## 2. Live fleet from dataset replay, Mode 1 (3 min)

```bash
make replay                   # 10 FD001 test engines at 10 cycles/s, looping (Ctrl-C stops)
```

Or start it from the dashboard: **Test & Simulation → Dataset replay**, profile FD001, units `37, 41, 36, 56, 90, 66, 79, 38, 1, 85`, speed 10.

On **Overview**, point out:
- tiles appear in *Warming up*, then turn Healthy; RUL counts down live (no page refresh, WebSocket);
- engines 37, 41, 36, 56, 90 and 66 end close to failure, so they go Warning, then Critical, and raise alerts in the feed;
- KPIs, lowest-RUL list and filters (state, profile, source) update with them; acknowledge one alert.

## 3. One component in depth (3 min)

Click engine **FD001-T037**:
- **Summary**: RUL ± interval, health gauge, RUL trend with the true RUL dashed (known in replay), and the
  final-cycle error card once the engine ends;
- **Sensors**: each informative sensor against the engine's own healthy baseline band; anomalies marked;
- **Subsystems**: deviation score per station (Fan … LPT) and the top contributing sensors (indicative, not a
  root cause);
- **Alerts** and **Model** tabs; **Export report** (JSON) and **Open printable**.

## 4. A device on Wi-Fi, Mode 2 (2 min)

Without a board, the virtual ESP32 sends byte-identical payloads:

```bash
docker compose exec backend pdm-virtual-esp32 --asset FD001-V001 --rate 2 --count 120
```

`FD001-V001` appears with a **VIRTUAL_ESP32** badge. With a flashed board (`iot/esp32/README.md`) it shows as
**ESP32**. **Test & Simulation → Devices → Run harness check** grades the stream (schema, sequence, latency, order).

## 5. Robustness (1 min, optional)

- `docker compose stop db` → ingest answers 503 and the dashboard shows a banner; `docker compose start db` → it recovers by itself.
- `docker compose restart backend` mid-replay → no telemetry lost (the broker queues it for the backend's persistent session).

## 6. Numbers to quote

See `docs/mvp_signoff.md` for the PRD targets and the measured results (model accuracy, alert quality, latency,
throughput).
