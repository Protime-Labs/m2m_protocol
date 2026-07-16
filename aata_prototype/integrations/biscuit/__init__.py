"""
Biscuit-style Ed25519 capability tokens (C5) -- the real asymmetric offline-attenuable
capability primitive the prototype's HMAC seal stands in for.

The HMAC token (aata/capability.py) is symmetric: whoever can *verify* a token can also
*mint* one (same key), so the verifier is a forgery risk and there is no rollback
resistance. Biscuit is asymmetric: an authority **secret** key mints; anyone with the
authority **public** key verifies; and a holder can **attenuate offline** (append a
narrowing block) without any secret from the authority. This module implements that
construction with Ed25519 (a signed block chain + per-block key rotation + a truncation
proof), demonstrating the exact security properties on real crypto.

Additive and offline-default: the core keeps its HMAC token; this integration is opt-in
and lazily imports `cryptography` (so the base suite/CI need it not). Enabled when
`cryptography` is importable.
"""
from integrations.biscuit.token import (
    BiscuitError,
    BiscuitToken,
    enabled,
    generate_authority,
)

__all__ = ["BiscuitToken", "BiscuitError", "generate_authority", "enabled"]
