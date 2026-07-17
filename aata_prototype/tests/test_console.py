"""
Console capture guarantees (Sprint 1 of the hosted single pane) -- fully offline.

What must hold before anything is trusted to a hosted console:
  * REGISTRATION: an agent appears in the registry the moment its W2 birth record lands
    (recorder tee), keyed (src, agent) so two estates birthing the same agent_id never merge.
  * VISIBILITY: early-return denies (revoked identity), DDIL isolated-mode evidence (teed
    ledger, incl. the mode-transition record), and result-record attribution are all in the
    event stream -- the exact blind spots the design review found.
  * SAFETY: a broken feed can NEVER change a gateway outcome (blanket-hardened emit,
    dropped counter); the tee preserves the fail-closed ACK and the `online` drill setter.
  * INGEST: binary, offset-based, complete-lines-only (a partially flushed line is pending,
    not skipped or fatal); the registry cursor is monotonic.

All deterministic: no threads, no server, no network.
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from aata.scenario import birth, build_estate
from console import ConsoleFeed, Registry


def _tmpdir() -> str:
    return tempfile.mkdtemp(prefix="aata-console-")


def _feed_estate(label="test"):
    d = _tmpdir()
    feed = ConsoleFeed(d, label=label)
    est = build_estate(backends=feed.backends())
    return d, feed, est


def _ingest(d) -> Registry:
    reg = Registry()
    reg.ingest_dir(d)
    return reg


# ---- registration ------------------------------------------------------------

def test_agent_registers_in_console_on_birth():
    d, feed, est = _feed_estate()
    birth(est, "rover-01", {"sensor_read"})
    reg = _ingest(d)
    key = (feed.src, "rover-01")
    assert key in reg.agents, list(reg.agents)
    assert reg.agents[key].birth.get("tools") == ["sensor_read"]
    assert any(e["kind"] == "birth" and e["agent"] == "rover-01" for e in reg.events)


def test_src_keying_keeps_same_agent_id_from_two_estates_apart():
    d = _tmpdir()
    f1, f2 = ConsoleFeed(d, label="siteA"), ConsoleFeed(d, label="siteB")
    e1 = build_estate(backends=f1.backends())
    e2 = build_estate(backends=f2.backends())
    birth(e1, "rover-01", {"sensor_read"})
    birth(e2, "rover-01", {"sensor_read"})
    reg = _ingest(d)
    rows = [k for k in reg.agents if k[1] == "rover-01"]
    assert len(rows) == 2 and rows[0][0] != rows[1][0], rows


# ---- visibility (the review's blind spots, closed) ---------------------------

def test_revoked_agent_early_deny_is_visible():
    d, feed, est = _feed_estate()
    svid, token = birth(est, "rover-01", {"sensor_read"})
    est.revocation.revoke("rover-01")
    out = est.gateway.call("rover-01", svid, token, "sensor_read", "x")
    assert not out.allowed
    reg = _ingest(d)
    denies = [e for e in reg.events if e["kind"] == "call" and e["agent"] == "rover-01"
              and not e["data"]["allowed"]]
    assert denies and "revocation" in denies[-1]["data"]["reason"], denies
    assert reg.agents[(feed.src, "rover-01")].posture(now_ts=0) == "drifting"


def test_isolated_mode_evidence_is_visible_via_teed_ledger():
    d, feed, est = _feed_estate()
    svid, token = birth(est, "rover-01", {"sensor_read"})
    est.ddil.go_isolated("console test")
    est.gateway.call("rover-01", svid, token, "sensor_read", "iso", confidence=0.95)
    reg = _ingest(d)
    kinds = [e["kind"] for e in reg.events]
    assert "mode" in kinds, kinds                      # the transition record itself
    iso_pre = [e for e in reg.events if e["kind"] == "pre-actuation"
               and e["agent"] == "rover-01"]
    assert iso_pre, kinds                              # isolated-mode call evidence, live


def test_allowed_calls_are_observed_as_allowed():
    """Regression (found by the live smoke): observers must see the FINAL outcome --
    gateway previously ran the fan-out before setting allowed/decision, so every
    successful call reached the console/OTel as a deny."""
    d, feed, est = _feed_estate()
    svid, token = birth(est, "rover-01", {"sensor_read"})
    out = est.gateway.call("rover-01", svid, token, "sensor_read", "x", confidence=0.95)
    assert out.allowed
    reg = _ingest(d)
    calls = [e for e in reg.events if e["kind"] == "call"]
    assert calls and calls[-1]["data"]["allowed"] is True, calls
    assert calls[-1]["data"]["decision"] == "allow"
    assert reg.agents[(feed.src, "rover-01")].allow_count == 1


def test_result_records_are_agent_attributed():
    d, feed, est = _feed_estate()
    svid, token = birth(est, "rover-01", {"sensor_read"})
    out = est.gateway.call("rover-01", svid, token, "sensor_read", "x")
    assert out.allowed
    reg = _ingest(d)
    results = [e for e in reg.events if e["kind"] == "result"]
    assert results and results[-1]["agent"] == "rover-01", results


def test_covert_incident_drives_posture_off_compliant():
    d, feed, est = _feed_estate()
    svid, token = birth(est, "rover-01", {"sensor_read", "purchase"})
    for i in range(3):                                  # warm the behavioral baseline
        est.gateway.call("rover-01", svid, token, "sensor_read", f"warm{i}", confidence=0.95)
    smuggled = "acct​-‌7788‍"            # zero-width covert channel
    est.gateway.call("rover-01", svid, token, "purchase", smuggled, confidence=0.9)
    reg = _ingest(d)
    st = reg.agents[(feed.src, "rover-01")]
    assert st.ioc_count > 0
    assert st.posture(now_ts=st.last_ts) in ("drifting", "out-of-scope", "quarantined")
    assert any(e["kind"] == "hygiene" for e in reg.events)   # W3 response is in the stream


# ---- safety: the feed can never hurt the hot path ----------------------------

class _BrokenSink:
    def write(self, line):
        raise IOError("disk gone")

    def close(self):
        pass


def test_broken_feed_leaves_gateway_outcomes_identical_and_counts_drops():
    # control estate: no feed at all
    ctrl = build_estate()
    csvid, ctok = birth(ctrl, "rover-01", {"sensor_read", "actuator_move"})
    # feed estate whose sink throws on EVERY write
    feed = ConsoleFeed(_tmpdir(), label="broken", sink=_BrokenSink())
    est = build_estate(backends=feed.backends())
    svid, token = birth(est, "rover-01", {"sensor_read", "actuator_move"})
    script = [("sensor_read", "a", 0.95), ("actuator_move", "go", 0.5),
              ("actuator_move", "go", 0.95)]
    for tool, arg, conf in script:
        co = ctrl.gateway.call("rover-01", csvid, ctok, tool, arg, confidence=conf)
        fo = est.gateway.call("rover-01", svid, token, tool, arg, confidence=conf)
        assert (co.allowed, co.decision, co.reason) == (fo.allowed, fo.decision, fo.reason)
        assert co.evidence_seq == fo.evidence_seq
    assert feed.dropped > 0 and "disk gone" in feed.last_error


def test_tee_preserves_fail_closed_ack_and_online_setter():
    d, feed, est = _feed_estate()
    svid, token = birth(est, "rover-01", {"actuator_move"})
    est.authoritative.online = False                    # the drill path: setter must proxy
    out = est.gateway.call("rover-01", svid, token, "actuator_move", "go", confidence=0.95)
    assert not out.allowed and "fail-closed" in out.reason
    reg = _ingest(d)
    # the append RAISED -> never spooled; but the deny outcome IS visible via the observer
    assert not [e for e in reg.events if e["kind"] == "pre-actuation"
                and e["data"].get("canonical_args") == "go"]
    fc = [e for e in reg.events if e["kind"] == "call" and not e["data"]["allowed"]]
    assert fc and "fail-closed" in fc[-1]["data"]["reason"]


# ---- ingest mechanics --------------------------------------------------------

def test_partial_line_is_pending_not_lost_and_cursor_is_monotonic():
    d = _tmpdir()
    p = os.path.join(d, "x.jsonl")
    e1 = json.dumps({"src": "s", "kind": "birth", "agent": "a1", "seq": 0, "t": 1,
                     "ts": 1.0, "data": {}})
    e2 = json.dumps({"src": "s", "kind": "call", "agent": "a1", "seq": None, "t": None,
                     "ts": 2.0, "data": {"allowed": True, "iocs": []}})
    with open(p, "w", encoding="utf-8") as f:
        f.write(e1 + "\n" + e2[:25])                    # second line partially flushed
    reg = Registry()
    assert reg.ingest_file(p) == 1 and reg.cursor == 1  # complete line only
    with open(p, "a", encoding="utf-8") as f:
        f.write(e2[25:] + "\n")                         # the rest of the line arrives
    assert reg.ingest_file(p) == 1 and reg.cursor == 2  # applied exactly once
    assert reg.bad_lines == 0
    assert [e["kind"] for e in reg.events_since(0)] == ["birth", "call"]


def test_stale_posture_uses_wall_clock():
    d, feed, est = _feed_estate()
    birth(est, "rover-01", {"sensor_read"})
    reg = _ingest(d)
    st = reg.agents[(feed.src, "rover-01")]
    assert st.posture(now_ts=st.last_ts) == "compliant"
    assert st.posture(now_ts=st.last_ts + 10_000) == "stale"


# ---- publisher (offline: injected transport, no thread, no network) ----------

def _mk_sink(status=200, fail=False):
    from console.publish import SupabaseSink
    calls = []

    def transport(url, anon, body):
        if fail:
            raise IOError("net down")
        calls.append(json.loads(body.decode()))
        return status
    s = SupabaseSink("https://x.supabase.co", "anon", "wk",
                     transport=transport, start_thread=False)
    return s, calls


def test_publisher_batches_and_sends():
    s, calls = _mk_sink()
    for i in range(5):
        s.write(json.dumps({"src": "s", "kind": "call", "agent": f"a{i}",
                            "seq": None, "t": None, "ts": 1.0, "data": {}}))
    assert s.flush() == 5 and s.sent == 5 and s.dropped == 0
    assert len(calls) == 1 and len(calls[0]["batch"]) == 5
    assert calls[0]["write_key"] == "wk"


def test_publisher_keeps_data_on_transport_failure_and_never_raises():
    s, _ = _mk_sink(fail=True)
    s.write(json.dumps({"src": "s", "kind": "birth", "agent": "a", "seq": 0,
                        "t": 1, "ts": 1.0, "data": {}}))
    assert s.flush() == 0                               # nothing sent...
    assert s.sent == 0 and "net down" in s.last_error
    with s._lock:
        assert len(s._buf) == 1                         # ...but nothing lost (requeued)


def test_publisher_overflow_drops_oldest_with_counter():
    import console.publish as pub
    s, _ = _mk_sink(fail=True)
    for i in range(pub.BUFFER_MAX + 7):
        s.write(f'{{"i":{i}}}')
    assert s.dropped == 7
    with s._lock:
        assert len(s._buf) == pub.BUFFER_MAX
        assert json.loads(s._buf[0])["i"] == 7          # oldest dropped, newest kept


def test_publisher_disabled_without_env():
    from console.publish import enabled, sink_from_env
    saved = {k: os.environ.pop(k, None)
             for k in ("AATA_CONSOLE_URL", "AATA_CONSOLE_ANON", "AATA_CONSOLE_WRITE_KEY")}
    try:
        assert not enabled() and sink_from_env() is None
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


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
    print(f"\n{passed}/{len(tests)} console tests passed")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(_run())
