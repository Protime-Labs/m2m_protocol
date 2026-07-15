"""
Fleet invariants -- the heterogeneous-fleet guarantees as executable assertions.

    python tests/test_fleet.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aata.behavioral import FleetAnalytics
from aata.embodiment import EMBODIMENTS, ReflexInterlock, coverage_matrix
from aata.fleet import FailureCause, MissionOrchestrator, TaskStatus
from aata.scenario import build_estate


def _orch(n=4, bad=1):
    est = build_estate()
    orch = MissionOrchestrator(est)
    orch.register_fleet(n_per_type=n, bad_per_type=bad)
    return est, orch


# ---- registration gating -------------------------------------------------

def test_tampered_build_is_rejected_at_registration():
    est, orch = _orch(n=4, bad=1)
    reg = orch.reg_summary
    assert reg["rejected"] == 4, reg           # 1 bad build per type x 4 types
    rejected = [m for m in orch.members.values() if not m.admitted]
    assert rejected and all(m.svid is None and m.reject_reason for m in rejected)


# ---- mission-control alignment to purpose --------------------------------

def test_per_type_kinetic_threshold_enforced():
    est, orch = _orch()
    probe = orch.probe_alignment(confidence=0.70)
    by = probe["by_type"]
    # same maneuver, same confidence -> rover ALLOWED, AV DENIED
    assert by["rover"]["allowed"] is True, by["rover"]
    assert by["autonomous_vehicle"]["allowed"] is False, by["autonomous_vehicle"]


# ---- failed-task accounting ---------------------------------------------

def test_failed_task_writes_outcome_with_cause():
    est, orch = _orch()
    fac = next(m for m in orch.members.values()
               if m.admitted and m.type_id == "factory_worker")
    task = orch.run_task(fac, "assemble", "jam", 0.9, "assemble unit")
    assert task.cause == FailureCause.TOOL_ERROR
    assert task.status in (TaskStatus.REASSIGNED, TaskStatus.FAILED)
    # a task-outcome record exists in the recorder for this task
    recs = [r for r in est.authoritative.records
            if r.kind == "task-outcome" and r.payload.get("task_id") == task.id]
    assert recs and recs[0].payload["cause"] == "tool_error"


def test_policy_denied_task_is_deferred():
    est, orch = _orch()
    av = next(m for m in orch.members.values()
              if m.admitted and m.type_id == "autonomous_vehicle")
    task = orch.run_task(av, "actuator_move", "maneuver", 0.50, "navigate")  # < 0.88
    assert task.cause == FailureCause.POLICY_DENIED
    assert task.status == TaskStatus.DEFERRED


# ---- fleet-level detection ----------------------------------------------

def test_monoculture_alarm_fires_on_correlated_variant_drift():
    fa = FleetAnalytics()
    for i in range(6):                       # rover/v-A: clean cohort, spend ~5
        fa.register(f"a{i}", "rover", "v-A")
        for _ in range(5):
            fa.observe(f"a{i}", "t", 1)
    for i in range(6):                       # rover/v-B: 4 of 6 drift together
        fa.register(f"b{i}", "rover", "v-B")
        for _ in range(13 if i < 4 else 5):
            fa.observe(f"b{i}", "t", 1)
    outliers, alarms = fa.assess()
    assert any(a.variant == "v-B" and a.n_drifting >= 4 for a in alarms), alarms
    # the clean sibling variant is NOT alarmed
    assert not any(a.variant == "v-A" for a in alarms)


# ---- reflex interlock (EX-02) -------------------------------------------

def test_reflex_persists_through_quarantine():
    r = ReflexInterlock(EMBODIMENTS["humanoid"])
    assert r.active
    assert r.on_cognition_quarantined() is True   # cognition isolated, reflex stays live
    assert r.active is True


# ---- coverage-gap map ----------------------------------------------------

def test_coverage_matrix_has_expected_gaps():
    rows = {r["dim"]: r["cells"] for r in coverage_matrix()}
    # continuous control on an AV is reflex-only (spec 10.7)
    assert rows["Continuous control-loop governance"]["autonomous_vehicle"]["level"] == "reflex-only"
    # semantic/intent is a gap for ALL types (spec 10.1)
    sem = rows["Semantic / intent verification"]
    assert all(sem[t]["level"] == "none" for t in EMBODIMENTS)


# ---- accounting reconciles with evidence --------------------------------

def test_external_report_reconciles_with_recorder():
    est, orch = _orch()
    for m in list(orch.members.values()):
        if m.admitted:
            orch.run_task(m, "sensor_read", "survey", 0.95, "survey")
    report = orch.external_report()
    assert report["evidence"]["authoritative_records"] == len(est.authoritative.records)
    assert report["evidence"]["chain_ok"] is True
    assert report["tasks"]["total"] == len(orch.tasks)


# ---- runner --------------------------------------------------------------

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
    print(f"\n{passed}/{len(tests)} fleet tests passed")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(_run())
