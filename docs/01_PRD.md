# 01 — Product Requirements Document (PRD)

**Product:** PdM-Live — IoT real-time predictive maintenance system
**Status:** Phase 1 (Context Architecture) — approved docs gate all code
**Dataset of record:** NASA C-MAPSS Turbofan Engine Degradation Simulation (FD001–FD004), located in `data/raw/cmapss/` (moved from `Dataset/` on 2026-11-20)
**Last updated:** 2026-11-20

---

## 1. Problem Statement

Plant and fleet assets degrade gradually and fail expensively. Maintenance teams today rely on fixed-interval servicing (wasting healthy life) or run-to-failure (causing unplanned downtime). They need a live view that answers three questions per asset:

1. **Is it healthy right now?** (health state: Healthy / Warning / Critical)
2. **How long until it fails?** (Remaining Useful Life, RUL, in operating cycles, with an uncertainty band)
3. **Why does the model think so?** (which sensors/subsystems are drifting from their healthy baseline)

No physical machinery or live industrial sensors are available. The system must therefore be proven against a realistic, labelled run-to-failure dataset (C-MAPSS) and against synthetic telemetry from a real Wi-Fi microcontroller (ESP32), while staying sensor-agnostic so real equipment can be connected later by adding an adapter, not by rewriting the pipeline.

### 1.1 Domain grounding (from `Dataset/readme.txt` and `Damage Propagation Modeling.pdf`)

- Each time series is one **turbofan engine** in a fleet of identical engines. Engines start with unknown initial wear (normal, not a fault), then develop a fault that grows until failure.
- One row = one **operational cycle** (not wall-clock time). 3 operational settings + 21 sensor channels.
- Training trajectories run to failure; test trajectories stop before failure and true RUL is given separately (`RUL_FD00x.txt`).
- Four subsets of increasing difficulty: FD001 (1 condition, 1 fault mode — HPC), FD002 (6 conditions, HPC), FD003 (1 condition, 2 fault modes — HPC + Fan), FD004 (6 conditions, HPC + Fan).

In product terms an **engine unit = a monitored asset ("component")**, and the engine's gas-path modules (Fan, LPC, HPC, HPT, LPT, Burner) are its **subsystems** shown in the drill-down report.

## 2. Target Personas

| Persona | Goal | Primary view |
|---|---|---|
| **Plant Operations Engineer** (primary) | Monitor the whole fleet at a glance; spot the assets that need attention this shift | System Overview |
| **Maintenance Technician** | Understand one asset in depth before intervening; see which subsystem/sensors are abnormal | Component Detail Report |
| **Reliability Manager** | Plan maintenance windows from RUL forecasts; trust model accuracy; review alert history | Overview + Detail (RUL trend, alert log, model card) |
| **System Integrator / Test Engineer** (internal) | Prove the pipeline end-to-end with dataset replay and with ESP32 hardware | Test & Simulation Controls |

## 3. MVP User Stories

Acceptance criteria are testable; IDs are referenced by `06_Plan.md`.

### 3.1 System Overview
- **US-01** As an operations engineer, I see every active asset as a tile/row showing ID, health state color, predicted RUL (cycles) with uncertainty band, last-seen time and data-source badge (REPLAY / ESP32 / LIVE).
  *AC:* overview loads ≤ 2 s for 300 assets; tiles update within 2 s of a new prediction without page reload.
- **US-02** I see fleet KPIs: count of Healthy / Warning / Critical / Offline assets, and the 5 assets with the lowest RUL.
- **US-03** I can sort by RUL or state and filter by state, dataset profile (FD001–FD004) and data source.
- **US-04** I see a live alert feed (newest first) with state transitions (e.g., `FD001-U034 Healthy → Warning, RUL 72`), and I can acknowledge an alert.

### 3.2 Component Detail Report (drill-down)
- **US-05** As a technician, selecting an asset opens `/assets/{asset_id}` showing: current state, RUL ± interval, health-index gauge, and a RUL-over-cycles trend chart (predicted vs. ground truth when known, i.e., in replay mode).
- **US-06** I see per-sensor trend charts for the informative sensors (see `05_ML_and_Data_Spec.md` §3.4) with the asset's healthy baseline band (mean ± 3σ of its first cycles, regime-normalized).
- **US-07** I see a **subsystem diagnostic panel** grouping sensors by engine station (Fan, LPC, HPC, Burner, HPT, LPT) with a deviation score per subsystem and the top-3 contributing sensors to the current prediction.
- **US-08** I see the asset's alert history and the model version + confidence/drift flags for the latest prediction.
- **US-09** I can export the diagnostic report (JSON + printable page).

### 3.3 Two-Tier Test Modes
- **US-10 (Mode 1 — Dataset Replay)** As a test engineer, I pick a subset (FD001–FD004), split (train/test), unit(s) and speed (cycles/sec, 0.5–50) and start a replay that streams records through the **same ingestion endpoint** real devices use. I can pause, resume and stop it.
  *AC:* predictions, alert transitions and dashboard charts appear for replayed assets; for test-split units, final-cycle RUL error is shown against `RUL_FD00x.txt`.
