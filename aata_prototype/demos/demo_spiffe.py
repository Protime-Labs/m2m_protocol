"""
SPIFFE X.509 SVIDs (C2/C4): real workload identity behind the HMAC SVID stand-in.

A trust-domain CA issues a short-lived leaf certificate whose SPIFFE ID is a URI SAN; it is
verified with the CA's PUBLIC cert alone (asymmetric), the lease is the cert notAfter, and
a foreign CA or an expired lease is rejected -- on real X.509 + Ed25519.

    pip install -r requirements-spiffe.txt   # cryptography
    python demos/demo_spiffe.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from integrations.spiffe import SvidError, enabled, issue_svid, new_ca, spiffe_id_of, verify_svid


def main() -> None:
    print("=" * 74)
    print("AATA SPIFFE X.509 SVIDs (C2/C4) -- real, lease-bound workload identity")
    print("=" * 74)

    if not enabled():
        print("\n  cryptography not installed -> SPIFFE integration disabled.")
        print("  pip install -r requirements-spiffe.txt   (then re-run)")
        return

    ca_key, ca_cert = new_ca("aata.mars")
    print(f"\n  trust-domain CA: {spiffe_id_of(ca_cert)} (self-signed; verifies leaves)")

    leaf_key, leaf = issue_svid(ca_key, ca_cert, "rover/rover-01", lease_seconds=300)
    print(f"  issued SVID -> {verify_svid(ca_cert, leaf)}  (verified with the CA public cert only)")

    print("\n  -- properties (real X.509 + Ed25519) --")

    _, other_ca = new_ca("attacker.io")
    try:
        verify_svid(other_ca, leaf); print("  foreign CA: ACCEPTED (bug!)")
    except SvidError:
        print("  asymmetric: a foreign CA cannot validate this SVID (verifier holds no signing key)")

    _, expired = issue_svid(ca_key, ca_cert, "rover/old", lease_seconds=-5)
    try:
        verify_svid(ca_cert, expired); print("  expired: ACCEPTED (bug!)")
    except SvidError:
        print("  short lease is cryptographic: an expired cert (past notAfter) is rejected")

    print("  identity is a standards-based SPIFFE ID in a URI SAN -> interoperable with SPIRE")

    print("\n  This is the C2/C4 production swap: SPIRE-issued X.509 SVIDs the HMAC-signed")
    print("  SVID dataclass only approximates (add Keylime TPM attestation for the hardware root).")


if __name__ == "__main__":
    main()
