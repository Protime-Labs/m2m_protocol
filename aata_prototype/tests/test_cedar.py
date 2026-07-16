"""
Cedar policy-engine guarantees -- real evaluation (the C6 production swap).

Two kinds of assurance:
  1. Behavioural: the real `cedarpy` engine enforces the constitution -- default-deny,
     constitutional prohibition, capability, a threat-tightened confidence threshold -- and
     the load-bearing fail-closed rule holds when the engine cannot decide.
  2. PARITY: for a matrix of inputs the real Cedar engine renders the SAME allow/deny
     decision as the hand-rolled core PDP (`aata/pdp.py`), proving it is a faithful drop-in.

Runs only when `cedarpy` is installed; skips cleanly otherwise so the base suite/CI stay
green (the CI 'integrations-extra' job installs it and exercises these).
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from integrations.cedar import CedarPDP, enabled, required_confidence


def _skip() -> bool:
    if not enabled():
        print("    (skip: cedarpy not installed)")
        return True
    return False


# ---- behavioural tests -------------------------------------------------------

def test_happy_path_allows():
    if _skip():
        return
    v = CedarPDP().evaluate("r1", "actuator_move", "reversible", confidence=0.9)
    assert v.allow and v.decision == "allow", v.reasons


def test_prohibited_tool_denied_and_fail_closed():
    if _skip():
        return
    v = CedarPDP().evaluate("r1", "self_destruct", "kinetic", confidence=0.99)
    assert not v.allow and v.fail_closed
    assert any("prohibited" in r for r in v.reasons), v.reasons


def test_low_confidence_kinetic_denied_fail_closed():
    if _skip():
        return
    v = CedarPDP().evaluate("r1", "fire", "kinetic", confidence=0.5)   # need 0.8
    assert not v.allow and v.fail_closed
    assert any("confidence" in r for r in v.reasons), v.reasons


def test_missing_capability_denied_not_fail_closed_for_reversible():
    if _skip():
        return
    v = CedarPDP().evaluate("r1", "move", "reversible", confidence=0.9, capability_ok=False)
    assert not v.allow and not v.fail_closed          # reversible is not irreversible
    assert any("capability" in r for r in v.reasons), v.reasons


def test_threat_posture_tightens_and_flips_allow_to_deny():
    if _skip():
        return
    pdp = CedarPDP()
    # financial base 0.7; confidence 0.8 passes when connected...
    assert pdp.evaluate("r1", "pay", "financial", confidence=0.8, threat_level=0.0).allow
    # ...but threat 2.0 raises the need to min(1.0, 0.7 + 0.30) = 1.0 -> now denied.
    v = pdp.evaluate("r1", "pay", "financial", confidence=0.8, threat_level=2.0)
    assert not v.allow and v.fail_closed


def test_engine_error_fails_closed_for_irreversible():
    if _skip():
        return
    v = CedarPDP().evaluate("r1", "move", "kinetic", confidence=0.9, engine_error=True)
    assert not v.allow and v.fail_closed
    assert "allow" not in v.decision


def test_engine_error_fails_degraded_for_informational():
    if _skip():
        return
    v = CedarPDP().evaluate("r1", "log", "informational", confidence=0.0, engine_error=True)
    assert v.allow and v.decision == "allow-degraded"


def test_required_confidence_matches_the_core_formula():
    if _skip():
        return
    assert required_confidence("kinetic", 0.0) == 0.8
    assert required_confidence("kinetic", 2.0) == 1.0          # min(1.0, 0.8 + 0.30)
    assert required_confidence("financial", 1.0) == 0.85       # 0.7 + 0.15
    assert required_confidence("reversible", 5.0) == 0.3       # not irreversible -> unchanged


# ---- parity with the hand-rolled core PDP ------------------------------------

def test_parity_with_core_pdp_across_matrix():
    if _skip():
        return
    from aata.pdp import PDP, PolicyBundle
    from aata.capability import Token, root_grant

    gov_key, auth_key = b"gov-secret-key", b"authority-key"
    tools = {"actuator_move", "self_destruct", "fire", "pay", "log"}
    # A permissive token so the CORE capability check always passes -- we compare the
    # POLICY decision (prohibition + confidence + posture), which both engines express.
    token = Token.issue(auth_key, "rover-01", root_grant(tools=tools))
    bundle = PolicyBundle("v1", ttl_until=10_000, prohibited_tools=frozenset({"self_destruct"})).sign(gov_key)
    core = PDP(gov_key, bundle)
    cedar = CedarPDP(prohibited_tools=frozenset({"self_destruct"}))

    checked = 0
    for tool in ["actuator_move", "self_destruct"]:
        for cls in ["informational", "reversible", "financial", "kinetic"]:
            for conf in [0.0, 0.5, 0.8, 0.95]:
                for threat in [0.0, 2.0]:
                    cv = core.evaluate(token, tool, cls, "public", 1, conf, now=1, threat_level=threat)
                    dv = cedar.evaluate("rover-01", tool, cls, confidence=conf,
                                        threat_level=threat, capability_ok=True)
                    assert cv.allow == dv.allow, (
                        f"DIVERGENCE tool={tool} class={cls} conf={conf} threat={threat}: "
                        f"core={cv.allow} cedar={dv.allow} ({cv.reason} | {dv.reasons})")
                    checked += 1
    print(f"    parity holds across {checked} (tool x class x confidence x threat) cases")


# ---- runner ------------------------------------------------------------------

def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}: {e}")
        except Exception as e:
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} cedar tests passed")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(_run())
