"""
C9 -- Flight Recorder.  Control: AATA-OB-01.

Production tooling: immudb or S3 Object-Lock WORM store + a custom hash-chain
writer with periodic external Merkle anchoring; the PRE-ACTUATION write hook
lives in the C1 gateway. In DDIL/Isolated mode this is the local reconciliation
ledger (SQLite hash-chain) that replays on reconnect (W4).

The load-bearing guarantee (W1 steps 6-7, the whole architecture's discipline):

    "no-evidence-no-action" -- the immutable decision record is appended to the
    hash chain and ACKed BEFORE the action is allowed to proceed. If the recorder
    is unreachable, kinetic actions do not proceed.

This module gives you:
  * append-only, hash-chained records (tamper-evident; break one link, break all)
  * an explicit ACK that the gateway must obtain before release
  * verify() to prove the chain reconciles with zero gaps (W4 pass-criterion)
  * an injectable "unreachable" flag to test the fail-closed path
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .clock import CLOCK

GENESIS = "0" * 64


def _hash(prev: str, payload: dict[str, Any]) -> str:
    blob = prev.encode() + json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


@dataclass
class Record:
    seq: int
    t: int
    kind: str                     # "birth" | "pre-actuation" | "result" | "hygiene" | "mode"
    payload: dict[str, Any]
    prev_hash: str
    this_hash: str = ""

    def finalize(self) -> "Record":
        self.this_hash = _hash(self.prev_hash, {
            "seq": self.seq, "t": self.t, "kind": self.kind, "payload": self.payload,
        })
        return self


class RecorderUnreachable(Exception):
    """Raised when a pre-actuation write cannot be ACKed (fail-closed trigger)."""


@dataclass
class FlightRecorder:
    """Append-only hash-chained WORM ledger."""
    name: str = "authoritative"
    records: list[Record] = field(default_factory=list)
    online: bool = True           # flip to False to simulate an unreachable recorder

    @property
    def head(self) -> str:
        return self.records[-1].this_hash if self.records else GENESIS

    def append(self, kind: str, payload: dict[str, Any]) -> Record:
        """
        Append + ACK. Returns the finalized record (the ACK). Raises
        RecorderUnreachable if offline -- the caller (gateway) must treat that
        as "evidence not written" and refuse to actuate kinetic classes.
        """
        if not self.online:
            raise RecorderUnreachable(f"recorder '{self.name}' unreachable")
        rec = Record(
            seq=len(self.records),
            t=CLOCK.tick(),
            kind=kind,
            payload=payload,
            prev_hash=self.head,
        ).finalize()
        self.records.append(rec)
        return rec

    def verify(self) -> tuple[bool, str]:
        """Re-walk the chain: every link must reconcile with zero gaps."""
        prev = GENESIS
        for i, rec in enumerate(self.records):
            if rec.seq != i:
                return False, f"seq gap at index {i}: record claims seq {rec.seq}"
            if rec.prev_hash != prev:
                return False, f"broken link at seq {rec.seq}: prev_hash mismatch"
            expect = _hash(rec.prev_hash, {
                "seq": rec.seq, "t": rec.t, "kind": rec.kind, "payload": rec.payload,
            })
            if expect != rec.this_hash:
                return False, f"tampered record at seq {rec.seq}: hash mismatch"
            prev = rec.this_hash
        return True, f"chain intact: {len(self.records)} records, head {self.head[:12]}..."

    def merkle_root(self) -> str:
        """External anchor value -- what you'd publish to an immutable anchor."""
        leaves = [r.this_hash for r in self.records] or [GENESIS]
        while len(leaves) > 1:
            nxt = []
            for i in range(0, len(leaves), 2):
                a = leaves[i]
                b = leaves[i + 1] if i + 1 < len(leaves) else a
                nxt.append(hashlib.sha256((a + b).encode()).hexdigest())
            leaves = nxt
        return leaves[0]
