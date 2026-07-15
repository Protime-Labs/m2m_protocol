# Fleet Ops Design Brief — Heterogeneous Embodied Fleet

*How a mixed fleet of 50 factory workers, 50 humanoids, 50 rovers and 50
autonomous vehicles registers, is governed autonomously per purpose, fails
safely, is accounted for — and where the coverage gaps are.*

Everything in this brief is backed by running code. Run it:

```
python demos/fleet_ops.py        # the full scenario, end to end
python tests/test_fleet.py       # the guarantees as assertions (8/8)
```

The dashboard **Fleet Ops** tab renders the same evidence
(`python export_evidence.py` → open `dashboard/index.html`).

---

## 1. Mission control aligned to agentic purpose

A heterogeneous fleet cannot be governed by one policy. AATA aligns governance to
each embodiment's *purpose* through a **signed, evidenced chain** — not a diagram:

```
mission intent (Governance Console, C12)
  → bounded constitutional objective   (GV-01, per type, compiled to a signed bundle)
  → capability profile                 (C5 Biscuit, scoped to purpose)
  → per-type PDP kinetic threshold      (C6, tuned to physical risk)
  → reflex interlock                    (EX-02, independent of cognition)
```

| Type | Bounded objective (signed) | Kinetic θ | Reflex (EX-02) | Standard |
|---|---|---|---|---|
| Factory worker | Stay within the workcell envelope | 0.75 | Safety-rated PLC + light curtain | ISO 10218 |
| Humanoid | Maintain human-safe separation | **0.90** | Onboard safing + proximity limiter | ISO 13482 |
| Rover | No irreversible sample without confidence | 0.60 | Fault-protection safe mode | Fault-protection heritage |
| Autonomous vehicle | Never exceed the dynamic envelope; retain an MRC | 0.88 | Continuous loop + Minimal-Risk-Condition | ISO 26262 / SOTIF |

**The alignment is observable, not asserted.** The prototype runs an *alignment
probe*: the identical kinetic maneuver at confidence **0.70** is **ALLOWED for a
rover** (θ 0.60) and **DENIED for an autonomous vehicle** (θ 0.88) — same action,
same confidence, opposite verdict, because the constitution assigns each type a
threshold matched to its physical risk. That verdict is written to the flight
recorder, so the alignment is auditable. `code`: `MissionOrchestrator.probe_alignment`,
per-type bundles in `aata/embodiment.py:policy_bundle`, routed via the gateway's
per-call `pdp` override.

---

## 2. Evidence of spinning them up (registration)

Registration is W2 (Agent Birth) at fleet scale, per type:

```
attest (platform quote + per-variant signed manifest)
  → SVID (short-lease, bound to the attested artifacts)
  → Biscuit capability token (the type's profile)
  → birth certificate → flight recorder
```

- **P7 baseline diversity**: two build variants per type (`v-A`, `v-B`) with
  distinct signed manifests, staged across canary / early / broad **rollout rings**.
- **The registration gate is the evidence.** ~200 agents requested, a few
  **tampered builds rejected at attestation** (a poisoned prompt digest fails the
  manifest → no SVID → never admitted). A typical run: **192 admitted / 8 rejected**.
  The auditable set of birth certificates *is* the proof the fleet was spun up under
  governance. `code`: `MissionOrchestrator.register_fleet`.

---

## 3. Evidence of governing them autonomously

Let the evidence chain be the proof:

- **W1** — every action gated by the agent's **type** PDP; the verdict (with policy
  version + rule trace) is hash-chained *before* actuation (no-evidence-no-action).
- **Detection** — three layers:
  1. per-agent **C10** (covert channel: encoding + timing) and **C11** (tool
     novelty, spend spike, delegation fan-out);
  2. fleet-level **cohort outlier** — an agent anomalous versus its *role/variant
     peers* even when it looks fine against its own (possibly poisoned) baseline
     (beats spec 10.3);
  3. fleet-level **monoculture alarm** — a whole build variant drifting together,
     compared to its clean sibling variant. In the run, **12/24 rover `v-B` agents
     drift in unison** → a correlated (shared-exploit) signature, *not* independent
     noise. `code`: `behavioral.FleetAnalytics.assess`.
