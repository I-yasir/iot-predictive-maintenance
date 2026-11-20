# Mode 2 harness report: PASS

Generated 2026-11-20T15:52:07+00:00 by `pdm-harness` (virtual ESP32).

| Setting | Value |
|---|---|
| mode | `virtual ESP32` |
| asset | `FD001-V052` |
| site | `lab` |
| rate_hz | `10.0` |
| count | `60` |
| faults | `malformed@10,missing@20,range@30,duplicate@40,out_of_order@45,drop@50:3` |
| generator_mode | `trajectory` |
| seed | `12345` |
| acks_from | `http://localhost:8000` |

## Checks

| Check | Result | Detail |
|---|---|---|
| schema | PASS | 58 accepted, 4 rejected ({'parse_error': 1, 'schema:sensors.T30': 1, 'range:T30': 1, 'duplicate_msg_id': 1}), 3 of those were injected |
| rate | PASS | observed 10.32 msg/s vs configured 10.0 |
| sequence | PASS | no permanent gaps (seq [10] unreadable by design) |
| latency | PASS | {"p50": 1.7, "p95": 35.8, "max": 301.6} |
| fault:malformed@10 | PASS | expected parse_error, got 1 parse_error for 1 injected |
| fault:missing@20 | PASS | expected schema:sensors.T30, got schema:sensors.T30 |
| fault:range@30 | PASS | expected range:T30, got range:T30 |
| fault:duplicate@40 | PASS | expected duplicate_msg_id, got 1 duplicate msg_id |
| fault:out_of_order@45 | PASS | expected cycle_regression, got regressions at seq [45] |
| fault:drop@50 | PASS | expected buffered_then_flushed, got 3 buffered and flushed, none lost; max latency 301.6 ms |
| acks | PASS | 57 accepted acks from the backend; expected 57 = 58 valid - 1 repeated cycle(s) (1 re-sent msg_id not counted as valid) |
| backend:asset | PASS | source VIRTUAL_ESP32, state OFFLINE, last cycle 60, RUL 112.4 |
| backend:dead-letter:malformed@10 | PASS | expected parse_error in the backend dead letter, found ['parse_error', 'range:T30', 'schema:sensors.T30'] |
| backend:dead-letter:missing@20 | PASS | expected schema:sensors.T30 in the backend dead letter, found ['parse_error', 'range:T30', 'schema:sensors.T30'] |
| backend:dead-letter:range@30 | PASS | expected range:T30 in the backend dead letter, found ['parse_error', 'range:T30', 'schema:sensors.T30'] |
| backend:stored | PASS | 57 distinct seqs stored; expected 57 (58 valid, minus 1 repeated cycle(s) the backend drops as duplicates) |
| backend:live-updates | PASS | 57 prediction events pushed over /ws/v1/stream |

## Traffic

- telemetry messages received: 62 (accepted 58)
- rejections: {'parse_error': 1, 'schema:sensors.T30': 1, 'range:T30': 1, 'duplicate_msg_id': 1}
- soft out-of-distribution flags: {'OOD:P15': 23, 'OOD:NRf': 1}
- late (buffered) seqs: none
- status messages: 0
