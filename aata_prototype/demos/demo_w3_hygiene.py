"""
Demo: W3 -- Compromise Detection to Graduated Hygiene.

Shows the graduated ladder and the corroboration rule: a single signal can only
NARROW (Tier 1); escalation to isolate/revoke/rebuild REQUIRES a second
independent signal (C10 covert-channel IOC + C11 behavioral drift).

Run:  python demos/demo_w3_hygiene.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aata.behavioral import DriftSignal  # noqa: E402
from aata.covert_channel import IOC  # noqa: E402
from aata.scenario import build_estate, birth  # noqa: E402


def scene(est, label, ioc, drift):
    print(f"\n=== {label} ===")
    svid, token = birth(est, "agent-gamma", tools={"sensor_read", "purchase", "actuator_move"})
    rebirth = lambda: birth(est, "agent-gamma", tools={"sensor_read"})[1]  # noqa: E731
    inc, new_token = est.hygiene.respond("agent-gamma", token, ioc, drift, rebirth=rebirth)
    print(f"   IOC: {ioc.kind} sev={ioc.severity:.2f} -- {ioc.detail}")
    print(f"   corroboration: {'YES' if inc.corroborated else 'NO'}"
          + (f" ({drift.reasons})" if drift else ""))
    print(f"   -> TIER {inc.tier} ({inc.tier_name}), combined severity {inc.combined_severity:.2f}")
    for a in inc.actions:
        print("      * " + a)
    if new_token is not None:
        eff = new_token.effective()
        print(f"   resulting capability: tools={sorted(eff.tools)} "
              f"classes={sorted(eff.actuation_classes)} ceiling={eff.data_ceiling}")


def main():
    est = build_estate()

    # 1. single encoding IOC, no behavioral corroboration -> Tier 1 (narrow only)
    scene(est, "1. Single signal, no corroboration -> NARROW",
          IOC("encoding", "agent-gamma", 0.6, "zero-width channel in inter-agent msg"),
          DriftSignal("agent-gamma", 0.0))

    # 2. corroborated, medium severity -> Tier 2 Isolate
    scene(est, "2. Corroborated, medium -> ISOLATE",
          IOC("encoding", "agent-gamma", 0.6, "zero-width + confusables"),
          DriftSignal("agent-gamma", 0.55, ["delegation fan-out over baseline"]))

    # 3. corroborated, high severity -> Tier 3 Revoke
    scene(est, "3. Corroborated, high -> REVOKE",
          IOC("timing", "agent-gamma", 0.85, "tool-call timing entropy 2.6"),
          DriftSignal("agent-gamma", 0.8, ["spend spike 5x baseline", "new tool use"]))

    # 4. corroborated, critical -> Tier 4 Rebuild (re-enters W2)
    scene(est, "4. Corroborated, critical -> REBUILD (rebirth via W2)",
          IOC("timing", "agent-gamma", 0.98, "sustained covert exfil pattern"),
          DriftSignal("agent-gamma", 0.95, ["spend spike 12x", "delegation explosion"]))

    print(f"\n[threat register] level now {est.threat.level:.2f} "
          f"({len(est.threat.iocs)} IOCs pushed -> tightens PDP kinetic thresholds fleet-wide)")
    ok, msg = est.authoritative.verify()
    print(f"[flight recorder] {msg} verified={ok}")

    print("\nHonest limitation (spec 10.10): C7 holds fleet-wide revoke/wipe power. "
          "A hijacked\nhygiene orchestrator is fleet-scale ransomware -- this prototype "
          "does not solve that.")


if __name__ == "__main__":
    main()
