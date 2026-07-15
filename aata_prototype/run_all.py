"""
Run the whole prototype: invariant tests + all four workflow demos + the drill.

    python run_all.py
"""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def banner(t):
    print("\n" + "=" * 74 + f"\n== {t}\n" + "=" * 74)


def run(path):
    """Run a script as __main__, absorbing its sys.exit() so the suite continues."""
    try:
        runpy.run_path(path, run_name="__main__")
    except SystemExit:
        pass


def main():
    banner("INVARIANT TESTS (aata guarantees as executable assertions)")
    run(os.path.join(HERE, "tests", "test_invariants.py"))
    banner("FLEET TESTS (heterogeneous-fleet guarantees)")
    run(os.path.join(HERE, "tests", "test_fleet.py"))
    banner("LLM-AGENT TESTS (Claude-as-governed-workload guarantees, offline)")
    run(os.path.join(HERE, "tests", "test_llm_agent.py"))
    banner("SEMANTIC-JUDGE TESTS (advisory C11 intent classifier, offline)")
    run(os.path.join(HERE, "tests", "test_semantic_judge.py"))
    banner("RED-TEAM TESTS (adversary probes + efficacy scorecard, offline)")
    run(os.path.join(HERE, "tests", "test_redteam.py"))

    for name, title in [
        ("demo_w2_birth", "W2 -- Agent Birth (attestation to capability)"),
        ("demo_w1_hotpath", "W1 -- Gated Tool/Actuator Call (the hot path)"),
        ("demo_w3_hygiene", "W3 -- Compromise Detection to Graduated Hygiene"),
        ("blackout_drill", "THE BLACKOUT DRILL (falsifiable demonstration)"),
        ("fleet_ops", "FLEET OPS (heterogeneous embodied fleet: 200 agents)"),
    ]:
        banner(title)
        run(os.path.join(HERE, "demos", f"{name}.py"))

    # The LLM demo is offline-forced here (env flag cleared) so the suite stays
    # deterministic and network-free even if a developer has AATA_LLM_BRAIN set.
    # Anthropic-integration demos run OFFLINE-forced here (env flag cleared) so the suite
    # stays deterministic and network-free even if a developer has AATA_LLM_BRAIN set.
    saved = os.environ.pop("AATA_LLM_BRAIN", None)
    try:
        banner("LLM-AGENT CAPABILITY (Claude as governed workload -- offline illustration)")
        run(os.path.join(HERE, "demos", "demo_llm_agent.py"))
        banner("SEMANTIC JUDGE (C11 advisory intent classifier -- offline stub)")
        run(os.path.join(HERE, "demos", "demo_semantic_judge.py"))
        banner("RED-TEAM HARNESS (adversary probes + efficacy scorecard -- offline)")
        run(os.path.join(HERE, "demos", "demo_redteam.py"))
    finally:
        if saved is not None:
            os.environ["AATA_LLM_BRAIN"] = saved


if __name__ == "__main__":
    main()
