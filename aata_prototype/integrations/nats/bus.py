"""
Store-and-forward bus: a durable, ordered message log with an ack cursor.

Interface every backend preserves (JetStream semantics):
  * `publish(record)` -- durably append a record (persists across disconnection).
  * `pending()` -- records published but not yet delivered (in FIFO order).
  * `drain()` -- return all pending records AND advance the ack cursor (custody transfer).
  * `depth` -- total durable records.

FIFO order is load-bearing: the DDIL replay re-chains records into the authoritative
recorder in publish order, and out-of-order delivery would break the zero-gap invariant.

`InMemoryBus` (default, offline, hermetic) needs no dependencies. `NatsJetStreamBus` is
opt-in (needs `nats-py` + a running JetStream server); it is lazily imported and not
exercised offline / in CI.
"""
from __future__ import annotations

import importlib.util
import json
import os
from abc import ABC, abstractmethod


def _frozen(record: dict) -> dict:
    return json.loads(json.dumps(record, sort_keys=True))


class StoreForwardBus(ABC):
    name: str = "bus"

    @abstractmethod
    def publish(self, record: dict) -> None: ...

    @abstractmethod
    def pending(self) -> list[dict]: ...

    @abstractmethod
    def drain(self) -> list[dict]: ...

    @property
    @abstractmethod
    def depth(self) -> int: ...


class InMemoryBus(StoreForwardBus):
    """Hermetic, dependency-free JetStream stand-in: an ordered durable log + ack cursor."""
    name = "in-memory-bus"

    def __init__(self):
        self._log: list[dict] = []       # durable, append-only, FIFO
        self._acked = 0                  # delivery cursor (custody transferred up to here)

    def publish(self, record: dict) -> None:
        self._log.append(_frozen(record))

    def pending(self) -> list[dict]:
        return [_frozen(r) for r in self._log[self._acked:]]

    def drain(self) -> list[dict]:
        out = self.pending()
        self._acked = len(self._log)     # custody transfer: ack everything delivered
        return out

    @property
    def depth(self) -> int:
        return len(self._log)


class NatsJetStreamBus(StoreForwardBus):
    """Opt-in: a real NATS JetStream stream as the store-and-forward transport.

    Requires `nats-py` and a running JetStream server. Records are published to a stream
    subject and consumed (with ack) on drain. Runs the async client on a private event loop
    so the caller stays synchronous. Lazily imported; never touched offline / in CI.
    """
    name = "nats-jetstream"

    def __init__(self, servers: str, subject: str = "aata.ddil.ledger",
                 stream: str = "AATA_DDIL"):
        import asyncio                                          # lazy
        import nats                                             # noqa: F401 (import check)
        self._asyncio = asyncio
        self._servers = servers
        self._subject = subject
        self._stream = stream
        self._loop = asyncio.new_event_loop()
        self._loop.run_until_complete(self._ensure_stream())

    async def _connect(self):
        import nats
        nc = await nats.connect(self._servers)
        return nc, nc.jetstream()

    async def _ensure_stream(self):
        nc, js = await self._connect()
        try:
            await js.add_stream(name=self._stream, subjects=[self._subject])
        except Exception:
            pass                                               # already exists
        finally:
            await nc.close()

    def publish(self, record: dict) -> None:
        async def _pub():
            nc, js = await self._connect()
            try:
                await js.publish(self._subject, json.dumps(record, sort_keys=True).encode())
            finally:
                await nc.close()
        self._loop.run_until_complete(_pub())

    def _fetch(self, ack: bool) -> list[dict]:
        async def _f():
            nc, js = await self._connect()
            out = []
            try:
                sub = await js.pull_subscribe(self._subject, durable="aata-reconcile")
                while True:
                    try:
                        msgs = await sub.fetch(50, timeout=1)
                    except Exception:
                        break
                    for m in msgs:
                        out.append(json.loads(m.data.decode()))
                        if ack:
                            await m.ack()
                    if len(msgs) < 50:
                        break
            finally:
                await nc.close()
            return out
        return self._loop.run_until_complete(_f())

    def pending(self) -> list[dict]:
        return self._fetch(ack=False)

    def drain(self) -> list[dict]:
        return self._fetch(ack=True)

    @property
    def depth(self) -> int:
        async def _d():
            nc, js = await self._connect()
            try:
                info = await js.stream_info(self._stream)
                return info.state.messages
            finally:
                await nc.close()
        return self._loop.run_until_complete(_d())


def enabled() -> bool:
    """True only if a real bus is opted in and its client lib is importable."""
    return os.getenv("AATA_NATS") is not None and importlib.util.find_spec("nats") is not None


def bus() -> StoreForwardBus:
    """The configured bus: real JetStream if opted in + available, else in-memory."""
    if enabled():
        return NatsJetStreamBus(os.environ.get("AATA_NATS", "nats://localhost:4222"))
    return InMemoryBus()
