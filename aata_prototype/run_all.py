"""
Run the whole prototype: invariant tests + all demos + the drill.

    python run_all.py

Exits non-zero if any test suite fails or any demo crashes -- so it can gate CI.
Everything here runs fully offline (no network, no dependencies); the Anthropic
integration demos are forced onto their offline path.
"""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_FAILURES: list[str] = []


def banner(t):
    print("\n" + "=" * 74 + f"\n== {t}\n" + "=" * 74)


def run(path):
    """Run a script as __main__. Records a failure on non-zero exit or crash."""
    try:
        runpy.run_path(path, run_name="__main__")
    except SystemExit as e:
        if e.code not in (0, None):
            _FAILURES.append(os.path.basename(path))
    except Exception as e:                       # a demo/test crashed outright
        print(f"\n!! {os.path.basename(path)} CRASHED: {type(e).__name__}: {e}")
        _FAILURES.append(os.path.basename(path))


def step(title, kind, name):
    banner(title)
    run(os.path.join(HERE, kind, name))


def main():
    for title, name in [
        ("INVARIANT TESTS (aata guarantees as executable assertions)", "test_invariants.py"),
        ("FLEET TESTS (heterogeneous-fleet guarantees)", "test_fleet.py"),
        ("DDIL TESTS (store-and-forward, reconciliation, merkle invariants)", "test_ddil.py"),
        ("IRREVERSIBILITY TAXONOMY (spec 10.11 -- graded, derives the fail-closed set)", "test_irreversibility.py"),
        ("LLM-AGENT TESTS (Claude-as-governed-workload guarantees, offline)", "test_llm_agent.py"),
        ("SEMANTIC-JUDGE TESTS (advisory C11 intent classifier, offline)", "test_semantic_judge.py"),
        ("RED-TEAM TESTS (adversary probes + efficacy scorecard, offline)", "test_redteam.py"),
        ("GOVERNANCE-CONSOLE TESTS (C12 copilot, reads-only, offline)", "test_governance_console.py"),
        ("OTEL TESTS (real-signal emission, additive, offline)", "test_otel.py"),
        ("WORM TESTS (durable write-once evidence store, offline)", "test_worm.py"),
        ("NATS TESTS (store-and-forward + custody-transfer replay, offline)", "test_nats.py"),
        ("EBPF TESTS (runtime-sensor ground-truth divergence, offline)", "test_ebpf.py"),
        ("BISCUIT TESTS (Ed25519 capability tokens C5 -- skips w/o cryptography)", "test_biscuit.py"),
        ("SPIFFE TESTS (X.509 SVID workload identity C2/C4 -- skips w/o cryptography)", "test_spiffe.py"),
        ("COSIGN TESTS (signed artifact registry C4 -- skips w/o cryptography)", "test_cosign.py"),
        ("CEDAR TESTS (real policy engine C6 + core-PDP parity -- skips w/o cedarpy)", "test_cedar.py"),
        ("END-TO-END REAL (overlay wired on real Cedar+WORM+OTel+eBPF+SPIFFE/cosign -- skips w/o libs)", "test_end_to_end_real.py"),
    ]:
        step(title, "tests", name)

    for name, title in [
        ("demo_w2_birth", "W2 -- Agent Birth (attestation to capability)"),
        ("demo_w1_hotpath", "W1 -- Gated Tool/Actuator Call (the hot path)"),
        ("demo_w3_hygiene", "W3 -- Compromise Detection to Graduated Hygiene"),
        ("blackout_drill", "THE BLACKOUT DRILL (falsifiable demonstration)"),
        ("fleet_ops", "FLEET OPS (heterogeneous embodied fleet: 200 agents)"),
    ]:
        step(title, "demos", f"{name}.py")

    # The integration demos run OFFLINE-forced here (env flags cleared) so the suite stays
    # deterministic and network-free even if a developer has AATA_LLM_BRAIN / AATA_OTEL set.
    saved = {k: os.environ.pop(k, None)
             for k in ("AATA_LLM_BRAIN", "AATA_OTEL", "AATA_WORM", "AATA_NATS", "AATA_EBPF")}
    try:
        for name, title in [
            ("demo_llm_agent", "LLM-AGENT CAPABILITY (Claude as governed workload -- offline)"),
            ("demo_semantic_judge", "SEMANTIC JUDGE (C11 advisory intent classifier -- offline)"),
            ("demo_redteam", "RED-TEAM HARNESS (adversary probes + efficacy scorecard -- offline)"),
            ("demo_governance_console", "GOVERNANCE CONSOLE (C12 copilot -- drafts, offline)"),
            ("demo_otel", "OTEL EMISSION (real signal pipeline C8 -- offline capture)"),
            ("demo_worm", "WORM EVIDENCE STORE (durable write-once C9 -- offline)"),
            ("demo_nats", "NATS STORE-AND-FORWARD (DDIL ledger transport C8/W4 -- offline)"),
            ("demo_ebpf", "RUNTIME SENSOR (kernel ground-truth divergence C3 -- offline)"),
            ("demo_biscuit", "BISCUIT Ed25519 TOKENS (asymmetric capability C5 -- skips w/o crypto)"),
            ("demo_spiffe", "SPIFFE X.509 SVIDs (workload identity C2/C4 -- skips w/o crypto)"),
            ("demo_cosign", "COSIGN SIGNED REGISTRY (artifact provenance C4 -- skips w/o crypto)"),
            ("demo_cedar", "CEDAR POLICY ENGINE (real C6 authorization -- skips w/o cedarpy)"),
            ("demo_all_real", "ALL-REAL WIRE-UP (overlay on real backends end-to-end -- skips w/o libs)"),
        ]:
            step(title, "demos", f"{name}.py")
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v

    banner("SUITE RESULT")
    if _FAILURES:
        print(f"  FAILED: {', '.join(_FAILURES)}")
        sys.exit(1)
    print("  ALL GREEN")
    sys.exit(0)


if __name__ == "__main__":
    main()
