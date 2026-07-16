"""
SPIRE-style workload identity (C2/C4) -- real X.509 SVIDs.

The core issues an HMAC-signed `SVID` dataclass (a faithful stand-in for the *shape* of a
lease-bound identity). This integration is the real primitive: a **SPIFFE X.509 SVID** --
a short-lived leaf certificate whose SPIFFE ID lives in a URI SAN (`spiffe://<trust
domain>/<workload>`), signed by a trust-domain CA and verified against the CA's public
certificate. It gives the properties the HMAC stand-in only approximates: asymmetric
issue/verify (the verifier holds no signing power), cryptographic expiry (the short lease
is the cert's `notAfter`), and a standards-based identity document.

Additive and offline-default: the core keeps its HMAC SVID; `cryptography` is imported
lazily and gated on `enabled()`, so the base suite/CI stay dependency-free.
"""
from integrations.spiffe.svid import (
    SvidError,
    enabled,
    issue_svid,
    new_ca,
    spiffe_id_of,
    verify_svid,
)

__all__ = [
    "new_ca", "issue_svid", "verify_svid", "spiffe_id_of", "SvidError", "enabled",
]
