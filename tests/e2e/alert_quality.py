"""P5.6 alert quality and calibration of the *served* system vs PRD §4.1.

Reads the engines streamed by the P5.1 batch run (asset prefix from tests/e2e/reports/p51_mode1_batch.json) and
scores the backend's own output at each engine's last cycle: the alert state the state machine reached (with
hysteresis and the p10 safety override, docs/02 §3), the P10–P90 interval and the point prediction.

This only measures. `config/alerts.yaml` is NOT tuned on these numbers: they come from the official test sets,
which must not be used for tuning (docs/06 P1.8). Gaps are documented instead.

    set -a; . ./.env; set +a; python tests/e2e/alert_quality.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from pdm_ml.io.loader import load_profile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tests" / "e2e" / "reports"
URL = os.environ.get("PDM_BACKEND", "http://localhost:8000")
CRIT_RECALL, FALSE_CRIT, COV_MIN, COV_LO, COV_HI, LATE = 0.90, 0.05, 0.80, 0.75, 0.90, 0.10


def main() -> None:
    p51 = json.loads((OUT / "p51_mode1_batch.json").read_text())
    prefix = p51["asset_prefix"]
    c = httpx.Client(base_url=URL, timeout=30)
    c.post("/api/v1/auth/login", json={"password": os.environ["DASHBOARD_PASSWORD"]}).raise_for_status()
    rep: dict[str, Any] = {"asset_prefix": prefix, "profiles": {}}
    for profile in p51["profiles"]:
        truth = load_profile(profile).true_rul
        rows = []
        for u in truth.index:
            aid = f"{prefix}{profile}-T{int(u):03d}"
            last = c.get(f"/api/v1/assets/{aid}/predictions", params={"limit": 1}).json()["items"][-1]
            rows.append((float(truth.loc[u]), last["rul_pred"], last["rul_p10"], last["rul_p90"], last["state"]))
        y = np.array([r[0] for r in rows])
        pred = np.array([r[1] for r in rows], float)
        lo, hi = np.array([r[2] for r in rows], float), np.array([r[3] for r in rows], float)
        state = np.array([r[4] for r in rows])
        crit = y <= 30
        healthy = y > 75
        m = {
            "engines": len(rows),
            "critical_recall_state": float(np.mean(state[crit] == "CRITICAL")) if crit.any() else None,
            "critical_recall_point": float(np.mean(pred[crit] <= 30)) if crit.any() else None,
            "false_critical_rate_state": float(np.mean(state[healthy] == "CRITICAL")) if healthy.any() else None,
            "coverage_p10_p90": float(np.mean((y >= lo) & (y <= hi))),
            "late_gt20_share": float(np.mean(pred - y > 20)),
            "coverage_in_75_90_band": bool(COV_LO <= float(np.mean((y >= lo) & (y <= hi))) <= COV_HI),
            "n_true_le30": int(crit.sum()), "n_true_gt75": int(healthy.sum()),
            "missed_critical": [{"unit": int(u), "true": int(t), "pred": round(float(p), 1), "p10": round(float(lo_), 1),
                                 "state": s} for u, t, p, lo_, s in zip(truth.index, y, pred, lo, state, strict=True)
                                if t <= 30 and s != "CRITICAL"],
        }
        m["meets"] = {
            "critical_recall": m["critical_recall_state"] is not None and m["critical_recall_state"] >= CRIT_RECALL,
            "false_critical": m["false_critical_rate_state"] is not None and m["false_critical_rate_state"] <= FALSE_CRIT,
            # PRD §4.1: at least 80 % inside the interval; the 75–90 % band is reported, not scored
            "calibration": m["coverage_p10_p90"] >= COV_MIN,
            "late_bias": m["late_gt20_share"] <= LATE,
        }
        rep["profiles"][profile] = m
        print(profile, json.dumps({k: v for k, v in m.items() if k != "missed_critical"}), flush=True)
    rep["ok"] = all(all(m["meets"].values()) for m in rep["profiles"].values())
    (OUT / "p56_alert_quality.json").write_text(json.dumps(rep, indent=2))
    lines = ["# P5.6 alert quality and calibration (served system vs PRD §4.1)", "",
             f"Engines streamed in P5.1 (`{prefix}FD00x-Tnnn`); scored on the backend's state and interval at each "
             "engine's last cycle. Targets: Critical recall ≥ 0.90 (true RUL ≤ 30), false Critical ≤ 5 % (true RUL "
             "> 75), ≥ 80 % inside P10–P90 (band 75–90 %), late > 20 cycles ≤ 10 %. Not used for tuning.", "",
             "| Profile | Critical recall (state) | (point ≤ 30) | False Critical | Coverage P10–P90 | Late > 20 | Meets all |",
             "|---|---|---|---|---|---|---|"]
    for p, m in rep["profiles"].items():
        lines.append(f"| {p} | {m['critical_recall_state']:.2f} ({m['n_true_le30']} engines) | "
                     f"{m['critical_recall_point']:.2f} | {m['false_critical_rate_state']:.3f} ({m['n_true_gt75']}) | "
                     f"{m['coverage_p10_p90']:.2f} ({'in' if m['coverage_in_75_90_band'] else 'outside'} band) | "
                     f"{m['late_gt20_share']:.2f} | "
                     f"{'yes' if all(m['meets'].values()) else 'no: ' + ', '.join(k for k, v in m['meets'].items() if not v)} |")
    lines += ["", "Missed Critical engines (true RUL ≤ 30, final state not CRITICAL):", ""]
    for p, m in rep["profiles"].items():
        for x in m["missed_critical"]:
            lines.append(f"- {p} unit {x['unit']}: true {x['true']}, predicted {x['pred']} (p10 {x['p10']}), state {x['state']}")
    (OUT / "p56_alert_quality.md").write_text("\n".join(lines) + "\n")
    sys.exit(0 if rep["ok"] else 1)


if __name__ == "__main__":
    main()
