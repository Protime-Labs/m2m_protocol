# Onboarding one Anthropic agent into the governed sandbox

This guide takes you from zero to **one live Claude agent, driven by your local
`ANTHROPIC_API_KEY`, operating inside the AATA governed sandbox** — with a tamper-evident
evidence trail you can verify at the end. Every command is copy-pasteable; every claim
points at the file that implements it. It is also runnable **without a key**: the complete
script at the end falls back to a deterministic offline illustration of the same governed
path.

---

## 1. The mental model (read this first)

Three things people usually get backwards:

**AATA does not spawn agents.** LangChain, CrewAI, a custom loop, or the Anthropic driver
in this repo — that is the agent's *brain*, and AATA is agnostic to it. AATA is the
**enforcement boundary the brain's actions must pass through**. There is no "connect your
framework" step; there is a "route every action through the gateway" requirement.

**Admission is gated, not detected.** No sensor "notices" a new worker and decides what to
do. AATA is fail-closed by identity: an agent that comes online can do nothing until it
attests itself into existence (**W2 birth**). "Coming online" and "being registered" are
the same event; anything that skips it is denied at the gateway's identity checks
([`aata/gateway.py`](../aata/gateway.py) step 3).

**"Under control" is an invariant, not a moment.** An agent is governed if and only if:

- **(a) it holds an attested identity** — a lease-bound SVID + a scoped capability Token
  from W2 birth, and
- **(b) interposition is real** — its *only* path to any side-effecting action is
  `gateway.call`, with no un-gated egress.

The prototype models (b) by offering the model **only** gateway-wrapped tools
([`integrations/anthropic/governed_tools.py`](../integrations/anthropic/governed_tools.py)).
In production, (b) comes from the **sandbox + egress lock** — see §12.

The lifecycle:

```
SPAWN            your process starts (any framework), inside a sandbox whose only
   |             network egress is the AATA gateway
   v
BIRTH (W2)       attest platform + artifact digests -> SVID + capability Token
   |             -> hash-chained C9 "birth" record   (= "joined the platform")
   v
RUN (W1)         every tool call: canonicalize -> capability -> PDP -> pre-actuation
   |             record ACK -> sandboxed execute -> result record
   |             denied call = an error to the brain, NOT an action
   v
DETECT/RESPOND   C10/C11 watch cadence + drift; IOCs -> graduated hygiene (W3):
                 attenuate -> quarantine -> revoke
```

---

## 2. Prerequisites

- **Python 3.10+** (the suite is CI-validated on 3.10–3.13).
- The repo, and an editable install with the Anthropic extra:

```bash
git clone https://github.com/Protime-Labs/m2m_protocol.git
cd m2m_protocol/aata_prototype
pip install -e ".[llm]"          # the anthropic SDK (only dependency of this guide)
```

- **A local Anthropic API key.** Export it in your shell (or authenticate with
  `ant auth login`, which the SDK picks up):

```bash
export ANTHROPIC_API_KEY=sk-ant-...        # PowerShell: $env:ANTHROPIC_API_KEY = "sk-ant-..."
```

Key hygiene: never commit it, never paste it into files or logs; if it ever lands in a
transcript or repo, **rotate it** at console.anthropic.com. The platform never requires the
key at rest — only the live agent process reads it, from the environment.

## 3. Step 0 — verify the platform first

```bash
python run_all.py        # offline, no key, no network
```

Expect **ALL GREEN** (142 tests across 17 suites) and exit 0. If this is red, fix that
before onboarding anything — the guarantees you are about to rely on are exactly what this
suite pins.

## 4. Step 1 — build the estate (the platform instance)

```python
from aata.scenario import build_estate
est = build_estate()                                  # offline default: pure-core backends
```

`build_estate()` wires all twelve overlay components around a small tool estate
([`aata/scenario.py`](../aata/scenario.py)). To run the same estate on the **real**
backends (real Cedar policy engine, WORM write-through store, OTel spans, real
SPIFFE+cosign attestation at birth):

```bash
pip install -e ".[integrations]"
export AATA_CEDAR=1 AATA_WORM=memory AATA_OTEL=1 AATA_ATTEST=1
```

```python
from integrations.wiring import select_backends
est = build_estate(backends=select_backends())        # real where installed+flagged
```

Either way the API that follows is identical — that is the point of the `Backends` seam.

## 5. Step 2 — the sandbox tool surface

The estate's [`Sandbox`](../aata/sandbox.py) (a gVisor/Kata stand-in) holds every tool an
agent could ever touch. Each `Tool` declares an **actuation class**
(`informational | reversible | financial | kinetic`), a **data level**, and a **cost** —
and those declarations drive the PDP: kinetic calls need confidence ≥ 0.8 by default,
informational reads need none. Execution requires a **single-use scoped credential** minted
per verdict, so a tool result cannot be replayed into a second actuation.

The default estate registers `sensor_read` (informational), `db_query` (informational,
confidential data), `purchase` (financial), `actuator_move` (kinetic). Add your own with
`est.sandbox.register(Tool(...))` — the gateway and PDP pick it up with no other changes.

