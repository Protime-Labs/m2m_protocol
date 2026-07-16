"""
C6 -- Policy Decision Point.  Controls: AATA-CT-01 (fail-closed kinetic),
AATA-GV-01 (signed constitutional policy).

Production tooling: OPA (Rego) or AWS Cedar engine, evaluated LOCALLY against a
cached, signed policy bundle with a TTL; a custom "constitutional compiler"
turns governance intent into the Rego/Cedar bundle. The bundle-TTL model is what
natively implements Degraded/Isolated-mode policy caching -- no cloud callback.

Guarantees demonstrated:
  * LOCAL evaluation against a cached bundle (works in a blackout).
  * FAIL-CLOSED for kinetic/irreversible classes: PDP timeout or error = DENY.
    Informational classes fail-degraded (allow with a flag) per policy.
  * A signed VERDICT carrying policy version + a rule trace.
  * THREAT-POSTURE aware: the current DDIL/threat register raises kinetic
    confidence thresholds (W4 step 2: "kinetic thresholds tighten").

This is intentionally a compact policy engine, not Rego. The Rego bundle it
mirrors is shown in policy/constitution.rego for the production swap.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Any

from .capability import ACTUATION_CLASSES, Token

# Which actuation classes are "kinetic/irreversible" -> fail-closed on error.
# Derived from the defensible per-class rubric in `irreversibility.py` (spec 10.11) rather
# than hardcoded -- reproduces the legacy {financial, kinetic} set, now as a threshold on a
# graded, per-tool-extensible score.
from .irreversibility import derive_irreversible_classes
IRREVERSIBLE = derive_irreversible_classes()


@dataclass
class PolicyBundle:
    """A signed, cached policy bundle with a TTL (mirrors an OPA bundle)."""
    version: str
    ttl_until: int
    # constitutional prohibitions: tools that are never allowed
    prohibited_tools: frozenset[str] = frozenset()
    # minimum "confidence" required per actuation class (threat-posture driven)
    min_confidence: dict[str, float] = field(default_factory=lambda: {
        "informational": 0.0, "reversible": 0.3, "financial": 0.7, "kinetic": 0.8,
    })
    signature: str = ""

    def sign(self, gov_key: bytes) -> "PolicyBundle":
        self.signature = hmac.new(gov_key, self._payload(), hashlib.blake2b).hexdigest()
        return self

    def _payload(self) -> bytes:
        return (self.version + "|" + ",".join(sorted(self.prohibited_tools)) + "|" +
                ",".join(f"{k}:{v}" for k, v in sorted(self.min_confidence.items()))).encode()

    def authentic(self, gov_key: bytes) -> bool:
        return hmac.compare_digest(
            hmac.new(gov_key, self._payload(), hashlib.blake2b).hexdigest(), self.signature)

    def tightened(self, threat_level: float) -> "PolicyBundle":
        """
        Return a posture-adjusted copy: higher threat raises irreversible-class
        thresholds. This is the W4 "kinetic thresholds tighten" mechanic and is
        applied locally with no callback.
        """
        mc = dict(self.min_confidence)
        for cls in IRREVERSIBLE:
            mc[cls] = min(1.0, mc[cls] + 0.15 * threat_level)
        return PolicyBundle(self.version, self.ttl_until, self.prohibited_tools,
                            mc, self.signature)


@dataclass
class Verdict:
    allow: bool
    decision: str            # "allow" | "deny" | "allow-degraded"
    reason: str
    policy_version: str
    rule_trace: list[str] = field(default_factory=list)
    fail_closed: bool = False


class PDP:
    """Local policy decision point."""

    def __init__(self, gov_key: bytes, bundle: PolicyBundle):
        self.gov_key = gov_key
        self.bundle = bundle

    def evaluate(
        self,
        token: Token,
        tool: str,
        actuation_class: str,
        data_level: str,
        cost: int,
        confidence: float,
        now: int,
        threat_level: float = 0.0,
        engine_error: bool = False,
    ) -> Verdict:
        trace: list[str] = []
        # Authenticity + TTL are checked against the SIGNED bundle. Threat-posture
        # tightening is a local, post-verification adjustment of thresholds only --
        # it must never be re-run through authentic() (the signature covers the
        # authored thresholds, not the runtime-tightened ones).
        signed = self.bundle
        ver = signed.version
        min_confidence = (signed.tightened(threat_level).min_confidence
                          if threat_level else signed.min_confidence)

        # (0) Engine error / timeout: fail-closed for irreversible classes.
        if engine_error:
            if actuation_class in IRREVERSIBLE:
                return Verdict(False, "deny",
                               "PDP engine error -> fail-closed (irreversible class)",
                               ver, ["engine_error", "fail_closed:irreversible"],
                               fail_closed=True)
            return Verdict(True, "allow-degraded",
                           "PDP engine error -> fail-degraded (informational class)",
                           ver, ["engine_error", "fail_degraded:informational"])

        # (1) Bundle authenticity + TTL (cached-but-signed).
        if not signed.authentic(self.gov_key):
            trace.append("bundle_signature:invalid")
            return Verdict(False, "deny", "policy bundle signature invalid", ver, trace,
                           fail_closed=actuation_class in IRREVERSIBLE)
        trace.append("bundle_signature:ok")
        if now > signed.ttl_until:
            trace.append("bundle_ttl:expired")
            # Expired cache is treated as engine-unavailable -> fail-closed kinetic.
            if actuation_class in IRREVERSIBLE:
                return Verdict(False, "deny", "policy bundle TTL expired (irreversible)",
                               ver, trace, fail_closed=True)
        else:
            trace.append("bundle_ttl:valid")

        # (2) Capability check (delegated to C5).
        ok, why = token.permits(tool, actuation_class, data_level, cost)
        trace.append(f"capability:{'ok' if ok else 'deny'}")
        if not ok:
            return Verdict(False, "deny", f"capability: {why}", ver, trace,
                           fail_closed=actuation_class in IRREVERSIBLE)

        # (3) Constitutional prohibition (never-allow tools).
        if tool in signed.prohibited_tools:
            trace.append("constitution:prohibited")
            return Verdict(False, "deny", f"tool '{tool}' constitutionally prohibited",
                           ver, trace, fail_closed=actuation_class in IRREVERSIBLE)
        trace.append("constitution:ok")

        # (4) Confidence threshold (threat-posture aware, locally tightened).
        need = min_confidence.get(actuation_class, 0.5)
        trace.append(f"confidence:{confidence:.2f}>=need:{need:.2f}")
        if confidence < need:
            return Verdict(False, "deny",
                           f"confidence {confidence:.2f} < required {need:.2f} for "
                           f"'{actuation_class}' at threat={threat_level:.1f}",
                           ver, trace, fail_closed=actuation_class in IRREVERSIBLE)

        return Verdict(True, "allow", "all policy checks passed", ver, trace)
