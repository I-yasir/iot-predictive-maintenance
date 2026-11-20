# P5.6 alert quality and calibration (served system vs PRD §4.1)

Engines streamed in P5.1 (`B88814FD00x-Tnnn`); scored on the backend's state and interval at each engine's last cycle. Targets: Critical recall ≥ 0.90 (true RUL ≤ 30), false Critical ≤ 5 % (true RUL > 75), ≥ 80 % inside P10–P90 (band 75–90 %), late > 20 cycles ≤ 10 %. Not used for tuning.

| Profile | Critical recall (state) | (point ≤ 30) | False Critical | Coverage P10–P90 | Late > 20 | Meets all |
|---|---|---|---|---|---|---|
| FD001 | 0.92 (25 engines) | 0.92 | 0.000 (57) | 0.93 (outside band) | 0.06 | yes |
| FD002 | 1.00 (61 engines) | 1.00 | 0.000 (139) | 0.79 (in band) | 0.05 | no: calibration |
| FD003 | 1.00 (20 engines) | 0.85 | 0.000 (51) | 0.92 (outside band) | 0.05 | yes |
| FD004 | 1.00 (53 engines) | 0.91 | 0.007 (140) | 0.78 (in band) | 0.06 | no: calibration |

Missed Critical engines (true RUL ≤ 30, final state not CRITICAL):

- FD001 unit 52: true 29, predicted 29.8 (p10 15.6), state WARNING
- FD001 unit 53: true 26, predicted 29.2 (p10 16.8), state WARNING