## 6. Step 3 — W2 birth: the agent joins the platform

```python
from aata.scenario import birth
svid, token = birth(est, "claude-rover-01",
                    tools={"sensor_read", "db_query", "actuator_move"},
                    lease=100_000)
```

What just happened ([`aata/scenario.py::birth`](../aata/scenario.py)):

1. The agent's artifacts (weights, adapter, **system prompt**, skills) were digest-checked
   against the signed golden manifest, and the platform quote against the golden PCRs.
   **Any mismatch → `PermissionError` — no SVID, never admitted.** A tampered prompt fails
   exactly like tampered weights.
2. A lease-bound **SVID** and a scoped **capability Token** were minted. The token is the
   agent's hard ceiling: tools, actuation classes, data ceiling, spend budget.
3. A hash-chained **C9 `birth` record** was written — the durable, tamper-evident
   "this agent joined" event. With `AATA_ATTEST=1` it also carries the real
   `spiffe_id` (X.509 SVID) and `cosign_ok` (real signature over the digest manifest).
4. `gateway.remember_token()` registered the token so autonomous hygiene (W3) can
   attenuate it later without asking anyone.

To list everyone who has ever joined: `[r for r in est.authoritative.records if r.kind == "birth"]`.

## 7. Step 4 — bind it as a governed workload

```python
from integrations.anthropic import GovernedAgent
agent = GovernedAgent("claude-rover-01", svid, token)
```

Two things now derive **from the token**, so the model's world is capability-shaped:

- **Tool definitions** ([`governed_tools.build_tool_defs`](../integrations/anthropic/governed_tools.py)):
  one Anthropic tool per *granted* tool, each taking `(arg, rationale, confidence)`.
  Irreversible tools carry a warning in their description.
- **The constitution** ([`constitution.render_system`](../integrations/anthropic/constitution.py)):
  a frozen, prompt-cached system prompt carrying the rules + the agent's exact capability
  envelope. Operator instructions mid-run go through `operator_message()` — a
  `role:"system"` message user/tool text cannot spoof. This is guidance, not enforcement:
  the gateway governs regardless of what the prompt says.

The model's stated `rationale` is **captured, canonicalized (C10), recorded (C9) — never
adjudicated**; its `confidence` is clamped to [0,1] and is one *necessary-not-sufficient*
input to the PDP. A model claiming 1.0 cannot authorize itself.

## 8. Step 5 — enable the live Anthropic path

The live path is off unless **all three** hold
([`llm_agent.enabled()`](../integrations/anthropic/llm_agent.py)):

```bash
export AATA_LLM_BRAIN=1          # explicit opt-in
export ANTHROPIC_API_KEY=...     # your local key
pip install -e ".[llm]"          # importable SDK
```

Miss any one → `enabled()` is False and callers take the offline path. Nothing imports
`anthropic` at module load, and `run_all.py` force-clears the flags — so CI and the offline
suite can never accidentally call the API or need a key.

## 9. Step 6 — run it

```python
from integrations.anthropic import LLMAgent
result = LLMAgent(est, agent,
                  objective="Operate the bay-3 survey robot safely.").run(
    "Survey bay-3: take sensor readings and one database lookup, then park the arm safely."
)
```

Per turn ([`llm_agent.py`](../integrations/anthropic/llm_agent.py)): one Messages-API call
(adaptive thinking) → every `tool_use` block is routed through
`dispatch()` → **`gateway.call`** → the result (or the denial reason, `is_error=True`)
returns to the model. **A denied call is an error message, never an action** — the model
reads the reason and adapts. `result` carries the stop reason, every governed
`ToolCallRecord` (verdict, evidence seq, IOCs), the final text, and summed token usage.

| Role | Model | Why |
|---|---|---|
| Agent brain (this guide) | `claude-opus-4-8` (default) | long-horizon agentic work |
| Cheap high-volume worker | `claude-haiku-4-5` | fast, low-cost governed actions |
| Middle tier | `claude-sonnet-5` | near-Opus at lower cost |

Pass `model="claude-haiku-4-5"` to `LLMAgent(...)` to change tiers.

## 10. Step 7 — verify the evidence

```python
ok, msg = est.authoritative.verify()
print(ok, msg, est.authoritative.merkle_root()[:16])

mine = [r for r in est.authoritative.records
        if r.payload.get("agent") == "claude-rover-01"]     # birth + pre-actuation + ...
for r in mine:
    print(r.seq, r.kind, r.this_hash[:12])
```

Every allowed action has a **pre-actuation record ACKed before release** — if the recorder
is unreachable, kinetic actions do not proceed (no-evidence-no-action). With `AATA_OTEL=1`,
each governed call also emitted an `aata.w1` span carrying `aata.agent` — the join key a
real collector correlates on. For the visual version:

```bash
python export_evidence.py
python -m http.server 8787 --bind 127.0.0.1 --directory dashboard
# open http://127.0.0.1:8787/index.html
```

## 11. The complete script

