"""
LIVE: the store-and-forward bus on a real NATS JetStream server (C8/W4). Opt-in; needs nats-py.

Proves what CI's in-memory bus cannot: isolated-mode evidence published to a durable JetStream
stream survives a reconnect and replays into a fresh authoritative recorder with custody
transfer -- the reconciled chain verifies, carries origin provenance, and preserves `agent_id`
(the sole cross-component join key) end to end through the real broker.
"""
from __future__ import annotations

import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))     # for _live
from _live import LiveSkip, require, run_id


def run() -> None:
    require(importlib.util.find_spec("nats") is not None,
            "nats-py not installed (pip install -e '.[nats]')")
    servers = os.getenv("AATA_NATS")
    require(bool(servers), "AATA_NATS not set (e.g. nats://localhost:4222)")

    from aata.recorder import FlightRecorder
    from aata.scenario import birth, build_estate
    from integrations.nats.bus import NatsJetStreamBus
    from integrations.nats.forwarder import LedgerForwarder

    rid = run_id()
    try:                                                            # connect preflight (ctor connects)
        bus = NatsJetStreamBus(servers, subject=f"aata.live.{rid}", stream=f"AATA_LIVE_{rid}")
    except Exception as e:                                         # noqa: BLE001
        raise LiveSkip(f"cannot reach NATS JetStream at {servers}: {e}")

    # Produce isolated-mode evidence: while Isolated, calls write to the DDIL ledger.
    est = build_estate()
    svid, token = birth(est, "rover-live", {"sensor_read"})
    est.ddil.go_isolated("live validation")
    for i in range(3):
        est.gateway.call("rover-live", svid, token, "sensor_read", f"x{i}")
    ledger = est.ddil.ledger
    require(len(ledger.records) > 0, "no isolated-mode ledger records produced")

    # Publish the ledger to the durable bus (store-and-forward while isolated).
    fwd = LedgerForwarder(bus)
    published = fwd.forward(ledger)
    assert published == len(ledger.records), (published, len(ledger.records))
    print(f"  published {published} isolated-mode records to NATS JetStream (stream AATA_LIVE_{rid})")

    # Reconnect: drain FROM the durable bus and re-chain into a FRESH authoritative recorder.
    fresh = FlightRecorder(name="reconnect-authoritative")
    res = fwd.replay(fresh, fleet_reattests_ok=True)
    assert res["ok"] and res["replayed"] == published, res
    ok, _ = fresh.verify()
    assert ok, "reconciled chain fails verify()"

    reconciled = [r for r in fresh.records if r.kind.startswith("reconciled:")]
    assert len(reconciled) == published, (len(reconciled), published)
    assert all(r.payload.get("origin") == "nats-jetstream" for r in reconciled), "origin provenance lost"
    agent_seen = any(isinstance(r.payload.get("payload"), dict)
                     and r.payload["payload"].get("agent") == "rover-live"
                     for r in reconciled)
    assert agent_seen, "agent_id join key not preserved through the bus"
    print(f"  reconnect replay: {res['replayed']} records re-chained, verify ok, "
          f"origin+agent_id preserved")

    # Re-attestation gate: a reconnect that fails fleet re-attestation must NOT silently rejoin.
    denied = LedgerForwarder(bus).replay(FlightRecorder(name="x"), fleet_reattests_ok=False)
    assert not denied["ok"], "reconnect without re-attestation was allowed"

    print("  NATS JetStream live validation PASSED")


if __name__ == "__main__":
    try:
        run()
    except LiveSkip as e:
        print(f"  SKIP: {e}")
