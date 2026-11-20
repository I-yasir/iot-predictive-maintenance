"""M2 — causal 1D-CNN sequence model on regime-normalised sensor histories (plan P1.11, docs/05 §7).

Input for the prediction at cycle t of one engine: the last `seq_len` regime-normalised sensor vectors
(cycles <= t only, left-padded with zeros) plus two channels per step: a 0/1 mask marking real cycles and
the cycle number / AGE_SCALE. The same tensor can be built online from a ring buffer of z vectors, so the
model is streaming-compatible by construction.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import torch
from numpy.lib.stride_tricks import sliding_window_view
from torch import nn

from pdm_ml.config import MIN_CYCLES, SEED

AGE_SCALE = 200.0


def build_windows(z: pd.DataFrame, sensors: tuple[str, ...], seq_len: int, min_cycles: int = MIN_CYCLES
                  ) -> tuple[np.ndarray, pd.DataFrame]:
    """z = regime-normalised frame (unit, cycle, sensors). Returns X (n, C, L) float32 and the index frame
    (unit, cycle) of each window's last cycle, gated like FeaturePipeline (row_in_unit >= min_cycles - 1)."""
    xs, idx = [], []
    c = len(sensors) + 2
    for u, g in z.sort_values(["unit", "cycle"], kind="stable").groupby("unit", sort=False):
        n = len(g)
        feat = np.zeros((n + seq_len - 1, c), np.float32)
        feat[seq_len - 1:, : len(sensors)] = g[list(sensors)].to_numpy(np.float32)
        feat[seq_len - 1:, -2] = 1.0
        feat[seq_len - 1:, -1] = g.cycle.to_numpy(np.float32) / AGE_SCALE
        w = sliding_window_view(feat, seq_len, axis=0)  # (n, C, L)
        keep = np.arange(n) >= min_cycles - 1
        xs.append(w[keep])
        idx.append(pd.DataFrame({"unit": u, "cycle": g.cycle.to_numpy()[keep]}))
    return np.ascontiguousarray(np.concatenate(xs)), pd.concat(idx, ignore_index=True)


