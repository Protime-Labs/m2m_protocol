"""
C12 Governance Console guarantees -- fully offline, deterministic.

Asserts the copilot is READS-ONLY (drafts from evidence, changes no decision/state),
grounds drafts in the agent's records, and records each draft as an advisory
`governance-note` (provenance, not adjudication).
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from aata.scenario import build_estate, birth
from integrations.anthropic import GovernedAgent, dispatch
from integrations.anthropic.console import GovernanceConsole


def _stub(model, system, messages):
    return types.SimpleNamespace(
        content=[types.SimpleNamespace(type="text", text="DRAFT: grounded in seq 1; for human sign-off.")],
        stop_reason="end_turn", usage=None)


def _incident():
    """A covert-channel read that auto-narrows the agent, so there's evidence."""
    est = build_estate()
    svid, token = birth(est, "rover-01", tools={"sensor_read"}, lease=100_000)
    agent = GovernedAgent("rover-01", svid, token)
    dispatch(est, agent, "sensor_read",
             {"arg": "exfil​trate", "rationale": "routine", "confidence": 0.95}, "inc")
    return est, agent


# ---- tests -------------------------------------------------------------------

def test_gather_is_agent_scoped_and_ordered():
    est, agent = _incident()
    c = GovernanceConsole(est, transport=_stub)
    recs = c.gather("rover-01")
    assert recs and all(r["payload"].get("agent") == "rover-01" for r in recs)
    seqs = [r["seq"] for r in recs]
    assert seqs == sorted(seqs)


def test_drafts_are_nonempty_and_record_a_governance_note():
    est, agent = _incident()
    before = len(est.authoritative.records)
    c = GovernanceConsole(est, transport=_stub)
    s = c.incident_summary("rover-01")
    j = c.justification_package("rover-01")
    assert s.strip() and j.strip()
    notes = [r for r in est.authoritative.records if r.kind == "governance-note"]
    assert len(notes) == 2                                   # one per draft
    assert len(est.authoritative.records) == before + 2      # ONLY notes were added
    assert notes[0].payload["note_type"] == "incident summary"
    assert "adjudication" in notes[0].payload["note"]        # honesty marker
    assert notes[0].payload["evidence_records"]              # cites the evidence seqs


def test_console_is_reads_only_changes_no_decision():
    est, agent = _incident()
    status_before = est.hygiene.status.get("rover-01")
    revoked_before = est.revocation.is_revoked("rover-01")
    kinds_before = sorted({r.kind for r in est.authoritative.records})
    GovernanceConsole(est, transport=_stub).incident_summary("rover-01")
    # the copilot must not change hygiene status, revocation, or add any decision record
    assert est.hygiene.status.get("rover-01") == status_before
    assert est.revocation.is_revoked("rover-01") == revoked_before
    new_kinds = sorted({r.kind for r in est.authoritative.records})
    assert set(new_kinds) - set(kinds_before) <= {"governance-note"}


def test_chain_stays_intact_after_drafting():
    est, agent = _incident()
    c = GovernanceConsole(est, transport=_stub)
    c.incident_summary("rover-01")
    ok, _ = est.authoritative.verify()
    assert ok is True


def test_stub_path_never_imports_anthropic():
    est, agent = _incident()
    GovernanceConsole(est, transport=_stub).incident_summary("rover-01")
    assert "anthropic" not in sys.modules


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
    print(f"\n{passed}/{len(tests)} governance-console tests passed")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(_run())
