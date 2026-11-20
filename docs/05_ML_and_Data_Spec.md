# 05 — ML & Data Specification

All facts in §1–§3 were measured directly from the files now in `data/raw/cmapss/` (originally `Dataset/`) on 2026-11-20 (pandas 2.3.3, numpy 2.2.6) and from `Dataset/readme.txt` + `Dataset/Damage Propagation Modeling.pdf` (Saxena et al., PHM08). Re-run `make audit` after any data change; it regenerates `data/reference/data_audit.json` and must agree with this document.

---

## 1. Dataset Inventory

**Source:** NASA C-MAPSS (Commercial Modular Aero-Propulsion System Simulation) turbofan run-to-failure data, PHM08.

| File | Rows | Units | Notes |
|---|---|---|---|
| `train_FD001.txt` | 20,631 | 100 | run to failure |
| `test_FD001.txt` | 13,096 | 100 | truncated before failure |
| `RUL_FD001.txt` | 100 | — | true RUL after last test cycle, one per test unit in unit order |
| `train_FD002.txt` | 53,759 | 260 | |
| `test_FD002.txt` | 33,991 | 259 | |
| `RUL_FD002.txt` | 259 | — | |
| `train_FD003.txt` | 24,720 | 100 | |
| `test_FD003.txt` | 16,596 | 100 | |
| `RUL_FD003.txt` | 100 | — | |
| `train_FD004.txt` | 61,249 | **249** | readme says 248 |
| `test_FD004.txt` | 41,214 | **248** | readme says 249 |
| `RUL_FD004.txt` | 248 | — | matches actual test units |
| `CMAPSSData.zip` | — | — | original archive (2008), same 14 files; use as checksum reference |
| `Damage Propagation Modeling.pdf` | — | — | sensor names/units (Table 2), noise model, scoring function |

| Subset | Op. conditions | Fault modes | Train life (cycles) min / median / max | Test length min / median / max | Test true RUL min / median / max |
|---|---|---|---|---|---|
| FD001 | 1 (sea level) | 1 — HPC degradation | 128 / 199 / 362 | 31 / 133.5 / 303 | 7 / 86 / 145 |
| FD002 | 6 | 1 — HPC | 128 / 199 / 378 | 21 / 132 / 367 | 6 / 80 / 194 |
| FD003 | 1 | 2 — HPC + Fan | 145 / 220.5 / 525 | 38 / 148 / 475 | 6 / 77.5 / 145 |
| FD004 | 6 | 2 — HPC + Fan | 128 / 234 / 543 | 19 / 153.5 / 486 | 6 / 88 / 195 |

Integrity checks (all passed): 26 columns in every file; no missing values; every unit's cycles are contiguous and start at 1; RUL file length = number of test units.

## 2. Domain Semantics (from readme + PDF)

- Each series = one engine of the same type; unknown initial wear and manufacturing variation (normal, not a fault). Initial health index starts between 0.99 and 1.0.
- The engine is normal at the start and develops a fault at an unknown point; in training data it grows until failure (health index reaches 0, i.e., an operability margin — HPC/LPC/fan stall margin 15 %, EGT margin ~2 % — is exhausted).
- Three operational settings substantially affect sensor values (they define flight condition: altitude, Mach number, throttle resolver angle — interpretation per PDF; the files only say "operational setting 1–3").
- Data contains multi-stage noise: process noise (mixture distributions) + measurement noise on all channels → smoothing/windowing is required.
- One row = one operational cycle (one flight). There is no wall-clock time.
- Official objective: predict remaining cycles after the last observed test cycle.
- Official asymmetric score (PDF eq. 11), d = predicted RUL − true RUL:
  `s = Σ_i ( e^(−d_i/13) − 1 )  if d_i < 0 ;  ( e^(d_i/10) − 1 ) if d_i ≥ 0` — late predictions (over-estimates) are penalized more.

## 3. Schema

