"""
Real cosign-style signed artifact-digest manifests on Ed25519.

The core (`aata/identity.py::SignedManifest`) seals a `{artifact name -> sha256 digest}`
map with an **HMAC** -- a faithful stand-in for the *shape* of a signed model registry, but
**symmetric**: the party that verifies holds the same `registry_key` that signs, so the
verifier can forge a manifest for any artifact set it likes. This integration is the real
primitive cosign provides: a **detached signature over the digest manifest**, signed by a
registry *private* key and verified with the registry *public* key alone.

  * `digest_of(data)`                    -> the sha256 hex of an artifact (matches the core).
  * `generate_signing_key()`             -> (signing_key, verify_key_bytes) for the registry.
  * `SignedManifest.sign(sk, digests)`   -> a manifest carrying an Ed25519 signature over the
                                            SAME canonical payload the core HMACs.
  * `m.verify(verify_key)`               -> the digest map, or raise `CosignError`.
  * `m.check(verify_key, artifacts)`     -> verify the signature AND re-hash each supplied
                                            artifact's bytes against the signed digest, so a
                                            swapped/backdoored artifact (changed digest) or a
                                            forged manifest (bad signature) is caught offline.

`cryptography` is imported lazily so the module imports cleanly when the package is absent.
The canonical payload is byte-identical to `aata/identity.py::SignedManifest._sign`, so this
is a genuine drop-in: the same golden manifest, a real signature instead of a shared secret.
"""
from __future__ import annotations

import importlib.util
import hashlib
from dataclasses import dataclass


class CosignError(Exception):
    """Invalid manifest: bad/absent signature, foreign verify key, or a digest mismatch."""


def enabled() -> bool:
    """True if the real crypto backend (`cryptography`) is importable."""
    return importlib.util.find_spec("cryptography") is not None


def digest_of(data: bytes) -> str:
    """sha256 hex of an artifact's bytes -- identical to aata/identity.py::digest."""
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- crypto helpers

def _ed():
    from cryptography.hazmat.primitives.asymmetric import ed25519   # lazy
    return ed25519


def _raw_pub(sk) -> bytes:
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    return sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def generate_signing_key():
    """Return a registry (signing_key, verify_key_bytes). The secret signs; the public verifies."""
    sk = _ed().Ed25519PrivateKey.generate()
    return sk, _raw_pub(sk)


def _canon(digests: dict) -> bytes:
    # Byte-identical to aata/identity.py::SignedManifest._sign so this manifest is a drop-in.
    return "|".join(f"{k}={digests[k]}" for k in sorted(digests)).encode()


# --------------------------------------------------------------------------- the manifest

@dataclass
class SignedManifest:
    """A `{artifact name -> sha256 digest}` map with a detached Ed25519 signature."""
    digests: dict          # name -> sha256 hex
    signature: bytes       # Ed25519 over _canon(digests)

    @classmethod
    def sign(cls, signing_key, digests: dict) -> "SignedManifest":
        """Sign a digest map with the registry secret key (cosign `sign`)."""
        sig = signing_key.sign(_canon(digests))
        return cls(dict(digests), sig)

    @classmethod
    def sign_artifacts(cls, signing_key, artifacts: dict) -> "SignedManifest":
        """Convenience: hash each `name -> content_bytes` then sign the digest map."""
        return cls.sign(signing_key, {n: digest_of(b) for n, b in artifacts.items()})

    def verify(self, verify_key: bytes) -> dict:
        """Return the signed digest map, or raise. Needs only the PUBLIC key (asymmetric)."""
        from cryptography.exceptions import InvalidSignature
        pub = _ed().Ed25519PublicKey.from_public_bytes(verify_key)
        try:
            pub.verify(self.signature, _canon(self.digests))     # tamper/forgery -> InvalidSignature
        except InvalidSignature as e:
            raise CosignError(f"manifest signature invalid: {e}") from e
        return dict(self.digests)

    def check(self, verify_key: bytes, artifacts: dict):
        """Verify the signature, then re-hash each supplied artifact against the signed digest.

        `artifacts` is `name -> content_bytes`. Returns (ok, mismatches). A swapped or
        backdoored artifact (its bytes now hash differently) and a manifest missing/adding an
        artifact are reported; a bad signature raises before any content is trusted.
        """
        signed = self.verify(verify_key)                         # raises on forged signature
        mismatches: list[str] = []
        for name, content in artifacts.items():
            expect = signed.get(name)
            if expect is None:
                mismatches.append(f"{name} (not in signed manifest)")
            elif expect != digest_of(content):
                mismatches.append(f"{name} (digest mismatch -- swapped/backdoored)")
        for name in signed:
            if name not in artifacts:
                mismatches.append(f"{name} (missing artifact)")
        return (not mismatches, mismatches)
