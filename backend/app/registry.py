"""P3.3 model registry: load the CURRENT bundle of every active profile at startup, verified, fail fast."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import torch

from pdm_ml.models.bundle import ModelBundle, load_bundle


class RegistryError(RuntimeError):
    """Raised at startup when any active profile has no loadable, verified bundle (docs/02 §8)."""


@dataclass
class ModelRegistry:
    root: Path
    bundles: dict[str, ModelBundle] = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path, profiles: list[str]) -> ModelRegistry:
        reg, errors = cls(root), []
        torch.set_num_threads(1)  # single-sample CNN inference: threads only add contention
        for p in profiles:
            try:
                reg.bundles[p] = load_bundle(root, p)
                reg.bundles[p].model.predict_threads = 1
            except Exception as e:  # missing CURRENT, missing file, checksum mismatch, unpickling error
                errors.append(f"{p}: {type(e).__name__}: {e}")
        if errors:
            raise RegistryError("model bundles failed verification:\n  " + "\n  ".join(errors))
        return reg

    def get(self, profile: str) -> ModelBundle | None:
        return self.bundles.get(profile)

    def describe(self) -> list[dict[str, Any]]:
        out = []
        for p, b in sorted(self.bundles.items()):
            card = b.card
            out.append({
                "profile": p,
                "model_version": b.version,
                "point_estimate": card.get("point_estimate", "LightGBM"),
                "has_sequence_model": b.seq is not None,
                "cap": b.model.cap,
                "conformal_q": b.model.conformal_q,
                "window": b.pipeline.window,
                "sensors_used": list(b.pipeline.sensors_used),
                "feature_names": b.model.feature_names,
                "cv": card.get("cv"),
                "test": card.get("test"),
                "training": {k: v for k, v in (card.get("training") or {}).items() if k != "params"},
                "created_utc": card.get("created_utc"),
                "library_versions": card.get("library_versions"),
            })
        return out
