# AWS Cedar policy engine — the C6 production swap

The prototype's Policy Decision Point (`aata/pdp.py`) is a compact, hand-rolled policy engine
— a faithful stand-in whose own docstring names **"OPA (Rego) or AWS Cedar"** as the
production tooling (the Rego form ships in [`policy/constitution.rego`](../../policy/constitution.rego)).
This integration is the real thing: the **same constitution** compiled to **Cedar policies**
and evaluated by the actual [`cedarpy`](https://pypi.org/project/cedarpy/) engine (the Rust
`cedar-policy` crate).

```bash
pip install -e ".[cedar]"   # cedarpy  (or: pip install -r requirements-cedar.txt)
python demos/demo_cedar.py
```

## What the real engine adds over the hand-rolled PDP

| Property | hand-rolled PDP (core) | Cedar engine (this) |
|---|---|---|
| Decision | Python `if` ladder | real `cedar-policy` evaluation, **default-deny**, `forbid` overrides `permit` |
| Constitution | inline constants | a **Cedar policy set** the C12 compiler could emit and sign |
| Prohibited tools | a `frozenset` check | a **`forbid … when resource in PolicyGroup::"prohibited"`** policy over an entity group |
| Confidence threshold | float compare | Cedar **decimal-extension** compare (`context.confidence.lessThan(context.required_confidence)`) |
| Reason trace | assembled by hand | the engine's **contributing-policy diagnostics** |
| Fail-closed | in the PDP | at the **enforcement point** — engine unreachable / NoDecision / error ⇒ DENY irreversible, allow-degraded informational (exactly as the Rego documents) |

## Faithful division of labor

Cedar has **no floating point**, so the posture-tightened `required_confidence`
(`min(1.0, base + 0.15·threat)`) is computed in the **compiler** (Python) and passed in as a
decimal; the *decision* — the comparison — runs **in Cedar**. This mirrors the real split: the
C12 "constitutional compiler" emits the bundle, the C1 sidecar enforces it locally under a TTL.

## Parity

`test_cedar.py` proves the real engine is a drop-in: across a **64-case matrix**
(tool × actuation-class × confidence × threat-level) the Cedar decision equals the core
`aata/pdp.py` decision, case for case.

## API

```python
from integrations.cedar import CedarPDP

pdp = CedarPDP(prohibited_tools=frozenset({"self_destruct"}))
v = pdp.evaluate("rover-01", "actuator_move", "kinetic", confidence=0.9, threat_level=2.0)
# -> CedarVerdict(allow, decision, reasons, fail_closed)
```

Additive and offline-default: the core keeps its hand-rolled PDP; `cedarpy` is imported
lazily and gated on `enabled()`, so `run_all.py`/CI stay dependency-free. Tests skip when
`cedarpy` is absent; the CI `integrations-extra` job installs it and runs them.

> OPA/Rego is the other production option (`policy/constitution.rego`); it needs the external
> `opa` Go binary, so Cedar — a pip-installable library — is the offline-validatable swap here.
