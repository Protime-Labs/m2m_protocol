"""
LLM-agent capability guarantees -- fully offline, deterministic.

Uses a STUB transport (no network, no `anthropic` import) that emits fixed tool calls,
so we can assert the invariant that matters: a Claude-driven session cannot act un-gated,
every governed call is recorded, intent is captured-not-trusted, and confidence is a
clamped, necessary-not-sufficient input. Also checks the enablement gate stays closed.
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from aata.scenario import build_estate, birth
from integrations.anthropic import GovernedAgent, LLMAgent, dispatch, enabled


# ---- helpers: fake Anthropic message/blocks (duck-typed like the SDK) --------

def _tool_use(tuid, name, arg, rationale, confidence):
    return types.SimpleNamespace(
        type="tool_use", id=tuid, name=name,
        input={"arg": arg, "rationale": rationale, "confidence": confidence})


def _text(t):
    return types.SimpleNamespace(type="text", text=t)


def _msg(content, stop_reason, usage=None):
    return types.SimpleNamespace(content=content, stop_reason=stop_reason, usage=usage)


def _scripted_transport(script):
    """Return a transport that yields the next canned response per call."""
    it = iter(script)

    def transport(model, system, messages, tools):
        return next(it)
    return transport


def _agent(tools=("sensor_read", "db_query", "actuator_move")):
    est = build_estate()
    svid, token = birth(est, "claude-01", tools=set(tools), lease=100_000)
    return est, GovernedAgent("claude-01", svid, token)


# ---- tests -------------------------------------------------------------------

def test_enabled_is_false_without_optin():
    saved = {k: os.environ.get(k) for k in ("AATA_LLM_BRAIN", "ANTHROPIC_API_KEY")}
    try:
        os.environ.pop("AATA_LLM_BRAIN", None)
        os.environ.pop("ANTHROPIC_API_KEY", None)
        assert enabled() is False
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_disabled_run_raises_without_transport():
    est, agent = _agent()
    saved = os.environ.pop("AATA_LLM_BRAIN", None)
    try:
        raised = False
        try:
            LLMAgent(est, agent).run("do something")
        except Exception as e:
            raised = e.__class__.__name__ == "LLMDisabled"
        assert raised, "disabled live run must raise LLMDisabled"
    finally:
        if saved is not None:
            os.environ["AATA_LLM_BRAIN"] = saved


def test_allowed_call_routes_through_gateway_and_records():
    est, agent = _agent()
    before = len(est.authoritative.records)
    script = [
        _msg([_tool_use("t1", "sensor_read", "bay-3", "survey first", 0.95)], "tool_use"),
        _msg([_text("done")], "end_turn"),
    ]
    result = LLMAgent(est, agent, transport=_scripted_transport(script)).run("survey")
    assert result.stop == "end_turn"
    assert len(result.calls) == 1
    rec = result.calls[0]
    assert rec.allowed is True
    assert rec.evidence_seq is not None                      # recorded pre-actuation
    assert len(est.authoritative.records) > before           # chain grew
    ok, _ = est.authoritative.verify()
    assert ok is True


def test_denied_kinetic_returns_error_and_does_not_actuate():
    est, agent = _agent()
    n_result_records = sum(1 for r in est.authoritative.records if r.kind == "result")
    # kinetic move under the per-type threshold -> gateway denies
    script = [
        _msg([_tool_use("t1", "actuator_move", "arm->extend", "reach", 0.30)], "tool_use"),
        _msg([_text("ok, staying put")], "end_turn"),
    ]
    result = LLMAgent(est, agent, transport=_scripted_transport(script)).run("reach out")
    rec = result.calls[0]
    assert rec.allowed is False
    assert rec.decision == "deny"
    # no successful actuation was recorded for this denied call
    assert sum(1 for r in est.authoritative.records if r.kind == "result") == n_result_records


def test_confidence_is_clamped_not_trusted():
    est, agent = _agent()
    # A model claiming 9.9 confidence is clamped to 1.0 (cannot overflow the gate).
    _, _, rec = dispatch(est, agent, "actuator_move",
                         {"arg": "arm->home", "rationale": "park", "confidence": 9.9},
                         task_id="x")
    assert rec.confidence == 1.0
    # And a garbage confidence becomes 0.0 (fails the kinetic threshold -> deny).
    _, _, rec2 = dispatch(est, agent, "actuator_move",
                          {"arg": "arm->home", "rationale": "park", "confidence": "high"},
                          task_id="y")
    assert rec2.confidence == 0.0 and rec2.allowed is False


def test_intent_is_recorded_as_provenance_but_canonicalized():
    est, agent = _agent()
    # zero-width chars in the rationale must be stripped before it is recorded.
    smuggled = "exfil​now"
    dispatch(est, agent, "sensor_read",
             {"arg": "bay-3", "rationale": smuggled, "confidence": 0.95}, task_id="z")
    pre = [r for r in est.authoritative.records if r.kind == "pre-actuation"][-1]
    intent = pre.payload.get("intent")
    assert intent, "pre-actuation record must carry the intent provenance"
    assert "​" not in "".join(intent)                   # C10 canonicalized
    assert "exfilnow" in "".join(intent)


def test_agent_only_offered_granted_tools():
    from integrations.anthropic import build_tool_defs
    est, agent = _agent(tools=("sensor_read", "db_query"))    # no kinetic grant
    names = {d["name"] for d in build_tool_defs(est, agent)}
    assert names == {"sensor_read", "db_query"}
    assert "actuator_move" not in names                       # capability-scoped


def test_stub_path_never_imports_anthropic():
    est, agent = _agent()
    script = [_msg([_text("hi")], "end_turn")]
    LLMAgent(est, agent, transport=_scripted_transport(script)).run("hello")
    assert "anthropic" not in sys.modules                     # offline guarantee


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
    print(f"\n{passed}/{len(tests)} llm-agent tests passed")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(_run())
