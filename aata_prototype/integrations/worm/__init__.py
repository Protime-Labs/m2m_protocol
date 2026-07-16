"""
WORM (write-once-read-many) evidence store for the AATA flight recorder (C9).

Faithful to the spec's C9 ("immudb / S3 Object-Lock WORM + hash-chain + Merkle anchor"):
the hash chain in `aata/recorder.py` stays the INTEGRITY spine (so every load-bearing
invariant is preserved -- synchronous fail-closed ACK, verify(), merkle, the logical
clock); this package adds durable, **write-once** persistence + an external Merkle anchor
on top, and can round-trip the chain back out of the store and re-verify it.

Offline by default: an in-memory write-once backend (no external deps) so the whole suite
stays offline and deterministic. Real backends (S3 Object-Lock, immudb) are opt-in via
AATA_WORM + their client libraries.
"""
from integrations.worm.backend import (
    InMemoryWormBackend,
    LocalFileWormBackend,
    WormBackend,
    WormViolation,
    enabled,
    worm_backend,
)
from integrations.worm.archiver import DurableRecorder, WormArchiver, make_durable

__all__ = [
    "WormBackend", "InMemoryWormBackend", "LocalFileWormBackend", "WormViolation",
    "worm_backend", "enabled",
    "WormArchiver", "DurableRecorder", "make_durable",
]
