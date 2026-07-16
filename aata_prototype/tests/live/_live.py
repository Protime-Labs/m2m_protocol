"""
Shared helpers for the OPT-IN live validation modules (S3 Object-Lock, NATS JetStream).

These run ONLY via `run_live.py` with real services up (docker-compose.yml) and `AATA_LIVE=1`.
`LiveSkip` signals an absent prerequisite (a lib, an env var, or an unreachable service) --
that is *not* a failure; the runner reports it and moves on. A live module raises AssertionError
only when a real service is present but its guarantee did not hold.
"""
from __future__ import annotations

import os
import sys

# Make `aata` / `integrations` importable when a module is run standalone or via run_live.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


class LiveSkip(Exception):
    """A prerequisite for a live check is absent (service/lib/env). Not a failure."""


def require(cond: bool, msg: str) -> None:
    if not cond:
        raise LiveSkip(msg)


def run_id() -> str:
    """A per-run namespace so repeated runs don't collide on bucket keys / JetStream cursors."""
    return os.getenv("AATA_LIVE_RUN", "0")
