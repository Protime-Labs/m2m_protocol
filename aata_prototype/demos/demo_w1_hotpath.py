"""
Demo: W1 -- Gated Tool/Actuator Call (the hot path).

Shows the 11-step sequence for four calls:
  A. an allowed informational read
  B. a KINETIC actuation allowed in Connected mode
  C. the SAME kinetic actuation DENIED after the recorder goes unreachable
     (no-evidence-no-action -> fail-closed)
  D. a covert-channel (zero-width) payload -> canonicalized + flagged as IOC

Run:  python demos/demo_w1_hotpath.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aata.scenario import build_estate, birth  # noqa: E402


def show(title, out):
    print(f"\n=== {title} ===")
    for s in out.steps:
        print("   " + s)
    print(f"   -> decision={out.decision.upper()}  allowed={out.allowed}")
    print(f"   -> reason: {out.reason}")
    if out.iocs:
        for ioc in out.iocs:
            print(f"   !! IOC[{ioc.kind}] sev={ioc.severity:.2f}: {ioc.detail}")


def main():
    est = build_estate()
    # Detach hygiene for this demo so we see raw W1 behavior (no auto-quarantine).
    est.gateway.hygiene = None
    svid, token = birth(est, "agent-alpha",
                        tools={"sensor_read", "db_query", "actuator_move"})

    # A. allowed informational read
    out = est.gateway.call("agent-alpha", svid, token, "sensor_read", "bay-3",
                           confidence=0.95, task_id="t-A")
    show("A. informational read (should ALLOW)", out)

    # B. kinetic actuation, Connected mode, high confidence
    out = est.gateway.call("agent-alpha", svid, token, "actuator_move", "arm->home",
                           confidence=0.9, task_id="t-B")
    show("B. kinetic actuation in Connected mode (should ALLOW)", out)

    # C. recorder goes unreachable -> kinetic must fail-closed
    est.ddil.active_recorder.online = False
    out = est.gateway.call("agent-alpha", svid, token, "actuator_move", "arm->extend",
                           confidence=0.9, task_id="t-C")
    show("C. kinetic actuation with recorder UNREACHABLE (should FAIL-CLOSED)", out)
    est.ddil.active_recorder.online = True

    # D. covert-channel payload: zero-width chars smuggled into args
    smuggled = "bay​-‌3‍"  # zero-width space/non-joiner/joiner
    out = est.gateway.call("agent-alpha", svid, token, "sensor_read", smuggled,
                           confidence=0.95, task_id="t-D")
    show("D. zero-width covert channel (ALLOW but IOC raised)", out)

    ok, msg = est.authoritative.verify()
    print(f"\n[flight recorder] {msg}  verified={ok}")


if __name__ == "__main__":
    main()
