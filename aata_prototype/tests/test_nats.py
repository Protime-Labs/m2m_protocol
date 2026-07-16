"""
NATS store-and-forward guarantees -- fully offline, deterministic.

Asserts durable store-and-forward under isolation, FIFO-ordered custody-transfer replay
into the authoritative chain (zero gaps + origin provenance), the re-attestation reentry
gate, and that the write-through ledger preserves the synchronous fail-closed ACK. No
`nats` import on the offline path.
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from aata.scenario import build_estate, birth
from aata.ddil import Tier
from integrations.nats import InMemoryBus, LedgerForwarder, bus, enabled, make_forwarding


def _isolated_scenario():
    est = build_estate()
    svid, token = birth(est, "rover-01", tools={"sensor_read"}, lease=100_000)
    est.ddil.go_isolated("cut")
    for i in range(3):
        est.gateway.call("rover-01", svid, token, "sensor_read", f"iso-{i}",
                         confidence=0.95, task_id=f"iso-{i}")
    return est


# ---- backend selection -------------------------------------------------------

def test_enabled_false_and_default_bus_is_in_memory():
    saved = os.environ.pop("AATA_NATS", None)
    try:
        assert enabled() is False
        assert isinstance(bus(), InMemoryBus)
    finally:
        if saved is not None:
            os.environ["AATA_NATS"] = saved


# ---- store-and-forward -------------------------------------------------------

def test_forward_publishes_all_ledger_records_durably():
    est = _isolated_scenario()
    b = InMemoryBus()
    n = LedgerForwarder(b).forward(est.ddil.ledger)
    assert n == len(est.ddil.ledger.records) == b.depth
    assert len(b.pending()) == b.depth               # held until delivered (store-and-forward)


def test_authoritative_untouched_under_isolation():
    est = _isolated_scenario()
    # only the birth record is in the authoritative chain; W1 evidence went to the ledger
    assert all(not r.kind.startswith("reconciled:") for r in est.authoritative.records)
    assert len(est.ddil.ledger.records) > 0


# ---- custody-transfer replay -------------------------------------------------

def test_replay_from_bus_re_chains_with_zero_gaps_and_provenance():
    est = _isolated_scenario()
    b = InMemoryBus()
    fwd = LedgerForwarder(b)
    fwd.forward(est.ddil.ledger)
    ledger_hashes = {r.this_hash for r in est.ddil.ledger.records}
    res = fwd.replay(est.authoritative, fleet_reattests_ok=True)
    reconciled = [r for r in est.authoritative.records if r.kind.startswith("reconciled:")]
    assert res["replayed"] == len(reconciled) == b.depth
    assert est.authoritative.verify()[0] is True     # zero gaps in the merged chain
    assert len(b.pending()) == 0                      # bus drained (custody transferred)
    for r in reconciled:
        assert r.payload["origin"] == "nats-jetstream"
        assert r.payload["origin_hash"] in ledger_hashes


def test_reentry_gate_refuses_without_reattestation():
    est = _isolated_scenario()
    b = InMemoryBus()
    fwd = LedgerForwarder(b)
    fwd.forward(est.ddil.ledger)
    res = fwd.replay(est.authoritative, fleet_reattests_ok=False)
    assert res["ok"] is False and res["replayed"] == 0
    assert len(b.pending()) == b.depth                # NOT drained -> no silent rejoin


def test_bus_preserves_fifo_order():
    b = InMemoryBus()
    for s in range(5):
        b.publish({"seq": s, "t": s, "kind": "x", "payload": {}, "prev_hash": "", "this_hash": str(s)})
    assert [r["seq"] for r in b.drain()] == [0, 1, 2, 3, 4]


# ---- write-through (behind the ledger) --------------------------------------

def test_make_forwarding_mirrors_appends_and_preserves_fail_closed():
    est = build_estate()
    b = InMemoryBus()
    make_forwarding(est, b)
    assert est.ddil.ledger is not None
    svid, token = birth(est, "rover-02", tools={"sensor_read"}, lease=100_000)
    est.ddil.go_isolated("cut")                       # mode records -> forwarding ledger -> bus
    est.gateway.call("rover-02", svid, token, "sensor_read", "iso", confidence=0.95, task_id="iso")
    assert b.depth == len(est.ddil.ledger.records)    # every isolated record mirrored to the bus
    assert est.ddil.ledger.verify()[0] is True
    # fail-closed still enforced through the forwarding ledger
    est.ddil.active_recorder.online = False
    raised = False
    try:
        est.ddil.active_recorder.append("pre-actuation", {"x": 1})
    except Exception as e:
        raised = type(e).__name__ == "RecorderUnreachable"
    assert raised


def test_offline_path_never_imports_nats():
    _isolated_scenario()
    LedgerForwarder(InMemoryBus())
    assert "nats" not in sys.modules


# ---- runner ------------------------------------------------------------------

def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}: {e}")
        except Exception as e:
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} nats tests passed")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(_run())