### 3.1 Column schema (raw files, 0-based column index)

| Idx | Raw name | Canonical name | Type |
|---|---|---|---|
| 0 | unit | `unit` | int |
| 1 | time (cycles) | `cycle` | int |
| 2–4 | operational setting 1–3 | `setting_1`, `setting_2`, `setting_3` | float |
| 5–25 | sensor measurement 1–21 | see §3.2 | float |

### 3.2 Sensor catalog (`data/reference/sensor_catalog.yaml`)

Names/units from PDF Table 2 (°R = degrees Rankine, psia = pounds per square inch absolute, pps = pounds per second). Subsystem = gas-path station grouping used for UI diagnostics (approximate, derived from the description; not a fault label).

| Raw | Symbol (payload key) | Description | Unit | Subsystem | FD001 mean ± std (train) | Trend toward failure (FD001) |
|---|---|---|---|---|---|---|
| s1 | T2 | Total temperature at fan inlet | °R | Fan | 518.67 ± 0 | constant |
| s2 | T24 | Total temperature at LPC outlet | °R | LPC | 642.68 ± 0.50 | ↑ |
| s3 | T30 | Total temperature at HPC outlet | °R | HPC | 1590.52 ± 6.13 | ↑ |
| s4 | T50 | Total temperature at LPT outlet | °R | LPT | 1408.93 ± 9.00 | ↑ |
| s5 | P2 | Pressure at fan inlet | psia | Fan | 14.62 ± 0 | constant |
| s6 | P15 | Total pressure in bypass duct | psia | Fan | 21.61 ± 0.0014 | quantized (2 values) |
| s7 | P30 | Total pressure at HPC outlet | psia | HPC | 553.37 ± 0.89 | ↓ |
| s8 | Nf | Physical fan speed | rpm | Fan | 2388.10 ± 0.07 | ↑ |
| s9 | Nc | Physical core speed | rpm | HPC | 9065.24 ± 22.08 | ↑ |
| s10 | epr | Engine pressure ratio (P50/P2) | — | Engine | 1.30 ± 0 | constant (FD001) |
| s11 | Ps30 | Static pressure at HPC outlet | psia | HPC | 47.54 ± 0.27 | ↑ |
| s12 | phi | Ratio of fuel flow to Ps30 | pps/psi | Burner | 521.41 ± 0.74 | ↓ |
| s13 | NRf | Corrected fan speed | rpm | Fan | 2388.10 ± 0.07 | ↑ |
| s14 | NRc | Corrected core speed | rpm | HPC | 8143.75 ± 19.08 | ↑ |
| s15 | BPR | Bypass ratio | — | Fan | 8.4421 ± 0.0375 | ↑ |
| s16 | farB | Burner fuel-air ratio | — | Burner | 0.03 ± 0 | constant |
| s17 | htBleed | Bleed enthalpy | — | HPT | 393.21 ± 1.55 | ↑ (integer-valued) |
| s18 | Nf_dmd | Demanded fan speed | rpm | Fan | 2388 ± 0 | constant (control setpoint) |
| s19 | PCNfR_dmd | Demanded corrected fan speed | rpm | Fan | 100 ± 0 | constant (control setpoint) |
| s20 | W31 | HPT coolant bleed | lbm/s | HPT | 38.82 ± 0.18 | ↓ |
| s21 | W32 | LPT coolant bleed | lbm/s | LPT | 23.2897 ± 0.1083 | ↓ |

Settings in FD001/FD003: setting_1 ∈ [−0.0087, 0.0087], setting_2 ∈ [−0.0006, 0.0007], setting_3 = 100 (single condition; the small variation is noise). FD002/FD004: six discrete operating regimes (rounded `setting_1, setting_2, setting_3`): (42, 0.84, 100) ≈ 25 % of rows, and (0, 0, 100), (10, 0.25, 100), (20, 0.7, 100), (25, 0.62, 60), (35, 0.84, 100) ≈ 15 % each.

