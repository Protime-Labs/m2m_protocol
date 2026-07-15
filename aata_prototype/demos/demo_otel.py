"""
Real signal pipeline (Slice: OTel emission, C8): emit the overlay's signals as
OpenTelemetry -- additive, offline by default.

Run a short governed scenario, then emit each W1 verdict, each C10 IOC, and the evidence
summary (merkle anchor) as normalized telemetry. Offline it goes to an in-memory capture
backend (no dependency); with the OTel SDK installed it exports real spans. Every signal
carries the `agent_id` join key.

    python demos/demo_otel.py                                  # offline capture
    pip install -r requirements-otel.txt
    AATA_OTEL=1 python demos/demo_otel.py                      # real OTel -> console
    AATA_OTEL=1 OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 python demos/demo_otel.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from aata.scenario import build_estate, birth
from integrations.anthropic import GovernedAgent, dispatch
from integrations.otel import TelemetryEmitter, enabled

CALLS = [
    ("sensor_read", "bay-3", "routine survey", 0.95),
    ("db_query", "telemetry", "check telemetry", 0.90),
    ("sensor_read", "bay​3", "read (smuggled)", 0.95),     # zero-width -> C10 IOC
    ("actuator_move", "arm->extend", "reach", 0.40),            # under kinetic threshold -> DENY
]


def main() -> None:
    print("=" * 74)
    print("AATA OTEL EMISSION -- the overlay's signals as OpenTelemetry (C8)")
    print("=" * 74)

    est = build_estate()
    svid, token = birth(est, "rover-07",
                        tools={"sensor_read", "db_query", "actuator_move"}, lease=100_000)
    agent = GovernedAgent("rover-07", svid, token)

    emitter = TelemetryEmitter()
    live = enabled()
    print(f"\n  mode: {'LIVE OpenTelemetry (spans exported)' if live else 'offline capture (in-memory)'}")

    for tool, arg, rationale, conf in CALLS:
        _, _, rec = dispatch(est, agent, tool,
                             {"arg": arg, "rationale": rationale, "confidence": conf},
                             task_id="otel-demo")
        emitter.emit_call(agent.agent_id, tool, rec.decision, rec.allowed,
                          rec.evidence_seq, [i.kind for i in rec.iocs], rec.confidence)
        for i in rec.iocs:
            emitter.emit_ioc(i.agent_id, i.kind, i.severity, i.detail)

    summary = emitter.emit_chain(est, scenario="otel-demo")
    emitter.flush()

    print(f"\n  emitted {len(emitter.signals)} signals (every one carries an agent_id join key)")
    print("\n  W1 + IOC signals:")
    for s in emitter.signals:
        if s.name in ("aata.w1", "aata.ioc"):
            print(f"    {s.name:11} agent={s.agent:9} {s.attrs}")
    print("\n  evidence summary signal:")
    print(f"    aata.evidence  merkle={summary.attrs['merkle_root'][:16]}... "
          f"chain_ok={summary.attrs['chain_ok']} records={summary.attrs['records']}")

    if not live:
        print("\n  (pip install -r requirements-otel.txt && AATA_OTEL=1 -> exports real OTel spans;")
        print("   set OTEL_EXPORTER_OTLP_ENDPOINT to ship them to a collector)")


if __name__ == "__main__":
    main()
