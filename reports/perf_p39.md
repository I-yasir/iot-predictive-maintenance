# P3.9 load test: PASS

2026-11-20T07:07:40+00:00 · 300 assets (FD001, FD002, FD004 train units, `--continuous`, 12 publisher processes) over MQTT QoS 1 · target 500 msg/s for 300 s · backend with 2 MQTT workers, TimescaleDB on the same host.

| NFR (docs/04 §8) | Target | Result |
|---|---|---|
| Throughput | ≥ 500 msg/s | 499.5 msg/s ✅ |
| p95 ingest → prediction persisted | ≤ 250 ms | 184.8 ms over the steady period (p50 81.4 ms; worst 10 s window 935.54 ms) ✅ |
| Backend memory, 300 active assets | ≤ 1 GB | max RSS 731.9 MB ✅ |

Steady period = after the first 60 s. The warm-up is reported, not scored: all 300 assets register and fill their windows at the same moment, worst 10 s p95 7523.72 ms.

Messages processed: 148950 (120089 in the steady period). Raw samples: `perf_p39.json`.
