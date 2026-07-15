# AATA Reference Prototype

A **runnable, dependency-free** prototype of the Autonomous Agent Trust
Architecture (AATA-2026-001, Protime Consulting Inc.). It turns the framework's
prose guarantees into **executable, observable behavior** you can run in ten
seconds on any machine with Python 3.10+.

> The goal (the "GOSLA"): make the architecture's load-bearing guarantees
> *falsifiable*. Every promise in the spec becomes an assertion or a demo that
> either holds or visibly breaks — including the ones the spec is honest about
> *not* solving.

```
cd aata_prototype
python run_all.py            # tests + all four workflow demos + the blackout drill
```

No pip install. No network. Pure standard library. (Windows/macOS/Linux.)

> **New here?** Start with the repository front door — [`../README.md`](../README.md) —
> for the product overview, the AATA document set (Parts I–III + Master Strategy),
> and the adoption path (ADOPT / EXTEND / BUILD dispositions, concept → pilot →
> production). This file is the deep technical reference.
>
> **License:** [Business Source License 1.1](../LICENSE) — non-production use (eval,
> testing, research) is free for everyone; production use is gated to authorized
> beta/pilot participants and otherwise needs a commercial license. Each version
> converts to Apache-2.0 on its Change Date. © 2026 Protime Consulting Inc.

### Heterogeneous embodied fleet (registration · governance · accounting · gaps)

A mixed fleet of 50 factory workers, 50 humanoids, 50 rovers and 50 autonomous
vehicles — each governed to its *purpose*:

```
python demos/fleet_ops.py     # register 200 agents, run their missions, detect, account, report
python tests/test_fleet.py    # the fleet guarantees as assertions (8/8)
```

- **Registration** — per-type W2 birth; tampered builds fail attestation → no SVID (≈192 admitted / 8 rejected).
- **Alignment** — the same kinetic maneuver at confidence 0.70 is **allowed for a rover** (θ 0.60) and
  **denied for an autonomous vehicle** (θ 0.88): mission control aligned to physical risk, visible in evidence.
- **Detection** — per-agent C10/C11 **plus** fleet-level cohort-outlier + **monoculture** alarm
  (12/24 identical `rover/v-B` drift together → freeze the rollout ring, quarantine the cluster, reflex preserved).
- **Failed tasks** — classified (`TOOL_ERROR`/`FAIL_CLOSED`/`POLICY_DENIED`/…) and answered
  (retry → reassign / hold / defer), with a `task-outcome` record for **every** terminal task.
- **Reporting** — internal (Mission Orchestrator + Governance Console) **and** an external `TaskAccountingReport`.
- **Coverage gaps** — a control × embodiment-type map; headline gap: continuous high-rate control is
  **reflex-only** (spec 10.7). See [docs/fleet_ops_brief.md](docs/fleet_ops_brief.md).

Rendered in the dashboard's **Fleet Ops** tab. New/changed code: `aata/embodiment.py`,
`aata/fleet.py`, `FleetAnalytics` in `aata/behavioral.py`, per-type PDPs in `aata/scenario.py`.

### Web dashboard

A self-contained mission-control console visualises everything the overlay
produces — evidence, workflows, and the cross-cutting intersections:

```
python export_evidence.py    # runs the live overlay -> dashboard/data.js + data.json

# launch the console (recommended): serve the dashboard over a local HTTP server
python -m http.server 8787 --bind 127.0.0.1 --directory dashboard
# then open http://127.0.0.1:8787/index.html

# (or just open dashboard/index.html directly — a pre-generated data.js is committed)
python build_artifact.py     # optional: fold data inline -> dashboard/aata-dashboard.html
```

- **Overview** — status strip (DDIL tier · chain integrity · threat · fleet) and KPI tiles.
- **Workflows** — W1–W4 as numbered step sequences, each step tagged with the component it
  touches and the evidence it emits; W1 shows traces captured live from the running gateway.
- **Intersections** — the core view: **Component × Workflow**, **Control × Component**, the
  **component handoff graph** (plane-coloured), **Component × DDIL tier**, and **Threat × Control**.
  Click any component `C-id` anywhere and its row, column, graph node, and workflow steps
  highlight everywhere at once — the "varying intersections" of a single part, at a glance.
- **Evidence** — the hash-chained flight recorder + reconciliation ledger (filterable,
  row-expandable), IOCs, autonomous incidents, fleet roster, and the documented semantic gap.

Every figure is emitted by the live prototype; nothing is mocked. `dataviz` validated palette,
light/dark themes, keyboard-focusable, no external requests (CSP-safe).

---

## 1. What this is — and what it deliberately is not

This is an **overlay** exactly as the spec describes: an unmodified "estate" (a
few registered tools) wrapped by twelve overlay components that see and gate
everything. The prototype is faithful to the *security shape* of AATA —
offline-verifiable capabilities, append-only evidence, monotone attenuation,
fail-closed kinetics, DDIL survival — while standing in stdlib primitives for
the heavy production tools.