class CNN(nn.Module):
    def __init__(self, c_in: int, width: int = 32, k: int = 5) -> None:
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv1d(c_in, width, k, padding=k // 2), nn.ReLU(),
            nn.Conv1d(width, width, k, padding=2 * (k // 2), dilation=2), nn.ReLU(),
            nn.Conv1d(width, width, k, padding=4 * (k // 2), dilation=4), nn.ReLU(),
        )
        self.head = nn.Sequential(nn.Linear(2 * width + 1, 64), nn.ReLU(), nn.Linear(64, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        mask = x[:, -2:-1, :]  # (B, 1, L)
        h = self.conv(x) * mask
        pooled = h.sum(-1) / mask.sum(-1).clamp(min=1.0)
        last = h[:, :, -1]
        age = x[:, -1, -1:]
        return self.head(torch.cat([pooled, last, age], dim=1)).squeeze(1)


@dataclass
class SeqConfig:
    seq_len: int = 50
    width: int = 32
    cap: int = 125
    lr: float = 1e-3
    batch: int = 512
    max_epochs: int = 40
    patience: int = 6
    seeds: int = 1


@dataclass
class SeqModel:
    sensors: tuple[str, ...]
    cfg: SeqConfig
    nets: list[CNN] = field(default_factory=list)
    epochs: list[int] = field(default_factory=list)

    def fit(self, X: np.ndarray, y: np.ndarray, X_val: np.ndarray, y_val: np.ndarray) -> SeqModel:
        torch.set_num_threads(max(1, torch.get_num_threads()))
        for s in range(self.cfg.seeds):
            net, ep = _train_one(X, y, X_val, y_val, self.cfg, SEED + s)
            self.nets.append(net)
            self.epochs.append(ep)
        return self

    def fit_fixed(self, X: np.ndarray, y: np.ndarray, epochs: int) -> SeqModel:
        """Final refit on all training engines for a CV-chosen number of epochs (no hold-out)."""
        for s in range(self.cfg.seeds):
            net, _ = _train_one(X, y, None, None, self.cfg, SEED + s, fixed_epochs=epochs)
            self.nets.append(net)
            self.epochs.append(epochs)
        return self

    @torch.no_grad()
    def predict(self, X: np.ndarray) -> np.ndarray:
        out = []
        for net in self.nets:
            net.eval()
            preds = [net(torch.from_numpy(X[i:i + 4096])).numpy() for i in range(0, len(X), 4096)]
            out.append(np.concatenate(preds))
        return np.clip(np.mean(out, axis=0) * self.cfg.cap, 0, self.cfg.cap)

    def state(self) -> dict[str, Any]:
        return {"sensors": list(self.sensors), "cfg": self.cfg.__dict__, "epochs": self.epochs,
                "nets": [n.state_dict() for n in self.nets]}

    @classmethod
    def from_state(cls, st: dict[str, Any]) -> SeqModel:
        cfg = SeqConfig(**st["cfg"])
        m = cls(tuple(st["sensors"]), cfg, epochs=list(st["epochs"]))
        for sd in st["nets"]:
            net = CNN(len(m.sensors) + 2, cfg.width)
            net.load_state_dict(sd)
            m.nets.append(net)
        return m


def _train_one(X: np.ndarray, y: np.ndarray, X_val: np.ndarray | None, y_val: np.ndarray | None,
               cfg: SeqConfig, seed: int, fixed_epochs: int | None = None) -> tuple[CNN, int]:
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    net = CNN(X.shape[1], cfg.width)
    opt = torch.optim.Adam(net.parameters(), lr=cfg.lr)
    Xt, yt = torch.from_numpy(X), torch.from_numpy((y / cfg.cap).astype(np.float32))
    best, best_state, best_ep, bad = np.inf, copy.deepcopy(net.state_dict()), 0, 0
    n_epochs = fixed_epochs or cfg.max_epochs
    for ep in range(1, n_epochs + 1):
        net.train()
        perm = torch.from_numpy(rng.permutation(len(X)))
        for i in range(0, len(X), cfg.batch):
            b = perm[i:i + cfg.batch]
            opt.zero_grad()
            loss = nn.functional.mse_loss(net(Xt[b]), yt[b])
            loss.backward()
            opt.step()
        if fixed_epochs or X_val is None or y_val is None:
            continue
        net.eval()
        with torch.no_grad():
            pv = np.concatenate([net(torch.from_numpy(X_val[i:i + 4096])).numpy()
                                 for i in range(0, len(X_val), 4096)]) * cfg.cap
        err = float(np.sqrt(np.mean((np.clip(pv, 0, cfg.cap) - y_val) ** 2)))
        if err < best - 1e-3:
            best, best_state, best_ep, bad = err, copy.deepcopy(net.state_dict()), ep, 0
        else:
            bad += 1
            if bad >= cfg.patience:
                break
    if not fixed_epochs:
        net.load_state_dict(best_state)
    return net, (fixed_epochs or best_ep)


class SeqStream:
    """Online twin of `build_windows` for one engine: keeps the last `seq_len` z vectors."""

    def __init__(self, n_sensors: int, seq_len: int) -> None:
        self.seq_len = seq_len
        self.buf: np.ndarray = np.zeros((n_sensors + 2, seq_len), np.float32)
        self.n_seen = 0

    def update(self, cycle: int, z: np.ndarray) -> np.ndarray:
        """Append one cycle; returns the (C, L) window ending at it (same values build_windows gives)."""
        self.buf = np.roll(self.buf, -1, axis=1)
        self.buf[:-2, -1] = np.asarray(z, np.float32)
        self.buf[-2, -1] = 1.0
        self.buf[-1, -1] = np.float32(cycle) / np.float32(AGE_SCALE)
        self.n_seen += 1
        return self.buf.copy()
