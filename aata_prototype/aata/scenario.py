"""
Wiring helper -- builds a complete, wired AATA overlay estate for the demos and
the Blackout Drill, plus a `birth()` function that runs W2 for a single agent.

This is the "overlay around an unmodified estate": we register a few tools
(the estate) and wrap them with all twelve components (the overlay).
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import Callable

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


@dataclass
class Backends:
    """Optional real backends injected into `build_estate`/`birth`.

    Every default is a pure-core stand-in, so the offline path imports NO integration
    (`grep 'from integrations' aata/` stays empty). `integrations/wiring.py::select_backends`
    builds a real one from the installed libs + env flags, and the demos/tests pass it via
    `build_estate(backends=...)`. The core never reaches into `integrations/`.
    """
    recorder_factory: Callable[[], object] | None = None          # () -> FlightRecorder-like
    pdp_factory: Callable[[bytes, "PolicyBundle"], object] | None = None  # (gov_key, bundle) -> PDP-like
    observers: list = field(default_factory=list)                 # gateway fan-out observers
    attestor: object | None = None                                # real SPIFFE+cosign attestor
    # Optional wrapper applied to the DDIL reconciliation ledger after construction
    # (the ledger is created inside DDILController, not via recorder_factory). Without
    # it, Degraded/Isolated evidence -- including the mode-transition record itself --
    # is invisible to any recorder-level sink until reconcile().
    wrap_ledger: Callable[[object], object] | None = None         # (FlightRecorder) -> FlightRecorder-like
    active: list = field(default_factory=list)                    # names of active real backends

    def __post_init__(self):
        if self.recorder_factory is None:
            self.recorder_factory = lambda: FlightRecorder(name="authoritative")
        if self.pdp_factory is None:
            self.pdp_factory = lambda gov_key, bundle: PDP(gov_key, bundle)

    def recorder(self):
        return self.recorder_factory()

    def make_pdp(self, gov_key: bytes, bundle: "PolicyBundle"):
        return self.pdp_factory(gov_key, bundle)


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
    backends: Backends                 # which real backends (if any) are wired


def build_estate(deterministic: bool = True, backends: Backends | None = None) -> Estate:
    backends = backends or Backends()          # pure-core stand-ins unless a real one is passed
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
    # A real attestor (SPIFFE+cosign), if wired, signs the golden manifest now so it can
    # verify each agent's artifacts at birth. No-op for the pure-core default.
    if backends.attestor is not None:
        backends.attestor.sign_golden(artifacts)

    sandbox = Sandbox()
    for t in _build_tools():
        sandbox.register(t)

    bundle = PolicyBundle(
        version="pol-2026.07.01",
        ttl_until=10_000,
        prohibited_tools=frozenset({"self_destruct"}),
    ).sign(gov_key)
    pdp = backends.make_pdp(gov_key, bundle)

    # Per-embodiment-type PDPs: the constitutional compiler emits one signed bundle
    # per type, with the kinetic threshold tuned to that type's physical risk. This
    # is how mission control aligns to agentic purpose (an AV maneuver needs more
    # confidence than a rover drive at the same PDP).
    pdp_by_type = {
        emb.id: backends.make_pdp(gov_key, embodiment.policy_bundle(emb, gov_key))
        for emb in embodiment.EMBODIMENTS.values()
    }

    authoritative = backends.recorder()
    ddil = DDILController(authoritative)
    if backends.wrap_ledger is not None:
        ddil.ledger = backends.wrap_ledger(ddil.ledger)
    revocation = RevocationList()
    threat = ThreatRegister()
    behavioral = BehavioralAnalytics()
    # Hygiene writes to whichever recorder is active now (authoritative when
    # Connected, reconciliation ledger when Degraded/Isolated).
    hygiene = HygieneOrchestrator(revocation, threat, lambda: ddil.active_recorder)

    gateway = Gateway(
        authority_key=authority_key, pdp=pdp, sandbox=sandbox, ddil=ddil,
        revocation=revocation, threat=threat, behavioral=behavioral,
        timing=TimingMonitor(), hygiene=hygiene, observers=backends.observers,
    )
    return Estate(authority_key, registry_key, gov_key, identity, manifest,
                  artifacts, sandbox, pdp, ddil, revocation, threat,
                  behavioral, gateway, hygiene, authoritative, pdp_by_type, backends)


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
    # Real SPIFFE + cosign attestation (only when a real attestor is wired): verify the
    # artifact manifest with a real cosign signature and issue+verify a real X.509 SVID. It
    # GATES birth exactly like the core attestation -- a tampered artifact fails both. (The
    # gateway hot path still validates the lightweight HMAC SVID; an X.509 SVID on the hot
    # path is a flagged follow-on, since it changes the gateway's SVID-validation interface.)
    real_att = None
    if estate.backends.attestor is not None:
        real_att = estate.backends.attestor.attest(agent_id, arts)
        if not real_att.ok:
            raise PermissionError(f"real (SPIFFE+cosign) attestation failed: {real_att.reason}")
    root = root_grant(tools=tools)
    token = Token.issue(estate.authority_key, agent_id, root)
    payload = {
        "agent": agent_id, "attestation_hash": att.attestation_hash[:12] + "...",
        "svid_lease_until": svid.lease_until, "tools": sorted(tools),
    }
    if real_att is not None:
        payload["spiffe_id"] = real_att.spiffe_id       # real X.509 SVID identity
        payload["cosign_ok"] = real_att.ok              # real signature over the digest manifest
    estate.authoritative.append("birth", payload)
    estate.gateway.remember_token(agent_id, token)
    return svid, token
