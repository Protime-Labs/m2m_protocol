"""
Demo: Heterogeneous embodied fleet -- registration, autonomous governance,
failed-task accounting, and coverage gaps.

Scenario: spin up 50 factory workers + 50 humanoids + 50 rovers + 50 autonomous
vehicles (parametric), each with a purpose. Show:
  * how they REGISTER (per-type W2 birth; bad builds rejected)
  * how mission controls ALIGN to purpose (per-type kinetic thresholds)
  * the DETECTION methods (per-agent + fleet-level cohort/monoculture)
  * how the overlay RESPONDS to failed tasks and ACCOUNTS/REPORTS them
  * the GAPS in coverage (per embodiment type)

Run:  python demos/fleet_ops.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aata.embodiment import EMBODIMENTS, coverage_matrix  # noqa: E402
from aata.fleet import MissionOrchestrator, TaskStatus  # noqa: E402
from aata.scenario import build_estate  # noqa: E402

N_PER_TYPE = 50
BAD_PER_TYPE = 2


def rule(t=""):
    print("\n" + "=" * 74)
    if t:
        print(t)
        print("=" * 74)


def main():
    est = build_estate()
    orch = MissionOrchestrator(est)

    # ---- registration -------------------------------------------------
    rule("1. REGISTRATION -- per-type W2 birth (attest -> SVID -> capability)")
    reg = orch.register_fleet(n_per_type=N_PER_TYPE, bad_per_type=BAD_PER_TYPE)
    print(f"  requested {reg['requested']}  admitted {reg['admitted']}  "
          f"rejected {reg['rejected']} (tampered builds fail attestation -> no SVID)")
    for tid, c in reg["by_type"].items():
        print(f"    {tid:20s} admitted {c['admitted']:2d}  rejected {c['rejected']}")
    print(f"  rollout rings: {reg['by_ring']}   variants (P7 diversity): {reg['variants']}")

    # ---- mission-control alignment to purpose -------------------------
    rule("2. MISSION-CONTROL ALIGNMENT -- same maneuver, per-type verdict differs")
    probe = orch.probe_alignment(confidence=0.70)
    for tid, r in probe["by_type"].items():
        print(f"  {tid:20s} kinetic maneuver @conf {r['confidence']} vs threshold "
              f"{r['kinetic_threshold']} -> {r['decision'].upper()}")
    print("  => identical action + identical confidence, opposite verdict: the "
          "constitution\n     aligns each type's kinetic threshold to its physical risk.")

    # ---- run the fleet's missions -------------------------------------
    rule("3. AUTONOMOUS GOVERNANCE -- run each admitted agent's task under its type PDP")
    # designate a compromised cohort: rover / v-B, a contiguous block (P7 monoculture)
    compromised = {m.agent_id for m in orch.members.values()
                   if m.admitted and m.type_id == "rover" and m.variant == "v-B"
                   and 12 <= int(m.agent_id.split("-")[1]) <= 36}
    for m in list(orch.members.values()):
        if not m.admitted or est.revocation.is_revoked(m.agent_id):
            continue
        if m.agent_id in compromised:
            for k in range(12):                          # adversarial high-spend (each call in-policy)
                orch._call(m, "sensor_read", f"probe{k}", 0.95)
            orch.run_task(m, "sensor_read", "survey", 0.95, "survey")
        elif m.type_id == "factory_worker":
            arg = "jam" if m.agent_id == "fac-002" else "unit"   # fac-002 hits a line jam
            orch.run_task(m, "assemble", arg, 0.90, "assemble unit")
        elif m.type_id == "humanoid":
            outage = (m.agent_id == "hum-002")            # hum-002 hits a recorder outage
            orch.run_task(m, "actuator_move", "fetch", 0.95, "fetch near operator",
                          sim_recorder_outage=outage)
        elif m.type_id == "rover":
            orch.run_task(m, "actuator_move", "drive", 0.70, "traverse to waypoint")
        elif m.type_id == "autonomous_vehicle":
            conf = 0.70 if m.agent_id == "veh-002" else 0.95   # veh-002 under-confident maneuver
            orch.run_task(m, "actuator_move", "navigate", conf, "navigate route")
    acc = orch.accounting()
    print(f"  tasks run: {acc['total']}   outcomes: {acc['by_status']}")

    # ---- detection ----------------------------------------------------
    rule("4. DETECTION -- per-agent (C10/C11) + fleet-level cohort/monoculture (C11)")
    det = orch.detect_and_respond()
    print(f"  cohort outliers (anomalous vs peers, not own baseline): {det['cohort_outliers']} "
          f"({det['lone_alerts']} lone -> alert only, awaiting corroboration)")
    print(f"  monoculture alarms (correlated same-variant drift): {det['monoculture_alarms']}")
    for a in orch.monoculture_alarms:
        print(f"    ! {a.reason}")
    print(f"  blast-radius cap -> frozen rollout rings: {det['frozen_variants']}")
    print(f"  autonomously quarantined CORRELATED cluster: {len(det['quarantined'])} agents; "
          f"reflex safety preserved through quarantine (EX-02): {det['reflex_preserved']}")

    # ---- failed-task accounting (the overlay's response) --------------
    rule("5. FAILED-TASK ACCOUNTING -- how the overlay responded, by cause")
    print(f"  failure causes: {acc['by_cause']}")
    examples = {}
    for t in orch.tasks:
        if t.status in (TaskStatus.FAILED, TaskStatus.REASSIGNED, TaskStatus.DEFERRED,
                        TaskStatus.QUARANTINED) and t.cause.value not in examples:
            examples[t.cause.value] = t
    for cause, t in examples.items():
        tgt = f" -> {t.reassigned_to}" if t.reassigned_to else ""
        print(f"    [{cause:20s}] {t.agent_id} ({t.type_id}) status={t.status.value}"
              f"{tgt}\n        {t.note}")
    print("  every terminal task (success AND failure) wrote a `task-outcome` record "
          "(evidence, P5).")

    # ---- report to the engine -----------------------------------------
    rule("6. REPORT TO THE ENGINE -- internal (Mission Orchestrator + Console) + external feed")
    report = orch.external_report()
    ev = report["evidence"]
    print(f"  internal: task rollup -> Mission Orchestrator; incidents/alarms -> "
          f"Governance Console (threat level {report['governance']['threat_level']})")
    print(f"  external TaskAccountingReport (engine-consumable):")
    print(f"    registration : {report['registration']['admitted']} admitted / "
          f"{report['registration']['rejected']} rejected")
    print(f"    tasks        : {report['tasks']['by_status']}")
    print(f"    detection    : {len(report['detection']['cohort_outliers'])} outliers, "
          f"{len(report['detection']['monoculture_alarms'])} monoculture alarms")
    print(f"    governance   : tier={report['governance']['ddil_tier']}, "
          f"frozen rings={report['governance']['frozen_rollout_rings']}")
    print(f"    evidence     : {ev['authoritative_records']} records, chain_ok={ev['chain_ok']}, "
          f"merkle={ev['merkle_root'][:12]}...")
    # reconcile check
    ok, msg = est.authoritative.verify()
    print(f"  evidence chain verify: {ok} ({msg})")

    # ---- coverage gaps ------------------------------------------------
    rule("7. GAPS IN COVERAGE -- control x embodiment type (the honest answer)")
    types = list(EMBODIMENTS.keys())
    hdr = "  " + "dimension".ljust(38) + "".join(t[:4].upper().ljust(9) for t in types)
    print(hdr)
    for row in coverage_matrix():
        line = "  " + f"{row['dim'][:36]:38s}"
        for t in types:
            line += row["cells"][t]["level"][:8].ljust(9)
        print(line)
    print("\n  headline gap (10.7): continuous high-rate control (AV steering, humanoid "
          "balance)\n  is REFLEX-ONLY -- a 1 kHz loop cannot be per-call authz-gated. "
          "Semantic/intent (10.1)\n  and attestation-!=-safety (10.2) are gaps for ALL types.")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