Save as `onboard_one_agent.py` in `aata_prototype/` and run `python onboard_one_agent.py`.
With the three enablement conditions met it runs the **live Claude session**; without them
it runs the **same governed path deterministically** (no key, no network), so you can
validate the wiring before spending a token.

```python
"""Onboard one Anthropic agent into the AATA governed sandbox, end to end."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aata.scenario import build_estate, birth
from integrations.anthropic import (GovernedAgent, LLMAgent, dispatch,
                                    enabled, granted_tools)

AGENT_ID = "claude-rover-01"
GOAL = ("Survey bay-3: take a couple of sensor readings and one database lookup, "
        "then park the robot arm safely. Be conservative with irreversible actions.")

# 1-2. platform + sandbox surface (add backends=select_backends() for real backends)
est = build_estate()

# 3. W2 birth: attest -> SVID + Token + C9 "birth" record  (= joined the platform)
svid, token = birth(est, AGENT_ID,
                    tools={"sensor_read", "db_query", "actuator_move"}, lease=100_000)

# 4. bind as a governed workload (tools + constitution derive from the token)
agent = GovernedAgent(AGENT_ID, svid, token)
print(f"born: {AGENT_ID}  granted={granted_tools(est, agent)}")

# 5-6. run -- live if enabled (AATA_LLM_BRAIN=1 + key + SDK), else offline illustration
if enabled():
    result = LLMAgent(est, agent, objective="Operate the bay-3 robot safely.").run(GOAL)
    print(f"live: stop={result.stop} turns={result.turns} usage={result.usage}")
    calls = result.calls
else:
    print("offline (set AATA_LLM_BRAIN=1 + ANTHROPIC_API_KEY for the live path)")
    calls = []
    for i, (tool, arg, why, conf) in enumerate([
            ("sensor_read", "bay-3", "survey before acting", 0.95),
            ("db_query", "telemetry", "check recent telemetry", 0.90),
            ("actuator_move", "arm->extend", "reach the sample", 0.40),  # DENIED: kinetic
            ("actuator_move", "arm->home", "park the arm safely", 0.95)]):
        _, _, rec = dispatch(est, agent, tool,
                             {"arg": arg, "rationale": why, "confidence": conf},
                             task_id=f"onboard-{i}")
        calls.append(rec)

for rec in calls:
    v = "ALLOW" if rec.allowed else f"DENY({rec.decision})"
    print(f"  {rec.tool}(conf={rec.confidence:.2f}) -> {v} seq={rec.evidence_seq}")

# 7. evidence: the tamper-evident trail of everything above
ok, msg = est.authoritative.verify()
mine = [r for r in est.authoritative.records if r.payload.get("agent") == AGENT_ID]
print(f"evidence: verify_ok={ok} ({msg}); {len(mine)} records for {AGENT_ID}; "
      f"merkle={est.authoritative.merkle_root()[:16]}...")
sys.exit(0 if ok else 1)
```

Expected offline: the two reads and the safe park **ALLOW** (each with an evidence seq),
the low-confidence kinetic move **DENY** — the gate biting — and `verify_ok=True`.

## 12. Production sandbox note (honest)

In this guide, the model cannot act un-gated because the *only tools it is offered* are
gateway wrappers. That is faithful for a driver you control — but **the wrapper is not the
control; the sandbox is**. A production deployment gets guarantee (b) from
infrastructure: the workload runs in **gVisor/Kata** with a network policy whose only
egress is the AATA gateway (Envoy AI Gateway / MCP gateway), so *any* framework — LangChain,
CrewAI, custom — is governed because it physically cannot reach anything else. Two honest
limits carry over from the spec: the gates are **syntactic** (a semantically malicious but
in-scope call passes and is recorded — 10.1; the advisory C11 judge surfaces, never
enforces), and attestation proves **provenance, not safety** (10.2).

## 13. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `LLMDisabled: Anthropic path disabled` | One of the three gates is unmet: `AATA_LLM_BRAIN=1`? key exported **in this shell**? `pip install -e ".[llm]"` done? |
| Kinetic call denied at low confidence | Working as intended — the PDP threshold (0.8 default). Gather info first or state honest higher confidence; the model is told to adapt. |
| `stop=refusal` | The model declined the goal (its own safety layer). Rephrase the goal; the overlay is separate from and additive to model-level refusals. |
| Key exported but `enabled()` False | Different shell/session; `echo $ANTHROPIC_API_KEY` (PS: `$env:ANTHROPIC_API_KEY`) must show it where you run Python. |
| `PermissionError` at `birth(...)` | Attestation failed — an artifact digest doesn't match the signed manifest. That is the platform refusing a tampered build; check what you changed. |
| `run_all.py` not ALL GREEN | Fix first; the suite pins the guarantees this guide relies on. |

---

*Next steps from here: [`integrations/anthropic/README.md`](../integrations/anthropic/README.md)
(judge, red-team, console roles) · [`docs/live-validation.md`](live-validation.md) (real
S3/NATS) · [`demos/demo_all_real.py`](../demos/demo_all_real.py) (everything on real
backends at once).*
