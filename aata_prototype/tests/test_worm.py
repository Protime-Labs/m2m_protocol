"""
WORM evidence-store guarantees -- fully offline, deterministic.

Asserts durable write-once persistence, an external Merkle anchor, tamper-evident
round-trip verification, and that the "behind the recorder" write-through preserves the
synchronous fail-closed ACK (no-evidence-no-action). No `boto3` import on the offline path.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from aata.scenario import build_estate, birth
from integrations.anthropic import GovernedAgent, dispatch
from integrations.worm import (
    InMemoryWormBackend, LocalFileWormBackend, WormArchiver, WormViolation,
    enabled, make_durable, worm_backend,
)


def _scenario():
    est = build_estate()
    svid, token = birth(est, "rover-01", tools={"sensor_read", "actuator_move"}, lease=100_000)
    agent = GovernedAgent("rover-01", svid, token)
    for tool, arg, c in [("sensor_read", "bay-3", 0.95), ("actuator_move", "arm->extend", 0.4)]:
        dispatch(est, agent, tool, {"arg": arg, "rationale": "x", "confidence": c}, "t")
    return est


# ---- backend selection -------------------------------------------------------

def test_enabled_false_and_default_backend_is_in_memory():
    saved = os.environ.pop("AATA_WORM", None)
    try:
        assert enabled() is False
        assert isinstance(worm_backend(), InMemoryWormBackend)
    finally:
        if saved is not None:
            os.environ["AATA_WORM"] = saved


# ---- archive / anchor / round-trip ------------------------------------------

def test_archive_and_load_verify_round_trips():
    est = _scenario()
    arch = WormArchiver(InMemoryWormBackend())
    n = arch.archive(est.authoritative)
    assert n == len(est.authoritative.records)
    res = arch.load_and_verify()
    assert res["ok"] is True
    assert res["records"] == n
    assert res["merkle_root"] == est.authoritative.merkle_root()   # durable copy == live anchor


def test_anchor_is_stored_and_matches_merkle():
    est = _scenario()
    be = InMemoryWormBackend()
    arch = WormArchiver(be)
    arch.archive(est.authoritative)
    root = arch.anchor(est.authoritative, {"scenario": "t"})
    anchors = be.anchors()
    assert len(anchors) == 1
    assert anchors[0]["merkle_root"] == root == est.authoritative.merkle_root()


def test_write_once_is_enforced():
    be = InMemoryWormBackend()
    be.put_record(0, {"seq": 0, "t": 1, "kind": "x", "payload": {}, "prev_hash": "", "this_hash": "h"})
    try:
        be.put_record(0, {"seq": 0, "t": 2, "kind": "y", "payload": {}, "prev_hash": "", "this_hash": "z"})
        assert False, "overwrite should have raised WormViolation"
    except WormViolation:
        pass


def test_tamper_on_worm_copy_is_detected_on_reload():
    est = _scenario()
    be = InMemoryWormBackend()
    WormArchiver(be).archive(est.authoritative)
    be._records[1]["payload"]["tampered"] = True          # tamper the durable copy
    res = WormArchiver(be).load_and_verify()
    assert res["ok"] is False and "tampered" in res["msg"]


# ---- behind the recorder (write-through) ------------------------------------

def test_make_durable_mirrors_gateway_writes_and_verifies():
    est = build_estate()
    be = InMemoryWormBackend()
    make_durable(est, be)
    # the swap propagates to the active recorder the gateway uses
    assert est.authoritative is est.ddil.authoritative
    svid, token = birth(est, "rover-02", tools={"sensor_read"}, lease=100_000)
    agent = GovernedAgent("rover-02", svid, token)
    dispatch(est, agent, "sensor_read", {"arg": "bay-3", "rationale": "x", "confidence": 0.95}, "t")
    assert len(be.all_records()) == len(est.authoritative.records)   # every record mirrored
    assert est.authoritative.verify()[0] is True


def test_durable_recorder_preserves_fail_closed():
    est = build_estate()
    make_durable(est, InMemoryWormBackend())
    est.ddil.active_recorder.online = False
    raised = False
    try:
        est.ddil.active_recorder.append("pre-actuation", {"x": 1})
    except Exception as e:
        raised = type(e).__name__ == "RecorderUnreachable"
    assert raised, "durable recorder must still raise RecorderUnreachable when offline"


# ---- local-file backend ------------------------------------------------------

def test_local_file_backend_round_trips_and_is_write_once():
    est = _scenario()
    with tempfile.TemporaryDirectory() as d:
        be = LocalFileWormBackend(d)
        WormArchiver(be).archive(est.authoritative)
        res = WormArchiver(be).load_and_verify()
        assert res["ok"] is True and res["records"] == len(est.authoritative.records)
        try:
            be.put_record(0, {"seq": 0, "t": 0, "kind": "x", "payload": {}, "prev_hash": "", "this_hash": "h"})
            assert False, "overwrite should have raised WormViolation"
        except WormViolation:
            pass


def test_offline_path_never_imports_boto3():
    _scenario()
    WormArchiver(InMemoryWormBackend()).load_and_verify()
    assert "boto3" not in sys.modules


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
    print(f"\n{passed}/{len(tests)} worm tests passed")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(_run())
