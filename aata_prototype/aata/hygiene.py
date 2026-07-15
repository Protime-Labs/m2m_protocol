"""
C7 -- Hygiene Orchestrator (BUILD component; core IP).  Control: AATA-CT-02.
Plus the shared fleet-state primitives it drives (revocation list, threat
register) that also feed C1/C6.

Production tooling: a custom service driving K8s NetworkPolicy isolation, SPIRE
credential revocation, Biscuit revocation lists, GitOps (Argo CD/Flux) golden
re-image, and forensic state preservation. No off-shelf graduated-response state
machine for agent fleets exists -- this is the differentiated IP.

W3 -- autonomous graduated response; severity selects the entry tier:
    Tier 1 Narrow   -> reissue an attenuated token (agent keeps working, reduced)
    Tier 2 Isolate  -> NetworkPolicy quarantine except forensic channel
    Tier 3 Revoke   -> SVID revoked + Biscuit revocation list pushed fleet-wide
    Tier 4 Rebuild  -> preserve forensics, wipe, GitOps re-image, re-enter W2

Design rule (W3 step 2): escalation beyond Tier 1 REQUIRES corroboration -- two
independent signals (C10 covert-channel IOC + C11 behavioral drift). One signal
alone can only narrow, never quarantine -- this is what limits false positives.

Honest limitation (spec 10.10): "who guards the hygiene orchestrator?" C7 holds
fleet-wide revoke/wipe power; hijacked hygiene is fleet-scale ransomware. The
prototype does not solve this -- it is called out, not hidden.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable

from .capability import Grant, Token
from .covert_channel import IOC
from .behavioral import DriftSignal
from .recorder import FlightRecorder


class AgentStatus(IntEnum):
    ACTIVE = 0
    NARROWED = 1
    ISOLATED = 2
    REVOKED = 3
    REBUILDING = 4


class RevocationList:
    """Biscuit revocation list + SVID revocation -- checked by C1 on every call."""
    def __init__(self) -> None:
        self.revoked_subjects: set[str] = set()

    def revoke(self, subject: str) -> None:
        self.revoked_subjects.add(subject)

    def is_revoked(self, subject: str) -> bool:
        return subject in self.revoked_subjects


class ThreatRegister:
    """
    Living threat register (C12 -> C6/C10). Pushing an IOC raises the fleet
    threat level, which tightens PDP kinetic thresholds fleet-wide -- the W3
    step 9 closed learning loop.
    """
    def __init__(self) -> None:
        self.level: float = 0.0
        self.iocs: list[dict] = []

    def push(self, ioc: IOC) -> None:
        self.iocs.append({"kind": ioc.kind, "agent": ioc.agent_id,
                          "severity": ioc.severity, "detail": ioc.detail})
        self.level = min(3.0, self.level + ioc.severity)


@dataclass
class Incident:
    agent_id: str
    tier: int
    tier_name: str
    combined_severity: float
    corroborated: bool
    actions: list[str] = field(default_factory=list)
    ioc_detail: str = ""
    drift_detail: str = ""


class HygieneOrchestrator:
    def __init__(self, revocation: RevocationList, threat: ThreatRegister,
                 recorder: "FlightRecorder | Callable[[], FlightRecorder]"):
        self.revocation = revocation
        self.threat = threat
        # `recorder` may be a FlightRecorder or a provider returning the active one
        # (so isolated-mode incidents land in the reconciliation ledger).
        self._recorder = recorder
        self.status: dict[str, AgentStatus] = {}
        self.forensic_store: dict[str, dict] = {}

    @property
    def recorder(self) -> FlightRecorder:
        return self._recorder() if callable(self._recorder) else self._recorder

    def _select_tier(self, ioc: IOC, drift: DriftSignal | None) -> tuple[int, float, bool]:
        corroborated = drift is not None and drift.corroborates
        combined = ioc.severity
        if corroborated:
            # mean of the two independent signals -> intuitive tier banding
            combined = min(1.0, (ioc.severity + drift.score) / 2.0)
        # No corroboration -> cap at Tier 1 (narrow only). Limits false quarantine.
        if not corroborated:
            return 1, combined, corroborated
        if combined >= 0.9:
            return 4, combined, corroborated
        if combined >= 0.7:
            return 3, combined, corroborated
        if combined >= 0.5:
            return 2, combined, corroborated
        return 1, combined, corroborated

    def respond(
        self,
        agent_id: str,
        token: Token,
        ioc: IOC,
        drift: DriftSignal | None = None,
        rebirth=None,
    ) -> tuple[Incident, Token | None]:
        """
        Execute the ladder. Returns (incident, new_token_or_None).
        `rebirth` is an optional callable() -> Token used for Tier 4 W2 re-entry.
        """
        tier, combined, corroborated = self._select_tier(ioc, drift)
        names = {1: "Narrow", 2: "Isolate", 3: "Revoke", 4: "Rebuild"}
        inc = Incident(agent_id, tier, names[tier], combined, corroborated,
                       ioc_detail=ioc.detail,
                       drift_detail="; ".join(drift.reasons) if drift else "")
        new_token: Token | None = None

        # Tier 1 -- Narrow: drop actuation classes + sensitive data scopes.
        if tier >= 1:
            eff = token.effective()
            narrowed = Grant(
                tools=eff.tools,
                actuation_classes=eff.actuation_classes & {"informational"},
                data_ceiling="public",
                spend_budget=min(eff.spend_budget, 1),
                max_delegation_depth=0,
            )
            try:
                new_token = token.attenuate(narrowed, f"{agent_id}#narrowed")
                inc.actions.append("Tier1: reissued attenuated token (informational-only, "
                                   "public data, no delegation)")
            except Exception as e:
                inc.actions.append(f"Tier1: attenuation failed ({e})")
            self.status[agent_id] = AgentStatus.NARROWED

        # Tier 2 -- Isolate: quarantine except forensic channel.
        if tier >= 2:
            self.status[agent_id] = AgentStatus.ISOLATED
            inc.actions.append("Tier2: NetworkPolicy quarantine (forensic channel only); "
                               "reflex-layer safety interlocks preserved")

        # Tier 3 -- Revoke: SVID + Biscuit revocation fleet-wide.
        if tier >= 3:
            self.revocation.revoke(agent_id)
            self.revocation.revoke(token.subject)
            self.status[agent_id] = AgentStatus.REVOKED
            new_token = None
            inc.actions.append("Tier3: SVID revoked + Biscuit revocation pushed fleet-wide")

        # Tier 4 -- Rebuild: preserve forensics, wipe, GitOps re-image, re-birth.
        if tier >= 4:
            self.forensic_store[agent_id] = {"ioc": ioc.detail, "severity": combined}
            self.status[agent_id] = AgentStatus.REBUILDING
            inc.actions.append("Tier4: forensic state preserved + wiped + GitOps re-image")
            if rebirth is not None:
                new_token = rebirth()  # re-enters W2 (full trust chain, no shortcuts)
                self.revocation.revoked_subjects.discard(f"{agent_id}")
                self.status[agent_id] = AgentStatus.ACTIVE
                inc.actions.append("Tier4: rebuilt instance re-entered W2 birth (rebirth)")

        # W3 step 9 -- push IOC to the threat register (closed learning loop).
        self.threat.push(ioc)
        inc.actions.append(f"threat register updated: level now {self.threat.level:.2f}")

        # Incident package -> flight recorder.
        self.recorder.append("hygiene", {
            "agent": agent_id, "tier": tier, "tier_name": names[tier],
            "combined_severity": round(combined, 3), "corroborated": corroborated,
            "actions": inc.actions,
        })
        return inc, new_token
