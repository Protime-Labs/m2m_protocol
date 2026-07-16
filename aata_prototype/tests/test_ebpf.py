"""
Runtime sensor (C3) guarantees -- fully offline, deterministic.

Asserts the sensor produces an attestation INDEPENDENT of the agent's self-report, that an
honest tool is confirmed while undeclared file access / egress is flagged as a
`runtime-divergence` IOC, and that the IOC corroborates through hygiene (lone signal ->
Tier 1). The real Tetragon parser is exercised against a fixture (it is stdlib-only).
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from aata.scenario import build_estate, birth
from aata.hygiene import AgentStatus
from aata.sandbox import ResourceAttestation
from integrations.ebpf import (
    SimulatedSensor, TetragonSensor, divergence, enabled, sensor,
)

CLAIMED = ResourceAttestation(cpu_ms=2, net_bytes=0, files_touched=["/dev/sensor0"])


# ---- sensor selection --------------------------------------------------------

def test_enabled_false_and_default_sensor_is_simulated():
    saved = os.environ.pop("AATA_EBPF", None)
    try:
        assert enabled() is False
        assert isinstance(sensor(), SimulatedSensor)
    finally:
        if saved is not None:
            os.environ["AATA_EBPF"] = saved


# ---- honest vs compromised ---------------------------------------------------

def test_honest_tool_is_confirmed_no_divergence():
    obs = SimulatedSensor().observe("a", "sensor_read", "bay-3", CLAIMED)
    assert obs.as_dict() == CLAIMED.as_dict()
    assert divergence(CLAIMED, obs, "a") is None


def test_undeclared_file_and_egress_are_flagged():
    s = SimulatedSensor(ground_truth={"sensor_read": {"files_touched": ["/etc/shadow"],
                                                       "net_bytes": 4096}})
    obs = s.observe("a", "sensor_read", "bay-3", CLAIMED)
    # observed is INDEPENDENT of the self-report -- it contains what the kernel saw
    assert "/etc/shadow" in obs.files_touched and obs.net_bytes == 4096
    ioc = divergence(CLAIMED, obs, "a")
    assert ioc is not None and ioc.kind == "runtime-divergence"
    assert "/etc/shadow" in ioc.detail and "4096" in ioc.detail


def test_divergence_severity_grows_with_extent():
    one = divergence(CLAIMED, ResourceAttestation(2, 0, ["/dev/sensor0", "/etc/shadow"]), "a")
    more = divergence(CLAIMED, ResourceAttestation(2, 8192, ["/dev/sensor0", "/etc/shadow", "/root/.ssh/id_rsa"]), "a")
    assert more.severity > one.severity


def test_divergence_ioc_corroborates_through_hygiene():
    est = build_estate()
    svid, token = birth(est, "rover-01", tools={"sensor_read"}, lease=100_000)
    out = est.gateway.call("rover-01", svid, token, "sensor_read", "bay-3",
                           confidence=0.95, task_id="t")
    claimed = ResourceAttestation(**{k: out.resource_attestation[k]
                                     for k in ("cpu_ms", "net_bytes", "files_touched")})
    s = SimulatedSensor(ground_truth={"sensor_read": {"files_touched": ["/etc/shadow"]}})
    ioc = divergence(claimed, s.observe("rover-01", "sensor_read", "bay-3", claimed), "rover-01")
    inc, _ = est.hygiene.respond("rover-01", est.gateway._tokens["rover-01"], ioc)   # lone signal
    assert inc.tier == 1 and inc.corroborated is False
    assert est.hygiene.status["rover-01"] == AgentStatus.NARROWED
    assert not est.revocation.is_revoked("rover-01")             # NOT quarantined on one signal


# ---- real Tetragon parser (fixture) -----------------------------------------

def test_tetragon_sensor_parses_events_and_detects_divergence():
    events = [
        '{"agent":"rover-01","tool":"sensor_read","event":"file","path":"/etc/shadow"}',
        '{"agent":"rover-01","tool":"sensor_read","event":"net","bytes":2048}',
        '{"agent":"other","tool":"sensor_read","event":"file","path":"/ignored"}',   # other agent
    ]
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "events.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(events))
        obs = TetragonSensor(path).observe("rover-01", "sensor_read", "bay-3", CLAIMED)
        assert "/etc/shadow" in obs.files_touched and "/ignored" not in obs.files_touched
        assert obs.net_bytes == CLAIMED.net_bytes + 2048
        assert divergence(CLAIMED, obs, "rover-01") is not None
        # a present event source flips enabled()
        os.environ["AATA_EBPF"] = path
        try:
            assert enabled() is True and isinstance(sensor(), TetragonSensor)
        finally:
            os.environ.pop("AATA_EBPF", None)


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
    print(f"\n{passed}/{len(tests)} ebpf tests passed")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(_run())
