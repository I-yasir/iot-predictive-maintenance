"""P3.5 per-asset streaming inference (docs/02 §2 steps 7-9, docs/05 §8).

Each asset keeps bounded state only: the FeaturePipeline stream (<= window cycles), the M2 SeqStream
(<= seq_len cycles) when the bundle has one, the first 20 z vectors (diagnostic baseline) and the last
50 (drift). The numbers equal the offline batch path (`ModelBundle.predict_history`) - see tests.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from pdm_ml.config import BASELINE_CYCLES
from pdm_ml.diagnostics.subsystems import asset_baseline, deviation_z, sensor_contributions, subsystem_scores
from pdm_ml.features.pipeline import StreamResult
from pdm_ml.features.window import StreamState
from pdm_ml.models.bundle import ModelBundle
from pdm_ml.models.seq import SeqStream

DRIFT_EVERY = 10  # KS tests are recomputed every N cycles (sticky in between) to bound CPU per message
CONTRIB_EVERY = 5  # SHAP contributions (diagnostics only) every N cycles, reused in between


@dataclass
class PredictionResult:
    status: str  # OK | WARMING_UP | ERROR
    cycle: int
    regime: int | None = None
    rul_pred: float | None = None
    rul_p10: float | None = None
    rul_p90: float | None = None
    health_index: float | None = None
    flags: list[str] = field(default_factory=list)
    contributors: list[dict[str, Any]] | None = None
    subsystem_scores: dict[str, float] | None = None
    n_seen: int = 0
    error: str = ""


@dataclass
class AssetRuntime:
    bundle: ModelBundle
    cfg: Mapping[str, Any]
    stream: StreamState
    seq: SeqStream | None
    baseline_z: list[np.ndarray] = field(default_factory=list)
    recent_z: deque[np.ndarray] = field(default_factory=lambda: deque(maxlen=50))
    last_rul: float | None = None
    drift_flag: bool = False
    last_contrib: np.ndarray | None = None
    phase: int = 0  # staggers the every-N-cycles work across assets so a fleet started together has no spikes

    @classmethod
    def create(cls, bundle: ModelBundle, cfg: Mapping[str, Any], phase: int = 0) -> AssetRuntime:
        seq = None
        if bundle.seq is not None:
            seq = SeqStream(len(bundle.seq.sensors), bundle.seq.cfg.seq_len)
        return cls(bundle, cfg, bundle.pipeline.new_stream(), seq,
                   recent_z=deque(maxlen=int(cfg.get("drift_window", 50))), phase=phase)

    def prepare(self, cycle: int, settings: Sequence[float], sensors: Mapping[str, float]) -> Prepared:
        """Advance the streaming state by one cycle (sequential per asset). No model call yet."""
        b = self.bundle
        res = b.pipeline.update(self.stream, cycle, settings, sensors)
        seq_x = self.seq.update(cycle, res.z) if self.seq is not None else None
        if len(self.baseline_z) < BASELINE_CYCLES:
            self.baseline_z.append(res.z)
        self.recent_z.append(res.z)
        flags = []
        ood = b.drift.ood_sensors({s: sensors[s] for s in b.pipeline.sensors_used if s in sensors})
        if ood or res.regime_ood:
            flags.append("OOD")
        return Prepared(self, cycle, res, seq_x, flags)

    def finish(self, prep: Prepared, rul: float, p10: float, p90: float, contrib: np.ndarray | None
               ) -> PredictionResult:
        """Flags + diagnostics after the (possibly batched) model call. Sequential per asset."""
        b, res, flags = self.bundle, prep.res, list(prep.flags)
        assert res.features is not None
        if p90 - p10 > float(self.cfg.get("low_confidence_width", 60)) or res.features[1] < float(
            self.cfg.get("low_confidence_window", 15)
        ):
            flags.append("LOW_CONFIDENCE")
        if (res.n_seen + self.phase) % DRIFT_EVERY == 0:
            self.drift_flag, _ = b.drift.drift(np.asarray(self.recent_z), rul)
        if self.drift_flag:
            flags.append("DRIFT")
        if self.last_rul is not None and abs(rul - self.last_rul) > float(self.cfg.get("prediction_jump", 25)):
            flags.append("JUMP")
        self.last_rul = rul
        if contrib is not None:
            self.last_contrib = contrib
        mu, sd = asset_baseline(np.asarray(self.baseline_z), b.fleet_baseline, BASELINE_CYCLES)
        z_dev = dict(zip(b.pipeline.sensors_used, deviation_z(res.ewm, mu, sd).tolist(), strict=True))
        return PredictionResult(
            "OK", prep.cycle, res.regime, rul, p10, p90,
            health_index=round(float(np.clip(rul / b.model.cap, 0.0, 1.0)), 4),
            flags=flags,
            contributors=None if self.last_contrib is None else sensor_contributions(
                self.last_contrib, b.model.feature_names, z_dev),
            subsystem_scores=subsystem_scores(z_dev, b.subsystem_of),
            n_seen=res.n_seen,
        )

    def step(self, cycle: int, settings: Sequence[float], sensors: Mapping[str, float]) -> PredictionResult:
        """Single-message path = prepare + batch of one + finish."""
        return infer_batch([self.prepare(cycle, settings, sensors)])[0]


@dataclass
class Prepared:
    rt: AssetRuntime
    cycle: int
    res: StreamResult
    seq_x: np.ndarray | None
    flags: list[str]

    @property
    def warming(self) -> bool:
        return self.res.features is None


def infer_batch(preps: list[Prepared]) -> list[PredictionResult]:
    """One LightGBM / M2 call per bundle for every ready row in the batch; results in input order.
    A failing bundle turns only its own rows into status ERROR (docs/02 §8)."""
    out: list[PredictionResult | None] = [None] * len(preps)
    groups: dict[int, list[int]] = {}
    for i, pr in enumerate(preps):
        if pr.warming:
            out[i] = PredictionResult("WARMING_UP", pr.cycle, pr.res.regime, flags=list(pr.flags),
                                      n_seen=pr.res.n_seen)
        else:
            groups.setdefault(id(pr.rt.bundle), []).append(i)
    for idx in groups.values():
        b = preps[idx[0]].rt.bundle
        try:
            X = np.vstack([preps[i].res.features for i in idx])
            seq_point = None
            if b.seq is not None:
                seq_point = b.seq.predict(np.stack([preps[i].seq_x for i in idx]))  # type: ignore[misc]
            pred, lo, hi = b.model.predict(X, seq_point)
            need = [k for k, i in enumerate(idx)
                    if preps[i].rt.last_contrib is None or (preps[i].res.n_seen + preps[i].rt.phase) % CONTRIB_EVERY == 0]
            contrib = b.model.contributions(X[need]) if need else None
            crow = {k: contrib[j] for j, k in enumerate(need)} if contrib is not None else {}
            for k, i in enumerate(idx):
                out[i] = preps[i].rt.finish(preps[i], float(pred[k]), float(lo[k]), float(hi[k]), crow.get(k))
        except Exception as e:
            for i in idx:
                out[i] = PredictionResult("ERROR", preps[i].cycle, error=f"{type(e).__name__}: {e}")
    return [r for r in out if r is not None]


def timed_step(rt: AssetRuntime, cycle: int, settings: Sequence[float], sensors: Mapping[str, float]
               ) -> tuple[PredictionResult, float]:
    t0 = time.perf_counter()
    try:
        r = rt.step(cycle, settings, sensors)
    except Exception as e:  # docs/02 §8: telemetry kept, prediction status ERROR, state unchanged
        r = PredictionResult("ERROR", cycle, error=f"{type(e).__name__}: {e}")
    return r, (time.perf_counter() - t0) * 1000.0
