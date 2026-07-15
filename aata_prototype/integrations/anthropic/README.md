# Anthropic integration — Claude as the governed workload

Slice 1 of the "real system" path: run **real Claude agents whose every tool call
transits the C1 gateway**, so the AATA overlay governs genuine model behavior — while
the core stays dependency-free, offline, and deterministic.

```bash
# offline default (no key, no deps): the governed path via a deterministic illustration
python demos/demo_llm_agent.py

# live: a real Claude agent pursues a goal; every call is gated + recorded
pip install -r requirements-llm.txt
export ANTHROPIC_API_KEY=...            # or: ant auth login
AATA_LLM_BRAIN=1 python demos/demo_llm_agent.py
```

## The one load-bearing rule

**Claude is the governed workload, never the enforcement path.** The only tools the
model is offered are gateway wrappers ([`governed_tools.py`](governed_tools.py)), so it
*cannot act un-gated*: a denied call returns a tool error, not an action. The
deterministic gates — fail-closed kinetic, monotone attenuation, no-evidence-no-action —
stay non-LLM. An LLM is prompt-injectable; the gate is not.

## How intent is used — capture-record-don't-trust

Each governed tool takes `(arg, rationale, confidence)` from the model:

- **`rationale`** is canonicalized with the same C10 pass as args (it's
  attacker-influenceable), carried as `context_provenance`, and recorded in the C9
  pre-actuation record as `intent`. It is **recorded, never adjudicated** (spec 10.1/10.8).
- **`confidence`** is clamped to `[0,1]` and fed to the existing PDP kinetic gate as one
  **necessary-not-sufficient** input. Capability still binds, irreversible acts still
  fail-closed, and C11 corroborates later — a model claiming `1.0` cannot authorize itself.
- The **verdict stays purely syntactic** (capability + actuation-class + PDP). Adjudicating
  intent is a later slice (the C11 semantic judge).

## Two API primitives that map onto AATA

- The **signed constitution** → a **frozen, prompt-cached system prompt**
  ([`constitution.py`](constitution.py), `cache_control: ephemeral`). Operator changes go
  through a **`role:"system"` mid-conversation message** (Opus 4.8) — the injection-safe
  C12→agent channel that user/tool text cannot spoof.
- **Token counting / response usage** → real spend signal (surfaced in the demo).

## Model choice

| Role | Model | Why |
|---|---|---|
| Autonomous agent brain | `claude-opus-4-8` (default) | long-horizon agentic work |
| Cheap high-volume worker | `claude-haiku-4-5` | fast, low-cost governed actions |
| Middle tier | `claude-sonnet-5` | near-Opus at lower cost |

## Offline / determinism guarantees

`enabled()` is True only when **all** of `AATA_LLM_BRAIN=1`, `ANTHROPIC_API_KEY`, and an
importable `anthropic` hold. Nothing imports `anthropic` at module load; the agent loop
is transport-injectable so [`tests/test_llm_agent.py`](../../tests/test_llm_agent.py)
runs the full path against a stub with no network. `python run_all.py` forces the offline
illustration, so the suite stays green and network-free regardless of your environment.

## Files
- `governed_tools.py` — the C1 interposition: tool schemas + `dispatch()` → `gateway.call`.
- `constitution.py` — the cached system prompt + injection-safe operator channel.
- `llm_agent.py` — `enabled()`, `LLMAgent` (manual Messages-API loop), transport injection.
