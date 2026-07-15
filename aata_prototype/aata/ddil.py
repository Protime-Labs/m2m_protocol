"""
W4 -- DDIL Transition and Reconciliation.  Control: AATA-DD-01.

Production tooling: NATS JetStream leaf nodes (store-and-forward) + the local
reconciliation ledger (SQLite hash-chain) + peer-attestation mesh (nested SPIRE /
quorum). The custody model is DTN Bundle Protocol (RFC 5050 / CCSDS) semantics.

Three connectivity tiers (from the framework's DDIL operating model):
    CONNECTED  -- central authority + PDP authoritative; human-on-the-loop.
    DEGRADED   -- policy cache with TTL governs; store-and-forward evidence.
    ISOLATED   -- intrinsic constitutional constraints are the sole governance;
                  peer mesh assumes trust duties; autonomous quarantine;
                  reconciliation ledger accrues for post-hoc audit.

Guarantees demonstrated:
  * Signed mode-transition records at every tier change.
  * On isolation, W1/W3 evidence accrues to a LOCAL reconciliation ledger under a
    custody model -- never dropped (zero evidence loss).
  * On reconnect, the ledger REPLAYS into the authoritative recorder with custody
    transfer, producing one continuous audit chain across the disconnection.
  * Reentry gate: privileges restore only AFTER fleet re-attestation.

Honest limitation (spec 10.6): revocation is a connectivity event -- a credential
compromised during isolation lives until the mesh notices. The drill records if a
credential lived longer than it should have rather than pretending it can't.
"""
from __future__ import annotations

from enum import IntEnum

from .recorder import FlightRecorder, Record


class Tier(IntEnum):
    CONNECTED = 0
    DEGRADED = 1
    ISOLATED = 2


class DDILController:
    """Manages tier transitions and the local reconciliation ledger."""

    def __init__(self, authoritative: FlightRecorder):
        self.tier = Tier.CONNECTED
        self.authoritative = authoritative
        # The local ledger used while Degraded/Isolated (store-and-forward).
        self.ledger = FlightRecorder(name="reconciliation-ledger")
        self.threat_level_floor = 0.0

    @property
    def active_recorder(self) -> FlightRecorder:
        """Where W1/W3 evidence is written right now."""
        return self.authoritative if self.tier == Tier.CONNECTED else self.ledger

    def transition(self, new_tier: Tier, reason: str) -> Record:
        old = self.tier
        self.tier = new_tier
        # kinetic thresholds tighten as we lose connectivity (W4 step 2).
        self.threat_level_floor = {Tier.CONNECTED: 0.0, Tier.DEGRADED: 1.0,
                                   Tier.ISOLATED: 2.0}[new_tier]
        rec = self.active_recorder.append("mode", {
            "from": old.name, "to": new_tier.name, "reason": reason,
            "kinetic_threshold_floor": self.threat_level_floor,
        })
        return rec

    def go_isolated(self, reason: str = "link loss: RTT>threshold / conjunction") -> None:
        if self.tier == Tier.CONNECTED:
            self.transition(Tier.DEGRADED, "link degrades")
        self.transition(Tier.ISOLATED, reason)

    def reconcile(self, fleet_reattests_ok: bool) -> dict:
        """
        Reconnect: fleet re-attests (reentry gate), then the local ledger replays
        into the authoritative recorder with custody-transfer semantics.
        """
        if not fleet_reattests_ok:
            return {"ok": False, "reason": "fleet re-attestation failed -- no silent rejoin",
                    "replayed": 0}
        replayed = 0
        for rec in self.ledger.records:
            # custody transfer: copy each isolated-mode record into the authoritative
            # chain, preserving payload + provenance (re-chained under the auth head).
            self.authoritative.append("reconciled:" + rec.kind, {
                "origin": "reconciliation-ledger",
                "origin_seq": rec.seq,
                "origin_hash": rec.this_hash,
                "payload": rec.payload,
            })
            replayed += 1
        # Custody transfer confirmed -> the ledger's evidence is now durable.
        self.transition(Tier.CONNECTED, "link restored + fleet re-attested")
        return {"ok": True, "replayed": replayed,
                "auth_head": self.authoritative.head[:12] + "..."}
