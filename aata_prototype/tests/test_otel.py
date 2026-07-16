"""
OTel emission guarantees -- fully offline, deterministic.

Asserts the emitter normalizes the overlay's signals, carries the `agent_id` join key on
every per-agent signal, emits the merkle anchor + chain status, and never imports
`opentelemetry` on the offline path (the whole point of the offline-default discipline).
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from aata.scenario import build_estate, birth
from integrations.anthropic import GovernedAgent, dispatch
from integrations.otel import TelemetryEmitter, enabled


def _run_scenario():
    est = build_estate()
    svid, token = birth(est, "rover-01",
                        tools={"sensor_read", "actuator_move"}, lease=100_000)
    agent = GovernedAgent("rover-01", svid, token)
    em = TelemetryEmitter()                      # offline -> capture backend
    calls = [
        ("sensor_read", "bay-3", 0.95),
        ("sensor_read", "bay​3", 0.95),      # zero-width -> C10 encoding IOC
        ("actuator_move", "arm->extend", 0.40),   # under threshold -> DENY
    ]
    for tool, arg, conf in calls:
        _, _, rec = dispatch(est, agent, tool,
                             {"arg": arg, "rationale": "x", "confidence": conf}, "t")
        em.emit_call(agent.agent_id, tool, rec.decision, rec.allowed,
                     rec.evidence_seq, [i.kind for i in rec.iocs], rec.confidence)
        for i in rec.iocs:
            em.emit_ioc(i.agent_id, i.kind, i.severity, i.detail)
    em.emit_chain(est, scenario="test")
    return est, em


# ---- tests -------------------------------------------------------------------

def test_enabled_is_false_without_optin():
    saved = os.environ.pop("AATA_OTEL", None)
    try:
        assert enabled() is False
    finally:
        if saved is not None:
            os.environ["AATA_OTEL"] = saved


def test_every_per_agent_signal_carries_agent_id():
    _, em = _run_scenario()
    per_agent = [s for s in em.signals if s.name in ("aata.w1", "aata.ioc")]
    assert per_agent and all(s.agent == "rover-01" for s in per_agent)


def test_w1_signal_can_carry_irreversibility_score():
    from aata.irreversibility import score_for
    em = TelemetryEmitter()
    kinetic = score_for("actuator_move", "kinetic")
    info = score_for("sensor_read", "informational")
    em.emit_call("a", "actuator_move", "deny", False, None, [], 0.4, irreversibility=kinetic)
    em.emit_call("a", "sensor_read", "allow", True, 1, [], 0.95, irreversibility=info)
    w1 = [s for s in em.signals if s.name == "aata.w1"]
    assert w1[0].attrs["irreversibility"] == kinetic and w1[1].attrs["irreversibility"] == info
    assert kinetic > info                                    # graded, per spec 10.11


def test_w1_signal_reflects_the_gateway_verdict():
    _, em = _run_scenario()
    w1 = [s for s in em.signals if s.name == "aata.w1"]
    assert any(s.attrs["allowed"] and s.attrs["decision"] == "allow" for s in w1)   # allowed read
    deny = [s for s in w1 if not s.attrs["allowed"]]
    assert deny and deny[0].attrs["decision"] == "deny" and deny[0].attrs["evidence_seq"] == -1


def test_covert_channel_emits_an_encoding_ioc_signal():
    _, em = _run_scenario()
    iocs = [s for s in em.signals if s.name == "aata.ioc"]
    assert any(s.attrs["kind"] == "encoding" and s.agent == "rover-01" for s in iocs)


def test_evidence_summary_carries_merkle_and_chain_status():
    est, em = _run_scenario()
    summ = [s for s in em.signals if s.name == "aata.evidence"]
    assert len(summ) == 1
    s = summ[0]
    assert s.agent is None                                   # fleet-wide summary
    assert s.attrs["merkle_root"] == est.authoritative.merkle_root()
    assert s.attrs["chain_ok"] is True
    assert s.attrs["records"] == len(est.authoritative.records)


def test_one_record_signal_per_authoritative_record():
    est, em = _run_scenario()
    recs = [s for s in em.signals if s.name == "aata.record"]
    assert len(recs) == len(est.authoritative.records)
    # record signals carry the agent from payload["agent"] where present
    assert any(s.agent == "rover-01" for s in recs)


def test_emission_is_additive_chain_unchanged():
    est, em = _run_scenario()
    ok, _ = est.authoritative.verify()
    assert ok is True                                        # emitting telemetry never touched the chain


def test_offline_path_never_imports_opentelemetry():
    _run_scenario()
    assert "opentelemetry" not in sys.modules


def test_real_otel_backend_actually_exports_spans():
    """Regression: spans must reach the exporter (the tracer must bind to OUR provider,
    not the global no-op one). Runs only when the OTel SDK is installed; the base offline
    suite / CI skips it -- the CI 'integrations-extra' job exercises it."""
    import importlib.util
    if importlib.util.find_spec("opentelemetry") is None:
        print("    (skip: opentelemetry not installed)")
        return
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from integrations.otel.emitter import _OTelBackend

    exporter = InMemorySpanExporter()
    em = TelemetryEmitter(backend=_OTelBackend(exporter=exporter))
    em.emit_call("rover-9", "sensor_read", "allow", True, 1, [], 0.95)
    em.emit_ioc("rover-9", "encoding", 0.6, "zw")
    em.flush()
    spans = exporter.get_finished_spans()
    names = [s.name for s in spans]
    assert "aata.w1" in names and "aata.ioc" in names        # actually exported, not dropped
    w1 = next(s for s in spans if s.name == "aata.w1")
    assert w1.attributes["aata.agent"] == "rover-9"          # agent_id join key on the real span


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
    print(f"\n{passed}/{len(tests)} otel tests passed")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(_run())
