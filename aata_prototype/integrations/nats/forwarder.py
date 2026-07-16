"""
Bridge the DDIL ledger and a store-and-forward bus, and replay FROM the bus with custody
transfer.

`LedgerForwarder.forward(ledger)` publishes ledger records to the bus (the durable
store-and-forward transport used while isolated). `LedgerForwarder.replay(authoritative,
fleet_reattests_ok)` is the reconnect path: the reentry gate + custody-transfer replay,
draining the bus (FIFO) and re-chaining each record into the authoritative recorder as
`reconciled:<kind>` with origin provenance -- the same semantics as `ddil.reconcile`, but
sourced from the durable bus. `ForwardingLedger` / `make_forwarding` is the write-through
form: every ledger `append` mirrors to the bus at write time while preserving the
synchronous fail-closed ACK.
"""
from __future__ import annotations

from aata.recorder import FlightRecorder, Record
from integrations.nats.bus import StoreForwardBus, bus as default_bus


def _rec_to_dict(r: Record) -> dict:
    return {"seq": r.seq, "t": r.t, "kind": r.kind, "payload": r.payload,
            "prev_hash": r.prev_hash, "this_hash": r.this_hash}


class LedgerForwarder:
    def __init__(self, bus: StoreForwardBus | None = None):
        self.bus = bus or default_bus()

    def forward(self, ledger: FlightRecorder) -> int:
        """Publish every ledger record to the durable bus (store-and-forward)."""
        n = 0
        for r in ledger.records:
            self.bus.publish(_rec_to_dict(r))
            n += 1
        return n

    def replay(self, authoritative: FlightRecorder, fleet_reattests_ok: bool = True) -> dict:
        """Reconnect: reentry gate, then custody-transfer replay FROM the bus (FIFO)."""
        if not fleet_reattests_ok:
            return {"ok": False, "reason": "fleet re-attestation failed -- no silent rejoin",
                    "replayed": 0}
        replayed = 0
        for rec in self.bus.drain():                          # FIFO; advances the ack cursor
            authoritative.append("reconciled:" + rec["kind"], {
                "origin": "nats-jetstream",
                "origin_seq": rec["seq"],
                "origin_hash": rec["this_hash"],
                "payload": rec["payload"],
            })
            replayed += 1
        return {"ok": True, "replayed": replayed, "auth_head": authoritative.head[:12] + "..."}


class ForwardingLedger:
    """A FlightRecorder that also publishes each append to a store-and-forward bus.

    Delegates the recorder interface to an inner in-memory ledger (which keeps the hash
    chain and the synchronous fail-closed ACK), then mirrors the finalized record to the
    bus. Drop it in via `make_forwarding(estate)`.
    """
    def __init__(self, inner: FlightRecorder, bus: StoreForwardBus | None = None):
        self._inner = inner
        self.bus = bus or default_bus()

    def append(self, kind: str, payload: dict) -> Record:
        rec = self._inner.append(kind, payload)               # raises RecorderUnreachable if offline
        self.bus.publish(_rec_to_dict(rec))                   # durable store-and-forward
        return rec

    def verify(self):
        return self._inner.verify()

    def merkle_root(self) -> str:
        return self._inner.merkle_root()

    @property
    def head(self) -> str:
        return self._inner.head

    @property
    def records(self):
        return self._inner.records

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def online(self) -> bool:
        return self._inner.online

    @online.setter
    def online(self, v: bool) -> None:
        self._inner.online = v


def make_forwarding(estate, bus: StoreForwardBus | None = None) -> ForwardingLedger:
    """Upgrade an estate's DDIL ledger to publish each record to a store-and-forward bus.

    `ddil.active_recorder` returns the ledger while Degraded/Isolated, so the swap makes
    isolated-mode evidence flow onto the durable bus as it is written.
    """
    bus = bus or default_bus()
    forwarding = ForwardingLedger(estate.ddil.ledger, bus)
    for r in estate.ddil.ledger.records:                      # mirror what's already there
        bus.publish(_rec_to_dict(r))
    estate.ddil.ledger = forwarding
    return forwarding
