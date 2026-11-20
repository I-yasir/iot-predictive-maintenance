"""P3.4 ingestion core shared by HTTP and MQTT (docs/02 §2, §8).

validate -> rate limit -> dedupe/order/gap -> auto-register / new life -> infer -> alert -> persist (one
transaction) -> broadcast -> ack. Synchronous per message; messages of one asset are serialised by a lock.
"""

from __future__ import annotations

import json
import threading
import time
import zlib
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import psycopg
from psycopg.types.json import Jsonb
from sqlalchemy import Engine, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError

from app import logging as applog
from app.alerts.state_machine import AlertConfig, AssetHealth, State, Transition
from app.db import models as m
from app.inference.service import AssetRuntime, PredictionResult, Prepared, infer_batch
from app.metrics import Metrics
from app.registry import ModelRegistry
from pdm_contracts import Accepted, Profile, Rejection, TelemetryPayload, validate_message
from pdm_ml.config import SETTINGS

log = applog.get("pdm.ingest")
Publish = Callable[[dict[str, Any]], None]
Ack = Callable[[str, str, dict[str, Any]], None]
DEAD_LETTER_RAW_MAX = 4096


@dataclass
class IngestResult:
    status: str  # accepted | duplicate | rejected | rate_limited | unavailable
    http_code: int
    body: dict[str, Any]


@dataclass
class AssetCtx:
    asset_id: str
    site_id: str
    profile: str
    source: str
    life_id: int
    health: AssetHealth
    runtime: AssetRuntime
    last_cycle: int | None = None
    last_seen: float | None = None
    expected_interval_s: float = 1.0
    seen_cycles: set[int] = field(default_factory=set)
    recent_msg_ids: deque[str] = field(default_factory=lambda: deque(maxlen=512))
    lock: threading.Lock = field(default_factory=threading.Lock)
    tokens: float = 0.0
    token_t: float = 0.0
    last_reason: str = ""


UNAVAILABLE = IngestResult("unavailable", 503, {"status": "unavailable", "detail": "storage unavailable"})


@dataclass
class _Item:
    """One accepted-schema message moving through a batch."""

    index: int
    raw: bytes
    transport: str
    t_recv: float
    p: TelemetryPayload
    acc: Accepted
    ctx: AssetCtx
    result: IngestResult | None = None
    flags: list[str] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)
    out_of_order: bool = False
    advance: bool = False
    life_id: int = 1
    prep: Prepared | None = None
    pred: PredictionResult | None = None
    true_rul: int | None = None
    state: str = ""
    pred_id: int | None = None
    alert_rows: list[dict[str, Any]] = field(default_factory=list)