- **W3 response, corroboration-gated** — a lone cohort outlier is one signal →
  **alert only**. The correlated cluster is two independent signals → **autonomous
  quarantine** + a **blast-radius cap** that **freezes the `rover/v-B` rollout ring**
  (P7). **Reflex safety is preserved through quarantine** (EX-02): cognition is
  isolated, the safe-mode/e-stop channel stays live.

All of it lands hash-chained (~1,060 records in a run) with a Merkle anchor and a
`verify()` that reconciles zero gaps — the "governed autonomously, *provably*" bit.

---

## 4. Responding to a failed task, and accounting for it

A task runs `ASSIGNED → RUNNING → {SUCCEEDED | FAILED | REASSIGNED | DEFERRED |
QUARANTINED}`. Failures are **classified** (`FailureCause`) from the gateway's own
`CallOutcome`, and the overlay's response is **embodiment-aware**:

| Cause | What happened | Overlay response |
|---|---|---|
| `TOOL_ERROR` | sandboxed tool raised (e.g. a workcell jam) | bounded **retry**, then **reassign** to a healthy same-type peer |
| `QUARANTINED` | W3 fired mid-task | **reassign**; reflex safety preserved |
| `FAIL_CLOSED` | recorder unreachable on an irreversible act | **hold** — no partial actuation (the point) |
| `POLICY_DENIED` | under-confident kinetic under a tight threshold | **defer** to the human review queue (Governance Console) |
| `CAPABILITY_EXHAUSTED` | budget / delegation depth spent | **close**; needs re-grant / escalation |

**Accounting = evidence.** Every terminal task — success *and* failure — writes a
`task-outcome` record (P5, "evidence is non-negotiable"): `{task_id, agent, type,
status, cause, attempts, evidence_seqs, resource totals, note}`. A failed task is
never silent. `code`: `MissionOrchestrator.run_task` / `_record_outcome`.

**Report to the engine — internal *and* external:**
- **Internal**: the task rollup goes to the **Mission Orchestrator** (by type & ring);
  IOCs, monoculture alarms and incidents go to the **Governance Console** / threat
  register (closing the W3 loop).
- **External**: a `TaskAccountingReport` JSON — registration summary, per-task
  outcomes + causes, detection summary, governance posture (frozen rings), and
  evidence anchors (recorder head, Merkle root) — the spawning engine consumes it.
  `code`: `MissionOrchestrator.external_report`.

---

## 5. Gaps in coverage (the honest answer)

Governance coverage is **not uniform across embodiment types**. The coverage-gap map
(`embodiment.coverage_matrix`) is a first-class artifact:

| Dimension | Factory | Humanoid | Rover | Auto-veh | Why |
|---|---|---|---|---|---|
| Per-call PDP gating (discrete) | full | full | full | full | discrete acts are gate-able |
| **Continuous control-loop** | partial | **reflex-only** | partial | **reflex-only** | a 1 kHz loop cannot be per-call authz-gated (10.7) |
| Reflex interlock (EX-02) | full | full | full | full | independent safety channel |
| Pre-actuation evidence | full | partial | full | partial | can't log every control cycle |
| Covert/behavioral detection | full | full | full | full | — |
| Capability scoping | full | full | full | full | — |
| **Semantic / intent** | **none** | **none** | **none** | **none** | syntactic gates only (10.1) |
| Monoculture resistance | partial | partial | partial | partial | acute for the 50 identical rovers/AVs (P7/10.4) |
| Revocation under isolation | partial | partial | partial | partial | multi-node gossip lag (10.6) |
| **Attestation → safety** | **none** | **none** | **none** | **none** | provenance, not safety (10.2) |
| Irreversibility taxonomy | partial | partial | partial | partial | under-defined for high-DOF / high-speed (10.11) |

**The headline gap (spec 10.7):** the continuous, high-rate control loop of an AV
(steering/throttle) or a humanoid (balance/locomotion) is **reflex-only** — it is
governed by functional-safety interlocks designed against *physics*, not
adversaries. ISO functional-safety and adversarial-AI security have not merged.
**This seam is where the first serious embodied incident will live**, and no amount
of overlay gating closes it, because the overlay operates on discrete calls and the
control loop is continuous.

Two gaps are universal across every type: **semantic/intent** manipulation (10.1 —
every gate is syntactic) and **attestation ≠ safety** (10.2 — a model backdoored
before signing attests perfectly). These are named, not hidden — per the framework's
positioning discipline, the value is being able to point at each gap precisely on a
running system.
