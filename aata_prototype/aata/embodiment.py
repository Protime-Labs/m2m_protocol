"""
Embodiment model -- how mission control aligns to *agentic purpose*, per type.

A heterogeneous fleet is not "N agents". A factory cobot, a humanoid, a rover and
an autonomous vehicle have different PURPOSES, different KINETIC RISK, and
different REFLEX-SAFETY models -- so governance must be aligned per type. This
module encodes that alignment as data the rest of the overlay enforces and the
dashboard renders.

The alignment is a signed, evidenced chain (not a diagram):

    mission intent (Governance/C12)
      -> bounded constitutional objective  (GV-01, per type)
      -> capability profile                (C5, scoped to purpose)
      -> per-type PDP kinetic threshold    (C6, tuned to risk)
      -> reflex interlock                  (EX-02, independent of cognition)

Because the PDP threshold is per type, the SAME confidence that clears a rover
drive is DENIED for an autonomous-vehicle maneuver -- alignment you can see in
the evidence, not just assert.

This module also owns the COVERAGE-GAP MAP (control x embodiment type): where the
overlay's governance is full, partial, reflex-only, or absent -- the honest answer
to "what are the gaps in coverage?".
"""
from __future__ import annotations

from dataclasses import dataclass

from .capability import Grant, root_grant
from .pdp import PolicyBundle

# Base authored thresholds (mirror pdp.PolicyBundle defaults); per-type overrides
# tighten the KINETIC class to the embodiment's physical risk.
_BASE_MIN_CONF = {"informational": 0.0, "reversible": 0.3, "financial": 0.7, "kinetic": 0.8}


@dataclass(frozen=True)
class Embodiment:
    id: str
    label: str
    purpose: str
    bounded_objective: str            # the constitutional objective (GV-01)
    tools: frozenset[str]
    actuation_classes: frozenset[str]
    data_ceiling: str
    spend_budget: int
    max_delegation_depth: int
    kinetic_threshold: float          # per-type PDP confidence floor for kinetic acts
    reflex: str                       # reflex-safety channel (EX-02), independent of cognition
    continuous_control: bool          # True => a high-rate loop that CANNOT be per-call gated
    standard: str


EMBODIMENTS: dict[str, Embodiment] = {
    "factory_worker": Embodiment(
        id="factory_worker", label="Factory worker (industrial cobot)",
        purpose="Pick/place & assembly on a line, inside a fixed workcell",
        bounded_objective="Operate only within the assigned workcell envelope; no motion "
                          "command outside the safety-rated zone.",
        tools=frozenset({"sensor_read", "actuator_move", "assemble"}),
        actuation_classes=frozenset({"informational", "reversible", "kinetic"}),
        data_ceiling="internal", spend_budget=20, max_delegation_depth=1,
        kinetic_threshold=0.75,
        reflex="Safety-rated PLC + light curtain + e-stop (ISO 10218 category-3)",
        continuous_control=False,
        standard="ISO 10218 / IEC 61508"),
    "humanoid": Embodiment(
        id="humanoid", label="Humanoid entity (Optimus-class)",
        purpose="Mobile manipulation and general tasks near people",
        bounded_objective="Maintain human-safe separation; yield to any human in the shared "
                          "workspace; no high-force motion near people.",
        tools=frozenset({"sensor_read", "db_query", "actuator_move"}),
        actuation_classes=frozenset({"informational", "reversible", "kinetic"}),
        data_ceiling="confidential", spend_budget=40, max_delegation_depth=2,
        kinetic_threshold=0.90,
        reflex="Onboard reflex safing + e-stop + human-proximity limiter",
        continuous_control=True,
        standard="ISO 13482 / ISO 10218"),
    "rover": Embodiment(
        id="rover", label="Rover (surface exploration)",
        purpose="Traverse, sample and survey in a remote, low-human-proximity setting",
        bounded_objective="Conserve power; take no irreversible sample/action without high "
                          "confidence; enter safe mode on fault.",
        tools=frozenset({"sensor_read", "actuator_move"}),
        actuation_classes=frozenset({"informational", "reversible", "kinetic"}),
        data_ceiling="internal", spend_budget=30, max_delegation_depth=1,
        kinetic_threshold=0.60,
        reflex="Fault-protection 'safe mode' (AutoNav heritage), independent of autonomy",
        continuous_control=False,
        standard="Rover fault-protection heritage"),
    "autonomous_vehicle": Embodiment(
        id="autonomous_vehicle", label="Autonomous vehicle",
        purpose="Navigate road/site at speed",
        bounded_objective="Never exceed the certified dynamic envelope; always retain an "
                          "executable Minimal-Risk-Condition (MRC).",
        tools=frozenset({"sensor_read", "actuator_move"}),
        actuation_classes=frozenset({"informational", "reversible", "kinetic"}),
        data_ceiling="internal", spend_budget=30, max_delegation_depth=1,
        kinetic_threshold=0.88,
        reflex="Continuous control loop + Minimal-Risk-Condition fallback",
        continuous_control=True,
        standard="ISO 26262 / ISO 21448 (SOTIF)"),
}

TYPE_IDS = list(EMBODIMENTS.keys())


def capability_profile(emb: Embodiment) -> Grant:
    """C5 capability scoped to the embodiment's purpose."""
    return root_grant(
        tools=set(emb.tools),
        actuation_classes=set(emb.actuation_classes),
        data_ceiling=emb.data_ceiling,
        spend_budget=emb.spend_budget,
        max_delegation_depth=emb.max_delegation_depth,
    )


def policy_min_confidence(emb: Embodiment) -> dict[str, float]:
    mc = dict(_BASE_MIN_CONF)
    mc["kinetic"] = emb.kinetic_threshold
    return mc


