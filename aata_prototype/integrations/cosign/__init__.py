"""
cosign-style signed artifact registry (C4) -- real detached signatures on Ed25519.

The core seals its `{artifact name -> sha256 digest}` golden manifest with an HMAC
(`aata/identity.py::SignedManifest`) -- a faithful stand-in for the *shape* of a signed
model registry, but symmetric: the verifier holds the signing secret and could forge. This
integration is the real primitive: a **detached Ed25519 signature over the digest manifest**
(cosign), verified with the registry PUBLIC key alone. It gives the property the HMAC
stand-in only approximates -- asymmetric sign/verify -- while catching the same swapped or
backdoored artifact via a changed sha256 digest.

Additive and offline-default: the core keeps its HMAC manifest; `cryptography` is imported
lazily and gated on `enabled()`, so the base suite/CI stay dependency-free.

Honest limitation (spec 10.2): a signature proves PROVENANCE, not SAFETY. A model backdoored
during training signs and verifies perfectly. This proves you run the signed artifacts; it
cannot prove those artifacts are benign.
"""
from integrations.cosign.manifest import (
    CosignError,
    SignedManifest,
    digest_of,
    enabled,
    generate_signing_key,
)

__all__ = [
    "SignedManifest", "generate_signing_key", "digest_of", "CosignError", "enabled",
]
