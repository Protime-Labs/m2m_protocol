"""
Real signal pipeline (Slice: NATS store-and-forward, C8 / W4): the DDIL reconciliation
ledger backed by a durable bus, with custody-transfer replay on reconnect.

Go Isolated (backhaul cut); isolated-mode evidence write-throughs to a durable
store-and-forward bus (a NATS JetStream leaf node in production; an in-memory durable log
offline). On reconnect, drain the bus and replay into the authoritative recorder with
custody transfer -- one continuous audit chain, zero evidence loss -- gated on fleet
re-attestation (no silent rejoin).

    python demos/demo_nats.py                                  # offline in-memory bus
    pip install -r requirements-nats.txt
    AATA_NATS=nats://localhost:4222 python demos/demo_nats.py  # real NATS JetStream
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from aata.scenario import build_estate, birth
from aata.ddil import Tier
from integrations.nats import LedgerForwarder, bus, make_forwarding


def main() -> None:
    print("=" * 74)
    print("AATA NATS STORE-AND-FORWARD (C8 / W4) -- durable ledger + custody replay")
    print("=" * 74)

    the_bus = bus()
    print(f"\n  bus: {the_bus.name}"
          + ("" if the_bus.name != "in-memory-bus" else "  (offline default)"))

    est = build_estate()
    svid, token = birth(est, "rover-07", tools={"sensor_read"}, lease=100_000)
    make_forwarding(est, the_bus)                # the DDIL ledger now write-throughs to the bus

    # --- go isolated: evidence accrues to the durable bus (store-and-forward) ---
    est.ddil.go_isolated("backhaul cut: RTT > threshold")
    for i in range(4):
        est.gateway.call("rover-07", svid, token, "sensor_read", f"iso-{i}",
                         confidence=0.95, task_id=f"iso-{i}")
    print(f"\n  ISOLATED ({est.ddil.tier.name}): {the_bus.depth} records held durably on the bus")
    print(f"  authoritative chain untouched under isolation: {len(est.authoritative.records)} records")

    # --- reconnect: reentry gate refuses without fleet re-attestation ---
    fwd = LedgerForwarder(the_bus)
    refused = fwd.replay(est.authoritative, fleet_reattests_ok=False)
    print(f"\n  reconnect w/o re-attestation -> {refused['ok']} "
          f"(reentry gate: no silent rejoin; {len(the_bus.pending())} still pending)")

    # --- reconnect with re-attestation: custody-transfer replay from the bus ---
    auth_before = len(est.authoritative.records)
    res = fwd.replay(est.authoritative, fleet_reattests_ok=True)
    reconciled = [r for r in est.authoritative.records if r.kind.startswith("reconciled:")]
    est.ddil.transition(Tier.CONNECTED, "link restored + fleet re-attested")
    ok, msg = est.authoritative.verify()
    print("\n-- CUSTODY-TRANSFER REPLAY (drain the bus into the authoritative chain) --")
    print(f"  replayed {res['replayed']} records; reconciled-in-chain={len(reconciled)}; "
          f"bus now pending={len(the_bus.pending())}")
    print(f"  provenance: each carries origin='nats-jetstream' + origin_seq/origin_hash")
    print(f"  {msg}  verify_ok={ok}  merkle={est.authoritative.merkle_root()[:16]}...")

    if the_bus.name == "in-memory-bus":
        print("\n  (AATA_NATS=nats://host:4222 + nats-py -> a real JetStream leaf node)")


if __name__ == "__main__":
    main()
