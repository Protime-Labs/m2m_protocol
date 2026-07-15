"""
C5 -- Capability Token Service.  Control mapped: AATA-TR-03.

Production tooling: Biscuit tokens (native offline monotone attenuation, Ed25519
block chain) + a custom semantics layer for tool classes, actuation classes,
spend ceilings, and delegation depth.

This prototype reproduces the two properties AATA actually leans on:

  1. OFFLINE verification -- a token is checked with the authority's key and no
     callback to the issuer (DDIL-safe; the reason Biscuit is chosen over
     OAuth-style introspection which would cost 6-44 min round trips on Mars).

  2. MONOTONE ATTENUATION -- a sub-agent's capability is always a strict SUBSET
     of its parent's. This is enforced *at verification time* by folding every
     block as an INTERSECTION, so even a maliciously crafted "broadening" block
     cannot grant more authority than the authority root block. That is the real
     guarantee and it holds regardless of the signature primitive.

Crypto note (honest): the block chain is sealed with an HMAC/BLAKE2 hash chain
from the stdlib instead of Biscuit's Ed25519. This gives tamper-evidence of the
authority block and supports offline appends, but does NOT replicate Biscuit's
asymmetric rollback-resistance. The one-line production swap is Biscuit
(`biscuit-python`) or Macaroons. See README "Prototype vs. production".
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any

# Ordered data classifications (index = sensitivity). A ceiling of "secret"
# permits everything at or below it.
DATA_LEVELS = ["public", "internal", "confidential", "secret"]

# Actuation classes in ascending irreversibility. This ordering is exactly the
# "action-irreversibility taxonomy" the spec (Section 10.11) calls the first
# research artifact -- here it is a concrete, testable enumeration.
ACTUATION_CLASSES = ["informational", "reversible", "financial", "kinetic"]


def _canon_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


@dataclass(frozen=True)
class Grant:
    """A capability grant -- root or (restricting) attenuation."""
    tools: frozenset[str]
    actuation_classes: frozenset[str]
    data_ceiling: str
    spend_budget: int
    max_delegation_depth: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "tools": sorted(self.tools),
            "actuation_classes": sorted(self.actuation_classes),
            "data_ceiling": self.data_ceiling,
            "spend_budget": self.spend_budget,
            "max_delegation_depth": self.max_delegation_depth,
        }


def _intersect(root: Grant, block: Grant) -> Grant:
    """Fold a block into the running effective grant -- INTERSECTION ONLY."""
    return Grant(
        tools=root.tools & block.tools,
        actuation_classes=root.actuation_classes & block.actuation_classes,
        data_ceiling=DATA_LEVELS[min(
            DATA_LEVELS.index(root.data_ceiling),
            DATA_LEVELS.index(block.data_ceiling),
        )],
        spend_budget=min(root.spend_budget, block.spend_budget),
        max_delegation_depth=min(root.max_delegation_depth, block.max_delegation_depth),
    )


class CapabilityError(Exception):
    pass


class Token:
    """An offline-verifiable, attenuable capability token."""

    def __init__(self, subject: str, root_subject: str, blocks: list[Grant],
                 seal: str, depth: int):
        self.subject = subject          # who holds this token
        self.root_subject = root_subject  # subject the seal chain is rooted at
        self.blocks = blocks            # blocks[0] is the authority root grant
        self.seal = seal                # hash-chain seal over root_subject+blocks
        self.depth = depth              # delegation depth (0 = authority root)

    # ---- seal helpers ------------------------------------------------------

    @staticmethod
    def _seal_chain(authority_key: bytes, root_subject: str,
                    blocks: list[Grant]) -> str:
        acc = hmac.new(authority_key, root_subject.encode(), hashlib.blake2b).digest()
        for b in blocks:
            acc = hmac.new(acc, _canon_json(b.to_dict()), hashlib.blake2b).digest()
        return acc.hex()

    # ---- issuance / attenuation -------------------------------------------

    @classmethod
    def issue(cls, authority_key: bytes, subject: str, root: Grant) -> "Token":
        """Mint the authority (root) token -- W2 step 8."""
        seal = cls._seal_chain(authority_key, subject, [root])
        return cls(subject, subject, [root], seal, depth=0)

    def attenuate(self, restriction: Grant, sub_subject: str) -> "Token":
        """
        Offline sub-agent capability subsetting (no issuer callback).

        The holder appends a restricting block. Enforced monotonicity: the new
        block must not broaden any dimension of the *current effective* grant.
        Re-sealing extends the hash chain from the current seal -- so this works
        with no authority key and no network (the DDIL-safe delegation path).
        """
        eff = self.effective()
        if self.depth + 1 > eff.max_delegation_depth:
            raise CapabilityError(
                f"delegation depth {self.depth + 1} exceeds max {eff.max_delegation_depth}"
            )
        if not restriction.tools <= eff.tools:
            raise CapabilityError("attenuation may not add tools")
        if not restriction.actuation_classes <= eff.actuation_classes:
            raise CapabilityError("attenuation may not add actuation classes")
        if DATA_LEVELS.index(restriction.data_ceiling) > DATA_LEVELS.index(eff.data_ceiling):
            raise CapabilityError("attenuation may not raise data ceiling")
        if restriction.spend_budget > eff.spend_budget:
            raise CapabilityError("attenuation may not raise spend budget")
        blocks = self.blocks + [restriction]
        acc = bytes.fromhex(self.seal)
        acc = hmac.new(acc, _canon_json(restriction.to_dict()), hashlib.blake2b).digest()
        return Token(sub_subject, self.root_subject, blocks, acc.hex(),
                     depth=self.depth + 1)

    # ---- verification / evaluation ----------------------------------------

    def verify(self, authority_key: bytes) -> bool:
        """
        Offline verification: recompute the seal from the authority root.
        Requires the authority key but NO network round trip -- what makes the
        token usable at 22 light-minutes or in a comms blackout.
        """
        expect = self._seal_chain(authority_key, self.root_subject, self.blocks)
        return hmac.compare_digest(expect, self.seal)

    def effective(self) -> Grant:
        """Effective capability = fold(intersection) over all blocks."""
        eff = self.blocks[0]
        for b in self.blocks[1:]:
            eff = _intersect(eff, b)
        return eff

    def permits(self, tool: str, actuation_class: str, data_level: str,
                cost: int) -> tuple[bool, str]:
        """Does this token permit a specific call?  (used by the C6 PDP)."""
        eff = self.effective()
        if tool not in eff.tools:
            return False, f"tool '{tool}' not in capability allowlist"
        if actuation_class not in eff.actuation_classes:
            return False, f"actuation class '{actuation_class}' not granted"
        if DATA_LEVELS.index(data_level) > DATA_LEVELS.index(eff.data_ceiling):
            return False, f"data level '{data_level}' exceeds ceiling '{eff.data_ceiling}'"
        if cost > eff.spend_budget:
            return False, f"cost {cost} exceeds spend budget {eff.spend_budget}"
        return True, "capability sufficient"


# --- helper to build a root grant with sensible full-scope defaults ---------

def root_grant(
    tools: set[str],
    actuation_classes: set[str] = frozenset(ACTUATION_CLASSES),
    data_ceiling: str = "secret",
    spend_budget: int = 1000,
    max_delegation_depth: int = 3,
) -> Grant:
    return Grant(
        tools=frozenset(tools),
        actuation_classes=frozenset(actuation_classes),
        data_ceiling=data_ceiling,
        spend_budget=spend_budget,
        max_delegation_depth=max_delegation_depth,
    )
