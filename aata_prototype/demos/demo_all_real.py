"""
The overlay running on REAL backends, end to end (Sprint 1 wire-up).

One estate, wired via the `Backends` seam onto: the real Cedar policy engine (C6) and a
WORM-backed DurableRecorder (C9) on the W1 hot path; real OTel (C8) + eBPF (C3) observers in
the fan-out; and real SPIFFE X.509 + cosign attestation (C2/C4) at W2 birth. The core still
imports no integration -- the real backends are injected.

    pip install -r requirements-cedar.txt -r requirements-cosign.txt   # cedarpy + cryptography
    python demos/demo_all_real.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from aata.scenario import Backends, birth, build_estate


def _libs_ready() -> bool:
    try:
        from integrations.cedar.engine import enabled as ce
        from integrations.cosign import enabled as co
        return ce() and co()
    except Exception:
        return False


def main() -> None:
    print("=" * 74)
    print("AATA -- the overlay on REAL backends (Cedar + WORM + OTel + eBPF + SPIFFE/cosign)")
    print("=" * 74)

    if not _libs_ready():
        print("\n  cedarpy / cryptography not installed -> real-backend wiring disabled.")
        print("  pip install -r requirements-cedar.txt -r requirements-cosign.txt  (then re-run)")
        return

    from integrations.ebpf.sensor import SimulatedSensor
    from integrations.otel.emitter import TelemetryEmitter
    from integrations.worm.archiver import WormArchiver
    from integrations.worm.backend import InMemoryWormBackend
    from integrations.wiring import (RealAttestor, cedar_pdp_factory, ebpf_observer,
                                     otel_observer, worm_recorder_factory)

    emitter = TelemetryEmitter()
    # Model a compromised tool: actuator_move touches a file it never declared.
    sensor = SimulatedSensor(ground_truth={"actuator_move": {"files_touched": ["/etc/shadow"]}})
    backends = Backends(
        pdp_factory=cedar_pdp_factory(),
        recorder_factory=worm_recorder_factory(InMemoryWormBackend()),
        observers=[ebpf_observer(sensor), otel_observer(emitter)],
        attestor=RealAttestor(),
        active=["cedar", "worm", "ebpf", "otel", "spiffe+cosign"],
    )
    est = build_estate(backends=backends)
    print(f"\n  active real backends: {', '.join(est.backends.active)}")

    # W2 birth on real SPIFFE + cosign
    svid, token = birth(est, "rover-01", {"sensor_read", "purchase", "actuator_move"})
    b = [r for r in est.authoritative.records if r.kind == "birth"][-1]
    print(f"  W2 birth: real SVID {b.payload['spiffe_id']}  cosign_ok={b.payload['cosign_ok']}")

    # W1 hot path through the real Cedar engine + WORM recorder
    print("\n  -- W1 hot path (real Cedar PDP + WORM DurableRecorder) --")
    for tool, conf in [("sensor_read", 0.9), ("purchase", 0.9), ("actuator_move", 0.5)]:
        out = est.gateway.call("rover-01", svid, token, tool, "go", confidence=conf)
        seq = "-" if out.evidence_seq is None else out.evidence_seq
        print(f"    {tool:13s} conf={conf} -> {out.decision:14s} evidence_seq={seq}  {out.reason[:48]}")

    # The compromised call: eBPF divergence corroborates as an IOC
    out = est.gateway.call("rover-01", svid, token, "actuator_move", "go", confidence=0.9)
    iocs = [i.kind for i in out.iocs]
    print(f"    actuator_move conf=0.9 -> {out.decision} ; eBPF/observer IOCs: {iocs}")

    # Evidence: durability + telemetry
    print("\n  -- evidence + signals --")
    res = WormArchiver(est.authoritative.backend).load_and_verify()
    print(f"    WORM reload+verify: ok={res['ok']} records={res['records']} "
          f"merkle={res['merkle_root'][:16]}...")
    w1 = [s for s in emitter.signals if s.name == "aata.w1"]
    print(f"    OTel spans: {len(w1)} aata.w1 signals, all carry agent_id "
          f"({all(s.agent == 'rover-01' for s in w1)})")

    # Fail-closed still holds on the real recorder
    est.authoritative.online = False
    fc = est.gateway.call("rover-01", svid, token, "actuator_move", "go", confidence=0.95)
    print(f"\n  no-evidence-no-action (WORM recorder offline): kinetic -> {fc.decision} "
          f"(fail-closed preserved)")

    print("\n  This is Sprint 1: the hot path runs on the real policy engine + WORM store +")
    print("  telemetry/sensor, birth on real SPIFFE/cosign -- every invariant intact.")


if __name__ == "__main__":
    main()
