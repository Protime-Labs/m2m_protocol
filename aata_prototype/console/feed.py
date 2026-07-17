"""
ConsoleFeed -- the estate-side event capture for the M2M fleet console.

Turns the overlay's existing seams into a single, ordered event stream keyed by
`(src, agent)`:

  * a RECORDER TEE (`feed.tee(inner)` / `feed.recorder_factory()` / `feed.wrap_ledger()`)
    mirrors every finalized C9 record -- `birth`, `pre-actuation`, `result`, `hygiene`,
    `task-outcome`, `mode`, `reconciled:*` -- so an agent is registered in the console the
    moment W2 birth writes its record, on either the authoritative recorder or the DDIL
    reconciliation ledger;
  * a GATEWAY OBSERVER (`feed.observer()`) captures every call OUTCOME -- including the
    early denies (revoked / expired / forged / unknown tool / fail-closed) which write no
    C9 record -- plus IOC kinds.

Events go to a sink. The offline default is a JSONL SPOOL file (one per process run, so
concurrent estates never share a writer); `console/publish.py` adds the opt-in Supabase
sink behind the same interface.

The feed is CONSTITUTIONALLY UNABLE to affect the hot path: every emit is wrapped in a
blanket try/except that only increments `dropped` (surfaced via periodic `feed-health`
events); writes are single `f.write` + flush under a lock with explicit UTF-8. The tee
mirrors a record only AFTER the inner append succeeded -- an append that raised
(`RecorderUnreachable`, fail-closed) is never spooled, and the tee proxies the FULL
FlightRecorder surface incl. the `online` setter so outage drills keep working.

Event line schema (one JSON object per line):
    {"src": <unique run id>, "kind": <event kind>, "agent": <agent_id or null>,
     "seq": <recorder seq or null>, "t": <logical tick or null>,
     "ts": <wall-clock unix seconds>, "data": {...}}
`src` = label + pid + wall-start, so two runs that both birth "rover-01" never merge.
`ts` is wall clock (liveness must never use the logical CLOCK, which freezes when the
estate idles); `t`/`seq` are kept for evidence correlation.
"""
from __future__ import annotations

import json
import os
import threading
import time

FEED_HEALTH_EVERY = 200          # emit a feed-health event every N events


class _SpoolSink:
    """Append-only JSONL file sink (the offline default)."""

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._f = open(path, "a", encoding="utf-8")

    def write(self, line: str) -> None:
        self._f.write(line + "\n")
        self._f.flush()

    def close(self) -> None:
        try:
            self._f.close()
        except Exception:
            pass


class ConsoleFeed:
    def __init__(self, spool_dir: str, label: str = "estate", sink=None):
        self.src = f"{label}-{os.getpid()}-{int(time.time())}"
        self.dropped = 0
        self.emitted = 0
        self.last_error = ""
        self._lock = threading.Lock()
        self._sink = None
        try:
            self._sink = sink if sink is not None else _SpoolSink(
                os.path.join(spool_dir, f"{self.src}.jsonl"))
        except Exception as e:                          # sink cannot open -> feed degrades, never raises
            self.dropped += 1
            self.last_error = f"{type(e).__name__}: {e}"

    # ------------------------------------------------------------------ emit (hardened)

    def _emit(self, kind: str, agent, seq, t, data: dict) -> None:
        """Emit one event. NEVER raises -- a console fault must not touch enforcement."""
        try:
            line = json.dumps(
                {"src": self.src, "kind": kind, "agent": agent, "seq": seq, "t": t,
                 "ts": time.time(), "data": data},
                separators=(",", ":"), default=str)
            with self._lock:
                if self._sink is None:
                    raise IOError("sink unavailable")
                self._sink.write(line)
                self.emitted += 1
                if self.emitted % FEED_HEALTH_EVERY == 0:
                    self._sink.write(json.dumps(
                        {"src": self.src, "kind": "feed-health", "agent": None,
                         "seq": None, "t": None, "ts": time.time(),
                         "data": {"emitted": self.emitted, "dropped": self.dropped,
                                  "last_error": self.last_error}},
                        separators=(",", ":")))
        except Exception as e:                          # blanket by design (see module docstring)
            self.dropped += 1
            self.last_error = f"{type(e).__name__}: {e}"

    # ------------------------------------------------------------------ attachment points

    def tee(self, inner) -> "_TeeRecorder":
        """Wrap an existing FlightRecorder-like so every append is mirrored to the feed."""
        return _TeeRecorder(inner, self)

    def recorder_factory(self):
        """A Backends.recorder_factory producing a feed-teed authoritative recorder."""
        from aata.recorder import FlightRecorder
        return lambda: self.tee(FlightRecorder(name="authoritative"))

    def wrap_ledger(self):
        """A Backends.wrap_ledger teeing the DDIL reconciliation ledger."""
        return lambda ledger: self.tee(ledger)

    def observer(self):
        """A gateway observer spooling every call outcome (incl. early denies) + IOCs."""
        def observe(out, agent_id, tool_name, canon):
            self._emit("call", agent_id, out.evidence_seq, None, {
                "tool": tool_name,
                "decision": out.decision,
                "allowed": out.allowed,
                "reason": out.reason,
                "evidence_seq": out.evidence_seq,
                "iocs": [i.kind for i in out.iocs],
            })
        observe.feed = self
        return observe

    def backends(self, **extra):
        """A ready-to-use core `Backends` wired to this feed (compose extras via kwargs)."""
        from aata.scenario import Backends
        observers = [self.observer()] + list(extra.pop("observers", []))
        return Backends(recorder_factory=self.recorder_factory(),
                        wrap_ledger=self.wrap_ledger(),
                        observers=observers,
                        active=["console"] + list(extra.pop("active", [])),
                        **extra)

    def close(self) -> None:
        if self._sink is not None:
            self._sink.close()


class _TeeRecorder:
    """FlightRecorder write-through: full proxy + feed mirror AFTER a successful append.

    Template: integrations/worm/archiver.py::DurableRecorder. The `online` setter is
    load-bearing -- outage drills set it directly on the active recorder.
    """

    def __init__(self, inner, feed: ConsoleFeed):
        self._inner = inner
        self._feed = feed

    def append(self, kind: str, payload: dict):
        rec = self._inner.append(kind, payload)          # raises RecorderUnreachable if offline
        self._feed._emit(kind, payload.get("agent"), rec.seq, rec.t, payload)
        return rec

    def verify(self):
        return self._inner.verify()

    def merkle_root(self) -> str:
        return self._inner.merkle_root()

    @property
    def head(self):
        return self._inner.head

    @property
    def records(self):
        return self._inner.records

    @property
    def name(self):
        return self._inner.name

    @property
    def online(self):
        return self._inner.online

    @online.setter
    def online(self, v) -> None:
        self._inner.online = v
