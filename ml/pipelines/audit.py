"""P1.4: regenerate data/reference/data_audit.json and config/profiles/FD00x.yaml.

python ml/pipelines/audit.py
"""

from __future__ import annotations

import json
import sys

from pdm_ml.audit.audit import run_audit
from pdm_ml.config import profiles_config_dir, raw_dir, reference_dir


def main() -> int:
    audit = run_audit(reference_dir(), profiles_config_dir(), raw_dir())
    path = reference_dir() / "data_audit.json"
    path.write_text(json.dumps(audit, indent=2))
    for p, a in audit["profiles"].items():
        flag = (
            ""
            if (a["train_units"], a["test_units"]) == tuple(a["readme_claimed_units"].values())
            else "  (readme differs)"
        )
        print(
            f"{p}: train {a['train_units']} units / {a['train_rows']} rows, test {a['test_units']} units, "
            f"regimes {a['n_regimes']}, constant {a['constant_sensors']}{flag}"
        )
    print(f"wrote {path} and {profiles_config_dir()}/FD00x.yaml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
