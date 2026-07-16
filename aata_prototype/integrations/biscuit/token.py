"""
A minimal, faithful Biscuit v2-style capability token on Ed25519.

Construction (append-only signed block chain with key rotation):
  * The authority block (block 0) carries the root grant and a *next* public key; it is
    signed by the authority secret key.
  * To attenuate, the holder generates a fresh key pair, appends a block carrying a caveat
    (a narrowing grant) and the new next public key, and signs it with the CURRENT block's
    secret key -- no authority secret required. The holder then carries the new secret key.
  * A `proof` signature by the last secret key over the chain of block signatures makes the
    token truncation/rollback-resistant: dropping a block would require an intermediate
    secret key the holder does not have.

Verification takes only the authority PUBLIC key: it walks the chain (each block verified
by the previous block's public key), checks the proof under the last public key, and
returns the EFFECTIVE grant = the intersection of the root grant and every caveat. Because
verification only ever intersects, attenuation can never broaden, and a crafted broadening
block is ignored.

`cryptography` is imported lazily so the module can be imported with the package absent.
"""
from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass, field


class BiscuitError(Exception):
    """Invalid token: broken signature chain, bad proof, or illegal operation."""


def enabled() -> bool:
    """True if the real crypto backend (`cryptography`) is importable."""
    return importlib.util.find_spec("cryptography") is not None


# --------------------------------------------------------------------------- crypto helpers

def _ed():
    from cryptography.hazmat.primitives.asymmetric import ed25519   # lazy
    return ed25519


def _raw_pub(sk) -> bytes:
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    return sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def _load_pub(raw: bytes):
    return _ed().Ed25519PublicKey.from_public_bytes(raw)


def _gen():
    sk = _ed().Ed25519PrivateKey.generate()
    return sk, _raw_pub(sk)


def generate_authority():
    """Return an authority (secret_key, public_key_bytes). The secret mints; the public verifies."""
    sk = _ed().Ed25519PrivateKey.generate()
    return sk, _raw_pub(sk)


def _payload(tools) -> bytes:
    return json.dumps({"tools": sorted(tools)}, separators=(",", ":")).encode()


def _tools(payload: bytes) -> frozenset:
    return frozenset(json.loads(payload)["tools"])


# --------------------------------------------------------------------------- the token

@dataclass
class BiscuitToken:
    # each block: (payload_bytes, next_public_key_raw, signature)
    blocks: list = field(default_factory=list)
    proof: bytes = b""
    _holder_sk: object = None            # secret key matching the last block's next-key

    # -- minting / attenuation ---------------------------------------------
    @classmethod
    def root(cls, authority_sk, tools: frozenset) -> "BiscuitToken":
        sk1, pk1 = _gen()
        payload = _payload(tools)
        sig = authority_sk.sign(payload + pk1)               # authority signs block 0
        blocks = [(payload, pk1, sig)]
        proof = sk1.sign(b"".join(b[2] for b in blocks))     # holder proves possession of sk1
        return cls(blocks, proof, sk1)

    def attenuate(self, tools_subset: frozenset) -> "BiscuitToken":
        """Append a narrowing caveat -- offline, WITHOUT any authority secret."""
        if self._holder_sk is None:
            raise BiscuitError("cannot attenuate a token whose holder key is absent")
        skn, pkn = _gen()
        payload = _payload(tools_subset)
        sig = self._holder_sk.sign(payload + pkn)            # signed by the CURRENT holder key
        blocks = self.blocks + [(payload, pkn, sig)]
        proof = skn.sign(b"".join(b[2] for b in blocks))     # re-prove under the new last key
        return BiscuitToken(blocks, proof, skn)

    # -- verification (authority PUBLIC key only) --------------------------
    def verify(self, authority_pub: bytes) -> frozenset:
        """Return the effective grant, or raise BiscuitError. Needs only the public key."""
        from cryptography.exceptions import InvalidSignature
        if not self.blocks:
            raise BiscuitError("empty token")
        key = _load_pub(authority_pub)
        effective = None
        try:
            for payload, next_pk, sig in self.blocks:
                key.verify(sig, payload + next_pk)           # tamper/forgery -> InvalidSignature
                tools = _tools(payload)
                effective = tools if effective is None else (effective & tools)
                key = _load_pub(next_pk)
            # truncation/rollback resistance: proof must verify under the LAST next-key
            key.verify(self.proof, b"".join(b[2] for b in self.blocks))
        except InvalidSignature as e:
            raise BiscuitError(f"signature chain invalid: {e}") from e
        return effective

    def permits(self, authority_pub: bytes, tool: str) -> bool:
        return tool in self.verify(authority_pub)

    # -- transport form (what would travel; holder key NOT included) -------
    def sealed(self) -> "BiscuitToken":
        """A copy without the holder secret -- verifiable + narrowable-by-others-no."""
        return BiscuitToken(list(self.blocks), self.proof, None)
