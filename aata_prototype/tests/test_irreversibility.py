"""
The action-irreversibility taxonomy (spec 10.11) as executable assertions.

Pins the rubric: it is total (every class + registered tool rated), monotone in the spec's
ascending-irreversibility class order, bounded in [0,1], and it DERIVES the same fail-closed
set the PDP uses -- so hardening the taxonomy did not change gate behavior, it made the
boundary defensible and extensible.
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from aata.capability import ACTUATION_CLASSES
from aata.irreversibility import (
    CLASS_RATINGS, IRREVERSIBLE_THRESHOLD, TOOL_RATINGS, derive_irreversible_classes,
    is_irreversible, rate_class, rate_tool, taxonomy,
)
from aata.pdp import IRREVERSIBLE as PDP_IRREVERSIBLE


def test_taxonomy_is_total_over_classes_and_registered_tools():
    for c in ACTUATION_CLASSES:
        assert c in CLASS_RATINGS
    for tool in ("sensor_read", "db_query", "purchase", "actuator_move", "assemble"):
        assert tool in TOOL_RATINGS


def test_scores_are_monotone_in_class_order():
    scores = [CLASS_RATINGS[c].score() for c in ACTUATION_CLASSES]
    assert scores == sorted(scores)
    assert len(set(scores)) == len(scores)                  # strictly increasing


def test_scores_are_bounded_unit_interval():
    for c in ACTUATION_CLASSES:
        s = CLASS_RATINGS[c].score()
        assert 0.0 <= s <= 1.0


def test_derived_set_reproduces_the_legacy_binary_and_matches_the_pdp():
    derived = derive_irreversible_classes()
    assert derived == frozenset({"financial", "kinetic"})   # backward-compatible
    assert set(PDP_IRREVERSIBLE) == set(derived)             # the PDP actually uses the derived set


def test_per_tool_irreversibility():
    assert is_irreversible(rate_tool("purchase", "financial").score())
    assert is_irreversible(rate_tool("actuator_move", "kinetic").score())
    assert not is_irreversible(rate_tool("sensor_read", "informational").score())
    assert not is_irreversible(rate_tool("db_query", "informational").score())


def test_unknown_tool_falls_back_to_class_rating():
    assert rate_tool("some_new_tool", "kinetic") == rate_class("kinetic")


def test_threshold_sensitivity():
    # a stricter threshold shrinks the fail-closed set (only the most irreversible survive)
    assert derive_irreversible_classes(0.9) == frozenset({"kinetic"})
    # a looser threshold widens it
    assert "reversible" in derive_irreversible_classes(0.25)


def test_taxonomy_artifact_is_well_formed():
    t = taxonomy()
    assert t["threshold"] == IRREVERSIBLE_THRESHOLD
    assert set(t["classes"]) == set(ACTUATION_CLASSES)
    assert t["irreversible_classes"] == ["financial", "kinetic"]
    assert abs(sum(t["weights"].values()) - 1.0) < 1e-9      # weights are a convex combination


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
    print(f"\n{passed}/{len(tests)} irreversibility tests passed")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(_run())
