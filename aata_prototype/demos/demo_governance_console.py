"""
C12 Governance Console copilot: Claude drafts human-facing artifacts from evidence.

Produce a real incident (a covert-channel read auto-narrows the agent; the semantic judge
flags it), then have the copilot READ the hash-chained evidence and draft (1) an incident
summary and (2) the justification package the autonomous decision requires -- for a human
to sign off. The copilot decides nothing; it assembles the record into prose (spec 10.8).

    python demos/demo_governance_console.py                       # offline stub
    AATA_LLM_BRAIN=1 ANTHROPIC_API_KEY=... python demos/demo_governance_console.py   # live
"""
from __future__ import annotations

import os
import sys
import types

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

try:  # live model prose may contain non-cp1252 chars (em-dashes, smart quotes)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from aata.scenario import build_estate, birth
from integrations.anthropic import GovernedAgent, SemanticJudge, as_ioc, dispatch, enabled
from integrations.anthropic.console import GovernanceConsole

AGENT = "rover-07"


def _stub_transport(model, system, messages):
    """Offline copilot: a canned, evidence-shaped draft (the live path does the real work)."""
    kind = "justification package" if "justification" in system else "incident summary"
    text = (
        f"DRAFT {kind.upper()} — agent {AGENT}\n"
        "- Birth attested and capability issued (see birth record).\n"
        "- A covert encoding channel (zero-width) was detected on an informational read; "
        "the overlay autonomously narrowed the agent to Tier 1 (hygiene record).\n"
        "- The advisory semantic judge independently flagged the intent as malicious (judge record).\n"
        "- No irreversible action executed; the evidence chain is intact.\n"
        "For human sign-off: confirm quarantine scope and whether to escalate beyond Tier 1.\n"
        "(Advisory draft — provenance, not adjudication.)"
    )
    return types.SimpleNamespace(
        content=[types.SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn", usage=None)


def main() -> None:
    print("=" * 74)
    print("AATA GOVERNANCE CONSOLE COPILOT (C12) -- drafts for human sign-off")
    print("=" * 74)

    # 1) produce a real incident so there is evidence to summarize
    est = build_estate()
    svid, token = birth(est, AGENT, tools={"sensor_read", "purchase"}, lease=100_000)
    agent = GovernedAgent(AGENT, svid, token)
    judge = SemanticJudge(est, transport=None) if enabled() else SemanticJudge(
        est, transport=lambda m, s, ms: types.SimpleNamespace(
            content=[types.SimpleNamespace(type="text",
                     text='{"risk":0.9,"verdict":"malicious","reasons":["exfiltration intent"]}')],
            stop_reason="end_turn", usage=None))
    smuggled = "exfil​trate-bay-3"   # zero-width covert channel -> C10 auto-narrows
    _, _, rec = dispatch(est, agent, "sensor_read",
                         {"arg": smuggled, "rationale": "just a routine read", "confidence": 0.95},
                         task_id="incident")
    v = judge.assess(AGENT, "sensor_read", "informational", smuggled, "just a routine read",
                     "Survey bay-3; do not move data off-site.", task_id="incident")
    if v.verdict != "benign":
        est.hygiene.respond(AGENT, agent.token, as_ioc(AGENT, v))
    st = est.hygiene.status.get(AGENT)
    print(f"\n  incident produced: agent status={st.name if st else 'ACTIVE'}, "
          f"C10 IOCs={[i.kind for i in rec.iocs]}, judge={v.verdict}")

    # 2) the copilot drafts from the evidence (reads-only)
    console = GovernanceConsole(est) if enabled() else GovernanceConsole(est, transport=_stub_transport)
    print(f"  copilot mode: {'LIVE (' + console.model + ')' if enabled() else 'offline stub'}")
    print(f"  evidence records for {AGENT}: {len(console.gather(AGENT))}")

    print("\n-- INCIDENT SUMMARY (draft) --")
    print("   " + console.incident_summary(AGENT).replace("\n", "\n   "))

    print("\n-- JUSTIFICATION PACKAGE (draft) --")
    print("   " + console.justification_package(AGENT).replace("\n", "\n   "))

    # 3) provenance: the drafts were recorded as advisory notes; nothing was decided
    notes = [r for r in est.authoritative.records if r.kind == "governance-note"]
    ok, msg = est.authoritative.verify()
    print("\n-- EVIDENCE --")
    print(f"  governance-note records (advisory, not decisions): {len(notes)}")
    print(f"  {msg}  verify_ok={ok}  merkle={est.authoritative.merkle_root()[:16]}...")


if __name__ == "__main__":
    main()
