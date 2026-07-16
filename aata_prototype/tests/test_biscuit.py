"""
Biscuit Ed25519 capability-token guarantees -- real crypto (the C5 production swap).

Mirrors the HMAC-token invariants (aata/capability.py: monotone attenuation, crafted
broadening ignored, offline verification needs the authority key) and adds the properties
only asymmetric crypto provides: verify with the PUBLIC key alone, and truncation/rollback
resistance. Runs only when `cryptography` is installed; skips cleanly otherwise so the base
suite/CI stay green (the CI 'integrations-extra' job installs it and exercises these).
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from integrations.biscuit import BiscuitError, BiscuitToken, enabled, generate_authority

_TOOLS = frozenset({"read:sensor", "write:db", "move:arm"})


def _skip() -> bool:
    if not enabled():
        print("    (skip: cryptography not installed)")
        return True
    return False


def _root():
    sk, pub = generate_authority()
    return sk, pub, BiscuitToken.root(sk, _TOOLS)


# ---- tests -------------------------------------------------------------------

def test_root_verifies_to_the_granted_tools():
    if _skip():
        return
    _, pub, root = _root()
    assert root.verify(pub) == _TOOLS


def test_attenuation_narrows_and_needs_no_authority_secret():
    if _skip():
        return
    _, pub, root = _root()
    child = root.attenuate(frozenset({"read:sensor", "write:db"}))    # holder key only, no authority sk
    assert child.verify(pub) == frozenset({"read:sensor", "write:db"})
    assert child.verify(pub) < _TOOLS                                 # strict subset


def test_attenuation_cannot_broaden():
    if _skip():
        return
    _, pub, root = _root()
    child = root.attenuate(frozenset({"read:sensor"}))
    broad = child.attenuate(_TOOLS | {"admin:all"})                  # ask for MORE than held
    assert broad.verify(pub) == frozenset({"read:sensor"})           # intersection -> no broadening


def test_crafted_broadening_block_is_ignored_at_verify():
    if _skip():
        return
    _, pub, root = _root()
    child = root.attenuate(frozenset({"read:sensor"}))
    # a validly-signed block claiming more tools still can't broaden (verify intersects)
    forged = child.attenuate(frozenset({"admin:all", "move:arm"}))
    assert "admin:all" not in forged.verify(pub) and "move:arm" not in forged.verify(pub)


def test_verify_is_asymmetric_public_key_only():
    if _skip():
        return
    sk, pub, root = _root()
    _, other_pub = generate_authority()
    # the authority PUBLIC key verifies; a different public key cannot (verifier != minter)
    assert root.verify(pub) == _TOOLS
    try:
        root.verify(other_pub)
        assert False, "a foreign public key must not verify"
    except BiscuitError:
        pass


def test_tampering_a_block_is_detected():
    if _skip():
        return
    _, pub, root = _root()
    child = root.attenuate(frozenset({"read:sensor"}))
    p, npk, sig = child.blocks[0]
    child.blocks[0] = (p.replace(b"read:sensor", b"admin:all!"), npk, sig)
    try:
        child.verify(pub)
        assert False, "tampered block must be rejected"
    except BiscuitError:
        pass


def test_truncation_rollback_is_rejected():
    if _skip():
        return
    _, pub, root = _root()
    child = root.attenuate(frozenset({"read:sensor"}))               # narrowed to 1 tool
    # try to drop the caveat block to widen back to the full root grant
    truncated = BiscuitToken(child.blocks[:1], child.proof, None)
    try:
        truncated.verify(pub)
        assert False, "truncated token must be rejected (proof over the last key)"
    except BiscuitError:
        pass


def test_sealed_token_cannot_be_attenuated_by_a_receiver():
    if _skip():
        return
    _, _pub, root = _root()
    sealed = root.sealed()                                            # no holder secret travels
    try:
        sealed.attenuate(frozenset({"read:sensor"}))
        assert False, "a token without its holder key must not attenuate"
    except BiscuitError:
        pass


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
    print(f"\n{passed}/{len(tests)} biscuit tests passed")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(_run())
