"""
NATS JetStream store-and-forward for the DDIL reconciliation ledger (C8 / W4).

While Degraded/Isolated the overlay accrues evidence to a LOCAL ledger (store-and-forward);
on reconnect it replays into the authoritative recorder with custody transfer -- one
continuous audit chain, zero evidence loss. This package makes that transport a real
durable bus (NATS JetStream leaf node) instead of an in-process list, and replays FROM the
bus into the authoritative chain, preserving the reconciliation invariants pinned by
tests/test_ddil.py (FIFO order, zero-gap replay, origin provenance, the re-attestation
reentry gate).

Offline by default: an in-memory durable bus (no `nats` import) so the whole suite stays
offline and deterministic. A real NATS JetStream bus is opt-in via AATA_NATS + `nats-py`.
"""
from integrations.nats.bus import InMemoryBus, StoreForwardBus, bus, enabled
from integrations.nats.forwarder import (
    ForwardingLedger,
    LedgerForwarder,
    make_forwarding,
)

__all__ = [
    "StoreForwardBus", "InMemoryBus", "bus", "enabled",
    "LedgerForwarder", "ForwardingLedger", "make_forwarding",
]
