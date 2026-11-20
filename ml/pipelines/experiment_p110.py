"""P1.10 experiment (CV only, never touches test files): horizon blend and feature ablations.

python ml/pipelines/experiment_p110.py > ml/reports/p110_experiment.json
"""

from __future__ import annotations

import json
import sys

from pdm_ml.config import DEFAULT_INPUTS, PROFILES
from pdm_ml.evaluate.cv import CVConfig, run_cv
from pdm_ml.io.loader import load_split

VARIANTS = [
    {"name": "cap125", "cap": 125},
    {"name": "cap160", "cap": 160},
    {"name": "blend125_160", "cap": 125, "cap_high": 160},
    {"name": "blend125_200", "cap": 125, "cap_high": 200},
    {"name": "cap125_alpha0.1", "cap": 125, "alpha": 0.1},
    {"name": "cap125_W50", "cap": 125, "window": 50},
    {"name": "blend125_160_alpha0.1_W50", "cap": 125, "cap_high": 160, "alpha": 0.1, "window": 50},
    {"name": "cap125_W70", "cap": 125, "window": 70},
    {"name": "cap125_W100", "cap": 125, "window": 100},
    {"name": "cap140_W50", "cap": 140, "window": 50},
]
if "--extra" in sys.argv:
    sys.argv.remove("--extra")
    VARIANTS = VARIANTS[-3:]
PARAMS = {
    "FD001": {"num_leaves": 15, "min_child_samples": 20},
    "FD002": {"num_leaves": 15, "min_child_samples": 50},
    "FD003": {"num_leaves": 15, "min_child_samples": 20},
    "FD004": {"num_leaves": 31, "min_child_samples": 50},
}


def main() -> int:
    out = {}
    for p in sys.argv[1:] or PROFILES:
        train = load_split(p, "train")
        out[p] = {}
        for v in VARIANTS:
            kw = {k: val for k, val in v.items() if k != "name"}
            r = run_cv(train, CVConfig(p, DEFAULT_INPUTS[p], params=PARAMS[p], **kw))
            out[p][v["name"]] = {
                "rmse_10_150": round(r["rmse_mean"], 2),
                "rmse_5_200": round(r["rmse_wide_mean"], 2),
                "std": round(r["rmse_std"], 2),
            }
            print(p, v["name"], out[p][v["name"]], file=sys.stderr, flush=True)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
