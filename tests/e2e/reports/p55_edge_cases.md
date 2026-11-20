# P5.5 edge and failure cases (full stack)

Result: **PASS** (run tag `E91762`, `python tests/e2e/edge_cases.py`).

| Case | Result | Key numbers |
|---|---|---|
| ood_values | pass | T30_sent=1632.24, soft_max=1616.91, hard_max=1647.565748, state=DEGRADED_DATA, seconds=0.7 |
| offline_detection | pass | expected_interval_s=0.6153, offline_after_s=1.6, offline_alert=True, seconds=7.2 |
| db_down | pass | status_while_down=503, answer_time_s=0.05, recovered_after_s=0.1, last_cycle_after=2, seconds=11.0 |
| db_down_mqtt | pass | published=196, published_before_db_stop=16, db_down_s=8, stored_rows=196, distinct_cycles=196, seconds=39.8 |
| broker_down | pass | messages=60, send_failures=0, last_cycle=60, backend_mqtt_reconnected=True, seconds=25.6 |
| backend_restart | pass | asset=E91762RFD001-T034, published=203, publish_failures=0, published_before_shutdown=35, backend_down_s=4.8, stored_cycles=203, seconds=20.9 |

Covered by other automated tests:

- **duplicate_and_out_of_order**: backend/tests/test_ingest.py::test_duplicate_out_of_order_gap; Mode 2 harness fault types duplicate/out_of_order (P5.3 report)
- **unit_restart_new_life**: backend/tests/test_ingest.py::test_new_life_on_cycle_restart
- **short_unit_fd004**: P5.1: every FD004 test engine, including the shortest (19 cycles), gets a served prediction equal to the offline one (tests/e2e/reports/p51_mode1_batch.md)
- **ws_disconnect_ui**: frontend/src/api/ws.test.ts (backoff, resync) and frontend/e2e/edge.spec.ts (socket dropped -> Reconnecting -> Live)
- **restart_rehydrates_stream**: backend/tests/test_ingest.py::test_restart_rehydrates_stream
