"""
DDIL store-and-forward + reconciliation + merkle invariants (W4 / C8 / C9).

These pin the custody-transfer and evidence-anchor guarantees that were previously
exercised only by demos -- and that ANY real store/bus swap (immudb / S3 WORM, NATS
store-and-forward) must preserve: zero evidence loss under isolation, the reentry gate,
zero-gap replay, origin provenance, and a byte-stable, tamper-evident merkle anchor
(the byte-stability comes from the logical clock; a wall-clock store would break it).
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from aata.scenario import build_estate, birth
from aata.ddil import Tier


def _est_agent():
    est = build_estate()                                   # deterministic keys (default)
    svid, token = birth(est, "rover-01", tools={"sensor_read"}, lease=100_000)
    return est, "rover-01", svid, token


def _read(est, aid, svid, token, arg):
    return est.gateway.call(aid, svid, token, "sensor_read", arg, confidence=0.95, task_id=arg)


# ---- store-and-forward -------------------------------------------------------

def test_store_and_forward_writes_to_ledger_when_isolated():
    est, aid, svid, token = _est_agent()
    assert est.ddil.tier == Tier.CONNECTED and est.ddil.active_recorder is est.authoritative
    est.ddil.go_isolated("backhaul cut")
    assert est.ddil.tier == Tier.ISOLATED and est.ddil.active_recorder is est.ddil.ledger
    auth_before = len(est.authoritative.records)
    _read(est, aid, svid, token, "iso-1")
    assert len(est.authoritative.records) == auth_before   # authoritative untouched under isolation
    assert len(est.ddil.ledger.records) > 0                # evidence accrues to the ledger (no loss)


def test_go_isolated_passes_through_degraded_with_signed_mode_records():
    est, *_ = _est_agent()
    est.ddil.go_isolated("backhaul cut")
    modes = [r for r in est.ddil.ledger.records if r.kind == "mode"]
    assert len(modes) >= 2
    assert modes[0].payload["to"] == "DEGRADED" and modes[-1].payload["to"] == "ISOLATED"


def test_threat_floor_tightens_per_tier():
    est, *_ = _est_agent()
    assert est.ddil.threat_level_floor == 0.0
    est.ddil.go_isolated("cut")
    assert est.ddil.threat_level_floor == 2.0              # ISOLATED tightens the kinetic floor


# ---- reconciliation ----------------------------------------------------------

def test_reconcile_refuses_without_fleet_reattestation():
    est, aid, svid, token = _est_agent()
    est.ddil.go_isolated("cut")
    _read(est, aid, svid, token, "iso")
    res = est.ddil.reconcile(fleet_reattests_ok=False)
    assert res["ok"] is False and res["replayed"] == 0
    assert est.ddil.tier == Tier.ISOLATED                 # reentry gate: no silent rejoin


def test_reconcile_replays_with_zero_gaps_and_both_chains_verify():
    est, aid, svid, token = _est_agent()
    est.ddil.go_isolated("cut")
    for i in range(3):
        _read(est, aid, svid, token, f"iso-{i}")
    ledger_n = len(est.ddil.ledger.records)
    auth_before = len(est.authoritative.records)
    res = est.ddil.reconcile(fleet_reattests_ok=True)
    assert res["ok"] is True and res["replayed"] == ledger_n
    reconciled = [r for r in est.authoritative.records if r.kind.startswith("reconciled:")]
    assert len(reconciled) == ledger_n
    # +1 authoritative "mode" record for the CONNECTED transition on reconnect
    assert len(est.authoritative.records) == auth_before + ledger_n + 1
    assert est.authoritative.verify()[0] is True          # zero gaps in the merged chain
    assert est.ddil.ledger.verify()[0] is True
    assert est.ddil.tier == Tier.CONNECTED


def test_reconciled_records_preserve_origin_provenance():
    est, aid, svid, token = _est_agent()
    est.ddil.go_isolated("cut")
    _read(est, aid, svid, token, "iso")
    ledger_hashes = {r.this_hash for r in est.ddil.ledger.records}
    est.ddil.reconcile(fleet_reattests_ok=True)
    reconciled = [r for r in est.authoritative.records if r.kind.startswith("reconciled:")]
    assert reconciled
    for r in reconciled:
        assert r.payload["origin"] == "reconciliation-ledger"
        assert "origin_seq" in r.payload and "payload" in r.payload
        assert r.payload["origin_hash"] in ledger_hashes  # points at a real ledger record


# ---- merkle anchor -----------------------------------------------------------

def test_merkle_is_byte_stable_across_identical_deterministic_runs():
    from aata.clock import CLOCK
    saved = CLOCK._t
    try:
        def run():
            CLOCK._t = 0                                   # a FRESH logical clock (as on a cold start)
            est, aid, svid, token = _est_agent()
            _read(est, aid, svid, token, "x")
            return est.authoritative.merkle_root()
        # same scenario from a fresh clock -> identical anchor. A wall-clock store
        # would make `t` (and thus the merkle) differ every run -- this pins that.
        assert run() == run()
    finally:
        CLOCK._t = saved                                   # don't disturb later tests


def test_merkle_changes_on_append_and_is_tamper_evident():
    est, aid, svid, token = _est_agent()
    _read(est, aid, svid, token, "x")
    m1 = est.authoritative.merkle_root()
    _read(est, aid, svid, token, "y")
    assert est.authoritative.merkle_root() != m1          # anchor moves with the chain
    est.authoritative.records[0].payload["tampered"] = True
    assert est.authoritative.merkle_root() != m1          # tamper changes the anchor
    assert est.authoritative.verify()[0] is False         # ...and breaks verification


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
    print(f"\n{passed}/{len(tests)} ddil tests passed")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(_run())
