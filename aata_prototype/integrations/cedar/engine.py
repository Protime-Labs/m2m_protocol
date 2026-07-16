"""
Real AWS Cedar policy evaluation for the C6 Policy Decision Point.

The core PDP (`aata/pdp.py`) is a compact, hand-rolled stand-in for a real policy engine;
its docstring names "OPA (Rego) or AWS Cedar" as the production tooling and ships the Rego
form in `policy/constitution.rego`. This integration is the real thing: the SAME
constitution -- capability, constitutional prohibition, and a threat-tightened confidence
threshold -- compiled to **Cedar policies** and evaluated by the actual `cedarpy` engine
(the Rust `cedar-policy` crate), default-deny with `forbid` overriding `permit`.

Faithful split of responsibilities (mirrors the C12 "constitutional compiler" + C1 sidecar):
  * The COMPILER (Python here) emits the Cedar policy set + the prohibited-tool entity group,
    and computes the posture-tightened `required_confidence` -- Cedar has no floating point,
    so the arithmetic lives in the compiler and the *decision* lives in policy (a documented
    Cedar idiom; the comparison itself runs in Cedar via the decimal extension).
  * The ENFORCEMENT POINT (the gateway/sidecar) keeps the load-bearing fail-closed rule: if
    the engine is unreachable / errors / returns NoDecision, irreversible classes DENY and
    informational classes allow-degraded -- exactly as the Rego notes ("that control lives at
    the enforcement point, not in policy").

`cedarpy` is imported lazily so the module imports cleanly when the package is absent.
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field

# The same graded irreversible set the core PDP uses (spec 10.11), imported so the fail-closed
# class boundary is identical between the stand-in and this real engine.
from aata.irreversibility import derive_irreversible_classes

IRREVERSIBLE = derive_irreversible_classes()

# Authored (connected-mode) confidence thresholds -- byte-for-byte the core PDP / Rego bundle.
BASE_THRESHOLD = {
    "informational": 0.0, "reversible": 0.3, "financial": 0.7, "kinetic": 0.8,
}


class CedarError(Exception):
    """The Cedar engine could not render a decision (treated as engine-unavailable)."""


def enabled() -> bool:
    """True if the real Cedar backend (`cedarpy`) is importable."""
    return importlib.util.find_spec("cedarpy") is not None


def required_confidence(actuation_class: str, threat_level: float,
                        base: dict | None = None) -> float:
    """Posture-tightened threshold -- identical formula to aata/pdp.py::tightened()."""
    base = base or BASE_THRESHOLD
    b = base.get(actuation_class, 0.5)
    if actuation_class in IRREVERSIBLE:
        return min(1.0, b + 0.15 * threat_level)
    return b


def _dec(x: float) -> dict:
    """A Cedar `decimal` extension value (Cedar has no float); 4 fractional digits."""
    return {"__extn": {"fn": "decimal", "arg": f"{x:.4f}"}}


@dataclass
class CedarVerdict:
    allow: bool
    decision: str                       # "allow" | "deny" | "allow-degraded"
    reasons: list = field(default_factory=list)
    fail_closed: bool = False
    policy_ids: list = field(default_factory=list)   # raw Cedar reason ids (audit)


class CedarPDP:
    """Local Cedar policy decision point -- a real-engine drop-in for aata/pdp.py::PDP."""

    def __init__(self, prohibited_tools=frozenset({"self_destruct"}),
                 base_thresholds: dict | None = None):
        self.prohibited_tools = frozenset(prohibited_tools)
        self.base_thresholds = base_thresholds or BASE_THRESHOLD
        # Emit the policy set in a FIXED order so a returned reason id maps to a human reason.
        # (cedarpy assigns positional ids policy0, policy1, ...; @id does not override them.)
        ordered = [
            ("permit(principal, action, resource);",
             "allow"),
            ("forbid(principal, action, resource) unless { context.capability_ok };",
             "capability insufficient (C5)"),
            ('forbid(principal, action, resource) when { resource in PolicyGroup::"prohibited" };',
             "tool constitutionally prohibited"),
            ("forbid(principal, action, resource) "
             "when { context.confidence.lessThan(context.required_confidence) };",
             "confidence below required threshold"),
        ]
        self._policy_text = "\n".join(t for t, _ in ordered)
        self._reason_by_id = {f"policy{i}": r for i, (_, r) in enumerate(ordered)}
        # The prohibited-tool group: each prohibited Tool is a child of PolicyGroup::"prohibited".
        self._entities = [
            {"uid": {"type": "PolicyGroup", "id": "prohibited"}, "attrs": {}, "parents": []},
        ] + [
            {"uid": {"type": "Tool", "id": t}, "attrs": {},
             "parents": [{"type": "PolicyGroup", "id": "prohibited"}]}
            for t in sorted(self.prohibited_tools)
        ]

    def evaluate(self, agent_id: str, tool: str, actuation_class: str, confidence: float,
                 threat_level: float = 0.0, capability_ok: bool = True,
                 engine_error: bool = False) -> CedarVerdict:
        # (0) Fail-closed at the enforcement point: engine unreachable -> DENY irreversible,
        #     allow-degraded informational. This never reaches Cedar (Cedar is what's down).
        if engine_error:
            return self._fail_closed(actuation_class, "cedar engine error")

        import cedarpy
        need = required_confidence(actuation_class, threat_level, self.base_thresholds)
        request = {
            "principal": f'Agent::"{agent_id}"',
            "action": 'Action::"invoke"',
            "resource": f'Tool::"{tool}"',
            "context": {
                "capability_ok": bool(capability_ok),
                "confidence": _dec(confidence),
                "required_confidence": _dec(need),
            },
        }
        try:
            res = cedarpy.is_authorized(request, self._policy_text, self._entities)
        except Exception as e:                               # a real evaluation error
            return self._fail_closed(actuation_class, f"cedar raised: {type(e).__name__}")

        errors = list(getattr(res.diagnostics, "errors", []) or [])
        # NoDecision or a policy-evaluation error == engine could not decide -> fail-closed.
        if errors or str(res.decision).endswith("NoDecision"):
            return self._fail_closed(actuation_class,
                                     "cedar could not decide: " + (errors[0] if errors else "no policy matched"))

        reason_ids = list(getattr(res.diagnostics, "reasons", []) or [])
        if res.allowed:
            return CedarVerdict(True, "allow", ["all policy checks passed"], False, reason_ids)
        # Denied: translate the contributing forbid policy ids to human reasons.
        reasons = [self._reason_by_id.get(pid, pid) for pid in reason_ids
                   if self._reason_by_id.get(pid) != "allow"]
        return CedarVerdict(False, "deny", reasons or ["denied"],
                            fail_closed=actuation_class in IRREVERSIBLE, policy_ids=reason_ids)

    def _fail_closed(self, actuation_class: str, why: str) -> CedarVerdict:
        if actuation_class in IRREVERSIBLE:
            return CedarVerdict(False, "deny", [f"{why} -> fail-closed (irreversible class)"],
                                fail_closed=True)
        return CedarVerdict(True, "allow-degraded",
                            [f"{why} -> fail-degraded (informational class)"], False)