### 3.3 Validation ranges (ingestion hard limits)

Per profile, per sensor: `hard_min = train_min − 5·σ_regime`, `hard_max = train_max + 5·σ_regime`, computed in P1.3 and stored in `config/profiles/{profile}.yaml`. Values outside → reject `range:<sensor>`. Values outside `[train_min, train_max]` but inside hard limits → accepted and flagged `OOD` (§8). Measured: a handful of test values already fall slightly outside train range (FD001: T24 2, T30 3, Nf 1, Ps30 2, phi 3, W32 2; FD004: P15 9) — confirming soft OOD flags must not reject.

### 3.4 Informative sensor sets (findings)

Correlation of regime-normalized sensors with capped RUL (cap 125) on train data:

| Sensor | FD001 | FD002 | FD003 | FD004 |
|---|---|---|---|---|
| T24 s2 | −0.68 | −0.63 | −0.68 | −0.58 |
| T30 s3 | −0.65 | −0.62 | −0.70 | −0.65 |
| T50 s4 | −0.76 | −0.74 | −0.77 | −0.72 |
| P30 s7 | +0.73 | +0.51 | **−0.36** | **−0.34** |
| Nf s8 | −0.62 | −0.48 | −0.63 | −0.57 |
| Nc s9 | −0.46 | −0.42 | −0.64 | −0.62 |
| Ps30 s11 | −0.77 | −0.77 | −0.80 | −0.76 |
| phi s12 | +0.75 | +0.53 | **−0.37** | **−0.36** |
| NRf s13 | −0.62 | −0.48 | −0.63 | −0.57 |
| NRc s14 | −0.37 | −0.32 | −0.56 | −0.55 |
| BPR s15 | −0.72 | −0.72 | **≈0.00** | **0.02** |
| htBleed s17 | −0.68 | −0.65 | −0.73 | −0.67 |
| W31 s20 | +0.70 | +0.48 | **0.05** | **0.02** |
| W32 s21 | +0.71 | +0.48 | **0.04** | **0.03** |
| P15 s6 | −0.11 | −0.36 | −0.10 | −0.12 |
| epr s10 | const | 0.04 | −0.49 | −0.36 |
| farB s16 | const | (2 values, regime-tied) | const | (2 values) |

**Key finding:** in FD003/FD004 (two fault modes) P30, phi, BPR, W31, W32 lose or flip their global correlation because HPC and Fan degradation move them in opposite directions. They are **still informative per unit** (direction identifies the fault mode) — do **not** drop sensors by global correlation in multi-fault profiles.

**Locked model input sensors:**
- Base set (all profiles, 14): T24, T30, T50, P30, Nf, Nc, Ps30, phi, NRf, NRc, BPR, htBleed, W31, W32.
- Added for FD003/FD004: epr (s10).
- Always excluded as model inputs (constant or control setpoints): T2, P2, Nf_dmd, PCNfR_dmd; farB; P15 (quantized). They are still ingested, stored and shown greyed in the UI.
- P15 and farB in FD002/FD004 are candidates for an ablation in P1.6; include only if they improve validation RMSE by ≥ 0.3 cycles.

Required payload sensors per profile = model input set (others optional).

## 4. Labels

- Train RUL per row: `RUL = max_cycle(unit) − cycle` (last row = 0).
- **Piecewise-linear target cap**: `RUL_target = min(RUL, 125)` — degradation is not observable early in life (health index starts 0.99–1.0); cap 125 is the standard choice and is validated in P1.6 against {110, 125, 140}.
- Test RUL per row (for replay plots): `RUL(row) = RUL_file[unit] + (last_cycle(unit) − cycle)`.
- Official evaluation uses only the **last cycle** of each test unit against `RUL_FD00x.txt` (uncapped truth; predictions are naturally ≤ cap — documented as known bias for true RUL > 125).

## 5. Feature Engineering & Preprocessing Pipeline

