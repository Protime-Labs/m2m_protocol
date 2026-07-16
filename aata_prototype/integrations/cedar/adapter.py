"""
CedarPDPAdapter -- make the real Cedar engine a drop-in for the core `aata/pdp.py::PDP`.

`CedarPDP.evaluate` and core `PDP.evaluate` have different signatures: the core PDP owns the
bundle-authenticity/TTL checks and the capability check (`token.permits`, which models
Grant/data-ceiling/spend that Cedar does not), and only its *prohibition + confidence*
decision overlaps with Cedar. This adapter reproduces the core PDP's own steps, then delegates
exactly that overlapping decision to the real Cedar engine, and maps the result back to a core
`Verdict`. It therefore plugs into `Gateway(pdp=...)` unchanged.

The 64-case matrix in `test_cedar.py` already proves the delegated (prohibition+confidence)
decision is identical to the core; `test_cedar.py::test_adapter_full_verdict_parity...` extends
that to the *whole* Verdict (incl. bundle-auth/TTL and capability paths, and a restrictive
token) so this really is a faithful swap.
"""
from __future__ import annotations

from aata.pdp import IRREVERSIBLE, Verdict

from integrations.cedar.engine import CedarPDP


class CedarPDPAdapter:
    """Core-PDP-compatible facade over CedarPDP. Constructed by the wiring factory."""

    def __init__(self, gov_key: bytes, bundle, cedar: CedarPDP | None = None):
        self.gov_key = gov_key
        self.bundle = bundle
        # The Cedar engine's prohibited set must match the signed bundle's.
        self.cedar = cedar or CedarPDP(prohibited_tools=bundle.prohibited_tools)

    def evaluate(self, token, tool, actuation_class, data_level, cost, confidence, now,
                 threat_level: float = 0.0, engine_error: bool = False) -> Verdict:
        ver = self.bundle.version

        # (0) Engine error/timeout: delegate to Cedar's fail-closed (identical class rule).
        if engine_error:
            cv = self.cedar.evaluate(token.subject, tool, actuation_class, confidence,
                                     threat_level, capability_ok=True, engine_error=True)
            return self._verdict(cv, ver, ["engine_error"])

        # (1) Bundle authenticity + TTL -- the core PDP's own steps, reproduced exactly.
        if not self.bundle.authentic(self.gov_key):
            return Verdict(False, "deny", "policy bundle signature invalid", ver,
                           ["bundle_signature:invalid"],
                           fail_closed=actuation_class in IRREVERSIBLE)
        trace = ["bundle_signature:ok"]
        if now > self.bundle.ttl_until:
            trace.append("bundle_ttl:expired")
            if actuation_class in IRREVERSIBLE:
                return Verdict(False, "deny", "policy bundle TTL expired (irreversible)",
                               ver, trace, fail_closed=True)
        else:
            trace.append("bundle_ttl:valid")

        # (2) Capability (C5) -- Cedar does not model Grant/data/spend; the core token does.
        cap_ok, _why = token.permits(tool, actuation_class, data_level, cost)
        trace.append(f"capability:{'ok' if cap_ok else 'deny'}")

        # (3+4) Constitutional prohibition + confidence threshold -> the real Cedar engine.
        cv = self.cedar.evaluate(token.subject, tool, actuation_class, confidence,
                                 threat_level, capability_ok=cap_ok)
        return self._verdict(cv, ver, trace)

    def _verdict(self, cv, ver, trace) -> Verdict:
        return Verdict(cv.allow, cv.decision, "; ".join(cv.reasons), ver,
                       trace + list(cv.reasons), fail_closed=cv.fail_closed)
