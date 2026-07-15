"""
C2 Identity Sidecar + C4 Identity/Attestation Service.
Controls: AATA-TR-01 (hardware-rooted identity), AATA-TR-02 (model attestation).

Production tooling: SPIRE (SVID issuance, nested topology for DDIL) + Keylime
(TPM platform attestation) + OCI registry & cosign (signed model registry) +
the *custom weights/prompt-digest attestor plugin* -- the piece that closes the
"SPIRE attests platforms, not weights" gap (AATA's differentiated IP).

W2 (Agent Birth) load-bearing rule:
    "Any digest mismatch at step 4 blocks identity issuance -- a poisoned weight
     file or tampered prompt never receives an SVID."

A tampered PROMPT fails identically to tampered WEIGHTS: both are artifacts in
the signed manifest. This module demonstrates exactly that.

Honest limitation (spec 10.2): attestation proves PROVENANCE, not SAFETY. A model
backdoored during training attests perfectly. The prototype can prove you are
running the signed artifacts; it cannot prove those artifacts are benign.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field

from .clock import CLOCK


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class Artifact:
    """A model-layer artifact: weights, LoRA adapter, system prompt, or skill."""
    name: str
    kind: str          # "weights" | "adapter" | "prompt" | "skill"
    content: bytes

    @property
    def digest(self) -> str:
        return digest(self.content)


@dataclass
class SignedManifest:
    """
    The signed golden manifest from the OCI registry (cosign in production).
    Maps artifact name -> expected digest, sealed with the registry key.
    """
    digests: dict[str, str]
    signature: str

    @classmethod
    def create(cls, registry_key: bytes, artifacts: list[Artifact]) -> "SignedManifest":
        digests = {a.name: a.digest for a in artifacts}
        sig = cls._sign(registry_key, digests)
        return cls(digests=digests, signature=sig)

    @staticmethod
    def _sign(registry_key: bytes, digests: dict[str, str]) -> str:
        payload = "|".join(f"{k}={digests[k]}" for k in sorted(digests)).encode()
        return hmac.new(registry_key, payload, hashlib.blake2b).hexdigest()

    def verify_self(self, registry_key: bytes) -> bool:
        return hmac.compare_digest(self._sign(registry_key, self.digests), self.signature)


@dataclass
class AttestationResult:
    ok: bool
    platform_ok: bool
    artifacts_ok: bool
    mismatches: list[str] = field(default_factory=list)
    attestation_hash: str = ""

    @property
    def reason(self) -> str:
        if self.ok:
            return "platform + all artifact digests match signed manifest"
        parts = []
        if not self.platform_ok:
            parts.append("platform integrity (TPM/Keylime) FAILED")
        if not self.artifacts_ok:
            parts.append("artifact mismatch: " + ", ".join(self.mismatches))
        return "; ".join(parts)


@dataclass
class SVID:
    """SPIFFE Verifiable Identity Document -- lease-based, bound to attestation."""
    subject: str
    attestation_hash: str
    issued_at: int
    lease_until: int
    signature: str

    def valid(self, authority_key: bytes, now: int | None = None) -> bool:
        now = CLOCK.now() if now is None else now
        if now > self.lease_until:
            return False
        return hmac.compare_digest(self._sign(authority_key), self.signature)

    def _sign(self, authority_key: bytes) -> str:
        payload = f"{self.subject}|{self.attestation_hash}|{self.issued_at}|{self.lease_until}"
        return hmac.new(authority_key, payload.encode(), hashlib.blake2b).hexdigest()


class IdentityAuthority:
    """SPIRE-server stand-in: attests, then issues short-lease SVIDs."""

    def __init__(self, authority_key: bytes, registry_key: bytes,
                 golden_platform_quote: str):
        self.authority_key = authority_key
        self.registry_key = registry_key
        self.golden_platform_quote = golden_platform_quote  # Keylime golden PCRs

    def attest(self, platform_quote: str, artifacts: list[Artifact],
               manifest: SignedManifest) -> AttestationResult:
        """W2 steps 1-5: platform quote + per-artifact digest match."""
        platform_ok = hmac.compare_digest(platform_quote, self.golden_platform_quote)
        manifest_authentic = manifest.verify_self(self.registry_key)
        mismatches: list[str] = []
        if manifest_authentic:
            for a in artifacts:
                expect = manifest.digests.get(a.name)
                if expect is None:
                    mismatches.append(f"{a.name} (not in manifest)")
                elif expect != a.digest:
                    mismatches.append(f"{a.name} ({a.kind} digest mismatch)")
            # every manifest entry must be present
            names = {a.name for a in artifacts}
            for name in manifest.digests:
                if name not in names:
                    mismatches.append(f"{name} (missing artifact)")
        else:
            mismatches.append("manifest signature invalid")
        artifacts_ok = manifest_authentic and not mismatches

        att_hash = ""
        if platform_ok and artifacts_ok:
            combined = platform_quote + "|" + manifest.signature
            att_hash = digest(combined.encode())
        return AttestationResult(
            ok=platform_ok and artifacts_ok,
            platform_ok=platform_ok,
            artifacts_ok=artifacts_ok,
            mismatches=mismatches,
            attestation_hash=att_hash,
        )

    def issue_svid(self, subject: str, att: AttestationResult,
                   lease: int = 100) -> SVID:
        """W2 step 6: issue SVID iff attestation passed. Else raise."""
        if not att.ok:
            raise PermissionError(f"SVID denied: {att.reason}")
        now = CLOCK.now()
        svid = SVID(
            subject=subject,
            attestation_hash=att.attestation_hash,
            issued_at=now,
            lease_until=now + lease,
            signature="",
        )
        svid.signature = svid._sign(self.authority_key)
        return svid
