# MVP sign-off (Phase 5, 2026-11-20)

Each PRD user story and success metric with its evidence. ✅ met · ⚠️ met with a gap noted · ❌ not met · ⏸ not yet verified.

## 1. User stories (PRD §3)

| Story | Status | Evidence |
|---|---|---|
| US-01 Fleet tiles (ID, state colour, RUL ± band, last seen, source badge), live without reload | ✅ | `routes/Overview.test.tsx`; `e2e/mode1_stream.spec.ts` records tile states changing live over the WebSocket. The "≤ 2 s for 300 assets" load time is not measured separately (P3.9 measured the backend at 300 assets) |
| US-02 KPIs and 5 lowest-RUL assets | ✅ | `Overview.test.tsx` |
| US-03 Sort and filter by state, profile, source | ✅ | `Overview.test.tsx` (filters are URL-synced) |
| US-04 Live alert feed with acknowledge | ✅ | `Overview.test.tsx`; `mode1_stream.spec.ts` finds the CRITICAL alert on the Alerts page |
| US-05 Detail: state, RUL ± interval, gauge, trend with ground truth in replay | ✅ | `AssetDetail.test.tsx`; `mode1_stream.spec.ts` checks "True RUL (replay)" and the final-cycle error card |
| US-06 Sensor trends with healthy baseline band | ✅ | `AssetDetail.test.tsx`, `GET /assets/{id}/sensors` (`backend/tests/test_api.py`) |
| US-07 Subsystem deviation scores and top-3 contributors | ✅ | `AssetDetail.test.tsx`; contributions are indicative (SHAP of the LightGBM half), not a root cause |
| US-08 Alert history, model version, confidence and drift flags | ✅ | `AssetDetail.test.tsx` |
| US-09 Export JSON and printable report | ✅ | `AssetDetail.test.tsx` |
| US-10 Replay: subset, split, units, speed 0.5–50, pause/resume/stop, same ingest path | ✅ | `TestPage.test.tsx`; `mode1_stream.spec.ts` drives it from `/test` at 20 cycles/s |
| US-11 Batch evaluation CLI with RMSE, NASA score, alert confusion matrix | ✅ | `make evaluate` (`ml/reports/test_FD00x.md`); served-path check `tests/e2e/mode1_batch.py` (P5.1) |
| US-12 ESP32 streams over Wi-Fi, shows with `ESP32` badge and degrades | ⏸ | Firmware builds with no warnings (P2.6). Hardware run P5.4 needs the board |
| US-13 Harness: schema, rate, gaps, latency, fault cases, pass/fail report | ✅ | `pdm-harness --virtual --backend …` all PASS against the full stack (`tests/e2e/reports/p53_mode2_virtual.md`); also in the dashboard (Test → Devices → Run harness check) |
| US-14 Virtual ESP32 with byte-identical payloads | ✅ | Identical to the C++ generator for 300 cycles (P2.7, `iot/tests`); now also falls back to HTTP like the firmware |

## 2. ML metrics (PRD §4.1, official test sets)

Bundles p5 (FD001/FD003) and p6 (FD002/FD004), `ml/reports/test_FD00x.md`. FD002/FD004 RMSE and score use truth capped at 125 (owner decision P1.11). These are also the live system's numbers: the backend's predictions match the offline ones to 0.00003 cycles on all 707 test engines (P5.1).

| Profile | RMSE (target) | NASA score (target) | Status |
|---|---|---|---|
| FD001 | 13.81 (≤ 16) | 268 (≤ 500) | ✅ |
| FD002 | 10.04 (≤ 22) | 430 (≤ 3,000) | ✅ |
| FD003 | 13.29 (≤ 16) | 333 (≤ 600) | ✅ |
| FD004 | 11.86 (≤ 24) | 756 (≤ 4,500) | ✅ |

All four beat the Ridge baseline by ≥ 15 % CV RMSE.

**P5.1 finding.** With the earlier bundles the live system matched the offline evaluation for FD001, FD002 and FD004 but not FD003 (served RMSE 14.31 vs 12.02 offline), because the training features leaked engine age through float rounding (`05` §5, Q18). The feature code was fixed, all models retrained with the unchanged procedure, and the owner approved one more, disclosed test-set look (the fifth) to score them (`05` §7.5.6).

## 3. Alert quality and calibration (PRD §4.1, served system)

Scored on the backend's own alert state and interval at each engine's last cycle (`tests/e2e/reports/p56_alert_quality.md`, p5/p6 bundles). Not used for tuning.

| Profile | Critical recall ≥ 0.90 | False Critical ≤ 5 % | Coverage ≥ 80 % (band 75–90 %) | Late > 20 ≤ 10 % |
|---|---|---|---|---|
| FD001 | 0.88 ❌ | 0 % ✅ | 0.91 ✅ (above band) | 5 % ✅ |
| FD002 | 1.00 ✅ | 0 % ✅ | 0.79 ⚠️ (in band) | 6 % ✅ |
| FD003 | 1.00 ✅ | 0 % ✅ | 0.93 ✅ (above band) | 6 % ✅ |
| FD004 | 1.00 ✅ | 0.7 % ✅ | 0.79 ⚠️ (in band) | 6 % ✅ |

Gaps: FD001 misses Critical on 3 of 25 engines (units 18, 40 and 53: true RUL 28, 28 and 26, predicted 31.6, 35.0 and 28.8), which end in WARNING. All three are within a few cycles of the threshold. FD002/FD004 intervals cover 79 %, just under 80 %. FD001/FD003 intervals are wider than needed. Thresholds were not tuned on these results, because they come from the test sets.

## 4. System metrics (PRD §4.2)

| Metric | Target | Result | Status |
|---|---|---|---|
| Ingest → prediction p95, steady load | ≤ 250 ms | 185 ms at 500 msg/s, 300 assets (`reports/perf_p39.md`) | ✅ |
| Throughput | ≥ 500 msg/s | 499.5 msg/s sustained 5 min | ✅ (at the target) |
| Backend memory, 300 assets | ≤ 1 GB | 732 MB | ✅ |
| Ingest → dashboard p95 | ≤ 2 s | Live updates verified (P5.2, P5.3: 57/57 WebSocket events), not timed end to end | ⏸ |
| ESP32 delivery ≥ 99 % over 30 min, reconnect ≤ 10 s | | needs the board (P5.4) | ⏸ |
| No data loss on backend restart / DB outage | | 203/203 and 196/196 cycles (P5.5) | ✅ |

## 5. Open items

1. P5.4 hardware run with the ESP32 board (US-12 and the ESP32 stream metric).
2. FD001 Critical recall 0.88 and FD002/FD004 coverage 0.79: closing them needs new validation work on training data (for example tuning the Critical confirmation count by CV), not the test sets.
3. CI pipeline (P5.8): all suites pass locally but nothing runs them automatically.
4. Ingest → dashboard latency is not timed end to end.
5. At replay speeds above ~5 cycles/s an engine's Critical phase can be shorter than a second, so it shows in the alert feed but barely on the tile. Use speed 10 or lower for demos.