- **US-11 (Mode 1 — Batch)** I can run a batch evaluation CLI over an entire test split and get RMSE, NASA score and alert confusion matrix as a report file, with no dashboard required.
- **US-12 (Mode 2 — ESP32 Synthetic Telemetry)** I flash the provided ESP32 sketch, set Wi-Fi + broker credentials, and the board streams synthetic payloads (perturbed replay of an embedded real trajectory, or sampled from dataset-derived distributions) over Wi-Fi via MQTT (HTTP fallback). The asset appears on the overview with an `ESP32` badge and its state evolves toward Warning/Critical as the synthetic degradation progresses.
- **US-13 (Mode 2 — Harness)** A host-side harness verifies the board's stream: payload schema validity, message rate, sequence gaps, end-to-end latency (device send → dashboard push), and injected fault cases (malformed JSON, missing field, out-of-range value, Wi-Fi drop). Result is a pass/fail report.
- **US-14 (No hardware fallback)** A Python "virtual ESP32" emits byte-identical payloads so Mode 2 logic is testable in CI without a board.

## 4. Success Metrics

### 4.1 ML metrics (evaluated on the official held-out test sets, last cycle per unit, true RUL from `RUL_FD00x.txt`)

| Subset | RMSE target (cycles) | NASA asymmetric score target | Stretch RMSE |
|---|---|---|---|
| FD001 | ≤ 16.0 | ≤ 500 | ≤ 13.0 |
| FD003 | ≤ 16.0 | ≤ 600 | ≤ 13.0 |
| FD002 | ≤ 22.0 | ≤ 3,000 | ≤ 18.0 |
| FD004 | ≤ 24.0 | ≤ 4,500 | ≤ 20.0 |

Must also beat the baseline (Ridge regression on last-cycle regime-normalized features) by ≥ 15 % RMSE on every subset.

- **Alert quality** (replay of test units, using the alert thresholds in `05_ML_and_Data_Spec.md` §7): Critical-state recall ≥ 0.90 for units with true RUL ≤ 30; false Critical rate ≤ 5 % for units with true RUL > 75.
- **Calibration:** ≥ 80 % of test units have true RUL inside the reported 80 % prediction interval (target band 75–90 %).
- **Late-prediction bias:** share of predictions over-estimating RUL by > 20 cycles ≤ 10 % (late = dangerous).

### 4.2 System metrics

| Metric | Target |
|---|---|
| Ingest → prediction latency (p95, single asset) | ≤ 250 ms |
| Ingest → dashboard update (p95) | ≤ 2 s |
| Sustained throughput (replay) | ≥ 500 msgs/s on a dev laptop |
| Payload validation | 100 % of malformed payloads rejected with a logged reason; 0 crashes |
| ESP32 stream | ≥ 99 % of messages received over 30 min at 1 msg/s on a healthy Wi-Fi link; auto-reconnect ≤ 10 s after AP returns |
| Offline detection | asset flagged Offline after 3 × its expected interval with no data |

## 5. Hardware & Testing Constraints (non-negotiable)

1. **No physical machinery or industrial sensors.** All telemetry comes from dataset replay or synthetic generation.
2. **Sensor-agnostic core.** Core pipeline consumes a canonical payload (`04_TRD.md` §5). Any source (replay, ESP32, future PLC/OPC-UA gateway) is an *adapter* that maps into it. Swapping in real sensors = new adapter + new feature profile; no changes to ingestion, inference, storage or UI.
3. **Ground truth is the dataset.** Feature schemas, units, value ranges and preprocessing derive from `Dataset/` and its PDF; any deviation is documented in `05_ML_and_Data_Spec.md`.
4. **Two-tier testing** (Mode 1 replay, Mode 2 ESP32) must both pass before MVP sign-off.
5. **ESP32 target:** a generic ESP32 DevKit (ESP32-WROOM-32, 2.4 GHz Wi-Fi). No external sensors are wired; values are synthetic.
6. **Time base is the operating cycle.** C-MAPSS has no timestamps; replay maps cycles to wall-clock at a configurable rate. Device timestamps are informational only.

## 6. Out of Scope (Non-Goals)

The MVP explicitly will **not**:

1. Connect to real industrial equipment, PLCs, SCADA, OPC-UA, Modbus or historians (adapter interface only).
2. Read physical sensors on the ESP32 (no ADC/I²C/SPI sensor drivers); the ESP32 sends synthetic data only.
3. Classify fault modes (HPC vs. Fan) as a supervised task — C-MAPSS provides no fault-mode labels. Subsystem panels show *deviation-based diagnostics*, labelled as indicative, not root-cause.
4. Prescribe maintenance actions, generate work orders, or integrate with CMMS/ERP (SAP PM, Maximo).
5. Perform online/continual model retraining in production. Retraining is an offline, manual pipeline run.
6. Support multi-tenant SaaS, SSO/OAuth, RBAC beyond a single shared API key + dashboard login.
7. Run at cloud scale (Kubernetes, Kafka, autoscaling). Target is a single host via Docker Compose.
8. Provide mobile native apps; the dashboard is responsive web only.
9. Do OTA firmware updates, device fleet provisioning, or TLS certificate management on ESP32 beyond optional MQTT username/password (TLS is a documented later step).
10. Use datasets other than C-MAPSS FD001–FD004 for training.
11. Guarantee aviation-grade or safety-certified predictions; this is a decision-support prototype.
12. Send notifications outside the dashboard (email, SMS, Slack, PagerDuty).

## 7. Assumptions & Open Questions

- **A1:** One "component" in the UI = one engine unit (`{subset}-U{unit:03d}`). If the user later wants plant-specific naming, it is a metadata change only.
- **A2:** One model per subset profile (FD001–FD004); each asset declares its `profile`. A unified cross-profile model is a post-MVP experiment.
- **A3:** Alert thresholds (Warning ≤ 75 cycles, Critical ≤ 30 cycles) are defaults, configurable per deployment. Owner confirmed the defaults on 2026-11-20.
- **Q1 (open):** Should production MQTT require TLS from day one? Default: no in dev, documented path for prod.
