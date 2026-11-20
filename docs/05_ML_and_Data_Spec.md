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
4. **Truncated-validation sampling** (`pdm_ml/evaluate/cv.py`): test units are truncated before failure, so validation mimics that — for each validation unit, sample up to 5 truncation points among rows with ≥ min(31, life) observed cycles and true remaining life in **[10, 150]** (the challenge test range documented in the PDF; was [5, 200] in run 1), and score against the **uncapped** truth (so different caps are comparable). Early stopping uses an inner 15 % hold-out of fold-train engines, never the validation fold.
   ⚠️ The best cap depends on this range (Q17). FD002/FD004 test truths reach 195, beyond the documented range, and are better served by caps 140–160 (§7.5.3). Choosing the range per profile without looking at test labels is an open item.
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

### 7.5.2 Phase-1 pipeline results (`make train` + `make evaluate`, bundle `20261120-p1`)

Selection by grouped CV (4-point grid × caps {110, 125, 140, 160} × extra-sensor ablation for FD002/FD004). Cap 160 was added after 140 won at the grid edge in every profile (CV-only decision, before any test evaluation). P15/farB did not improve FD002/FD004 by ≥ 0.3 cycles and are not used.

| Profile | Selected config | CV RMSE Ridge / LGBM | Test RMSE | NASA score | Coverage (conformal) | Critical recall | False Critical | Target |
|---|---|---|---|---|---|---|---|---|
| FD001 | cap 140, leaves 15, min_child 50 | 26.2 / 20.6 | 16.2 | 411 | 0.94 | 0.92 | 0 % | ❌ RMSE ≤ 16 (score ✅) |
| FD002 | cap 140, leaves 31, min_child 20 | 27.3 / 22.9 | 22.8 | 3,962 | 0.80 | 0.97 | 0 % | ❌ RMSE ≤ 22, score ≤ 3,000 |
| FD003 | cap 160, leaves 15, min_child 20 | 27.7 / 20.6 | 17.9 | 1,085 | 0.86 | 0.90 | 0 % | ❌ RMSE ≤ 16, score ≤ 600 |
| FD004 | cap 160, leaves 31, min_child 50 | 30.9 / 24.6 | 22.6 | 4,395 | 0.82 | 0.81 | 0 % | ✅ RMSE ≤ 24, score ≤ 4,500 |

CV RMSE here is against uncapped truth up to 200 cycles, so it is not comparable with the capped-truth CV numbers in §7.5.1. LightGBM beats Ridge by 16–26 % in CV for every profile. Conformal widening brings interval coverage into 0.80–0.94, but intervals are wide (mean 91–107 cycles), so the `LOW_CONFIDENCE` width rule (> 60) would fire on most predictions; revisit in P5.6.
**Diagnosis:** the notebook (cap 125, uncapped CV not used) reached 12.6 RMSE on FD001/FD003. Higher caps help truths in 125–200, which barely exist in the FD001/FD003 test sets (max 145), and hurt the 76–125 bucket (FD001 20.8, FD003 26.3). Fix = truncation range per §6 item 4 warning. Re-evaluating after that fix is a second look at the test set and must be reported as such.

### 7.5.3 Run 2: corrected validation range (post-hoc, ACTIVE bundles `20261120-p2`)

**Disclosure:** run 1 (§7.5.2) was the single planned look at the official test set. After diagnosing the validation-range mismatch, the owner approved fixing it and re-evaluating. Run 2 numbers were produced **after the test set had been seen once**, so they are optimistic relative to a truly blind evaluation. Only one change was made between runs: `TRUNC_RUL_RANGE` (5, 200) → (10, 150), the range documented in the PDF. Grid, caps, sensors and code are otherwise identical. No per-profile cherry-picking between runs: run 2 bundles are active for **all** profiles, and run 1 stays archived in `ml/reports/run1_20261120-p1/` and `ml/artifacts/*/20261120-p1/`.

