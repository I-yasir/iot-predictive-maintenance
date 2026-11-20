"""Write iot/contracts/telemetry_v1.schema.json from the Pydantic model."""

from __future__ import annotations

import json
from pathlib import Path

from pdm_contracts.telemetry import json_schema

if __name__ == "__main__":
    out = Path(__file__).resolve().parents[2] / "iot" / "contracts" / "telemetry_v1.schema.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(json_schema(), indent=2) + "\n")
    print("wrote", out)
