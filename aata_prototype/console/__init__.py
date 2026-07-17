"""
M2M fleet console -- the estate-side capture layer for the hosted single pane.

`ConsoleFeed` (feed.py) turns the overlay's existing seams (recorder tee via
`Backends.recorder_factory`/`wrap_ledger`, gateway observer via `Backends.observers`)
into one ordered event stream keyed `(src, agent)`; sinks are a JSONL spool (offline
default) or the opt-in Supabase publisher (publish.py). `Registry` (registry.py) is the
deterministic CI mirror of the console's posture logic; the authoritative posture/report
logic lives in Supabase SQL views.

The console is a READ-MODEL: it never sits on the enforcement path, and a feed fault can
never affect a gateway decision (blanket-hardened emit; see feed.py).
"""
from console.feed import ConsoleFeed
from console.registry import AgentState, Registry

__all__ = ["ConsoleFeed", "Registry", "AgentState"]