| Profile | Selected config | CV RMSE Ridge / LGBM | Test RMSE (run 1 → run 2) | NASA score (run 1 → 2) | Coverage | Critical recall | False Critical | PRD target |
|---|---|---|---|---|---|---|---|---|
| FD001 | cap 125, leaves 15, min_child 20 | 19.7 / 15.7 | 16.2 → **14.9** | 411 → 293 | 0.88 | 0.92 | 0 % | ✅ |
| FD002 | cap 125, leaves 15, min_child 50 | 20.1 / 17.7 | 22.8 → **24.8** | 3,962 → 5,433 | 0.72 | 0.98 | 0 % | ❌ (≤ 22; also beats Ridge by only 12 % < 15 %) |
| FD003 | cap 125, leaves 15, min_child 20 | 19.5 / 14.9 | 17.9 → **12.8** | 1,085 → 269 | 0.87 | 0.90 | 0 % | ✅ |
| FD004 | cap 125, leaves 31, min_child 50 | 21.6 / 18.3 | 22.6 → **26.1** | 4,395 → 4,513 | 0.71 | 0.87 | 0 % | ❌ (≤ 24) |

Mean interval width dropped from 91–107 to 70–75 cycles. FD002/FD004 errors are concentrated in true RUL > 125 (RMSE 47 / 44), the region a cap of 125 cannot reach. Next lever, decided on CV only: profile-specific validation range derived from *training* data (e.g. the distribution of remaining life at random truncation of training engines), or a sequence model (M2) for FD002/FD004 — the latter needs owner approval per PRD.

### 7.5.4 Run 3 — P1.10 (post-hoc, ACTIVE bundles `20261120-p3`)

**What changed (all decided on CV, `ml/reports/p110_experiment.json`):**
* CV now samples truncation points with remaining life in [5, 200] and reports two metrics: primary = [10, 150] (documented range, used for selection) and wide = [5, 200].
* Tried, CV-only: **horizon blend** (cap-125 model ramping into a cap-160/200 model when it saturates), EWM α = 0.1, and feature windows 50/70/100. The blend improved the wide metric but worsened the primary metric on every profile → **rejected** by the pre-set rule (primary may not worsen by > 0.2). Longer windows improved **both** metrics on every profile → feature window added to the selection grid {30, 50, 70, 100}. α = 0.1 did not help.
* Selected windows: FD001 50, FD002 100, FD003 70, FD004 70; cap 125 everywhere; extra sensors still rejected.

**Disclosure:** third look at the official test set (after runs 1 and 2). Treat these numbers as optimistic.

| Profile | Config | CV RMSE Ridge / LGBM | Test RMSE run 1 → 2 → **3** | NASA score (run 3) | Coverage | Width | Critical recall | PRD target |
|---|---|---|---|---|---|---|---|---|
| FD001 | W 50, leaves 31, min_child 20 | 20.3 / 14.3 | 16.2 → 14.9 → **14.2** | 284 | 0.93 | 82 | 0.92 | ✅ |
| FD002 | W 100, leaves 31, min_child 20 | 20.9 / 15.8 | 22.8 → 24.8 → **23.4** | 3,745 | 0.79 | 85 | 0.98 | ❌ RMSE ≤ 22, score ≤ 3,000 |
| FD003 | W 70, leaves 31, min_child 50 | 19.5 / 14.5 | 17.9 → 12.8 → **12.0** | 286 | 0.92 | 89 | 0.85 ⚠️ | ✅ (recall < 0.90) |
| FD004 | W 70, leaves 31, min_child 50 | 21.5 / 17.1 | 22.6 → 26.1 → **26.0** | 4,492 | 0.78 | 93 | 0.89 | ❌ RMSE ≤ 24 |

LightGBM beats Ridge by 20–29 % in CV everywhere. False Critical rate remains 0 % for all profiles. Online buffer must hold `window` cycles (up to 100), not 64 (docs/04 §8 updated).
**Residual gap (FD002/FD004):** error is dominated by engines with true RUL > 125 (RMSE ≈ 44), which any cap-125 model under-predicts, while alert-relevant buckets are fine (RUL ≤ 30: 3.4 / 7.3). Closing it without further test-set looks needs a different model class (M2 sequence model, owner approval per PRD) or revised PRD targets for multi-condition profiles. **No further tuning against the test set.**

### 7.5.5 P1.11 — M2 sequence model (owner approved 2026-11-20; CV only)

