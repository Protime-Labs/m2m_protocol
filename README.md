# AATA — Autonomous Agent Trust Architecture

[![CI](https://github.com/Protime-Labs/m2m_protocol/actions/workflows/ci.yml/badge.svg)](https://github.com/Protime-Labs/m2m_protocol/actions/workflows/ci.yml)

**A zero-trust security overlay for fleets of autonomous, agentic, and embodied
machines.** AATA (AATA-2026-001) wraps an unmodified estate of agents, tools, and
actuators in twelve overlay components that *see and gate every action* — giving
each machine a hardware-rooted identity, offline-verifiable capabilities,
fail-closed kinetics, tamper-evident evidence, and autonomous hygiene that all
keep working when the network doesn't.

This repository is the home of the **M2M (machine-to-machine) trust protocol**: the
AATA specification set **plus a runnable reference prototype and evidence console**
that turns every load-bearing guarantee in the spec into executable, observable
behavior.

> **Positioning discipline.** AATA is sold as *the architecture that stays
> survivable while the hard problems stay open.* It does not claim to solve
> semantic intent verification or make attestation equal safety — it makes each
> gap **nameable and observable on a running system.** A demo of only green
> checkmarks would be evidence of a rigged test.

---

## What's in this repo

| Path | What it is |
|---|---|
| **[`aata_prototype/`](aata_prototype/)** | The runnable reference prototype + web console. Dependency-free Python 3.10+. Start here. |
| [`aata_prototype/integrations/`](aata_prototype/integrations/) | Opt-in, offline-default integrations — the Anthropic capability + the real-signal pipeline (OTel / WORM / NATS). See [Real-system integrations](#real-system-integrations-anthropic--real-signals). |
| `AATA_Framework_v1.0.pdf` | **Part I** — the framework: threat model, planes, principles (P1–P7), standards mapping. |
| `AATA_PartII_Component_Tooling_Spec_v1.0.pdf` | **Part II** — the twelve components (C1–C12), tooling, and DDIL behavior per component. |
| `AATA_PartIII_Workflows_FutureProofing_v1.0.pdf` | **Part III** — the four workflows (W1–W4) and future-proofing. |
| `AATA_Master_Strategy_Concept_to_Pilot_v1.0.pdf` | **Master Strategy** — the adoption roadmap from concept to production pilot. |

The prototype is faithful to the *security shape* of AATA; where the spec calls for
production public-key primitives (SPIRE, Biscuit, cosign, OPA), the prototype uses
clearly-labelled stdlib stand-ins. See [Adoption → Production swaps](#production-swaps).

---

## Quickstart (≈10 seconds, no dependencies)

Requires only Python **3.10+** (validated on 3.13). No `pip install`, no network.

```bash
git clone https://github.com/Protime-Labs/m2m_protocol.git
cd m2m_protocol/aata_prototype

python run_all.py        # the whole suite: tests + all demos + the blackout drill
```

Expected: **85 tests pass** — core invariants + fleet + DDIL reconciliation + the LLM and
real-signal integrations, all offline — then the W1–W4 demos and the blackout drill report
`continuity / containment / evidence-integrity = PASS` with the semantic gap documented
(by design). The suite is **CI-enforced across Python 3.10–3.13**, and `run_all.py` exits
non-zero on any failure.

### Launch the evidence console

```bash
cd aata_prototype
python export_evidence.py            # run the live overlay -> dashboard/data.js + data.json
python -m http.server 8787 --bind 127.0.0.1 --directory dashboard
# open http://127.0.0.1:8787/index.html
```

The console renders everything the overlay produces — the hash-chained flight
recorder, the Component × Workflow / Control × Component intersections, the
component handoff graph, DDIL behavior, the threat register, and the **Fleet Ops**
tab (200 heterogeneous agents). Nothing is mocked; every figure is emitted by the
live prototype. A pre-generated `dashboard/data.js` is committed, so the console
also works by opening `dashboard/index.html` directly.

> Full technical reference — the guarantees table, component→code map, the
> blackout drill, and prototype-vs-production detail — lives in
> **[`aata_prototype/README.md`](aata_prototype/README.md)**.

---

## The architecture at a glance

Five planes, twelve components, four workflows.

**Planes** — Governance · Trust · Control · Observability/Evidence · Data-plane (interception).

**Components (C1–C12)**

| | Component | Plane | Stands in for (production tooling) |
|---|---|---|---|
| C1 | Agent Gateway (PEP) | Data-plane | Envoy AI Gateway / LiteLLM + MCP filters |
| C2 | Identity Sidecar | Data-plane | SPIRE agent + cosign verify |
| C3 | Runtime Sensor + sandbox | Data-plane | Tetragon/Falco (eBPF) + gVisor/Kata |
| C4 | Identity + Attestation | Trust | SPIRE + Keylime (TPM) + OCI/cosign |
| C5 | Capability Token Service | Trust | Biscuit (offline monotone attenuation) |
| C6 | Policy Decision Point | Control | OPA (Rego) / Cedar, signed bundle + TTL |
| C7 | Hygiene Orchestrator | Control | K8s NetworkPolicy + revoke + Argo CD/Flux |
| C8 | Telemetry Bus | Observability | OTel GenAI + NATS JetStream leaf nodes |
| C9 | Flight Recorder | Observability | immudb / S3 Object-Lock WORM + Merkle |
| C10 | Covert-Channel Monitor | Observability | ICU NFKC + zero-width/confusables + timing |
| C11 | Behavioral Analytics | Observability | Flink/Faust + embedding baselines (agent UEBA) |
| C12 | Governance Console | Governance | intent authoring + override + threat register |

**Workflows (W1–W4)** — W1 Gated tool/actuator call (the hot path) · W2 Agent birth
(attestation → capability) · W3 Compromise → graduated hygiene · W4 DDIL transition
+ reconciliation.

**Load-bearing guarantees** (each a runnable assertion in the prototype): no-evidence-no-action,
monotone capability attenuation, fail-closed kinetic / fail-degraded informational,
kinetic thresholds tighten under threat, covert-channel destruction, autonomous
graduated hygiene, zero evidence loss across disconnection, tamper-evident evidence chain.

---

## Real-system integrations (Anthropic + real signals)

Beyond the stdlib core, [`aata_prototype/integrations/`](aata_prototype/integrations/) adds
**opt-in, offline-default** integrations that make the overlay a real system — each
preserving the framework's discipline (Claude is never on the deterministic enforcement
path; the load-bearing invariants stay intact and CI-pinned).

**Anthropic capability** ([`integrations/anthropic/`](aata_prototype/integrations/anthropic/)) — four honest Claude roles:
- **Governed workload** — real Claude agents whose *every* tool call transits the C1 gateway (the model cannot act un-gated; stated intent is recorded, never trusted).
- **Semantic judge (C11)** — an advisory classifier that *surfaces* the spec-10.1 semantic-gap attack the syntactic gates allow; recorded and corroboration-gated, never authoritative.
- **Red-team harness** — labeled adversaries probe the overlay and score efficacy (recall/precision, containment, honestly-reported gaps — not an all-green rig).
- **Governance Console copilot (C12)** — Claude drafts incident summaries / justification packages from the evidence chain for human sign-off (reads-only; provenance, not adjudication).

**Real signal pipeline** — the spec's production tooling, behind the existing interfaces:
- **OpenTelemetry emission** ([`integrations/otel/`](aata_prototype/integrations/otel/)) — the overlay's signals as real OTel spans (C8), additive; every signal carries the `agent_id` join key.
- **WORM evidence store** ([`integrations/worm/`](aata_prototype/integrations/worm/)) — durable write-once persistence + external Merkle anchor (immudb / S3 Object-Lock), with round-trip re-verification, preserving the synchronous fail-closed ACK (C9).
- **NATS store-and-forward** ([`integrations/nats/`](aata_prototype/integrations/nats/)) — the DDIL ledger backed by a durable bus with FIFO custody-transfer replay on reconnect (C8 / W4).
- **Runtime sensor** ([`integrations/ebpf/`](aata_prototype/integrations/ebpf/)) — kernel ground truth (Tetragon/Falco) independent of the agent's self-report; flags undeclared file access / egress as a divergence IOC (C3, W1 step 9).

Every integration is **offline by default** (in-memory backends, no third-party imports) so
the whole suite and CI stay dependency-free and deterministic; the real backends
(`anthropic`, `opentelemetry`, `boto3`, `nats-py`) are opt-in via a `requirements-*.txt` +
an env flag. Each folder has its own README with the enable steps and honesty notes.

---

## Adoption

AATA is an **overlay**: you deploy it around an existing estate without modifying
the agents themselves. Each component carries a **disposition** that tells you how
much you build versus buy.

### Build vs. buy, per component

| Disposition | Meaning | Components |
|---|---|---|
| **ADOPT** | Deploy a mature off-the-shelf tool largely as-is | **C2** Identity Sidecar (SPIRE) · **C3** Runtime Sensor + sandbox (Tetragon/Falco + gVisor) · **C8** Telemetry Bus (OTel + NATS) |
| **EXTEND** | Adopt a tool, add AATA-specific glue/config | **C1** Gateway · **C4** Identity + Attestation · **C5** Capability Token Service (Biscuit) · **C6** PDP (OPA) · **C9** Flight Recorder |
| **BUILD** | Net-new, AATA-specific engineering | **C7** Hygiene Orchestrator · **C10** Covert-Channel Monitor · **C11** Behavioral Analytics · **C12** Governance Console |

The BUILD set is where the differentiated work is — and it's exactly the set the
prototype implements most fully, so you can validate the design before committing
production effort.

### Concept → pilot → production

1. **Understand** — read *Part I (Framework)* for the threat model and principles; run
   `python run_all.py` to see the guarantees hold and fail on cue.
2. **Evaluate** — open the console; walk the Component × Workflow intersections and the
   blackout drill. Confirm the security *shape* matches your estate.
3. **Pilot** — follow the *Master Strategy: Concept to Pilot* doc. Stand up the ADOPT
   components first (SPIRE, OTel/NATS, eBPF sensors), then the EXTEND glue.
4. **Harden** — replace stdlib stand-ins with the named production primitives (below),
   one bounded swap at a time.
5. **Operate** — run the BUILD components (C7/C10/C11/C12) against real fleet telemetry.

### <a name="production-swaps"></a>Production swaps

The prototype's security *properties* are faithful; only the primitives are swapped.
Each swap is a bounded, well-scoped task, and each named tool already ships a native
offline mode (which is why the spec chose it).

| Concern | Prototype stand-in (stdlib) | Production swap |
|---|---|---|
| Capability signature | HMAC/BLAKE2 hash-chain seal | Biscuit Ed25519 block chain (`biscuit-python`) |
| Workload identity | HMAC-signed SVID dataclass | SPIRE SVID (X.509/JWT) + Keylime TPM attestation |
| Artifact signing | HMAC over digest map | cosign signatures over an OCI image manifest |
| Policy engine | compact Python evaluator | OPA (`policy/constitution.rego`) or Cedar, signed bundle + TTL |
| Sandbox / runtime sensor | in-process sandbox + self-reported attestation | gVisor/Kata; Tetragon/Falco eBPF ground truth — ✅ [`integrations/ebpf/`](aata_prototype/integrations/ebpf/) |
| WORM store | in-memory hash-chain | immudb / S3 Object-Lock + Merkle anchoring — ✅ [`integrations/worm/`](aata_prototype/integrations/worm/) |
| Bus / store-and-forward | direct ledger writes | NATS JetStream leaf nodes — ✅ [`integrations/nats/`](aata_prototype/integrations/nats/) |
| Telemetry / observability | direct in-process signals | OTel GenAI spans → collector — ✅ [`integrations/otel/`](aata_prototype/integrations/otel/) |

### Standards alignment

Controls map to **NIST AI RMF** (GOVERN/MAP/MEASURE/MANAGE), **NIST SP 800-53** (AC/AU/IA/IR/CP families),
**SP 800-207** (Zero Trust), **SSDF / SLSA** (supply chain), **MITRE ATLAS** (adversarial ML), and, for
embodiment, **ISO 10218 / 13482 / 26262 / SOTIF** and **IEC 61508** functional safety.

---

## Honest limitations (reproduced, not hidden)

The prototype demonstrates these live rather than papering over them:

- **Semantic gap (10.1)** — every gate is syntactic; an in-scope prompt-injection passes them all and is *recorded, not judged*.
- **Attestation ≠ safety (10.2)** — a model backdoored before signing attests perfectly.
- **Continuous control is reflex-only (10.7)** — a 1 kHz steering/balance loop cannot be per-call authz-gated; this seam is where the first serious embodied incident will live.
- **Revocation is a connectivity event (10.6)** — under isolation a compromised credential lives until mesh gossip converges.
- **Evidence ≠ adjudication (10.8)** — "the ledger has it" is provenance, not accountability.
- **Who guards the hygiene orchestrator (10.10)** — C7 holds fleet-wide revoke/wipe power; a hijacked C7 is fleet-scale ransomware.

See the **Fleet Ops** design brief ([`aata_prototype/docs/fleet_ops_brief.md`](aata_prototype/docs/fleet_ops_brief.md))
for the full control × embodiment-type coverage-gap map.

---

## Status & license

**Status:** reference prototype (AATA-2026-001, v0.1.0). Not production crypto and
not a product — it is a faithful, falsifiable model of the architecture's security
guarantees, intended for evaluation and pilot design.

**License:** [Business Source License 1.1](LICENSE) — *source-available, not (yet) open source.*

- **Free for everyone:** copy, modify, and make **non-production** use (evaluation, testing, non-commercial research).
- **Production use** is granted only to **authorized participants in a Protime Consulting Inc. beta / pilot program** under a separate written agreement (terms outlined in [`BETA.md`](BETA.md) — a draft pending counsel review); any other production or commercial use (including offering it as a hosted/managed service) requires a **commercial license**.
- **Auto-converts to open:** each released version becomes available under the **Apache License 2.0** on its Change Date (**2030-07-15** for v0.1.0, i.e. four years after release).

© 2026 Protime Consulting Inc. For commercial or alternative licensing, contact **info@protimeconsulting.com** (see [`LICENSE`](LICENSE)).
