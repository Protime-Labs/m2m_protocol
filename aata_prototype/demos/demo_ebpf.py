"""
Real signal pipeline (Slice: runtime sensor, C3): kernel ground truth independent of the
agent's self-report -- catch a tool that did more than it declared.

After each governed call, an independent sensor produces its own resource attestation and
we compare it to what the tool *claimed*. An honest tool's self-report is confirmed; a
compromised tool that touches undeclared files or exfiltrates bytes is caught by the kernel
ground truth and flagged (a `runtime-divergence` IOC fed to hygiene). Offline uses a
deterministic simulated sensor; a real Tetragon/Falco event source is opt-in via AATA_EBPF.

    python demos/demo_ebpf.py                                  # simulated sensor
    AATA_EBPF=/var/run/tetragon/events.jsonl python demos/demo_ebpf.py   # real events
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from aata.scenario import build_estate, birth
from aata.sandbox import ResourceAttestation
from integrations.ebpf import SimulatedSensor, divergence, enabled, sensor


def _claimed(outcome) -> ResourceAttestation:
    a = outcome.resource_attestation
    return ResourceAttestation(a["cpu_ms"], a["net_bytes"], a["files_touched"])


def main() -> None:
    print("=" * 74)
    print("AATA RUNTIME SENSOR (C3) -- kernel ground truth vs the agent's self-report")
    print("=" * 74)
    print(f"\n  sensor: {sensor().name}"
          + ("" if enabled() else "  (offline default)"))

    est = build_estate()
    svid, token = birth(est, "rover-07", tools={"sensor_read", "db_query"}, lease=100_000)

    # An honest sensor confirms self-reports; here we ALSO model a compromised sensor_read
    # that secretly reads /etc/shadow and exfiltrates -- to show the kernel catching it.
    live = enabled()
    honest = sensor() if live else SimulatedSensor()
    compromised = sensor() if live else SimulatedSensor(
        ground_truth={"sensor_read": {"files_touched": ["/etc/shadow"], "net_bytes": 4096}})

    print("\n-- HONEST TOOL (kernel confirms the self-report) --")
    out = est.gateway.call("rover-07", svid, token, "db_query", "telemetry",
                           confidence=0.95, task_id="s")
    claimed = _claimed(out)
    obs = honest.observe("rover-07", "db_query", "telemetry", claimed)
    ioc = divergence(claimed, obs, "rover-07")
    print(f"   claimed={claimed.as_dict()}")
    print(f"   observed={obs.as_dict()}  -> divergence: {ioc or 'none (confirmed)'}")

    print("\n-- COMPROMISED TOOL (kernel sees undeclared behavior) --")
    out2 = est.gateway.call("rover-07", svid, token, "sensor_read", "bay-3",
                            confidence=0.95, task_id="c")
    claimed2 = _claimed(out2)
    obs2 = compromised.observe("rover-07", "sensor_read", "bay-3", claimed2)
    ioc2 = divergence(claimed2, obs2, "rover-07")
    print(f"   claimed={claimed2.as_dict()}")
    print(f"   observed={obs2.as_dict()}")
    if ioc2:
        print(f"   -> DIVERGENCE IOC: {ioc2.kind} sev={ioc2.severity:.2f} | {ioc2.detail}")
        inc, _ = est.hygiene.respond("rover-07", est.gateway._tokens["rover-07"], ioc2)
        print(f"   -> hygiene: Tier {inc.tier} ({inc.tier_name}), corroborated={inc.corroborated} "
              f"(a lone signal narrows; a second independent signal would quarantine)")

    ok, msg = est.authoritative.verify()
    print("\n-- EVIDENCE --")
    print(f"  {msg}  verify_ok={ok}")
    print("  the sensor attestation is INDEPENDENT of the agent -- a tool cannot hide")
    print("  undeclared file access or egress behind an honest-looking self-report (W1 step 9).")


if __name__ == "__main__":
    main()
