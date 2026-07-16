"""
Persist the flight-recorder hash chain to a WORM backend, anchor it, and round-trip it.

`WormArchiver` mirrors an existing chain to a write-once store, anchors the Merkle root,
and can `load_and_verify()` -- reconstruct the chain FROM the store and re-verify it,
proving the durable copy is intact and tamper-evident independently of the live process.

`DurableRecorder` is the "behind the recorder" form: it wraps the in-memory FlightRecorder
and write-throughs every `append` to the WORM backend at write time -- while preserving the
in-memory recorder's synchronous fail-closed ACK (append still raises `RecorderUnreachable`
when the recorder is offline, so no-evidence-no-action is untouched).
"""
from __future__ import annotations

from aata.recorder import FlightRecorder, Record
from integrations.worm.backend import WormBackend, worm_backend


def _rec_to_dict(r: Record) -> dict:
    return {"seq": r.seq, "t": r.t, "kind": r.kind, "payload": r.payload,
            "prev_hash": r.prev_hash, "this_hash": r.this_hash}


def _dict_to_rec(d: dict) -> Record:
    return Record(seq=d["seq"], t=d["t"], kind=d["kind"], payload=d["payload"],
                  prev_hash=d["prev_hash"], this_hash=d["this_hash"])


class WormArchiver:
    def __init__(self, backend: WormBackend | None = None):
        self.backend = backend or worm_backend()

    def archive(self, recorder: FlightRecorder) -> int:
        """Mirror every record to the WORM store (write-once). Returns records written."""
        n = 0
        for r in recorder.records:
            self.backend.put_record(r.seq, _rec_to_dict(r))
            n += 1
        return n

    def anchor(self, recorder: FlightRecorder, meta: dict | None = None) -> str:
        """Write the current Merkle root to the immutable anchor location."""
        root = recorder.merkle_root()
        self.backend.put_anchor(root, {"records": len(recorder.records), **(meta or {})})
        return root

    def load_and_verify(self) -> dict:
        """Reconstruct the chain from WORM and re-verify it (durability + tamper check)."""
        recs = [_dict_to_rec(d) for d in self.backend.all_records()]
        rebuilt = FlightRecorder(name="worm-reload", records=recs)
        ok, msg = rebuilt.verify()
        return {"ok": ok, "msg": msg, "records": len(recs),
                "merkle_root": rebuilt.merkle_root(),
                "anchors": self.backend.anchors()}


class DurableRecorder:
    """A FlightRecorder that also write-throughs each append to a WORM backend.

    Delegates the FlightRecorder interface to an inner in-memory recorder (which keeps the
    hash chain and the synchronous fail-closed ACK), then mirrors the finalized record to
    the WORM store. Drop it in via `make_durable(estate)`.
    """
    def __init__(self, inner: FlightRecorder, backend: WormBackend | None = None):
        self._inner = inner
        self.backend = backend or worm_backend()

    # -- FlightRecorder interface --------------------------------------------
    def append(self, kind: str, payload: dict) -> Record:
        rec = self._inner.append(kind, payload)          # raises RecorderUnreachable if offline
        self.backend.put_record(rec.seq, _rec_to_dict(rec))   # durable write-through
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


def make_durable(estate, backend: WormBackend | None = None) -> DurableRecorder:
    """Upgrade an estate's authoritative recorder to write-through to a WORM backend.

    Mirrors any pre-existing records first, then re-points `estate.authoritative` and
    `estate.ddil.authoritative` at the durable recorder (the gateway/hygiene read the
    active recorder through `ddil`, so the swap propagates).
    """
    backend = backend or worm_backend()
    durable = DurableRecorder(estate.authoritative, backend)
    for r in estate.authoritative.records:               # mirror what's already there
        backend.put_record(r.seq, _rec_to_dict(r))
    estate.authoritative = durable
    estate.ddil.authoritative = durable
    return durable