Implemented once in `ml/pdm_ml/features/` and used verbatim by training and online inference. All steps are causal (use only current and past cycles of the same unit).

1. **Load & name** columns (§3.1, §3.2). Parse `sep=r"\s+"`, `header=None`, assert 26 columns.
2. **Operating-regime assignment**
   - FD001/FD003: single regime `0`.
   - FD002/FD004: `KMeans(n_clusters=6, n_init=10, random_state=42)` on standardized `setting_1..3`, fit on **training units only**. Online: nearest centroid; distance > 6σ of training cluster distances → flag `OOD:regime`.
3. **Regime-wise normalization**: for each regime, z-score each input sensor with mean/std from **training-fold units only** (`StandardScaler` per regime). Std = 0 → sensor dropped for that profile (logged).
4. **Denoising**: exponentially weighted mean per unit, `alpha = 0.3` (causal), on normalized sensors.
5. **Window features** over the last `W = 30` cycles (or all available if fewer, minimum 5):
   - for each sensor: last EWM value, window mean, window std, linear-regression slope over the window, (last − first-5-cycles mean) "delta from own baseline".
   - unit-level: `cycle` (current cycle index), `window_len`.
   - regime one-hot (FD002/FD004) is **not** used after normalization (regime effect already removed); regime id is kept only for drift checks.
6. **Feature vector** size ≈ 14 sensors × 5 + 2 = 72 (FD003/4: 77). Feature list and order saved in `preprocessor.joblib`; inference asserts identical order.
7. **Prediction gating**: < 5 cycles → `WARMING_UP`, no prediction.

Online buffer per asset holds the last 64 raw cycles + EWM state + first-5-cycles baseline, so per-message cost is O(W).

## 6. Train / Validation / Test Strategy (leakage prevention)

1. **Official test sets (`test_FD00x` + `RUL_FD00x`) are untouched until final evaluation** (P1.8). No tuning on them.
2. **Split by engine unit, never by row.** Validation = `GroupKFold(n_splits=5, groups=unit)` on training units. Rows from one engine never appear in both fit and validation folds (prevents trajectory leakage).
3. **All fitted preprocessors** (regime KMeans, scalers, drift reference, diagnostic baselines) are fit inside each fold on fold-train units only (sklearn-style pipeline per fold).
4. **Truncated-validation sampling:** test units are truncated before failure, so validation scoring mimics that — for each validation unit, sample 5 random truncation points uniformly in `[min(31, life), life]` and score the prediction at the truncation point against true remaining cycles. Also report all-row RMSE for reference.
5. Training rows: all rows with `cycle ≥ 5` (warm-up gating).
6. Hyperparameter search: Optuna is **not** used; a fixed small grid (§7.2) evaluated by 5-fold grouped CV mean truncated-RMSE.
7. Final model per profile refit on all training units with the chosen config; evaluated once on the official test set; results written to `model_card.json` and must meet `01_PRD.md` §4.1.
8. Replay Mode 1 for demos uses **test-split** units by default (unseen by the model). Replaying train units is allowed but the UI labels them "seen in training".

## 7. Models & Evaluation

### 7.1 Model ladder
| ID | Model | Purpose |
|---|---|---|
| M0 | Ridge regression (alpha via CV) on last-cycle features | baseline; must be beaten by ≥ 15 % RMSE |
| **M1 (primary)** | LightGBM regressor (objective `l2`) on window features | point RUL |
| M1-q | LightGBM `objective="quantile"`, alpha 0.1 and 0.9, same features | P10/P90 interval |
| M2 (post-MVP, optional) | 1D-CNN / LSTM on raw windows | only if M1 misses targets |

One model set per profile (FD001–FD004).

### 7.2 M1 grid
`num_leaves ∈ {15, 31}`, `learning_rate ∈ {0.03, 0.05}`, `n_estimators` up to 2000 with early stopping 100 on fold validation, `min_child_samples ∈ {20, 50}`, `feature_fraction 0.8`, `bagging_fraction 0.8`, `bagging_freq 1`, `lambda_l2 1.0`, `seed 42`. Monotone constraint on `cycle` feature: −1.