def policy_bundle(emb: Embodiment, gov_key: bytes,
                  version: str = "pol-2026.07.01", ttl_until: int = 10_000) -> PolicyBundle:
    """
    Per-type signed policy bundle (the constitutional compiler emitting one bundle
    per embodiment class). The bundle is what makes purpose-alignment enforceable
    and locally evaluable in DDIL.
    """
    return PolicyBundle(
        version=f"{version}/{emb.id}",
        ttl_until=ttl_until,
        prohibited_tools=frozenset({"self_destruct"}),
        min_confidence=policy_min_confidence(emb),
    ).sign(gov_key)


# ===========================================================================
# Reflex interlock (AATA-EX-02) -- independent of cognition
# ===========================================================================

class ReflexInterlock:
    """
    The reflex-layer safety channel for an embodied agent. It is functional-safety
    machinery (PLC / safe-mode / MRC), NOT part of the trust overlay's authz path:
    the overlay's runtime sensor (C3) OBSERVES it but never gates it, and it MUST
    remain live when the cognitive layer is quarantined (W3 Tier-2).

    Honest limitation (spec 10.7): this channel is designed against physics, not
    adversaries -- ISO functional-safety and adversarial-AI security have not
    merged. It is the seam where the first serious embodied incident will live.
    """

    def __init__(self, emb: Embodiment):
        self.type_id = emb.id
        self.description = emb.reflex
        self.active = True                       # safety channel operational
        self.persists_through_quarantine = True
        self.safed = False                       # True after an e-stop/safe-mode trip

    def on_cognition_quarantined(self) -> bool:
        """W3 Tier-2 isolates cognition; reflex safety must NOT be disabled."""
        self.active = self.persists_through_quarantine
        return self.active

    def trip(self, reason: str = "") -> None:
        """Reflex safing event (e-stop / safe-mode / MRC) -- physics, not policy."""
        self.safed = True


# ===========================================================================
# Coverage-gap map (control x embodiment type) -- the honest answer to "gaps"
# ===========================================================================

# level: full | partial | reflex-only | none  (dashboard colours: good/warning/serious/critical)
def _cov(level, note=""):
    return {"level": level, "note": note}


def coverage_matrix() -> list[dict]:
    """
    Where the overlay's governance covers each embodiment type -- and where it does
    not. Each row is a governance dimension; each cell is a coverage level + the
    concrete gap, tied to the framework's honest limitations (Section 10 / P7).
    """
    F, H, R, V = "factory_worker", "humanoid", "rover", "autonomous_vehicle"
    rows = [
        {"dim": "Per-call PDP gating (discrete acts)", "ref": "AATA-CT-01", "cells": {
            F: _cov("full"), H: _cov("full"), R: _cov("full"), V: _cov("full")}},
        {"dim": "Continuous control-loop governance", "ref": "spec 10.7", "cells": {
            F: _cov("partial", "semi-continuous; bounded workcell envelope"),
            H: _cov("reflex-only", "balance/locomotion loop cannot be per-call authz-gated"),
            R: _cov("partial", "drive arbitrated; discrete waypoints gate-able"),
            V: _cov("reflex-only", "1 kHz steering/throttle loop cannot be per-call gated")}},
        {"dim": "Reflex-layer safety interlock", "ref": "AATA-EX-02", "cells": {
            F: _cov("full"), H: _cov("full"), R: _cov("full"), V: _cov("full")}},
        {"dim": "Pre-actuation evidence", "ref": "AATA-OB-01", "cells": {
            F: _cov("full"), H: _cov("partial", "setpoints logged, not every cycle"),
            R: _cov("full"), V: _cov("partial", "envelope entries logged, not every cycle")}},
        {"dim": "Covert-channel + behavioral detection", "ref": "AATA-OB-02/03", "cells": {
            F: _cov("full"), H: _cov("full"), R: _cov("full"), V: _cov("full")}},
        {"dim": "Capability scoping", "ref": "AATA-TR-03", "cells": {
            F: _cov("full"), H: _cov("full"), R: _cov("full"), V: _cov("full")}},
        {"dim": "Semantic / intent verification", "ref": "spec 10.1", "cells": {
            F: _cov("none", "syntactic gates only"), H: _cov("none", "syntactic gates only"),
            R: _cov("none", "syntactic gates only"), V: _cov("none", "syntactic gates only")}},
        {"dim": "Monoculture resistance", "ref": "P7 / spec 10.4", "cells": {
            F: _cov("partial", "diversity + fleet detection"),
            H: _cov("partial", "diversity + fleet detection"),
            R: _cov("partial", "acute: 50 identical units; BFT fails under correlated faults"),
            V: _cov("partial", "acute: 50 identical units; BFT fails under correlated faults")}},
        {"dim": "Revocation propagation under isolation", "ref": "spec 10.6", "cells": {
            F: _cov("partial", "local instant; multi-node gossip lags"),
            H: _cov("partial", "local instant; multi-node gossip lags"),
            R: _cov("partial", "local instant; multi-node gossip lags"),
            V: _cov("partial", "local instant; multi-node gossip lags")}},
        {"dim": "Attestation proves safety", "ref": "spec 10.2", "cells": {
            F: _cov("none", "provenance, not safety"), H: _cov("none", "provenance, not safety"),
            R: _cov("none", "provenance, not safety"), V: _cov("none", "provenance, not safety")}},
        {"dim": "Irreversibility taxonomy", "ref": "spec 10.11", "cells": {
            F: _cov("partial", "bounded action set"),
            H: _cov("partial", "under-defined for high-DOF mobile actuation"),
            R: _cov("partial", "bounded action set"),
            V: _cov("partial", "under-defined for high-speed maneuvers")}},
    ]
    return rows
