"""
Cedar policy engine (C6): the real authorization engine behind the hand-rolled PDP.

The same constitution the core PDP hard-codes -- capability, a never-allow prohibition, and a
threat-tightened confidence threshold -- compiled to Cedar policies and evaluated by the real
`cedarpy` engine (default-deny, forbid-overrides-permit, with a policy-reason trace). The
load-bearing fail-closed rule is preserved at the enforcement point: if the engine cannot
decide, irreversible classes DENY and informational classes allow-degraded.

    pip install -r requirements-cedar.txt   # cedarpy
    python demos/demo_cedar.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from integrations.cedar import CedarPDP, enabled, required_confidence


def main() -> None:
    print("=" * 74)
    print("AATA Cedar policy engine (C6) -- real authorization behind the hand-rolled PDP")
    print("=" * 74)

    if not enabled():
        print("\n  cedarpy not installed -> Cedar integration disabled.")
        print("  pip install -r requirements-cedar.txt   (then re-run)")
        return

    pdp = CedarPDP(prohibited_tools=frozenset({"self_destruct"}))

    def show(label, **kw):
        v = pdp.evaluate(**kw)
        print(f"  {label:34s} -> {v.decision:14s} fail_closed={str(v.fail_closed):5s} {v.reasons[0]}")

    print("\n  -- real Cedar decisions (cedar-policy engine) --")
    show("honest reversible call", agent_id="rover-01", tool="actuator_move",
         actuation_class="reversible", confidence=0.9)
    show("constitutionally prohibited tool", agent_id="rover-01", tool="self_destruct",
         actuation_class="kinetic", confidence=0.99)
    show("kinetic, confidence too low", agent_id="rover-01", tool="fire",
         actuation_class="kinetic", confidence=0.5)
    show("capability insufficient (C5)", agent_id="rover-01", tool="move",
         actuation_class="reversible", confidence=0.9, capability_ok=False)

    print("\n  -- W4 posture: losing connectivity tightens irreversible thresholds --")
    show("financial @ connected (need 0.70)", agent_id="rover-01", tool="pay",
         actuation_class="financial", confidence=0.8, threat_level=0.0)
    print(f"       (isolated: need rises to {required_confidence('financial', 2.0):.2f})")
    show("financial @ isolated  (need 1.00)", agent_id="rover-01", tool="pay",
         actuation_class="financial", confidence=0.8, threat_level=2.0)

    print("\n  -- fail-closed when the engine itself is unreachable (enforcement point) --")
    show("engine down, kinetic", agent_id="rover-01", tool="move",
         actuation_class="kinetic", confidence=0.9, engine_error=True)
    show("engine down, informational", agent_id="rover-01", tool="log",
         actuation_class="informational", confidence=0.0, engine_error=True)

    print("\n  This is the C6 production swap: the real Cedar engine renders the same decisions")
    print("  the hand-rolled PDP does (parity-tested across 64 cases) -- now in signed policy.")


if __name__ == "__main__":
    main()
