"""
C10 -- Covert-Channel Monitor (BUILD component, flagship differentiator).

Production tooling: custom service -- ICU Unicode canonicalization, confusables
+ zero-width detection, semantic drift scoring, timing-entropy analysis on
tool-call cadence. Runs ASYNC off the W1 hot path (W1 step 10).

This module produces IOCs (indicators of compromise). Two detectors:

  1. Encoding channel: was a canonicalization delta observed?  (from C10 inline)
  2. Timing channel: is the inter-call interval sequence carrying information?
     Detected via Shannon entropy of quantized inter-arrival gaps -- a covert
     timing channel modulates the gaps, raising their entropy above an
     agent's normal near-constant cadence.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from .canonicalize import CanonResult


@dataclass
class IOC:
    """Indicator of compromise emitted by C10."""
    kind: str            # "encoding" | "timing"
    agent_id: str
    severity: float      # 0.0 .. 1.0
    detail: str
    payload: str = ""    # captured evidence


def encoding_ioc(agent_id: str, canon: CanonResult) -> IOC | None:
    """Turn a canonicalization delta into an IOC (W3 step 1)."""
    if not canon.delta_is_ioc:
        return None
    sev = min(1.0, 0.5 + 0.1 * (canon.zero_width_removed + canon.confusables_mapped))
    return IOC(
        kind="encoding",
        agent_id=agent_id,
        severity=sev,
        detail="; ".join(canon.notes) or "canonicalization delta",
        payload=repr(canon.raw),
    )


def _shannon_entropy(symbols: list[int]) -> float:
    if not symbols:
        return 0.0
    counts = Counter(symbols)
    n = len(symbols)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


class TimingMonitor:
    """
    Tracks per-agent tool-call cadence and flags high-entropy timing patterns.

    A normal agent calls tools on a roughly regular cadence (low entropy of
    inter-arrival gaps). A covert timing channel deliberately varies the gaps
    to encode bits, which shows up as elevated entropy.
    """

    def __init__(self, quantum: int = 1, window: int = 12, threshold: float = 1.8):
        self.quantum = quantum
        self.window = window
        self.threshold = threshold
        self._last: dict[str, int] = {}
        self._gaps: dict[str, list[int]] = {}

    def observe(self, agent_id: str, t: int) -> IOC | None:
        last = self._last.get(agent_id)
        self._last[agent_id] = t
        if last is None:
            return None
        gap = max(0, (t - last)) // self.quantum
        gaps = self._gaps.setdefault(agent_id, [])
        gaps.append(gap)
        if len(gaps) > self.window:
            gaps.pop(0)
        if len(gaps) < self.window:
            return None
        ent = _shannon_entropy(gaps)
        if ent >= self.threshold:
            return IOC(
                kind="timing",
                agent_id=agent_id,
                severity=min(1.0, ent / 3.0),
                detail=f"tool-call inter-arrival entropy {ent:.2f} >= {self.threshold}",
                payload=str(gaps),
            )
        return None
