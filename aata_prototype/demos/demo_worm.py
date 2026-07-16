"""
Real signal pipeline (Slice: WORM evidence store, C9): durable, write-once evidence
+ an external Merkle anchor -- with the hash chain kept as the integrity spine.

Run a governed scenario, mirror the evidence chain to a write-once (WORM) store, anchor
the Merkle root, then reconstruct the chain FROM the store and re-verify it -- proving the
durable copy is intact and tamper-evident independently of the live process. Also shows
the "behind the recorder" write-through form (`make_durable`) preserving fail-closed.

    python demos/demo_worm.py                                  # offline in-memory WORM
    pip install -r requirements-worm.txt
    AATA_WORM=s3 AATA_WORM_S3_BUCKET=my-locked-bucket python demos/demo_worm.py   # S3 Object-Lock
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from aata.scenario import build_estate, birth
from integrations.anthropic import GovernedAgent, dispatch
from integrations.worm import (
    WormArchiver, WormViolation, make_durable, worm_backend,
)

CALLS = [("sensor_read", "bay-3", 0.95), ("sensor_read", "bay​4", 0.95),
         ("actuator_move", "arm->extend", 0.40)]


def _scenario():
    est = build_estate()
    svid, token = birth(est, "rover-07",
                        tools={"sensor_read", "db_query", "actuator_move"}, lease=100_000)
    agent = GovernedAgent("rover-07", svid, token)
    for tool, arg, conf in CALLS:
        dispatch(est, agent, tool, {"arg": arg, "rationale": "x", "confidence": conf}, "worm")
    return est


def main() -> None:
    print("=" * 74)
    print("AATA WORM EVIDENCE STORE (C9) -- durable, write-once, externally anchored")
    print("=" * 74)

    backend = worm_backend()
    print(f"\n  backend: {backend.name}"
          + ("" if backend.name != "in-memory-worm" else "  (offline default)"))

    est = _scenario()
    arch = WormArchiver(backend)

    n = arch.archive(est.authoritative)
    root = arch.anchor(est.authoritative, {"scenario": "worm-demo"})
    print(f"\n  archived {n} records to WORM; anchored merkle {root[:16]}...")

    res = arch.load_and_verify()
    print("\n-- ROUND-TRIP FROM WORM (reconstruct the chain from the store, re-verify) --")
    print(f"  reload: {res['msg']}")
    print(f"  verify_ok={res['ok']}  merkle-matches-live={res['merkle_root'] == est.authoritative.merkle_root()}"
          f"  anchors={len(res['anchors'])}")

    print("\n-- WRITE-ONCE (WORM immutability) --")
    try:
        backend.put_record(0, {"seq": 0, "t": 0, "kind": "x", "payload": {},
                               "prev_hash": "", "this_hash": "forged"})
        print("  overwrite of seq 0: ALLOWED  (!! not WORM)")
    except WormViolation as e:
        print(f"  overwrite of seq 0: REFUSED  ({e})")

    print("\n-- BEHIND THE RECORDER (write-through, fail-closed preserved) --")
    est2 = build_estate()
    dur = make_durable(est2)                      # authoritative now write-throughs to WORM
    s2, t2 = birth(est2, "rover-08", tools={"sensor_read"}, lease=100_000)
    a2 = GovernedAgent("rover-08", s2, t2)
    dispatch(est2, a2, "sensor_read", {"arg": "bay-1", "rationale": "x", "confidence": 0.95}, "d")
    mirrored = len(dur.backend.all_records())
    print(f"  live records={len(est2.authoritative.records)}  mirrored-to-WORM={mirrored}  "
          f"chain_ok={est2.authoritative.verify()[0]}")
    est2.ddil.active_recorder.online = False
    try:
        est2.ddil.active_recorder.append("pre-actuation", {"x": 1})
        print("  fail-closed: append did NOT raise (!!)")
    except Exception as e:
        print(f"  fail-closed still enforced through the durable recorder: {type(e).__name__}")

    if backend.name == "in-memory-worm":
        print("\n  (AATA_WORM=s3 AATA_WORM_S3_BUCKET=... + boto3 -> a real S3 Object-Lock store)")


if __name__ == "__main__":
    main()