class _Stats:
    """Rolling ingest statistics for GET /stats and the dashboard test page."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.counts: Counter[str] = Counter()
        self.reasons: Counter[str] = Counter()
        self.latency_ms: deque[float] = deque(maxlen=5000)
        self.times: deque[float] = deque(maxlen=20000)
        self.started = time.time()

    def add(self, status: str, reason: str = "", latency_ms: float | None = None) -> None:
        with self.lock:
            self.counts[status] += 1
            if reason:
                self.reasons[reason] += 1
            if latency_ms is not None:
                self.latency_ms.append(latency_ms)
            self.times.append(time.time())

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            now = time.time()
            recent = [t for t in self.times if now - t <= 10.0]
            lat = np.asarray(self.latency_ms) if self.latency_ms else None
            return {
                "since": datetime.fromtimestamp(self.started, UTC).isoformat(),
                "counts": dict(self.counts),
                "rejected_by_reason": dict(self.reasons),
                "rate_msgs_s_10s": round(len(recent) / 10.0, 2),
                "latency_ms": None if lat is None else {
                    "p50": round(float(np.percentile(lat, 50)), 2),
                    "p95": round(float(np.percentile(lat, 95)), 2),
                    "max": round(float(lat.max()), 2),
                },
            }


class IngestService:
    def __init__(self, engine: Engine, registry: ModelRegistry, profiles: dict[str, Profile],
                 alerts_cfg: dict[str, Any], metrics: Metrics, publish: Publish | None = None,
                 max_payload_bytes: int = 4096) -> None:
        self.engine, self.registry, self.metrics = engine, registry, metrics
        self.profiles = {k: v for k, v in profiles.items() if k in registry.bundles}
        self.cfg = alerts_cfg
        self.alert_cfg = AlertConfig.from_dict(alerts_cfg)
        self.publish: Publish = publish or (lambda e: None)
        self.ack: Ack | None = None
        self.max_payload_bytes = max_payload_bytes
        self.assets: dict[str, AssetCtx] = {}
        self._assets_lock = threading.Lock()
        self._db_sweep_t = 0.0
        self.stats = _Stats()
        self.rate = float(alerts_cfg.get("rate_limit_per_asset", 50))
        self.db_ok = True

    # ------------------------------------------------------------------ public entry points
    def process(self, raw: bytes, transport: str, topic_ids: tuple[str, str] | None = None,
                received_at: float | None = None) -> IngestResult:
        return self.process_batch([(raw, transport, topic_ids, received_at)])[0]

    def process_batch(self, items: list[tuple[bytes, str, tuple[str, str] | None, float | None]]
                      ) -> list[IngestResult]:
        """Messages in arrival order. Per-asset order is preserved; model calls and DB writes are batched
        (one LightGBM/M2 call per profile, one transaction) so throughput does not hinge on per-message
        round trips. A batch of one is the HTTP path."""
        results: list[IngestResult | None] = [None] * len(items)
        work: list[_Item] = []
        for i, (raw, transport, topic_ids, t) in enumerate(items):
            t_recv = t or time.time()
            if len(raw) > self.max_payload_bytes:
                results[i] = self._reject(raw, transport, topic_ids, Rejection("too_large", f"{len(raw)} bytes"), 413)
                continue
            res = validate_message(raw, self.profiles, topic_ids)
            if isinstance(res, Rejection):
                results[i] = self._reject(raw, transport, topic_ids, res, 422)
                continue
            ctx = self._ctx(res.payload, t_recv)
            if ctx is None:
                results[i] = UNAVAILABLE
                continue
            if transport != "internal" and not self._take_token(ctx, t_recv):  # in-process replay is trusted
                self.metrics.rate_limited.inc()
                self.stats.add("rate_limited")
                results[i] = IngestResult("rate_limited", 429, {"status": "rate_limited", "asset_id": ctx.asset_id})
                continue
            work.append(_Item(i, raw, transport, t_recv, res.payload, res, ctx))
        if work:
            ctxs = [c for _, c in sorted({w.ctx.asset_id: w.ctx for w in work}.items())]
            for c in ctxs:  # fixed order -> no deadlock with a concurrent HTTP request
                c.lock.acquire()
            try:
                for w, r in zip(work, self._process_locked(work, ctxs), strict=True):
                    results[w.index] = r
            finally:
                for c in ctxs:
                    c.lock.release()
        return [r if r is not None else UNAVAILABLE for r in results]

    # ------------------------------------------------------------------ steps
    def _process_locked(self, work: list[_Item], ctxs: list[AssetCtx]) -> list[IngestResult]:
        live: list[_Item] = []
        for w in work:  # A: order/dedupe/new life + streaming state, sequential per asset
            self._stage(w)
            if w.result is None:
                live.append(w)
        ready = [w for w in live if w.prep is not None]
        for w, pr in zip(ready, infer_batch([w.prep for w in ready if w.prep is not None]), strict=True):
            w.pred = pr  # B: one model call per profile
        for w in live:  # C: flags + alert state machine, sequential in arrival order
            ctx = w.ctx
            if w.pred is not None:
                if w.pred.status == "ERROR":
                    self.metrics.inference_errors.labels(ctx.profile).inc()
                    log.error("inference_error", asset_id=ctx.asset_id, cycle=w.p.cycle, error=w.pred.error)
                w.flags += [f for f in w.pred.flags if f not in w.flags]
            if t := ctx.health.on_data_quality("OOD" in w.flags):
                w.transitions.append(t)
            wp = w.pred
            if wp is not None and wp.status == "OK" and wp.rul_pred is not None and wp.rul_p10 is not None \
                    and (t := ctx.health.on_prediction(wp.rul_pred, wp.rul_p10)):
                w.transitions.append(t)
            w.state = ctx.health.state.value
        try:  # D: one transaction for the whole batch
            self._persist_batch(live)
        except (SQLAlchemyError, psycopg.Error) as e:
            self.db_ok = False
            log.error("db_write_failed", n=len(live), error=str(e)[:200])
            # Nothing of this batch was stored, but staging already advanced each asset's in-memory state
            # (dedupe sets, streaming features, life, health). Drop those contexts: the next message for the
            # asset rebuilds it from what *is* stored (the restart path, _load_or_register), so a redelivery
            # after the outage is processed exactly once and the features are not fed the same cycle twice.
            with self._assets_lock:
                for c in ctxs:
                    if self.assets.get(c.asset_id) is c:
                        del self.assets[c.asset_id]
                self.metrics.active_assets.set(len(self.assets))
            for w in live:
                w.result = UNAVAILABLE
            return [w.result or UNAVAILABLE for w in work]
        self.db_ok = True
        now = time.time()
        for w in live:  # E: metrics, push, acks
            ctx, p = w.ctx, w.p
            ctx.last_seen = max(ctx.last_seen or 0.0, w.t_recv)
            latency_ms = (now - w.t_recv) * 1000.0
            self.metrics.ingested.labels(w.transport, ctx.profile).inc()
            self.metrics.latency.observe(latency_ms / 1000.0)
            self.stats.add("accepted", latency_ms=latency_ms)
            self._broadcast(ctx, w, latency_ms)
            body: dict[str, Any] = {"status": "accepted", "asset_id": p.asset_id, "cycle": p.cycle,
                                    "prediction_id": w.pred_id, "msg_id": p.msg_id, "state": w.state}
            if w.pred is not None and w.pred.rul_pred is not None:
                body["rul_pred"] = round(w.pred.rul_pred, 2)
            if self.ack is not None and w.transport == "mqtt":
                self.ack(p.site_id, p.asset_id, {**body, "latency_ms": round(latency_ms, 2)})
            w.result = IngestResult("accepted", 200, body)
        return [w.result or UNAVAILABLE for w in work]

    def _stage(self, w: _Item) -> None:
        ctx, p = w.ctx, w.p
        w.flags = ["OOD"] if w.acc.flags else []  # soft range flags (OOD:<sensor>) collapse to one flag
        if p.msg_id in ctx.recent_msg_ids:  # exact re-delivery (QoS 1 retry, client resend)
            w.result = self._duplicate(w)
            return
        if p.cycle == 1 and ctx.last_cycle is not None and ctx.last_cycle > 1:  # new life
            ctx.life_id += 1
            ctx.runtime = AssetRuntime.create(self.registry.bundles[ctx.profile], self.cfg, _phase(ctx.asset_id))
            ctx.seen_cycles.clear()
            ctx.last_cycle = None
            if t := ctx.health.on_new_life():
                w.transitions.append(t)
        if p.cycle in ctx.seen_cycles:
            w.result = self._duplicate(w)
            return
        w.out_of_order = ctx.last_cycle is not None and p.cycle < ctx.last_cycle
        if w.out_of_order:
            w.flags.append("out_of_order")
        elif ctx.last_cycle is not None and p.cycle > ctx.last_cycle + 1:
            w.flags.append("gap")
        if p.ts is not None and abs(p.ts.timestamp() - w.t_recv) > float(self.cfg.get("clock_skew_s", 300)):
            w.flags.append("clock_skew")
        if ctx.last_seen is not None:
            dt_s = max(1e-3, w.t_recv - ctx.last_seen)
            ctx.expected_interval_s = 0.8 * ctx.expected_interval_s + 0.2 * min(dt_s, 60.0)
        if t := ctx.health.on_message():
            w.transitions.append(t)
        w.life_id = ctx.life_id
        w.advance = ctx.last_cycle is None or p.cycle >= ctx.last_cycle
        ctx.seen_cycles.add(p.cycle)
        ctx.recent_msg_ids.append(p.msg_id)
        if not w.out_of_order:  # never re-infer past cycles (docs/02 §2.4)
            ctx.last_cycle = p.cycle
            settings = [float(getattr(p.settings, s)) for s in SETTINGS]
            try:
                w.prep = ctx.runtime.prepare(p.cycle, settings, p.sensors)
            except Exception as e:  # docs/02 §8: telemetry kept, prediction ERROR, state unchanged
                w.pred = PredictionResult("ERROR", p.cycle, error=f"{type(e).__name__}: {e}")
        tr = p.meta.get("true_rul")
        w.true_rul = tr if isinstance(tr, int) and not isinstance(tr, bool) else None

    def _duplicate(self, w: _Item) -> IngestResult:
        self.metrics.duplicates.labels(w.transport).inc()
        self.stats.add("duplicate")
        return IngestResult("duplicate", 200, {"status": "duplicate", "asset_id": w.p.asset_id, "cycle": w.p.cycle})

    def _reject(self, raw: bytes, transport: str, topic_ids: tuple[str, str] | None, rej: Rejection,
                code: int) -> IngestResult:
        asset_id = topic_ids[1] if topic_ids else _peek_asset(raw)
        self.metrics.rejected.labels(transport, rej.reason).inc()
        self.stats.add("rejected", rej.reason)
        try:
            with self.engine.begin() as c:
                c.execute(insert(m.dead_letter).values(
                    transport=transport, topic=None if topic_ids is None else "/".join(topic_ids),
                    asset_id=asset_id, reason=rej.reason, detail=rej.detail[:500], raw=raw[:DEAD_LETTER_RAW_MAX]))
        except SQLAlchemyError as e:
            log.error("dead_letter_write_failed", error=str(e)[:200])
        ctx = self.assets.get(asset_id or "")
        if ctx is not None:
            with ctx.lock:
                ctx.last_reason = rej.reason
                t = ctx.health.on_data_quality(True)
                if t:
                    self._persist_transitions(ctx, [t], ctx.last_cycle or 0, None)
        if self.ack is not None and transport == "mqtt" and topic_ids is not None:
            self.ack(topic_ids[0], topic_ids[1], {"status": "rejected", "reason": rej.reason})
        return IngestResult("rejected", code, {"status": "rejected", "reason": rej.reason, "detail": rej.detail})

    def _take_token(self, ctx: AssetCtx, now: float) -> bool:
        if self.rate <= 0:
            return True
        with ctx.lock:
            # receipt times can be older than token_t when a queue backs up: never refill negatively
            ctx.tokens = min(self.rate, ctx.tokens + max(0.0, now - ctx.token_t) * self.rate)
            ctx.token_t = max(ctx.token_t, now)
            if ctx.tokens < 1.0:
                return False
            ctx.tokens -= 1.0
            return True

    # ------------------------------------------------------------------ asset registry
    def _ctx(self, p: TelemetryPayload, t_recv: float | None = None) -> AssetCtx | None:
        ctx = self.assets.get(p.asset_id)
        if ctx is not None:
            return ctx
        with self._assets_lock:
            ctx = self.assets.get(p.asset_id)
            if ctx is not None:
                return ctx
            try:
                ctx = self._load_or_register(p, t_recv)
            except SQLAlchemyError as e:
                self.db_ok = False
                log.error("asset_register_failed", asset_id=p.asset_id, error=str(e)[:200])
                return None
            self.assets[p.asset_id] = ctx
            self.metrics.active_assets.set(len(self.assets))
            return ctx

    def _load_or_register(self, p: TelemetryPayload, t_recv: float | None = None) -> AssetCtx:
        bundle = self.registry.bundles[p.profile]
        with self.engine.begin() as c:
            row = c.execute(select(m.assets).where(m.assets.c.asset_id == p.asset_id)).mappings().first()
            if row is None:
                c.execute(pg_insert(m.assets).values(
                    asset_id=p.asset_id, site_id=p.site_id, profile=str(p.profile), source=str(p.source),
                    life_id=1, state=State.NEW.value, meta={}).on_conflict_do_nothing())
                row = c.execute(select(m.assets).where(m.assets.c.asset_id == p.asset_id)).mappings().one()
            ctx = AssetCtx(row["asset_id"], row["site_id"], row["profile"], row["source"], row["life_id"],
                           AssetHealth(self.alert_cfg, State(row["state"])),
                           AssetRuntime.create(bundle, self.cfg, _phase(p.asset_id)), tokens=self.rate,
                           # the bucket starts at the message's receipt time, so a backlog that queued up while
                           # storage was down is rate-limited by when it arrived, not all at once now
                           token_t=t_recv or time.time())
            if row["profile"] != str(p.profile):
                log.warning("profile_changed", asset_id=p.asset_id, old=row["profile"], new=str(p.profile))
            # rehydrate rolling state from this life's stored telemetry (restart safety)
            hist = c.execute(
                select(m.telemetry.c.cycle, m.telemetry.c.settings, m.telemetry.c.sensors)
                .where(m.telemetry.c.asset_id == p.asset_id, m.telemetry.c.life_id == row["life_id"])
                .order_by(m.telemetry.c.cycle, m.telemetry.c.received_at)
            ).all()
        last = None
        for cyc, st, se in hist:
            if cyc in ctx.seen_cycles:
                continue
            ctx.seen_cycles.add(cyc)
            if last is not None and cyc < last:
                continue  # out-of-order rows never entered the stream
            ctx.runtime.prepare(cyc, [float(st[s]) for s in SETTINGS], se)
            last = cyc
        ctx.last_cycle = row["last_cycle"]
        if row["state"] == State.OFFLINE.value:
            ctx.health.before_offline = State.WARMING_UP if not hist else None
        if hist:
            log.info("asset_rehydrated", asset_id=p.asset_id, life_id=row["life_id"], cycles=len(hist))
        return ctx

    # ------------------------------------------------------------------ persistence
    def _persist_batch(self, live: list[_Item]) -> None:
        if not live:
            return
        now = datetime.now(UTC)
        tel, preds, pred_items = [], [], []
        for w in live:
            ctx, p = w.ctx, w.p
            received = datetime.fromtimestamp(w.t_recv, UTC)
            tel.append({"asset_id": ctx.asset_id, "life_id": w.life_id, "cycle": p.cycle, "received_at": received,
                        "device_ts": p.ts, "msg_id": p.msg_id, "seq": p.seq, "settings": p.settings.model_dump(),
                        "sensors": dict(p.sensors), "regime": None if w.pred is None else w.pred.regime,
                        "flags": w.flags, "meta": p.meta or None})
            if w.pred is not None:
                pr = w.pred
                preds.append({"asset_id": ctx.asset_id, "life_id": w.life_id, "cycle": p.cycle, "created_at": now,
                              "model_version": self.registry.bundles[ctx.profile].version, "status": pr.status,
                              "rul_pred": pr.rul_pred, "rul_p10": pr.rul_p10, "rul_p90": pr.rul_p90,
                              "health_index": pr.health_index, "state": w.state, "flags": w.flags,
                              "contributors": pr.contributors, "subsystem_scores": pr.subsystem_scores,
                              "latency_ms": (time.time() - w.t_recv) * 1000.0, "true_rul": w.true_rul})
                pred_items.append(w)
        last: dict[str, dict[str, Any]] = {}
        for w in live:  # final asset row per asset (latest message wins)
            row = last.setdefault(w.ctx.asset_id, {"a": w.ctx.asset_id, "adv": None, "true_end": None})
            row.update(state=w.state, seen=datetime.fromtimestamp(w.t_recv, UTC), life=w.life_id,
                       interval=round(w.ctx.expected_interval_s, 4))
            if w.advance:
                row["adv"] = w.p.cycle
            if w.true_rul is not None and w.p.meta.get("eol"):
                row["true_end"] = w.true_rul
        with self.engine.begin() as c:
            # COPY + pre-allocated ids: two round trips for the whole batch instead of one statement per row
            cur = c.connection.driver_connection.cursor()  # type: ignore[union-attr]
            with cur.copy(f"COPY telemetry ({', '.join(TEL_COLS)}) FROM STDIN") as cp:
                for r in tel:
                    cp.write_row([Jsonb(r[k]) if k in JSON_COLS and r[k] is not None else r[k] for k in TEL_COLS])
            if preds:
                cur.execute("SELECT nextval('predictions_prediction_id_seq') FROM generate_series(1, %s)",
                            (len(preds),))
                ids = [row[0] for row in cur.fetchall()]
                with cur.copy(f"COPY predictions (prediction_id, {', '.join(PRED_COLS)}) FROM STDIN") as cp:
                    for pid, r, w in zip(ids, preds, pred_items, strict=True):
                        w.pred_id = pid
                        cp.write_row([pid] + [Jsonb(r[k]) if k in JSON_COLS and r[k] is not None else r[k]
                                              for k in PRED_COLS])
            for w in live:
                if w.transitions:
                    w.alert_rows = self._insert_alerts(c, w.ctx, w.transitions, w.p.cycle,
                                                       None if w.pred is None else w.pred.rul_pred)
            rows = list(last.values())
            c.execute(UPDATE_ASSETS, {k: [r[k] for r in rows] for k in ("a", "state", "seen", "life", "interval",
                                                                         "adv", "true_end")})

    def _insert_alerts(self, c: Any, ctx: AssetCtx, transitions: list[Transition], cycle: int,
                       rul: float | None) -> list[dict[str, Any]]:
        rows = []
        for t in transitions:
            if t.from_state == State.NEW and t.to_state == State.WARMING_UP:
                continue  # docs/02 §3: no alert for the first message
            row = {"asset_id": ctx.asset_id, "life_id": ctx.life_id, "cycle": cycle,
                   "from_state": t.from_state.value, "to_state": t.to_state.value, "rul_pred": rul,
                   "reason": t.reason, "created_at": datetime.now(UTC)}
            row["alert_id"] = c.execute(insert(m.alerts).values(**row).returning(m.alerts.c.alert_id)).scalar_one()
            self.metrics.alerts.labels(t.to_state.value).inc()
            rows.append(row)
        return rows

    def _persist_transitions(self, ctx: AssetCtx, transitions: list[Transition], cycle: int,
                             rul: float | None) -> None:
        try:
            with self.engine.begin() as c:
                rows = self._insert_alerts(c, ctx, transitions, cycle, rul)
                c.execute(update(m.assets).where(m.assets.c.asset_id == ctx.asset_id)
                          .values(state=ctx.health.state.value))
        except SQLAlchemyError as e:
            log.error("alert_write_failed", asset_id=ctx.asset_id, error=str(e)[:200])
            return
        for r in rows:
            self.publish({"type": "alert", "data": _jsonable(r)})
        self.publish({"type": "asset_status", "data": self._status(ctx)})

    # ------------------------------------------------------------------ watchdog + push
    def check_offline(self, now: float | None = None) -> int:
        now = now or time.time()
        factor = float(self.cfg.get("offline_factor", 3))
        n = 0
        for ctx in list(self.assets.values()):
            if ctx.last_seen is None or now - ctx.last_seen <= factor * max(ctx.expected_interval_s, 0.05):
                continue
            with ctx.lock:
                t = ctx.health.on_offline()
                if t:
                    n += 1
                    self._persist_transitions(ctx, [t], ctx.last_cycle or 0, ctx.health.last_rul)
        if now - self._db_sweep_t >= 5.0:
            self._db_sweep_t = now
            n += self._check_offline_db(now, factor)
        return n

    def _check_offline_db(self, now: float, factor: float) -> int:
        """Offline sweep for assets that are not in memory: they stopped sending while the backend was
        down, or their context was evicted after a storage error and no message has come since. Without
        this they would keep their last state forever after a restart."""
        a = m.assets.c
        try:
            with self.engine.connect() as c:
                rows = c.execute(select(a.asset_id, a.life_id, a.state, a.last_cycle, a.last_seen_at,
                                        a.expected_interval_s)
                                 .where(a.state.notin_([State.OFFLINE.value, State.NEW.value]),
                                        a.last_seen_at.isnot(None))).mappings().all()
        except SQLAlchemyError:
            return 0
        n = 0
        for r in rows:
            interval = max(float(r["expected_interval_s"] or 1.0), 0.05)
            if r["asset_id"] in self.assets or now - r["last_seen_at"].timestamp() <= factor * interval:
                continue
            t = AssetHealth(self.alert_cfg, State(r["state"])).on_offline()
            if t is None:
                continue
            row: dict[str, Any] = {
                "asset_id": r["asset_id"], "life_id": r["life_id"], "cycle": r["last_cycle"] or 0,
                "from_state": t.from_state.value, "to_state": t.to_state.value, "rul_pred": None,
                "reason": t.reason, "created_at": datetime.now(UTC)}
            try:
                with self.engine.begin() as c:
                    # only if nothing arrived since the read: a message in between owns the state now
                    done = c.execute(update(m.assets).where(a.asset_id == r["asset_id"], a.state == r["state"],
                                                            a.last_seen_at == r["last_seen_at"])
                                     .values(state=State.OFFLINE.value)).rowcount
                    if not done:
                        continue
                    row["alert_id"] = c.execute(insert(m.alerts).values(**row)
                                                .returning(m.alerts.c.alert_id)).scalar_one()
            except SQLAlchemyError as e:
                log.error("alert_write_failed", asset_id=r["asset_id"], error=str(e)[:200])
                continue
            n += 1
            self.metrics.alerts.labels(State.OFFLINE.value).inc()
            self.publish({"type": "alert", "data": _jsonable(row)})
            self.publish({"type": "asset_status", "data": {
                "asset_id": r["asset_id"], "state": State.OFFLINE.value, "life_id": r["life_id"],
                "last_cycle": r["last_cycle"], "last_seen": r["last_seen_at"].isoformat()}})
        return n

    def _status(self, ctx: AssetCtx) -> dict[str, Any]:
        return {"asset_id": ctx.asset_id, "state": ctx.health.state.value, "life_id": ctx.life_id,
                "last_cycle": ctx.last_cycle,
                "last_seen": None if ctx.last_seen is None else datetime.fromtimestamp(ctx.last_seen, UTC).isoformat()}

    def _broadcast(self, ctx: AssetCtx, w: _Item, latency_ms: float) -> None:
        pred, p = w.pred, w.p
        if pred is not None:
            self.publish({"type": "prediction", "data": {
                "asset_id": ctx.asset_id, "life_id": w.life_id, "cycle": p.cycle, "status": pred.status,
                "rul_pred": pred.rul_pred, "rul_p10": pred.rul_p10, "rul_p90": pred.rul_p90,
                "health_index": pred.health_index, "state": w.state, "flags": w.flags, "true_rul": w.true_rul,
                "ts": datetime.fromtimestamp(w.t_recv, UTC).isoformat(), "latency_ms": round(latency_ms, 2),
                "profile": ctx.profile, "source": ctx.source}})
        for r in w.alert_rows:
            self.publish({"type": "alert", "data": _jsonable(r)})
        if w.alert_rows:
            self.publish({"type": "asset_status", "data": self._status(ctx)})

    def reset(self) -> None:
        """Forget in-memory runtimes (tests / admin)."""
        with self._assets_lock:
            self.assets.clear()
            self.metrics.active_assets.set(0)


def _phase(asset_id: str) -> int:
    return zlib.crc32(asset_id.encode()) % 10


TEL_COLS = ("asset_id", "life_id", "cycle", "received_at", "device_ts", "msg_id", "seq", "settings", "sensors",
            "regime", "flags", "meta")
PRED_COLS = ("asset_id", "life_id", "cycle", "created_at", "model_version", "status", "rul_pred", "rul_p10",
             "rul_p90", "health_index", "state", "flags", "contributors", "subsystem_scores", "latency_ms",
             "true_rul")
JSON_COLS = frozenset({"settings", "sensors", "meta", "contributors", "subsystem_scores"})
UPDATE_ASSETS = text("""
UPDATE assets AS t SET state = u.state, last_seen_at = u.seen, life_id = u.life, expected_interval_s = u.interval,
       last_cycle = COALESCE(u.adv, t.last_cycle), true_rul_at_end = CASE WHEN u.life <> t.life_id THEN u.true_end
                                                     ELSE COALESCE(u.true_end, t.true_rul_at_end) END
FROM unnest(CAST(:a AS text[]), CAST(:state AS text[]), CAST(:seen AS timestamptz[]), CAST(:life AS int[]),
            CAST(:interval AS real[]), CAST(:adv AS int[]), CAST(:true_end AS int[]))
     AS u(a, state, seen, life, interval, adv, true_end)
WHERE t.asset_id = u.a""")


def _peek_asset(raw: bytes) -> str | None:
    try:
        v = json.loads(raw).get("asset_id")
        return v if isinstance(v, str) else None
    except (ValueError, AttributeError, UnicodeDecodeError):
        return None


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in row.items()}
