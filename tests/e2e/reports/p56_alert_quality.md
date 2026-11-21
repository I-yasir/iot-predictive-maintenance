# P5.6 alert quality and calibration (served system vs PRD §4.1)

Engines streamed in P5.1 (`B25229FD00x-Tnnn`); scored on the backend's state and interval at each engine's last cycle. Targets: Critical recall ≥ 0.90 (true RUL ≤ 30), false Critical ≤ 5 % (true RUL > 75), ≥ 80 % inside P10–P90 (band 75–90 %), late > 20 cycles ≤ 10 %. Not used for tuning.

| Profile | Critical recall (state) | (point ≤ 30) | False Critical | Coverage P10–P90 | Late > 20 | Meets all |
|---|---|---|---|---|---|---|
| FD001 | 0.88 (25 engines) | 0.88 | 0.000 (57) | 0.91 (outside band) | 0.05 | no: critical_recall |
| FD002 | 1.00 (61 engines) | 1.00 | 0.000 (139) | 0.79 (in band) | 0.06 | no: calibration |
| FD003 | 1.00 (20 engines) | 0.90 | 0.000 (51) | 0.93 (outside band) | 0.06 | yes |
| FD004 | 1.00 (53 engines) | 0.91 | 0.007 (140) | 0.79 (in band) | 0.06 | no: calibration |

Missed Critical engines (true RUL ≤ 30, final state not CRITICAL):

- FD001 unit 18: true 28, predicted 31.6 (p10 17.6), state WARNING
- FD001 unit 40: true 28, predicted 35.0 (p10 19.3), state WARNING
- FD001 unit 53: true 26, predicted 28.8 (p10 17.3), state WARNING
