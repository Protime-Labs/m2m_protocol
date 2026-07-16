"""
The wiring seam: turn installed libraries + env flags into a core `aata.scenario.Backends`.

The core defines the `Backends` protocol with pure-core defaults and never imports anything
under `integrations/`. THIS module (which lives in `integrations/`, so it may import both) is
what a caller uses to run the overlay on real backends:

    from aata.scenario import build_estate
    from integrations.wiring import select_backends
    estate = build_estate(backends=select_backends())     # real where installed+flagged, else core

`select_backends()` is env-gated and offline-default: with no libs and no flags it returns an
all-core `Backends` (identical to `Backends()`), so nothing changes. Each real backend turns on
only when its library is importable AND its flag is set:

  * `AATA_CEDAR=1`  + cedarpy        -> the real Cedar policy engine on the hot path (via adapter)
  * `AATA_WORM=...` (+ boto3 for s3) -> a DurableRecorder write-through to a WORM backend
  * `AATA_OTEL=1`   + opentelemetry  -> a gateway observer emitting real OTel spans
  * `AATA_EBPF=<events>`             -> a gateway observer producing runtime-divergence IOCs
  * `AATA_ATTEST=1` + cryptography   -> real SPIFFE X.509 SVID + cosign manifest at birth

The helper constructors (`cedar_pdp_factory`, `worm_recorder_factory`, `otel_observer`,
`ebpf_observer`, `RealAttestor`) are used by `select_backends` and can also be composed
directly by demos/tests for deterministic, env-free wiring.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from aata.scenario import Backends


# --------------------------------------------------------------------------- Cedar (C6)

def cedar_pdp_factory():
    """A pdp_factory(gov_key, bundle) -> CedarPDPAdapter (drop-in for core PDP)."""
    from integrations.cedar.adapter import CedarPDPAdapter
    return lambda gov_key, bundle: CedarPDPAdapter(gov_key, bundle)


# --------------------------------------------------------------------------- WORM (C9)

def worm_recorder_factory(backend=None):
    """A recorder_factory() -> DurableRecorder(FlightRecorder, WORM backend).

    Preserves the synchronous fail-closed ACK (the inner FlightRecorder still raises
    RecorderUnreachable when offline). Default backend is the pure-stdlib in-memory WORM,
    so the durable write-through path runs deterministically with no external service.
    """
    from aata.recorder import FlightRecorder
    from integrations.worm.archiver import DurableRecorder
    from integrations.worm.backend import worm_backend
    b = backend or worm_backend()
    return lambda: DurableRecorder(FlightRecorder(name="authoritative"), b)


# --------------------------------------------------------------------------- observers

def otel_observer(emitter=None):
    """A gateway observer that emits one real OTel span per governed W1 call.

    Emit-only (never mutates the outcome). `agent_id` rides on every span as `aata.agent`
    (the sole cross-component join key), plus the decision, evidence seq, and IOC kinds.
    """
    from integrations.otel.emitter import TelemetryEmitter
    em = emitter or TelemetryEmitter()

    def observe(out, agent_id, tool_name, canon):
        em.emit_call(agent_id, tool_name, out.decision, out.allowed, out.evidence_seq,
                     ioc_kinds=[i.kind for i in out.iocs])
    observe.emitter = em          # exposed for inspection in tests/demos
    return observe


def ebpf_observer(sensor=None):
    """A gateway observer that compares the tool's self-reported attestation to the kernel's
    ground truth and appends a `runtime-divergence` IOC when the kernel saw more. Runs before
    hygiene, so a divergence corroborates like any other IOC.
    """
    from aata.sandbox import ResourceAttestation
    from integrations.ebpf.sensor import divergence
    from integrations.ebpf.sensor import sensor as default_sensor
    s = sensor or default_sensor()

    def observe(out, agent_id, tool_name, canon):
        claimed_d = out.resource_attestation
        if not claimed_d:                                   # denied/short-circuited call
            return
        claimed = ResourceAttestation(cpu_ms=claimed_d["cpu_ms"],
                                      net_bytes=claimed_d["net_bytes"],
                                      files_touched=list(claimed_d["files_touched"]))
        observed = s.observe(agent_id, tool_name, canon.canonical, claimed)
        ioc = divergence(claimed, observed, agent_id)
        if ioc:
            out.iocs.append(ioc)
    observe.sensor = s
    return observe


# --------------------------------------------------------------------------- attestor (C2/C4)

@dataclass
class RealAttestation:
    ok: bool
    reason: str
    spiffe_id: str


class RealAttestor:
    """SPIFFE X.509 SVID + cosign signed manifest, exercised at W2 birth.

    `sign_golden(artifacts)` signs the golden `{name -> sha256}` manifest with a real cosign
    key (called once by build_estate). `attest(agent_id, arts)` verifies the presented
    artifacts against that signature (a tampered artifact -> ok=False -> birth denied) and
    issues+verifies a real X.509 SVID whose SPIFFE ID identifies the workload.
    """
    def __init__(self, trust_domain: str = "aata.local"):
        from integrations.cosign import generate_signing_key
        from integrations.spiffe import new_ca
        self._cosign_sk, self._cosign_pub = generate_signing_key()
        self._ca_key, self._ca_cert = new_ca(trust_domain)
        self._manifest = None

    def sign_golden(self, artifacts) -> None:
        from integrations.cosign import SignedManifest
        self._manifest = SignedManifest.sign_artifacts(
            self._cosign_sk, {a.name: a.content for a in artifacts})

    def attest(self, agent_id: str, artifacts) -> RealAttestation:
        from integrations.cosign import CosignError
        from integrations.spiffe import SvidError, issue_svid, verify_svid
        if self._manifest is None:
            return RealAttestation(False, "golden manifest not signed", "")
        try:
            ok, mism = self._manifest.check(self._cosign_pub,
                                            {a.name: a.content for a in artifacts})
        except CosignError as e:
            return RealAttestation(False, f"cosign verify failed: {e}", "")
        if not ok:
            return RealAttestation(False, "cosign digest mismatch: " + "; ".join(mism), "")
        try:
            _leaf_key, leaf = issue_svid(self._ca_key, self._ca_cert, agent_id, lease_seconds=500)
            spiffe_id = verify_svid(self._ca_cert, leaf)
        except SvidError as e:
            return RealAttestation(False, f"SPIFFE SVID failed: {e}", "")
        return RealAttestation(True, "spiffe+cosign ok", spiffe_id)


# --------------------------------------------------------------------------- the factory

def select_backends() -> Backends:
    """Assemble a `Backends` from the environment. Offline-default: no flags -> all core."""
    from integrations.cedar.engine import enabled as cedar_enabled
    from integrations.cosign import enabled as cosign_enabled
    from integrations.ebpf.sensor import enabled as ebpf_enabled
    from integrations.otel.emitter import enabled as otel_enabled
    from integrations.spiffe import enabled as spiffe_enabled

    active: list[str] = []
    pdp_factory = None
    recorder_factory = None
    observers: list = []
    attestor = None

    if os.getenv("AATA_CEDAR") == "1" and cedar_enabled():
        pdp_factory = cedar_pdp_factory()
        active.append("cedar")

    if os.getenv("AATA_WORM"):
        recorder_factory = worm_recorder_factory()
        active.append("worm")

    if ebpf_enabled():                          # a real event source is present
        observers.append(ebpf_observer())
        active.append("ebpf")

    if otel_enabled():                          # emit-only observer runs after IOC producers
        observers.append(otel_observer())
        active.append("otel")

    if os.getenv("AATA_ATTEST") == "1" and cosign_enabled() and spiffe_enabled():
        attestor = RealAttestor()
        active.append("spiffe+cosign")

    return Backends(recorder_factory=recorder_factory, pdp_factory=pdp_factory,
                    observers=observers, attestor=attestor, active=active)
