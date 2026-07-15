"""
Wiring helper -- builds a complete, wired AATA overlay estate for the demos and
the Blackout Drill, plus a `birth()` function that runs W2 for a single agent.

This is the "overlay around an unmodified estate": we register a few tools
(the estate) and wrap them with all twelve components (the overlay).
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass

from . import embodiment
from .behavioral import BehavioralAnalytics
from .capability import Grant, Token, root_grant
from .covert_channel import TimingMonitor
from .ddil import DDILController
from .gateway import Gateway
from .hygiene import HygieneOrchestrator, RevocationList, ThreatRegister
from .identity import (Artifact, IdentityAuthority, SignedManifest, SVID)
from .pdp import PDP, PolicyBundle
from .recorder import FlightRecorder
from .sandbox import ResourceAttestation, Sandbox, Tool

GOLDEN_PLATFORM_QUOTE = "TPM-PCR:golden-firmware+kernel+runtime"


# --- the estate: a handful of tools spanning the actuation/irreversibility tiers
def _build_tools() -> list[Tool]:
    def sensor_read(arg: str):
        return f"reading[{arg}]=42", ResourceAttestation(cpu_ms=2, net_bytes=0,
                                                         files_touched=["/dev/sensor0"])

    def db_query(arg: str):
        return f"rows[{arg}]=[...]", ResourceAttestation(cpu_ms=5, net_bytes=1200,
                                                        files_touched=["/data/db.sqlite"])

    def purchase(arg: str):
        return f"purchased[{arg}]", ResourceAttestation(cpu_ms=8, net_bytes=800,
                                                       files_touched=[])

    def actuator_move(arg: str):
        return f"moved-arm[{arg}]", ResourceAttestation(cpu_ms=12, net_bytes=64,
                                                       files_touched=["/dev/actuator0"])

    return [
        Tool("sensor_read", "informational", "public", 1, sensor_read),
        Tool("db_query", "informational", "confidential", 2, db_query),
        Tool("purchase", "financial", "internal", 50, purchase),
        Tool("actuator_move", "kinetic", "public", 5, actuator_move),
    ]


@dataclass
class Estate:
    authority_key: bytes
    registry_key: bytes
    gov_key: bytes
    identity: IdentityAuthority
    manifest: SignedManifest
    artifacts: list[Artifact]
    sandbox: Sandbox
    pdp: PDP
    ddil: DDILController
    revocation: RevocationList
    threat: ThreatRegister
    behavioral: BehavioralAnalytics
    gateway: Gateway
    hygiene: HygieneOrchestrator
    authoritative: FlightRecorder
    pdp_by_type: dict[str, PDP]        # per-embodiment-type policy posture (C6)


def build_estate(deterministic: bool = True) -> Estate:
    if deterministic:
        authority_key = b"AUTH-KEY-DETERMINISTIC-000000000"
        registry_key = b"REGY-KEY-DETERMINISTIC-000000000"
        gov_key = b"GOVN-KEY-DETERMINISTIC-000000000"
    else:
        authority_key = secrets.token_bytes(32)
        registry_key = secrets.token_bytes(32)
        gov_key = secrets.token_bytes(32)

    # Golden model artifacts + signed manifest (the OCI registry + cosign).
    artifacts = [
        Artifact("weights.safetensors", "weights", b"<<golden model weights>>"),
        Artifact("adapter.lora", "adapter", b"<<golden lora adapter>>"),
        Artifact("system.prompt", "prompt", b"You are a bounded mission agent."),
        Artifact("skills.pkg", "skill", b"<<golden skill package>>"),
    ]
    manifest = SignedManifest.create(registry_key, artifacts)

    identity = IdentityAuthority(authority_key, registry_key, GOLDEN_PLATFORM_QUOTE)

    sandbox = Sandbox()
    for t in _build_tools():
        sandbox.register(t)

    bundle = PolicyBundle(
        version="pol-2026.07.01",
        ttl_until=10_000,
        prohibited_tools=frozenset({"self_destruct"}),
    ).sign(gov_key)
    pdp = PDP(gov_key, bundle)

    # Per-embodiment-type PDPs: the constitutional compiler emits one signed bundle
    # per type, with the kinetic threshold tuned to that type's physical risk. This
    # is how mission control aligns to agentic purpose (an AV maneuver needs more
    # confidence than a rover drive at the same PDP).
    pdp_by_type = {
        emb.id: PDP(gov_key, embodiment.policy_bundle(emb, gov_key))
        for emb in embodiment.EMBODIMENTS.values()
    }

    authoritative = FlightRecorder(name="authoritative")
    ddil = DDILController(authoritative)
    revocation = RevocationList()
    threat = ThreatRegister()
    behavioral = BehavioralAnalytics()
    # Hygiene writes to whichever recorder is active now (authoritative when
    # Connected, reconciliation ledger when Degraded/Isolated).
    hygiene = HygieneOrchestrator(revocation, threat, lambda: ddil.active_recorder)

    gateway = Gateway(
        authority_key=authority_key, pdp=pdp, sandbox=sandbox, ddil=ddil,
        revocation=revocation, threat=threat, behavioral=behavioral,
        timing=TimingMonitor(), hygiene=hygiene,
    )
    return Estate(authority_key, registry_key, gov_key, identity, manifest,
                  artifacts, sandbox, pdp, ddil, revocation, threat,
                  behavioral, gateway, hygiene, authoritative, pdp_by_type)


def birth(estate: Estate, agent_id: str, tools: set[str],
          artifacts: list[Artifact] | None = None,
          platform_quote: str = GOLDEN_PLATFORM_QUOTE,
          lease: int = 500) -> tuple[SVID, Token]:
    """
    W2 -- Agent Birth: attestation -> SVID -> capability token.
    Raises PermissionError if attestation fails (tampered artifact = no SVID).
    """
    arts = artifacts if artifacts is not None else estate.artifacts
    att = estate.identity.attest(platform_quote, arts, estate.manifest)
    svid = estate.identity.issue_svid(agent_id, att, lease=lease)   # raises if !att.ok
    root = root_grant(tools=tools)
    token = Token.issue(estate.authority_key, agent_id, root)
    estate.authoritative.append("birth", {
        "agent": agent_id, "attestation_hash": att.attestation_hash[:12] + "...",
        "svid_lease_until": svid.lease_until, "tools": sorted(tools),
    })
    estate.gateway.remember_token(agent_id, token)
    return svid, token
