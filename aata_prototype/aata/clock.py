"""
Deterministic logical clock.

The prototype avoids wall-clock time so that runs are reproducible and the
evidence chain is byte-stable across machines. In production every timestamp
here is a real monotonic clock reading; the *ordering* guarantees the chain
relies on do not depend on which clock is used.
"""
from __future__ import annotations

import threading


class LogicalClock:
    """Monotonic tick counter. One shared instance drives the whole demo."""

    def __init__(self, start: int = 0) -> None:
        self._t = start
        self._lock = threading.Lock()

    def tick(self, dt: int = 1) -> int:
        with self._lock:
            self._t += dt
            return self._t

    def now(self) -> int:
        return self._t


# A single process-wide clock keeps evidence timestamps consistent.
CLOCK = LogicalClock()