### 7.3 Post-processing
`rul_pred = clip(pred, 0, cap)`; enforce `p10 ≤ pred ≤ p90` by sorting; interval may be widened by a conformal factor `q` computed on CV residuals so that 80 % empirical coverage holds (split-conformal on out-of-fold predictions).

### 7.4 Health index (UI gauge)
`health_index = clip(rul_pred / cap, 0, 1)` — a display transformation, documented as such (not the simulator's true health index, which is not in the data).

### 7.5 Metrics (reported per profile)
- RMSE (last-cycle official test) — primary.
- NASA asymmetric score (§2).
- MAE, bias (mean d), share of late predictions > 20 cycles.
- Interval coverage (P10–P90) and mean width.
- Alert confusion matrix: true state from true RUL using the same thresholds vs. predicted state.
- Plots: predicted vs. true scatter, error by true-RUL bucket, example RUL trajectories for 6 units.

### 7.5.1 Baseline results (notebook run, 2026-11-20)

From `ml/notebooks/01_data_audit_and_baseline.ipynb`: fixed LightGBM config (num_leaves 31, lr 0.05, iterations = CV mean of early-stopping), cap 125, W = 30, no grid search, no conformal widening.

| Profile | CV RMSE Ridge / LGBM (capped truth) | Test RMSE LGBM | Test RMSE Ridge | NASA score | P10–P90 coverage | Critical recall | Meets PRD target |
|---|---|---|---|---|---|---|---|
| FD001 | 17.2 / 10.5 | **12.6** | 17.2 | 207 | 0.69 | 0.96 | yes |
| FD002 | 17.5 / 12.2 | 24.1 | 27.9 | 6,616 | 0.66 | 0.97 | no (target 22) |
| FD003 | 16.3 / 10.4 | **12.6** | 16.8 | 276 | 0.56 | 0.90 | yes |
| FD004 | 18.0 / 13.7 | 24.9 | 29.3 | 4,050 | 0.57 | 0.89 | no (target 24) |

Test RMSE by true-RUL bucket (≤30 / 31–75 / 76–125 / >125): FD001 3.8 / 7.9 / 14.5 / 20.7 · FD002 3.2 / 12.6 / 13.9 / 46.7 · FD003 3.0 / 7.6 / 15.9 / 18.2 · FD004 6.0 / 14.6 / 15.2 / 43.0. No healthy engine was predicted Critical in any profile. Takeaways: (1) FD002/FD004 misses come from the >125 bucket (cap effect, Q15); (2) raw quantile intervals under-cover (0.56–0.69 vs. 0.80 target) — split-conformal widening (§7.3) is required.

### 7.6 Diagnostics (component detail report)
- **Per-sensor deviation**: z-score of current EWM value vs. the asset's own healthy baseline (first 20 cycles, regime-normalized; fallback to fleet training baseline when < 20 cycles).
- **Subsystem score** (0–100): `min(100, 100 × mean(|z| of the subsystem's input sensors) / 6)`.
- **Top contributors**: LightGBM `pred_contrib=True` SHAP values aggregated per sensor (sum over its 5 features), reported as % of total |contribution| with direction relative to baseline.
- Labelled "indicative" — no fault-mode ground truth exists (PRD non-goal 3).

## 8. Confidence, OOD & Drift Rules

| Flag | Rule | Effect |
|---|---|---|
| `LOW_CONFIDENCE` | `(p90 − p10) > 60` cycles, or `window_len < 15` | UI info icon; alert escalation still allowed |
| `OOD` | any input sensor outside `[train_min, train_max]` of the profile, or regime distance > 6σ | flag + count; if ≥ 3 consecutive → `DEGRADED_DATA` state |
| `DRIFT` | per asset, rolling 50-cycle window of regime-normalized sensors: KS statistic vs. training reference distribution of *healthy-phase* rows (RUL ≥ 125) > 0.3 for ≥ 3 sensors **while** `rul_pred ≥ 100` (degradation explains drift otherwise) | flag `DRIFT`, metric `drift_assets` |
| Fleet drift | > 20 % of active assets flagged `DRIFT` in 1 hour | banner on `/about/model` recommending retrain |
| Prediction jump | `|rul_pred(t) − rul_pred(t−1)| > 25` cycles | logged, debounced by hysteresis (`02` §3) |

Thresholds live in `config/alerts.yaml`; values above are defaults to be confirmed in P5 against replay results.

### 8.1 Alert thresholds (defaults)
Healthy `> 75`, Warning `(30, 75]`, Critical `≤ 30` cycles of predicted RUL; safety override Critical if `p10 ≤ 15`. Hysteresis in `02_AppFlow.md` §3.

## 9. Inference & Storage Schema (PostgreSQL 16 + TimescaleDB)

```sql
-- component / asset metadata
CREATE TABLE assets (
  asset_id      TEXT PRIMARY KEY,
  site_id       TEXT NOT NULL,
  profile       TEXT NOT NULL,             -- FD001..FD004
  source        TEXT NOT NULL,             -- REPLAY|ESP32|VIRTUAL_ESP32|LIVE
  display_name  TEXT,
  life_id       INT  NOT NULL DEFAULT 1,   -- increments when a unit restarts at cycle 1
  state         TEXT NOT NULL DEFAULT 'NEW',
  last_cycle    INT,
  last_seen_at  TIMESTAMPTZ,
  expected_interval_s REAL DEFAULT 1.0,
  true_rul_at_end INT,                     -- replay test units only
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  meta          JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE devices (
  device_id TEXT PRIMARY KEY, asset_id TEXT REFERENCES assets, fw TEXT, ip TEXT,
  rssi INT, online BOOLEAN, last_status_at TIMESTAMPTZ
);

-- time-series telemetry (hypertable on received_at)
CREATE TABLE telemetry (
  asset_id    TEXT NOT NULL REFERENCES assets,
  life_id     INT  NOT NULL,
  cycle       INT  NOT NULL,
  received_at TIMESTAMPTZ NOT NULL,
  device_ts   TIMESTAMPTZ,
  msg_id      TEXT,
  seq         INT,
  settings    JSONB NOT NULL,              -- setting_1..3
  sensors     JSONB NOT NULL,              -- symbol -> value (all received keys)
  regime      SMALLINT,
  flags       TEXT[] NOT NULL DEFAULT '{}', -- gap, out_of_order, OOD, clock_skew
  PRIMARY KEY (asset_id, life_id, cycle, received_at)
);
SELECT create_hypertable('telemetry', 'received_at');
CREATE UNIQUE INDEX ON telemetry (asset_id, life_id, cycle, received_at);

-- prediction log (hypertable)
CREATE TABLE predictions (
  prediction_id BIGSERIAL,
  asset_id      TEXT NOT NULL REFERENCES assets,
  life_id       INT  NOT NULL,
  cycle         INT  NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  model_version TEXT NOT NULL,
  status        TEXT NOT NULL,             -- OK|WARMING_UP|ERROR
  rul_pred REAL, rul_p10 REAL, rul_p90 REAL, health_index REAL,
  state         TEXT NOT NULL,
  flags         TEXT[] NOT NULL DEFAULT '{}',
  contributors  JSONB,                     -- [{sensor, pct, direction}]
  subsystem_scores JSONB,                  -- {Fan: 12.3, HPC: 71.0, ...}
  latency_ms    REAL,
  PRIMARY KEY (prediction_id, created_at)
);
SELECT create_hypertable('predictions', 'created_at');
CREATE INDEX ON predictions (asset_id, life_id, cycle DESC);

CREATE TABLE alerts (
  alert_id BIGSERIAL PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES assets, life_id INT NOT NULL,
  cycle INT NOT NULL, from_state TEXT NOT NULL, to_state TEXT NOT NULL, rul_pred REAL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), acknowledged_at TIMESTAMPTZ, acknowledged_by TEXT
);

CREATE TABLE dead_letter (
  id BIGSERIAL PRIMARY KEY, received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  transport TEXT, topic TEXT, reason TEXT NOT NULL, raw BYTEA  -- truncated to 4 KB
);

CREATE TABLE model_registry (
  profile TEXT, model_version TEXT, active BOOLEAN, metrics JSONB, created_at TIMESTAMPTZ,
  PRIMARY KEY (profile, model_version)
);
```

Retention (TimescaleDB policies): telemetry 30 days, predictions 90 days, alerts/dead_letter indefinite in MVP.

## 10. ESP32 Synthetic Profile Export (Mode 2)

`ml/pipelines/export_esp32_profile.py --profile FD001 --unit-from test --unit 34` generates `iot/esp32/include/profile_fd001.h` containing:
- `TRAJECTORY` mode: one real test-unit trajectory (default unit chosen with median life), 14–15 input sensors + 3 settings as `float` arrays in flash (`PROGMEM`; ~200 cycles × 18 × 4 B ≈ 14 KB). Firmware adds Gaussian noise `σ = 0.25 × sensor measurement-noise σ` (estimated from detrended healthy-phase residuals) so each run differs.
- `DISTRIBUTION` mode: per sensor healthy mean `μ0`, noise σ, and a degradation curve fitted on training units: `x(c) = μ0 + k · exp(c / τ)` style per-sensor coefficients over normalized life; firmware samples a life length from the training life distribution (log-normal fit) and generates values cycle by cycle. Constant sensors sent at their constant values.
- Profile header has a version + data SHA so the backend can tag `meta.mode` and the harness can verify the expected RUL trajectory.

## 11. Known Quirks & Edge Cases (keep updated)

| # | Quirk | Handling |
|---|---|---|
| Q1 | Trailing whitespace in raw rows | `sep=r"\s+"` |
| Q2 | Readme says 26 sensors; actually 21 | schema = 26 columns total |
| Q3 | Readme FD004 train/test counts swapped (actual 249/248) | trust files; audit asserts actual counts |
| Q4 | Readme has cp1252 bytes | read with `encoding="cp1252"` |
| Q5 | Constant sensors per profile (s1, s5, s10, s16, s18, s19 in FD001/FD003 except s10 varies in FD003) | excluded from model; std=0 guard in scaler |
| Q6 | P15 (s6) quantized to 2 values in FD001 | excluded (ablation in FD002/4) |
| Q7 | Settings jitter in single-condition subsets (±0.009) | single regime; never cluster FD001/FD003 |
| Q8 | Some test values outside train range | soft `OOD` flag, not reject |
| Q9 | Shortest test unit has 19 cycles (FD004), 21 (FD002) | min 5 cycles, partial windows supported |
| Q10 | True RUL > cap (up to 195 in FD004) | known bias; report error by RUL bucket |
| Q11 | Multi-fault sensors flip correlation sign (FD003/4) | keep sensors; tree model handles interaction |
| Q12 | No timestamps; cycle is the time axis | replay maps cycles→seconds via `speed_cps` |
| Q13 | Data delivered in `Dataset/`, not `data/` | moved to `data/raw/cmapss/` on 2026-11-20 (done) |
| Q14 | Truncated-validation RMSE against *uncapped* truth is dominated by early truncation points (true RUL up to 500) and is meaningless (30–60 cycles) | CV scores use the capped truth; official test uses uncapped truth as specified |
| Q15 | FD002/FD004 test sets contain many engines with true RUL > 125 (up to 194/195); the cap makes them the main error source | cap ablation {110,125,140} in P1.6 is mandatory for these profiles |
