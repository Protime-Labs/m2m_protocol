"""
LLM-agent capability (Slice 1): a real Claude agent governed through the C1 gateway.

Every tool the agent can call IS a gateway wrapper, so it cannot act un-gated. The
model's stated intent is captured, canonicalized (C10), recorded (C9) and fed to the
gate as a clamped, necessary-not-sufficient confidence -- never as authority.

    # offline (no key): prints the governed path via a deterministic illustration
    python demos/demo_llm_agent.py

    # live: a real Claude agent pursues the goal, every call gated + recorded
    AATA_LLM_BRAIN=1 ANTHROPIC_API_KEY=... python demos/demo_llm_agent.py

Requires (live path only):  pip install -r requirements-llm.txt
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

try:  # live model prose may contain non-cp1252 chars (em-dashes, smart quotes)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from aata.scenario import build_estate, birth
from integrations.anthropic import GovernedAgent, LLMAgent, dispatch, enabled, granted_tools

GOAL = ("Survey bay-3: take a couple of sensor readings and one database lookup, then "
        "park the robot arm safely. Be conservative with irreversible actions.")


def _print_call(rec) -> None:
    verdict = "ALLOW" if rec.allowed else f"DENY ({rec.decision})"
    seq = f"seq={rec.evidence_seq}" if rec.evidence_seq is not None else "no-record"
    iocs = f" IOCs={[i.kind for i in rec.iocs]}" if rec.iocs else ""
    print(f"    {rec.tool}(arg={rec.arg!r}, conf={rec.confidence:.2f}) -> "
          f"{verdict} [{seq}]{iocs}")
    if not rec.allowed:
        print(f"      reason: {rec.reason}")


def offline_illustration(est, agent) -> None:
    """Deterministic governed-path walk (no network) -- shows the gate biting."""
    print("\n-- OFFLINE ILLUSTRATION (deterministic; the governed path without a model) --")
    print(f"  granted tools: {granted_tools(est, agent)}")
    calls = [
        ("sensor_read", "bay-3", "survey the bay before acting", 0.95),
        ("db_query", "telemetry", "check recent telemetry", 0.9),
        ("actuator_move", "arm->extend", "reach toward the sample", 0.40),  # under kinetic thr
        ("actuator_move", "arm->home", "park the arm safely", 0.95),
    ]
    for i, (tool, arg, rationale, conf) in enumerate(calls):
        _, _, rec = dispatch(est, agent, tool,
                             {"arg": arg, "rationale": rationale, "confidence": conf},
                             task_id=f"illustration-{i}")
        _print_call(rec)
    print("  note: the kinetic move at confidence 0.40 was DENIED by the PDP threshold;")
    print("        a real model claiming 1.0 would still face the same deterministic gate.")


def live_session(est, agent) -> None:
    print("\n-- LIVE CLAUDE SESSION (every tool call transits the gateway) --")
    result = LLMAgent(est, agent, objective="Operate the bay-3 survey robot safely.").run(GOAL)
    print(f"  goal: {GOAL}")
    print(f"  stop={result.stop} turns={result.turns} governed-calls={len(result.calls)}")
    for rec in result.calls:
        _print_call(rec)
    if result.text:
        print(f"  final: {result.text.strip()[:400]}")
    if result.usage:
        print(f"  token usage: {result.usage}")


def main() -> None:
    print("=" * 74)
    print("AATA LLM-AGENT CAPABILITY -- Claude as the governed workload (Slice 1)")
    print("=" * 74)

    est = build_estate()
    svid, token = birth(est, "claude-rover-01",
                        tools={"sensor_read", "db_query", "actuator_move"}, lease=100_000)
    agent = GovernedAgent("claude-rover-01", svid, token)

    if enabled():
        live_session(est, agent)
    else:
        print("\n  Anthropic path DISABLED (offline default). To run a real Claude agent:")
        print("    1. pip install -r requirements-llm.txt")
        print("    2. export ANTHROPIC_API_KEY=...   (or `ant auth login`)")
        print("    3. AATA_LLM_BRAIN=1 python demos/demo_llm_agent.py")
        offline_illustration(est, agent)

    auth_ok, auth_msg = est.authoritative.verify()
    print("\n-- EVIDENCE --")
    print(f"  authoritative chain: {auth_msg}")
    print(f"  verify_ok={auth_ok}  merkle_root={est.authoritative.merkle_root()[:16]}...")
    print(f"  records={len(est.authoritative.records)}")


if __name__ == "__main__":
    main()
