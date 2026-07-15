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
        ("LLM-AGENT TESTS (Claude-as-governed-workload guarantees, offline)", "test_llm_agent.py"),
        ("SEMANTIC-JUDGE TESTS (advisory C11 intent classifier, offline)", "test_semantic_judge.py"),
        ("RED-TEAM TESTS (adversary probes + efficacy scorecard, offline)", "test_redteam.py"),
        ("GOVERNANCE-CONSOLE TESTS (C12 copilot, reads-only, offline)", "test_governance_console.py"),
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

    # The Anthropic-integration demos run OFFLINE-forced here (env flag cleared) so the
    # suite stays deterministic and network-free even if a developer has AATA_LLM_BRAIN set.
    saved = os.environ.pop("AATA_LLM_BRAIN", None)
    try:
        for name, title in [
            ("demo_llm_agent", "LLM-AGENT CAPABILITY (Claude as governed workload -- offline)"),
            ("demo_semantic_judge", "SEMANTIC JUDGE (C11 advisory intent classifier -- offline)"),
            ("demo_redteam", "RED-TEAM HARNESS (adversary probes + efficacy scorecard -- offline)"),
            ("demo_governance_console", "GOVERNANCE CONSOLE (C12 copilot -- drafts, offline)"),
        ]:
            step(title, "demos", f"{name}.py")
    finally:
        if saved is not None:
            os.environ["AATA_LLM_BRAIN"] = saved

    banner("SUITE RESULT")
    if _FAILURES:
        print(f"  FAILED: {', '.join(_FAILURES)}")
        sys.exit(1)
    print("  ALL GREEN")
    sys.exit(0)


if __name__ == "__main__":
    main()
