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

## Semantic judge (C11) — surfacing the 10.1 gap, honestly

Every AATA gate is syntactic; none inspects meaning. [`judge.py`](judge.py) adds an
**advisory** semantic classifier: given a call's objective + tool + canonicalized
arg/rationale, Claude returns `{risk, verdict, reasons}`. It is used honestly:

- **Advisory, never the enforcement path.** It runs post-hoc (like C11), records a
  `judge` evidence record (C9), and feeds the existing hygiene corroboration gate. A
  **lone** judge signal caps at **Tier 1 (Narrow)** — it can never alone quarantine or
  reverse an action.
- **The judge is itself fallible/injectable** (10.1 recursion): its inputs are
  C10-canonicalized, and a parse failure fails toward `suspicious` (flag for review), not
  toward trust.
- This **does not close** the semantic gap — it lets the overlay *surface* the attack it
  previously could only document. `demos/demo_semantic_judge.py` shows a syntactically
  clean, semantically malicious call: the gateway ALLOWS it (the documented gap), the
  judge FLAGS it, and the agent is narrowed advisorily — the attack is surfaced, not un-done.

Default model: `claude-haiku-4-5` (cheap, high-volume classification).

## Red-team harness — validate the overlay, honestly

[`redteam.py`](redteam.py) probes the overlay with **labeled adversaries** (covert channel
→ C10, semantic-gap → C11 judge, over-confident kinetic → PDP, capability escalation → C5,
recorder-outage → no-evidence-no-action, and a high-confidence covert kinetic) plus honest
agents as false-positive controls. It **drives** the attacks and **observes** the overlay's
autonomous response (the gateway already auto-fires hygiene on IOCs), then scores against
ground truth (`demos/demo_redteam.py`):

```
detection recall : 1.00  (6/6 adversaries detected)
precision        : 1.00  (honest false-positives: 0)
malicious irreversible actions executed : 1   <- the characterized gap, reported not hidden
```

**Not a rigged all-green.** The high-confidence covert kinetic executes in connected mode
before hygiene reacts (detected + evidenced) — a **characterized gap** (spec 10.7 seam), and
its detection then elevates the threat level so the same attack is denied under sustained
threat / isolation (the demo shows both). A real Claude adversary (live flavor) typically
*refuses* an exfiltration goal outright — overlay-level red-teaming uses the deterministic
harness, which doesn't depend on model cooperation.

## Governance Console copilot (C12) — drafts for human sign-off

[`console.py`](console.py) is the lowest-risk Claude role: it **reads** the hash-chained
evidence for an agent and **drafts** an incident summary or the justification package an
autonomous (isolated-mode) decision requires — for a human to review and sign off
(`demos/demo_governance_console.py`). It is **reads-only**: it gates nothing, decides
nothing, adjudicates nothing (spec 10.8 — "the ledger has it" is provenance, not
adjudication). Every draft is grounded in cited record seqs, and the fact that a draft was
produced is recorded as an advisory `governance-note` (provenance, never a decision).
Default model: `claude-sonnet-5`.

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
