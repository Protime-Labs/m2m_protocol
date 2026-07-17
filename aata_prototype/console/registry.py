"""
Slim console registry -- deterministic spool replay for CI.

Rebuilds console state from ConsoleFeed spool files: the live-agent roster keyed
`(src, agent)` (two estates that both birth "rover-01" never merge), per-agent rollups,
and a posture verdict. In the hosted console the AUTHORITATIVE posture/report logic lives
in Supabase SQL views over the same events; this Python mirror exists so CI can validate
the event-stream semantics offline -- it is a test harness, not the product path.

Ingestion is incremental and Windows-safe: files are read in BINARY mode from a remembered
per-file byte offset, and only complete `\n`-terminated lines are parsed -- a partially
flushed tail line stays pending until its newline arrives (never skipped past, never
crashed on). Bad lines are counted, not fatal. The registry assigns its own monotonic
event cursor at ingest (spool fields contain no valid global cursor: `seq` is
per-recorder, `t` is a per-process logical clock).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

# hygiene tiers: 1 Narrow, 2 Isolate, 3 Revoke, 4 Rebuild
_STALE_AFTER_S = 300.0            # no event for this long (wall clock) -> stale


@dataclass
class AgentState:
    src: str
    agent: str
    first_seen_ts: float = 0.0
    last_ts: float = 0.0
    birth: dict = field(default_factory=dict)
    allow_count: int = 0
    deny_count: int = 0
    ioc_count: int = 0
    hygiene_count: int = 0
    max_tier: int = 0
    records: int = 0                      # C9 records attributed to this agent

    @property
    def assurance(self) -> str:
        """Portal honesty gate V13: crypto-attested only when real SPIFFE+cosign fields
        were recorded at birth; anything else is software-attested and shown as such."""
        if self.birth.get("spiffe_id") and self.birth.get("cosign_ok"):
            return "crypto-attested"
        return "software-attested"

    def posture(self, now_ts: float) -> str:
        if self.max_tier >= 3:
            return "quarantined"          # revocation inferred from Tier>=3 (documented)
        if self.max_tier == 2:
            return "out-of-scope"
        if self.ioc_count > 0 or self.deny_count > 0:
            return "drifting"
        if self.last_ts and (now_ts - self.last_ts) > _STALE_AFTER_S:
            return "stale"
        return "compliant"


class Registry:
    def __init__(self):
        self.agents: dict[tuple[str, str], AgentState] = {}
        self.events: list[dict] = []      # cursor = index (registry-assigned, monotonic)
        self.sources: dict[str, float] = {}          # src -> last ts seen
        self.feed_health: dict[str, dict] = {}       # src -> latest feed-health data
        self.bad_lines = 0
        self._offsets: dict[str, int] = {}           # path -> byte offset consumed
        self._pending: dict[str, bytes] = {}         # path -> partial tail (no newline yet)

    # ------------------------------------------------------------------ ingest

    def ingest_dir(self, spool_dir: str) -> int:
        n = 0
        if not os.path.isdir(spool_dir):
            return 0
        for name in sorted(os.listdir(spool_dir)):
            if name.endswith(".jsonl"):
                n += self.ingest_file(os.path.join(spool_dir, name))
        return n

    def ingest_file(self, path: str) -> int:
        """Incremental, binary, complete-lines-only. Returns events applied."""
        try:
            with open(path, "rb") as f:
                f.seek(self._offsets.get(path, 0))
                chunk = f.read()
                self._offsets[path] = f.tell()
        except OSError:
            return 0
        buf = self._pending.pop(path, b"") + chunk
        lines = buf.split(b"\n")
        self._pending[path] = lines.pop()             # tail without newline stays pending
        applied = 0
        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                evt = json.loads(raw.decode("utf-8"))
                self._apply(evt)
                applied += 1
            except Exception:
                self.bad_lines += 1                   # counted, never fatal, never skipped-past
        return applied

    @property
    def cursor(self) -> int:
        return len(self.events)

    def events_since(self, cursor: int) -> list[dict]:
        return self.events[cursor:]

    # ------------------------------------------------------------------ apply

    def _apply(self, evt: dict) -> None:
        self.events.append(evt)
        src, kind = evt.get("src", "?"), evt.get("kind", "?")
        ts = float(evt.get("ts") or 0.0)
        self.sources[src] = max(self.sources.get(src, 0.0), ts)
        if kind == "feed-health":
            self.feed_health[src] = evt.get("data", {})
            return
        agent = evt.get("agent")
        if not agent:
            return
        st = self.agents.setdefault((src, agent), AgentState(src=src, agent=agent))
        st.last_ts = max(st.last_ts, ts)
        data = evt.get("data", {})
        if kind == "birth":
            st.first_seen_ts = st.first_seen_ts or ts
            st.birth = data
            st.records += 1
        elif kind == "call":
            if data.get("allowed"):
                st.allow_count += 1
            else:
                st.deny_count += 1
            st.ioc_count += len(data.get("iocs", []))
        elif kind == "hygiene":
            st.hygiene_count += 1
            st.records += 1
            tier = data.get("tier")
            if isinstance(tier, int):
                st.max_tier = max(st.max_tier, tier)
        else:                                          # pre-actuation, result, task-outcome, ...
            st.records += 1

    # ------------------------------------------------------------------ views

    def roster(self, now_ts: float) -> list[dict]:
        return [{
            "src": st.src, "agent": st.agent, "posture": st.posture(now_ts),
            "assurance": st.assurance, "first_seen_ts": st.first_seen_ts,
            "last_ts": st.last_ts, "allow": st.allow_count, "deny": st.deny_count,
            "iocs": st.ioc_count, "max_tier": st.max_tier, "records": st.records,
        } for st in self.agents.values()]
