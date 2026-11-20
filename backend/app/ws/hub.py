"""WebSocket push hub (docs/04 §5.5). `publish` is thread-safe: ingest runs in worker / paho threads."""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass
from typing import Any

from app.metrics import Metrics

QUEUE_MAX = 1000


@dataclass(eq=False)
class Client:
    queue: asyncio.Queue[str]
    asset: str | None = None
    dropped: int = 0


class Hub:
    def __init__(self, metrics: Metrics) -> None:
        self.clients: set[Client] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.metrics = metrics

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def connect(self, asset: str | None = None) -> Client:
        c = Client(asyncio.Queue(QUEUE_MAX), asset)
        self.clients.add(c)
        self.metrics.ws_clients.set(len(self.clients))
        return c

    def disconnect(self, c: Client) -> None:
        self.clients.discard(c)
        self.metrics.ws_clients.set(len(self.clients))

    def publish(self, event: dict[str, Any]) -> None:
        if self.loop is None or not self.clients:
            return
        msg = json.dumps(event, default=str, allow_nan=False)
        asset = (event.get("data") or {}).get("asset_id")
        with contextlib.suppress(RuntimeError):  # loop closed during shutdown
            self.loop.call_soon_threadsafe(self._fanout, msg, asset)

    def _fanout(self, msg: str, asset: str | None) -> None:
        for c in list(self.clients):
            if c.asset and asset and c.asset != asset:
                continue
            try:
                c.queue.put_nowait(msg)
            except asyncio.QueueFull:  # slow client: drop, it refetches the REST snapshot on reconnect
                c.dropped += 1
