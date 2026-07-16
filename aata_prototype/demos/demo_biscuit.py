"""
Biscuit Ed25519 capability tokens (C5): the real asymmetric primitive behind the HMAC seal.

Shows the properties the HMAC stand-in cannot provide: mint with the authority SECRET key,
verify with only the PUBLIC key, attenuate offline WITHOUT any authority secret, and
resistance to broadening, tampering, and truncation/rollback -- all on real Ed25519.

    pip install -r requirements-biscuit.txt   # cryptography
    python demos/demo_biscuit.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from integrations.biscuit import BiscuitError, BiscuitToken, enabled, generate_authority


def main() -> None:
    print("=" * 74)
    print("AATA BISCUIT Ed25519 CAPABILITY TOKENS (C5) -- asymmetric, offline-attenuable")
    print("=" * 74)

    if not enabled():
        print("\n  cryptography not installed -> Biscuit integration disabled.")
        print("  pip install -r requirements-biscuit.txt   (then re-run)")
        return

    authority_sk, authority_pub = generate_authority()
    print("\n  authority: a SECRET key mints; only the PUBLIC key is needed to verify")
    print("  (contrast HMAC: the verify key IS the mint key -> the verifier is a forgery risk)")

    root = BiscuitToken.root(authority_sk, frozenset({"read:sensor", "write:db", "move:arm"}))
    print(f"\n  root grant (verified w/ public key): {sorted(root.verify(authority_pub))}")

    # a sub-agent attenuates OFFLINE -- it holds no authority secret
    delegated = root.attenuate(frozenset({"read:sensor", "write:db"}))
    print(f"  sub-agent attenuates offline (no authority secret) -> {sorted(delegated.verify(authority_pub))}")

    print("\n  -- properties (all on real Ed25519) --")

    # cannot broaden
    broad = delegated.attenuate(frozenset({"read:sensor", "write:db", "move:arm", "admin:all"}))
    print(f"  cannot broaden: attenuate to a superset -> {sorted(broad.verify(authority_pub))} "
          f"(admin/move stay revoked)")

    # asymmetric: another authority's public key can't verify this token
    _, other_pub = generate_authority()
    try:
        delegated.verify(other_pub); print("  wrong key: ACCEPTED (bug!)")
    except BiscuitError:
        print("  asymmetric: a different public key cannot verify -> the verifier can't mint")

    # tamper-evident
    t = BiscuitToken(list(delegated.blocks), delegated.proof, None)
    p, npk, sig = t.blocks[0]
    t.blocks[0] = (p.replace(b"read:sensor", b"admin:all!"), npk, sig)
    try:
        t.verify(authority_pub); print("  tamper: ACCEPTED (bug!)")
    except BiscuitError:
        print("  tamper-evident: editing any block breaks the signature chain -> rejected")

    # truncation / rollback resistance
    trunc = BiscuitToken(delegated.blocks[:1], delegated.proof, None)   # drop the caveat to widen
    try:
        trunc.verify(authority_pub); print("  truncation: ACCEPTED (bug!)")
    except BiscuitError:
        print("  rollback-resistant: stripping a caveat needs an intermediate secret key "
              "the holder lacks -> rejected")

    print("\n  This is the C5 production swap: real asymmetric, offline-attenuable capability")
    print("  tokens the HMAC hash-chain stand-in only approximates.")


if __name__ == "__main__":
    main()
