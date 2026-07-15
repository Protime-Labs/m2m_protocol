"""
Invariant tests -- the architecture's promises, as executable assertions.

No third-party test runner needed:  python tests/test_invariants.py
(Also works under pytest if you have it.)

Each test maps to a load-bearing guarantee from the AATA spec.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aata.canonicalize import canonicalize
from aata.capability import CapabilityError, Grant, Token, root_grant
from aata.pdp import PDP, PolicyBundle
from aata.recorder import FlightRecorder, RecorderUnreachable
from aata.scenario import build_estate, birth


# ---- C5 : monotone attenuation ------------------------------------------

def test_attenuation_is_monotone_subset():
    key = b"k" * 32
    tok = Token.issue(key, "parent", root_grant(
        tools={"a", "b", "c"}, spend_budget=100, max_delegation_depth=3))
    child = tok.attenuate(Grant(frozenset({"a", "b"}), frozenset({"informational"}),
                          "internal", 50, 3), "child")
    eff = child.effective()
    assert eff.tools == {"a", "b"}, eff.tools
    assert eff.spend_budget == 50
    assert child.verify(key)


def test_attenuation_cannot_broaden():
    key = b"k" * 32
    tok = Token.issue(key, "parent", root_grant(tools={"a"}, spend_budget=10))
    try:
        tok.attenuate(Grant(frozenset({"a", "b"}), frozenset({"informational"}),
                      "public", 10, 1), "child")
        assert False, "broadening tools should have raised"
    except CapabilityError:
        pass
    try:
        tok.attenuate(Grant(frozenset({"a"}), frozenset({"informational"}),
                      "public", 9999, 1), "child")
        assert False, "raising budget should have raised"
    except CapabilityError:
        pass


def test_even_crafted_broadening_block_is_ignored_at_verify():
    # Bypass the attenuate() guard and hand-craft a broadening block; the
    # effective() fold must STILL intersect it away (defence at evaluation time).
    key = b"k" * 32
    tok = Token.issue(key, "parent", root_grant(tools={"a"}, spend_budget=10))
    tok.blocks.append(Grant(frozenset({"a", "EVIL"}), frozenset({"kinetic"}),
                      "secret", 9999, 9))
    assert "EVIL" not in tok.effective().tools
    assert tok.effective().spend_budget == 10


def test_delegation_depth_cap():
    key = b"k" * 32
    tok = Token.issue(key, "p", root_grant(tools={"a"}, max_delegation_depth=1))
    c1 = tok.attenuate(Grant(frozenset({"a"}), frozenset({"informational"}),
                       "public", 1, 1), "c1")
    try:
        c1.attenuate(Grant(frozenset({"a"}), frozenset({"informational"}),
                     "public", 1, 1), "c2")
        assert False, "should exceed max delegation depth"
    except CapabilityError:
        pass


def test_offline_verification_needs_authority_key():
    key = b"k" * 32
    tok = Token.issue(key, "p", root_grant(tools={"a"}))
    assert tok.verify(key)
    assert not tok.verify(b"x" * 32)


# ---- C9 : flight recorder chain integrity + no-evidence-no-action --------

def test_chain_detects_tampering():
    r = FlightRecorder()
    r.append("pre-actuation", {"x": 1})
    r.append("result", {"y": 2})
    ok, _ = r.verify()
    assert ok
    r.records[0].payload["x"] = 999  # tamper
    ok, msg = r.verify()
    assert not ok and "tampered" in msg


def test_recorder_unreachable_raises():
    r = FlightRecorder()
    r.online = False
    try:
        r.append("pre-actuation", {"x": 1})
        assert False, "should raise RecorderUnreachable"
    except RecorderUnreachable:
        pass


def test_no_evidence_no_action_fail_closed_kinetic():
    est = build_estate()
    est.gateway.hygiene = None
    svid, token = birth(est, "a1", tools={"actuator_move"})
    est.ddil.active_recorder.online = False           # recorder down
    out = est.gateway.call("a1", svid, token, "actuator_move", "go", confidence=0.99)
    assert not out.allowed and out.decision == "deny", out.decision
    # no result record should exist for this call
    assert all(r.kind != "result" for r in est.authoritative.records)


# ---- C6 : fail-closed vs fail-degraded ----------------------------------

def test_pdp_fail_closed_on_engine_error():
    gov = b"g" * 32
    pdp = PDP(gov, PolicyBundle("v1", 10_000).sign(gov))
    tok = Token.issue(b"k" * 32, "p", root_grant(tools={"t"}))
    # kinetic + engine error -> deny
    v = pdp.evaluate(tok, "t", "kinetic", "public", 1, 0.99, now=0, engine_error=True)
    assert not v.allow and v.fail_closed
    # informational + engine error -> allow-degraded
    v = pdp.evaluate(tok, "t", "informational", "public", 1, 0.99, now=0, engine_error=True)
    assert v.allow and v.decision == "allow-degraded"


def test_pdp_kinetic_thresholds_tighten_with_threat():
    gov = b"g" * 32
    pdp = PDP(gov, PolicyBundle("v1", 10_000).sign(gov))
    tok = Token.issue(b"k" * 32, "p", root_grant(tools={"t"}))
    # confidence 0.85 allowed at threat 0, denied at high threat (threshold tightens)
    v0 = pdp.evaluate(tok, "t", "kinetic", "public", 1, 0.85, now=0, threat_level=0.0)
    v2 = pdp.evaluate(tok, "t", "kinetic", "public", 1, 0.85, now=0, threat_level=2.0)
    assert v0.allow and not v2.allow


# ---- C2/C4 : attestation blocks tampered artifacts -----------------------

def test_tampered_prompt_gets_no_svid():
    from aata.identity import Artifact
    est = build_estate()
    bad = [
        Artifact("weights.safetensors", "weights", b"<<golden model weights>>"),
        Artifact("adapter.lora", "adapter", b"<<golden lora adapter>>"),
        Artifact("system.prompt", "prompt", b"tampered"),
        Artifact("skills.pkg", "skill", b"<<golden skill package>>"),
    ]
    try:
        birth(est, "bad", tools={"sensor_read"}, artifacts=bad)
        assert False, "tampered prompt must not receive an SVID"
    except PermissionError:
        pass


# ---- C10 : covert channel canonicalization -------------------------------

def test_zero_width_is_stripped_and_flagged():
    r = canonicalize("bay​-‌3")   # contains zero-width chars
    assert r.zero_width_removed >= 1
    assert r.delta_is_ioc
    assert "​" not in r.canonical


# ---- runner --------------------------------------------------------------

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
    print(f"\n{passed}/{len(tests)} invariant tests passed")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(_run())
