"""Versioned model bundle (docs/04 §6): write, verify, load.

ml/artifacts/{profile}/{version}/
  model_point.txt  model_q10.txt  model_q90.txt  preprocessor.joblib  baselines.joblib
  drift_reference.json  model_card.json  MANIFEST.sha256
  seq_model.pt   (optional, P1.11: M2 sequence model; point = mean(LightGBM, M2))
ml/artifacts/{profile}/CURRENT  -> active version string
"""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import sklearn
import torch

from pdm_ml.diagnostics.subsystems import FleetBaseline
from pdm_ml.drift.reference import DriftReference
from pdm_ml.features.pipeline import FeaturePipeline
from pdm_ml.models.lgbm import RULModel
from pdm_ml.models.seq import SeqModel, build_windows

MODEL_FILES = ("model_point.txt", "model_q10.txt", "model_q90.txt")
BUNDLE_FILES = (
    *MODEL_FILES,
    "preprocessor.joblib",
    "baselines.joblib",
    "drift_reference.json",
    "model_card.json",
)
SEQ_FILE = "seq_model.pt"
MANIFEST = "MANIFEST.sha256"


def _files(has_seq: bool) -> tuple[str, ...]:
    return (*BUNDLE_FILES, SEQ_FILE) if has_seq else BUNDLE_FILES


class BundleIntegrityError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class ModelBundle:
    profile: str
    version: str
    pipeline: FeaturePipeline
    model: RULModel
    fleet_baseline: FleetBaseline
    subsystem_of: dict[str, str]
    drift: DriftReference
    card: dict[str, Any]
    seq: SeqModel | None = None

    def predict_frame(self, feats: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """LightGBM-only bundles. Bundles with an M2 model need the raw history: use `predict_history`."""
        return self.model.predict(feats)

    def predict_history(self, df: pd.DataFrame) -> pd.DataFrame:
        """Raw rows of one or more engines -> features + (unit, cycle, pred, lo, hi) for every gated cycle.
        Each prediction uses only cycles <= its own (both feature paths are causal)."""
        F = self.pipeline.transform(df)
        seq_point = None
        if self.seq is not None:
            X, idx = build_windows(
                self.pipeline.normalize(df), self.seq.sensors, self.seq.cfg.seq_len, self.pipeline.min_cycles
            )
            if (
                not (idx.unit.to_numpy() == F.unit.to_numpy()).all()
                or not (idx.cycle.to_numpy() == F.cycle.to_numpy()).all()
            ):
                raise RuntimeError("sequence windows and feature rows are misaligned")
            seq_point = self.seq.predict(X)
        pred, lo, hi = self.model.predict(F, seq_point)
        return F.assign(pred=pred, lo=lo, hi=hi)


def library_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scikit-learn": sklearn.__version__,
        "lightgbm": lgb.__version__,
        "torch": torch.__version__.split("+")[0],
        "joblib": joblib.__version__,
    }


def write_bundle(root: Path, bundle: ModelBundle, set_current: bool = True) -> Path:
    out = root / bundle.profile / bundle.version
    out.mkdir(parents=True, exist_ok=True)
    bundle.model.point.save_model(str(out / "model_point.txt"))
    bundle.model.q10.save_model(str(out / "model_q10.txt"))
    bundle.model.q90.save_model(str(out / "model_q90.txt"))
    joblib.dump(bundle.pipeline, out / "preprocessor.joblib")
    joblib.dump(
        {"fleet_baseline": bundle.fleet_baseline, "subsystem_of": bundle.subsystem_of},
        out / "baselines.joblib",
    )
    (out / "drift_reference.json").write_text(json.dumps(bundle.drift.to_json()))
    if bundle.seq is not None:
        torch.save(bundle.seq.state(), out / SEQ_FILE)
    card = {
        **bundle.card,
        "profile": bundle.profile,
        "model_version": bundle.version,
        "feature_names": bundle.model.feature_names,
        "cap": bundle.model.cap,
        "conformal_q": bundle.model.conformal_q,
        "seq_model": None
        if bundle.seq is None
        else {"file": SEQ_FILE, **bundle.seq.cfg.__dict__, "epochs": bundle.seq.epochs},
        "library_versions": library_versions(),
    }
    (out / "model_card.json").write_text(json.dumps(card, indent=2, default=float))
    lines = [f"{sha256_file(out / f)}  {f}" for f in _files(bundle.seq is not None)]
    (out / MANIFEST).write_text("\n".join(lines) + "\n")
    if set_current:
        (root / bundle.profile / "CURRENT").write_text(bundle.version + "\n")
    return out


def verify_bundle(path: Path) -> None:
    mf = path / MANIFEST
    if not mf.is_file():
        raise BundleIntegrityError(f"{path}: missing {MANIFEST}")
    listed = {}
    for line in mf.read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        listed[name.strip()] = digest
    card = json.loads((path / "model_card.json").read_text()) if (path / "model_card.json").is_file() else {}
    required = _files(bool(card.get("seq_model")))
    missing = [f for f in required if f not in listed or not (path / f).is_file()]
    if missing:
        raise BundleIntegrityError(f"{path}: missing files {missing}")
    bad = [f for f, d in listed.items() if sha256_file(path / f) != d]
    if bad:
        raise BundleIntegrityError(f"{path}: checksum mismatch for {bad}")


def current_version(root: Path, profile: str) -> str:
    p = root / profile / "CURRENT"
    if not p.is_file():
        raise FileNotFoundError(f"no CURRENT model for {profile} under {root}")
    return p.read_text().strip()


def load_bundle(root: Path, profile: str, version: str | None = None) -> ModelBundle:
    version = version or current_version(root, profile)
    path = root / profile / version
    verify_bundle(path)  # never unpickle unverified files
    card = json.loads((path / "model_card.json").read_text())
    boosters = {f: lgb.Booster(model_file=str(path / f)) for f in MODEL_FILES}
    model = RULModel(
        card["feature_names"],
        int(card["cap"]),
        boosters["model_point.txt"],
        boosters["model_q10.txt"],
        boosters["model_q90.txt"],
        float(card["conformal_q"]),
        needs_seq=bool(card.get("seq_model")),
    )
    seq = None
    if card.get("seq_model"):
        seq = SeqModel.from_state(torch.load(path / SEQ_FILE, weights_only=True))
    base = joblib.load(path / "baselines.joblib")
    return ModelBundle(
        profile=profile,
        version=version,
        pipeline=joblib.load(path / "preprocessor.joblib"),
        model=model,
        fleet_baseline=base["fleet_baseline"],
        subsystem_of=base["subsystem_of"],
        drift=DriftReference.from_json(json.loads((path / "drift_reference.json").read_text())),
        card=card,
        seq=seq,
    )


def update_model_card(root: Path, profile: str, version: str, patch: dict[str, Any]) -> None:
    """Trusted pipelines only (evaluate.py): merge `patch` into model_card.json and re-sign the manifest."""
    path = root / profile / version
    verify_bundle(path)
    card = json.loads((path / "model_card.json").read_text())
    card.update(patch)
    (path / "model_card.json").write_text(json.dumps(card, indent=2, default=float))
    lines = [f"{sha256_file(path / f)}  {f}" for f in _files(bool(card.get("seq_model")))]
    (path / MANIFEST).write_text("\n".join(lines) + "\n")