**Pre-registered before any M2 result was seen:**
* Candidates: M2 causal 1D-CNN on regime-normalised sensor histories (`pdm_ml/models/seq.py`; sequence length 50 or 100, cap 125 or 150) and the mean of LightGBM + M2.
* Scored on the identical GroupKFold folds, inner early-stopping split and truncation points as the LightGBM CV (`ml/pipelines/experiment_p111.py`).
* **Adoption rule:** the best candidate by primary CV RMSE [10, 150] replaces LightGBM for a profile only if it improves primary RMSE by ≥ 0.5 cycles **and** the wide [5, 200] RMSE does not worsen by more than 0.2. Otherwise LightGBM stays and no test look is taken.
* If adopted, exactly one further test evaluation (the fourth look), labelled post-hoc.

**Results (CV, `ml/reports/p111_experiment.json`; LightGBM reproduces its p3 CV exactly, so the points are identical):**

| Candidate | FD002 CV [10,150] / [5,200] | FD004 CV [10,150] / [5,200] |
|---|---|---|
| LightGBM p3 (active) | 15.82 / 22.11 | 17.11 / 26.82 |
| M2, L 50 | 17.73 / 23.88 | 17.46 / 27.22 |
| M2, L 100 | 15.43 / 22.24 | 15.96 / 26.03 |
| M2, L 50, cap 150 | 19.51 / 22.40 | 20.38 / 24.86 |
| **mean(LightGBM, M2 L 100)** | **14.76 / 21.61** | **15.84 / 26.04** |

Rule outcome: the LightGBM + M2 (L 100) mean is adopted for **both** profiles (−1.06 and −1.27 primary; wide improves too). Bundles `20261120-p4` (FD002, FD004) = p3 LightGBM point/quantile models + preprocessor + `seq_model.pt`; M2 refit on all training engines for the median CV epoch count (12 / 11). Split-conformal margin recomputed for the ensemble on CV out-of-fold points: coverage 0.57 → 0.80 (q = 13.0) and 0.56 → 0.81 (q = 18.0). SHAP contributions still come from the LightGBM half (diagnostics only). FD001/FD003 keep p3.

**Run 4 (post-hoc, fourth look at the FD002/FD004 test sets; treat as optimistic):**

| Profile | Test RMSE run 3 → **4** | NASA score 3 → 4 | Coverage | Critical recall | RMSE by true RUL ≤30 / 31–75 / 76–125 / >125 |
|---|---|---|---|---|---|
| FD002 | 23.37 → **23.00** ❌ (≤ 22) | 3,745 → 3,853 ❌ (≤ 3,000) | 0.79 | 0.98 → 1.00 | 2.9 / 10.9 / 13.5 / 44.8 |
| FD004 | 25.99 → **24.69** ❌ (≤ 24) | 4,492 → 3,761 ✅ | 0.78 | 0.89 → 0.91 | 5.7 / 13.7 / 15.1 / 42.7 |

Every bucket at or below 125 cycles improved; the > 125 bucket (57 of 259 and 67 of 248 test engines) did not, and it dominates the miss. On engines with true RUL ≤ 125 the RMSE is 10.5 (FD002) and 12.6 (FD004); with the literature convention of capping the truth at 125 it is 10.0 and 11.9. Engines that far from failure look healthy, so no capped model (LightGBM or M2) can tell 130 from 190 remaining cycles; raising the cap made CV worse (cap-150 rows above). Remaining gap = a target-definition question for the owner, not a modelling one. **No further tuning against the test set.**


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
| Q14 | Truncation points with unrestricted remaining life (up to 500) make CV RMSE meaningless (30–60 cycles) | CV restricts truncation to remaining life ≤ 200 and scores uncapped truth (§6 item 4) |
| Q15 | FD002/FD004 test sets contain many engines with true RUL > 125 (up to 194/195); the cap makes them the main error source | cap ablation in P1.6 picked 140 (FD002) / 160 (FD004) |
| Q16 | LightGBM rejects `monotone_constraints` with the quantile objective | constraint applied to the point model only |
| Q17 | Best cap depends on the remaining-life range validated on; FD001/FD003 test truths ≤ 145 vs FD002/FD004 ≤ 195 | see §7.5.2 |
