"""
SPIFFE X.509 SVID guarantees -- real crypto (the C2/C4 workload-identity swap).

Mirrors the core HMAC SVID's properties (lease-bound identity, verification needs the
authority) and adds what real PKI provides: asymmetric issue/verify (the verifier holds no
signing key), cryptographic expiry (the lease is the cert notAfter), and a standards-based
SPIFFE ID. Runs only when `cryptography` is installed; skips cleanly otherwise.
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from integrations.spiffe import SvidError, enabled, issue_svid, new_ca, verify_svid


def _skip() -> bool:
    if not enabled():
        print("    (skip: cryptography not installed)")
        return True
    return False


def _ca(td="aata.mars"):
    return new_ca(td)


# ---- tests -------------------------------------------------------------------

def test_issue_and_verify_returns_spiffe_id():
    if _skip():
        return
    ca_key, ca_cert = _ca()
    _, leaf = issue_svid(ca_key, ca_cert, "rover/rover-01", lease_seconds=300)
    assert verify_svid(ca_cert, leaf) == "spiffe://aata.mars/rover/rover-01"


def test_spiffe_id_is_bound_to_the_workload_path():
    if _skip():
        return
    ca_key, ca_cert = _ca()
    _, leaf = issue_svid(ca_key, ca_cert, "humanoid/hum-002", lease_seconds=300)
    assert verify_svid(ca_cert, leaf).endswith("/humanoid/hum-002")


def test_verify_is_asymmetric_a_foreign_ca_cannot_validate():
    if _skip():
        return
    ca_key, ca_cert = _ca()
    _, leaf = issue_svid(ca_key, ca_cert, "rover/rover-01", lease_seconds=300)
    _, other_ca = _ca("attacker.io")
    # the CA's public cert verifies; a different CA cert cannot (verifier != issuer)
    assert verify_svid(ca_cert, leaf).startswith("spiffe://aata.mars/")
    try:
        verify_svid(other_ca, leaf)
        assert False, "a foreign CA must not validate this SVID"
    except SvidError:
        pass


def test_expired_lease_is_rejected():
    if _skip():
        return
    ca_key, ca_cert = _ca()
    _, expired = issue_svid(ca_key, ca_cert, "rover/old", lease_seconds=-5)   # already past notAfter
    try:
        verify_svid(ca_cert, expired)
        assert False, "expired SVID must be rejected"
    except SvidError as e:
        assert "expired" in str(e)


def test_not_yet_valid_is_rejected():
    if _skip():
        return
    from datetime import datetime, timedelta, timezone
    ca_key, ca_cert = _ca()
    _, leaf = issue_svid(ca_key, ca_cert, "rover/future", lease_seconds=300)
    past = datetime.now(timezone.utc) - timedelta(days=1)                    # before notBefore
    try:
        verify_svid(ca_cert, leaf, now=past)
        assert False, "SVID must not verify before its validity window"
    except SvidError as e:
        assert "not yet valid" in str(e)


def test_forged_issuer_signed_by_non_ca_key_is_rejected():
    if _skip():
        return
    ca_key, ca_cert = _ca()
    other_key, _ = _ca("attacker.io")
    # a cert claiming our issuer name but signed by a DIFFERENT key must not verify
    _, forged = issue_svid(other_key, ca_cert, "rover/rover-01", lease_seconds=300)
    try:
        verify_svid(ca_cert, forged)
        assert False, "SVID not signed by the real CA key must be rejected"
    except SvidError:
        pass


def test_verify_needs_only_the_ca_public_cert():
    if _skip():
        return
    ca_key, ca_cert = _ca()
    _, leaf = issue_svid(ca_key, ca_cert, "rover/rover-01", lease_seconds=300)
    # verification is done with the CA cert alone -- no CA private key in scope here
    assert verify_svid(ca_cert, leaf).startswith("spiffe://")


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
    print(f"\n{passed}/{len(tests)} spiffe tests passed")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(_run())
