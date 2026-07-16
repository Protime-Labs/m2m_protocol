"""
AWS Cedar policy engine (C6) -- real policy evaluation behind the hand-rolled PDP.

The core PDP (`aata/pdp.py`) is a compact stand-in whose own docstring names "OPA (Rego) or
AWS Cedar" as the production tooling (the Rego form ships in `policy/constitution.rego`).
This integration compiles the SAME constitution -- capability, constitutional prohibition,
and a threat-tightened confidence threshold -- to **Cedar policies** and evaluates them with
the actual `cedarpy` engine (the Rust `cedar-policy` crate): default-deny, `forbid` overrides
`permit`, decisions carry a policy-reason trace.

The load-bearing fail-closed rule is preserved at the enforcement point exactly as the Rego
documents it: if the engine is unreachable / errors / returns NoDecision, irreversible
classes DENY and informational classes allow-degraded.

Additive and offline-default: the core keeps its hand-rolled PDP; `cedarpy` is imported
lazily and gated on `enabled()`, so the base suite/CI stay dependency-free.
"""
from integrations.cedar.engine import (
    BASE_THRESHOLD,
    IRREVERSIBLE,
    CedarError,
    CedarPDP,
    CedarVerdict,
    enabled,
    required_confidence,
)

__all__ = [
    "CedarPDP", "CedarVerdict", "required_confidence",
    "BASE_THRESHOLD", "IRREVERSIBLE", "CedarError", "enabled",
]
