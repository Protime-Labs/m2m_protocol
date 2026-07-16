"""
A testable taxonomy of action irreversibility (spec 10.11).

The spec names this "the single most tractable unclaimed problem": turning the coarse
binary `IRREVERSIBLE = {financial, kinetic}` into a defensible, per-tool rating. This
module does that -- a small, deterministic rubric over four dimensions, a composite score
in [0,1], and a threshold that DERIVES the irreversible set. It is backward-compatible:
`derive_irreversible_classes()` reproduces the legacy `{financial, kinetic}` set, so the
PDP's fail-closed behavior is unchanged while the boundary is now a defensible, extensible
property rather than a hardcoded guess.

Pure stdlib, no side effects -- the graded score is available to the PDP / constitution and
to per-tool policy, and every rating is pinned by tests/test_irreversibility.py.
"""
from __future__ import annotations

from dataclasses import dataclass

from .capability import ACTUATION_CLASSES

# The four dimensions of irreversibility, each in [0,1] (higher = harder to undo / worse to
# get wrong). Weighted so "can it be undone" and "how far does it reach" dominate.
DIMENSIONS = ("reversibility", "blast_radius", "latency_to_effect", "opacity")
_WEIGHTS = {"reversibility": 0.40, "blast_radius": 0.30,
            "latency_to_effect": 0.20, "opacity": 0.10}

IRREVERSIBLE_THRESHOLD = 0.5


@dataclass(frozen=True)
class Rating:
    """An irreversibility rating across the four dimensions."""
    reversibility: float        # 0 = fully undoable ............ 1 = never
    blast_radius: float         # 0 = self only ................. 1 = external world
    latency_to_effect: float    # 0 = deferred (intervenable) ... 1 = immediate, no window
    opacity: float              # 0 = fully auditable ........... 1 = silent / unobservable

    def score(self) -> float:
        return round(sum(getattr(self, d) * _WEIGHTS[d] for d in DIMENSIONS), 4)

    def as_dict(self) -> dict:
        return {d: getattr(self, d) for d in DIMENSIONS} | {"score": self.score()}


# Per actuation-class base ratings -- the defensible rubric. Monotone in the spec's
# ascending-irreversibility class order, and the composite lands financial/kinetic above
# the threshold and informational/reversible below it.
CLASS_RATINGS: dict[str, Rating] = {
    "informational": Rating(reversibility=0.00, blast_radius=0.10, latency_to_effect=0.00, opacity=0.10),
    "reversible":    Rating(reversibility=0.30, blast_radius=0.30, latency_to_effect=0.20, opacity=0.20),
    "financial":     Rating(reversibility=0.85, blast_radius=0.60, latency_to_effect=0.50, opacity=0.30),
    "kinetic":       Rating(reversibility=1.00, blast_radius=0.90, latency_to_effect=1.00, opacity=0.40),
}

# Per-tool refinements (default: the tool's actuation-class rating). Concrete ratings for the
# prototype's registered tools -- the seed of a per-tool-tested rating (spec 10.11).
TOOL_RATINGS: dict[str, Rating] = {
    "sensor_read":   CLASS_RATINGS["informational"],
    "db_query":      CLASS_RATINGS["informational"],
    "purchase":      CLASS_RATINGS["financial"],
    "actuator_move": CLASS_RATINGS["kinetic"],
    "assemble":      CLASS_RATINGS["kinetic"],
}


def rate_class(actuation_class: str) -> Rating:
    return CLASS_RATINGS[actuation_class]


def rate_tool(tool: str, actuation_class: str) -> Rating:
    """A tool's rating -- its explicit rating if present, else its actuation-class rating."""
    return TOOL_RATINGS.get(tool) or CLASS_RATINGS[actuation_class]


def is_irreversible(score: float, threshold: float = IRREVERSIBLE_THRESHOLD) -> bool:
    return score >= threshold


def derive_irreversible_classes(threshold: float = IRREVERSIBLE_THRESHOLD) -> frozenset[str]:
    """The actuation classes whose composite score crosses the threshold (fail-closed set)."""
    return frozenset(c for c in ACTUATION_CLASSES
                     if is_irreversible(CLASS_RATINGS[c].score(), threshold))


def taxonomy() -> dict:
    """The full rated taxonomy -- an auditable artifact for the console / constitution."""
    return {
        "threshold": IRREVERSIBLE_THRESHOLD,
        "weights": dict(_WEIGHTS),
        "classes": {c: CLASS_RATINGS[c].as_dict() for c in ACTUATION_CLASSES},
        "tools": {t: r.as_dict() for t, r in TOOL_RATINGS.items()},
        "irreversible_classes": sorted(derive_irreversible_classes()),
    }
