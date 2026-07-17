"""
Supabase publisher -- the opt-in cloud sink for ConsoleFeed (standard integration
discipline: offline default, env-gated, zero new dependencies).

  enabled()  <=>  AATA_CONSOLE_URL + AATA_CONSOLE_ANON + AATA_CONSOLE_WRITE_KEY are set.

`SupabaseSink` implements the same sink interface as the JSONL spool and is NON-BLOCKING:
`write(line)` only appends to a bounded in-memory queue; a daemon thread batches and POSTs
to the `console_ingest` RPC (PostgREST) via stdlib urllib. Failures retry with the buffer
intact; overflow drops oldest-with-counter. Nothing here can raise into the estate -- and
the enforcement path never waits on the network (the console is a read-model; a console
outage must never gate an action).

Auth model: the anon key (public) authenticates the transport; the WRITE KEY (private,
held server-side in `console_config`, rotatable with one UPDATE) authorizes ingestion.
Neither key grants reads (RLS: `authenticated` users only).

Backfill/smoke CLI:  python -m console.publish <spool.jsonl>
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from collections import deque

BATCH_MAX = 200          # events per POST
FLUSH_SECS = 1.0         # max buffering delay
BUFFER_MAX = 10_000      # bounded store-and-forward; beyond -> drop oldest, count


def enabled() -> bool:
    return all(os.getenv(k) for k in
               ("AATA_CONSOLE_URL", "AATA_CONSOLE_ANON", "AATA_CONSOLE_WRITE_KEY"))


def _default_transport(url: str, anon: str, body: bytes) -> int:
    """One RPC POST. Returns HTTP status. Raises on transport errors (caught by caller)."""
    req = urllib.request.Request(
        url + "/rest/v1/rpc/console_ingest",
        data=body,
        headers={"Content-Type": "application/json", "apikey": anon,
                 "Authorization": f"Bearer {anon}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status


class SupabaseSink:
    """Feed-compatible sink: buffered, batched, background-flushed, never raises."""

    def __init__(self, url: str, anon: str, write_key: str,
                 transport=None, start_thread: bool = True):
        self.url = url.rstrip("/")
        self._anon = anon
        self._write_key = write_key
        self._transport = transport or _default_transport
        self._buf: deque = deque()
        self._lock = threading.Lock()
        self._closed = False
        self.sent = 0
        self.dropped = 0
        self.last_error = ""
        self._thread = None
        if start_thread:
            self._thread = threading.Thread(target=self._loop, daemon=True,
                                            name="aata-console-publish")
            self._thread.start()

    # -- sink interface (called under the feed's lock; must be O(1) and non-blocking) --

    def write(self, line: str) -> None:
        with self._lock:
            if len(self._buf) >= BUFFER_MAX:
                self._buf.popleft()                     # drop OLDEST; newest state wins
                self.dropped += 1
            self._buf.append(line)

    def close(self) -> None:
        self._closed = True
        self.flush()

    # -- flushing ----------------------------------------------------------------------

    def _take_batch(self) -> list:
        with self._lock:
            n = min(len(self._buf), BATCH_MAX)
            return [self._buf.popleft() for _ in range(n)]

    def _requeue(self, batch: list) -> None:
        with self._lock:
            for line in reversed(batch):
                if len(self._buf) >= BUFFER_MAX:
                    self.dropped += 1
                    break
                self._buf.appendleft(line)

    def flush(self) -> int:
        """Drain what's buffered now. Returns events sent. Never raises."""
        total = 0
        while True:
            batch = self._take_batch()
            if not batch:
                return total
            events = []
            for line in batch:
                try:
                    events.append(json.loads(line))
                except Exception:
                    self.dropped += 1                   # malformed line: count, move on
            if not events:
                continue
            body = json.dumps({"batch": events, "write_key": self._write_key}).encode()
            try:
                status = self._transport(self.url, self._anon, body)
                if status >= 300:
                    raise IOError(f"HTTP {status}")
                self.sent += len(events)
                total += len(events)
            except Exception as e:                      # keep the data; retry next flush
                self.last_error = f"{type(e).__name__}: {e}"
                self._requeue(batch)
                return total

    def _loop(self) -> None:
        while not self._closed:
            time.sleep(FLUSH_SECS)
            self.flush()


def sink_from_env():
    """The env-gated sink, or None (offline default -> caller uses the JSONL spool)."""
    if not enabled():
        return None
    return SupabaseSink(os.environ["AATA_CONSOLE_URL"],
                        os.environ["AATA_CONSOLE_ANON"],
                        os.environ["AATA_CONSOLE_WRITE_KEY"])


def upload_spool(path: str, sink: SupabaseSink | None = None) -> dict:
    """Backfill an existing JSONL spool file into the console. Returns a summary."""
    s = sink or sink_from_env()
    if s is None:
        return {"ok": False, "reason": "publisher not enabled (set AATA_CONSOLE_* env)"}
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                s.write(line)
                n += 1
    sent = s.flush()
    return {"ok": s.last_error == "" and sent > 0, "queued": n, "sent": s.sent,
            "dropped": s.dropped, "last_error": s.last_error}


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("usage: python -m console.publish <spool.jsonl>")
        raise SystemExit(2)
    print(json.dumps(upload_spool(sys.argv[1]), indent=2))