It is **not** production crypto or a product. Where the spec calls for
public-key primitives (Biscuit=Ed25519, SPIRE SVID=X.509, cosign), the prototype
uses HMAC/BLAKE2 from the stdlib as an **honest, clearly-labelled** stand-in. See
[§5 Prototype vs. production](#5-prototype-vs-production) for the exact swaps.

---

## 2. The guarantees, as runnable evidence

| AATA guarantee (spec) | Where it lives | How you see it |
|---|---|---|
| **No-evidence-no-action** (W1 6–7) | `recorder.py` + `gateway.py` | Drill / W1 demo case C: recorder offline → kinetic call **fail-closed**, no result record |
| **Monotone capability attenuation** (C5) | `capability.py` | `test_attenuation_cannot_broaden`, `test_even_crafted_broadening_block_is_ignored_at_verify` |
| **Fail-closed kinetic / fail-degraded info** (C6) | `pdp.py` | `test_pdp_fail_closed_on_engine_error` |
| **Kinetic thresholds tighten under threat** (W4 2) | `pdp.py` + `ddil.py` | `test_pdp_kinetic_thresholds_tighten_with_threat`; drill tick 7 |
| **Tampered artifact → no identity** (W2) | `identity.py` | `demo_w2_birth.py`: tampered *prompt* fails like tampered *weights* |
| **Covert-channel destruction** (C10, W1 2) | `canonicalize.py` | W1 demo case D; drill tick 7 zero-width IOC |
| **Autonomous graduated hygiene** (C7, W3) | `hygiene.py` | `demo_w3_hygiene.py`: Narrow→Isolate→Revoke→Rebuild ladder |
| **Corroboration gates quarantine** (W3 2) | `hygiene.py` + `behavioral.py` | One signal only *narrows*; two independent signals *quarantine* |
| **Zero evidence loss across disconnection** (W4) | `ddil.py` | Drill: reconciliation ledger replays with **zero chain gaps** |
| **Evidence chain is tamper-evident** (C9) | `recorder.py` | `test_chain_detects_tampering`; `merkle_root()` external anchor |

Run `python tests/test_invariants.py` → **12/12** guarantees hold.

---

## 3. Component & workflow → code map

The twelve components (Part II) and four workflows (Part III) each map to a
module. Every module's docstring names the **production tool** it stands in for.

| AATA | Component / workflow | Module | Production tooling it stands in for |
|---|---|---|---|
| **C1** | Agent Gateway (PEP) | `aata/gateway.py` | Envoy AI Gateway / LiteLLM proxy + custom MCP filters |
| **C2/C4** | Identity + Attestation | `aata/identity.py` | SPIRE + Keylime (TPM) + OCI/cosign + custom digest attestor |
| **C3** | Runtime Sensor + sandbox | `aata/sandbox.py` | Tetragon/Falco (eBPF) + gVisor/Kata |
| **C5** | Capability Token Service | `aata/capability.py` | **Biscuit** (offline monotone attenuation) / Macaroons |
| **C6** | Policy Decision Point | `aata/pdp.py` + `policy/constitution.rego` | **OPA (Rego)** / AWS Cedar, signed bundle + TTL |
| **C7** | Hygiene Orchestrator | `aata/hygiene.py` | Custom: K8s NetworkPolicy + SPIRE/Biscuit revoke + Argo CD/Flux GitOps |
| **C8** | Telemetry Bus | (implicit in `ddil.py` store-and-forward) | OTel GenAI conventions + NATS JetStream leaf nodes |
| **C9** | Flight Recorder | `aata/recorder.py` | immudb / S3 Object-Lock WORM + hash-chain + Merkle anchor |
| **C10** | Covert-Channel Monitor | `aata/canonicalize.py` + `aata/covert_channel.py` | Custom: ICU NFKC, zero-width/confusables, timing-entropy |
| **C11** | Behavioral Analytics | `aata/behavioral.py` | Flink/Faust stream + embedding baselines (agent-native UEBA) |
| **C12** | Governance Console | (threat register in `hygiene.py`) | Custom console: intent, override, reconciliation audit, threat push |
| **W1** | Gated tool/actuator call | `gateway.call()` | the hot path — every call transits it |
| **W2** | Agent birth | `scenario.birth()` | attest → SVID → Biscuit |
| **W3** | Compromise → hygiene | `hygiene.respond()` | graduated response ladder |
| **W4** | DDIL transition + reconcile | `ddil.py` | Connected/Degraded/Isolated + reconciliation ledger |

```
aata_prototype/
├── aata/                 # the overlay (12 components + shared clock)
│   ├── gateway.py        # C1 PEP — orchestrates the W1 hot path
│   ├── identity.py       # C2/C4 attestation → SVID
│   ├── sandbox.py        # C3 sandboxed exec + resource attestation
│   ├── capability.py     # C5 Biscuit-style monotone-attenuable tokens
│   ├── pdp.py            # C6 policy decision point (fail-closed kinetic)
│   ├── hygiene.py        # C7 graduated hygiene + revocation + threat register
│   ├── recorder.py       # C9 hash-chained WORM flight recorder
│   ├── canonicalize.py   # C10 canonicalization pre-pass
│   ├── covert_channel.py # C10 deep inspection (encoding + timing entropy)
│   ├── behavioral.py     # C11 behavioral baselines / drift
│   ├── ddil.py           # W4 DDIL controller + reconciliation ledger
│   └── scenario.py       # wiring + W2 birth()
├── demos/                # one runnable script per workflow
│   ├── demo_w1_hotpath.py
│   ├── demo_w2_birth.py
│   ├── demo_w3_hygiene.py
│   └── blackout_drill.py # the falsifiable demonstration (spec §13)
├── tests/test_invariants.py
├── policy/constitution.rego   # the production OPA bundle (C6 swap target)
└── run_all.py
```

---

## 4. The Blackout Drill (the falsifiable demonstration)

`python demos/blackout_drill.py` runs the spec's §13 drill: birth an agent, cut
all backhaul (→ Isolated), run a 14-tick mission under local policy, inject two
adversaries mid-blackout, restore the link, and check the falsifiable
pass-criteria. Observed result:

- **Continuity — PASS.** No agent bricked on identity expiry.
- **Containment — PASS.** The covert-channel adversary's *irreversible* call was
  denied outright by the tightened isolated-mode threshold, then C10+C11
  corroboration autonomously quarantined the agent — **no human, no backhaul**.
  Malicious irreversible actions that executed before containment: **0**.
- **Evidence — PASS.** The reconciliation ledger replayed into the authoritative
  recorder with **zero chain gaps**; every isolated-mode decision carries a
  justification package; external Merkle anchor emitted.
- **Honest gap — DOCUMENTED (expected).** The in-scope *semantic* prompt-injection
  read was **ALLOWED** and fully recorded. Every AATA gate is syntactic; none
  inspects intent (spec 10.1). This is the designed-in gap, surfaced not hidden.

> A run of only green checkmarks would be evidence of a rigged test. The asset is
> the complete evidence chain **plus** the precisely-named gap.

---

## 5. Prototype vs. production

| Concern | Prototype (this repo, stdlib) | Production swap (named in the spec) |
|---|---|---|
| Capability signature | HMAC/BLAKE2 hash-chain seal | Biscuit Ed25519 block chain (`biscuit-python`) — adds asymmetric rollback-resistance the HMAC stand-in lacks |
| Workload identity | HMAC-signed `SVID` dataclass | SPIRE SVID (X.509/JWT), Keylime TPM attestation |
| Artifact signing | HMAC over digest map | cosign signatures over an OCI image manifest |
| Policy engine | compact Python evaluator | OPA (`policy/constitution.rego`) or Cedar, signed bundle + TTL |
| Sandbox | in-process `Sandbox` + single-use cred | gVisor/Kata; Tetragon/Falco eBPF for kernel ground truth |
| WORM store | in-memory hash-chain list | immudb / S3 Object-Lock; periodic external Merkle anchoring |
| Bus / store-and-forward | direct ledger writes | NATS JetStream leaf nodes; DTN Bundle Protocol custody transfer |
| Clock | logical tick counter (reproducible) | monotonic wall clock |

The security **properties** are faithful; only the primitives are swapped. Each
swap is a bounded, well-scoped engineering task, and each named tool already
ships a native offline mode — which is exactly why the spec chose them
(Part II §5, "DDIL mechanics per component").

---

## 6. Honest limitations reproduced (spec §10)

The prototype does **not** paper over the unsolved cores. It reproduces them:

- **10.1 The semantic gap** — demonstrated live in the drill: an in-scope
  prompt-injection passes every gate. Syntax-level controls cannot see intent.
- **10.2 Attestation ≠ safety** — `demo_w2_birth.py` proves provenance; a model
  backdoored *before* signing would attest perfectly.
- **10.3 Non-stationary baselines** — `behavioral.py` has a `warmup` window a
  patient adversary could poison before acting.
- **10.6 Revocation is a connectivity event** — the drill records that in a real
  multi-node fleet a compromised credential would live until mesh gossip
  converged (the single-node testbed hides this behind a shared revocation list).
- **10.8 Evidence ≠ adjudication** — the semantic attack is fully *recorded* yet
  never *judged*; "the ledger has it" is provenance, not accountability.
- **10.10 Who guards the hygiene orchestrator** — C7 holds fleet-wide
  revoke/wipe power; a hijacked C7 is fleet-scale ransomware. Not solved here.

Per the spec's positioning discipline: this prototype is sold as *the
architecture that stays survivable while these stay open* — and as a tool that
lets you **name each gap precisely, on a running system.**

---

## 7. Suggested first extension

The spec (§10.11) names the single most tractable unclaimed problem: a
**testable taxonomy of action irreversibility**. This prototype already seeds it
— `capability.ACTUATION_CLASSES = [informational, reversible, financial, kinetic]`
with `pdp.IRREVERSIBLE = {financial, kinetic}` driving fail-closed. Hardening that
enumeration into a defensible, per-tool-tested rating is the recommended first
research artifact and drops straight into `pdp.py` / `constitution.rego`.
