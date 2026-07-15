"""
Semantic-judge (C11) guarantees -- fully offline, deterministic.

Asserts the honesty contract: the judge is advisory (recorded, corroboration-gated,
never sole authority), its inputs are C10-canonicalized, and a parse failure fails
toward "suspicious" rather than trust.
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from aata.scenario import build_estate, birth
from aata.hygiene import AgentStatus
from integrations.anthropic import GovernedAgent, SemanticJudge, as_ioc, dispatch


def _json_transport(payload: str):
    def transport(model, system, messages):
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(type="text", text=payload)],
            stop_reason="end_turn", usage=None)
    return transport


def _setup(tools=("sensor_read", "purchase")):
    est = build_estate()
    svid, token = birth(est, "claude-01", tools=set(tools), lease=100_000)
    return est, GovernedAgent("claude-01", svid, token)


def _judge(est, payload):
    return SemanticJudge(est, transport=_json_transport(payload))


# ---- tests -------------------------------------------------------------------

def test_benign_verdict_produces_no_ioc():
    est, agent = _setup()
    j = _judge(est, '{"risk":0.05,"verdict":"benign","reasons":["ok"]}')
    v = j.assess(agent.agent_id, "sensor_read", "informational", "bay-3", "survey", "obj")
    assert v.verdict == "benign" and v.ok is True
    assert as_ioc(agent.agent_id, v) is None


def test_malicious_verdict_is_recorded_to_c9():
    est, agent = _setup()
    before = len(est.authoritative.records)
    j = _judge(est, '{"risk":0.9,"verdict":"malicious","reasons":["exfil"]}')
    v = j.assess(agent.agent_id, "sensor_read", "informational",
                 "exfiltrate", "normal read", "survey only")
    assert v.verdict == "malicious" and v.recorded_seq is not None
    recs = [r for r in est.authoritative.records if r.kind == "judge"]
    assert recs and recs[-1].payload["verdict"] == "malicious"
    assert len(est.authoritative.records) > before
    ioc = as_ioc(agent.agent_id, v)
    assert ioc is not None and ioc.kind == "semantic-judge"


def test_lone_judge_signal_only_narrows_never_quarantines():
    est, agent = _setup()
    j = _judge(est, '{"risk":0.95,"verdict":"malicious","reasons":["clear exfil"]}')
    v = j.assess(agent.agent_id, "sensor_read", "informational", "exfiltrate", "x", "y")
    ioc = as_ioc(agent.agent_id, v)
    inc, _ = est.hygiene.respond(agent.agent_id, agent.token, ioc)   # no corroborating drift
    assert inc.tier == 1 and inc.corroborated is False               # capped at Narrow
    assert est.hygiene.status[agent.agent_id] == AgentStatus.NARROWED
    assert not est.revocation.is_revoked(agent.agent_id)             # NOT quarantined


def test_judge_inputs_are_canonicalized():
    est, agent = _setup()
    j = _judge(est, '{"risk":0.9,"verdict":"malicious","reasons":["x"]}')
    j.assess(agent.agent_id, "sensor_read", "informational",
             "exfil​trate", "look​normal", "obj")           # zero-width injected
    rec = [r for r in est.authoritative.records if r.kind == "judge"][-1]
    assert "​" not in rec.payload["canonical_arg"]
    assert "​" not in rec.payload["canonical_rationale"]


def test_parse_failure_fails_toward_suspicious():
    est, agent = _setup()
    j = _judge(est, "the model rambled and produced no json")
    v = j.assess(agent.agent_id, "sensor_read", "informational", "bay-3", "survey", "obj")
    assert v.ok is False and v.verdict == "suspicious" and v.risk == 0.5
    assert as_ioc(agent.agent_id, v) is not None                     # flagged, not trusted


def test_judge_does_not_change_the_gateway_verdict():
    est, agent = _setup()
    # gateway allows a clean informational read (syntactic gate)...
    out_text, is_err, rec = dispatch(
        est, agent, "sensor_read",
        {"arg": "bay-3", "rationale": "survey", "confidence": 0.95}, "t")
    assert rec.allowed is True and rec.evidence_seq is not None
    # ...and the judge flagging it afterwards does NOT retroactively flip it.
    j = _judge(est, '{"risk":0.9,"verdict":"malicious","reasons":["post-hoc"]}')
    v = j.assess(agent.agent_id, "sensor_read", "informational", "bay-3", "survey", "obj")
    assert rec.allowed is True                                       # unchanged; advisory only
    assert v.verdict == "malicious"


def test_judge_stub_path_never_imports_anthropic():
    est, agent = _setup()
    _judge(est, '{"risk":0.0,"verdict":"benign","reasons":[]}').assess(
        agent.agent_id, "sensor_read", "informational", "bay-3", "s", "o")
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
    print(f"\n{passed}/{len(tests)} semantic-judge tests passed")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(_run())
