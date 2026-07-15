"""
C1 -- Agent Gateway / Policy Enforcement Point.
Controls: AATA-OB-01/02, AATA-CT-01, AATA-EX-01, AATA-TR-03.

Production tooling: Envoy AI Gateway or LiteLLM proxy core + custom MCP gateway
filters (tool mediation, context-provenance tagging, canonicalization pre-pass).

This is the W1 HOT PATH -- every LLM tool call and physical actuation transits
this exact sequence. The invariant the whole architecture rests on:

    NO ACTUATION BEFORE EVIDENCE. Steps 6-7 write the immutable pre-actuation
    record and require its ACK before any scoped credential is released. If the
    recorder is unreachable, kinetic/irreversible actions do not proceed.

The gateway wires together every other component:
    C10 canonicalize -> C5 capability -> C6 PDP -> C9 recorder(ACK) ->
    C3 sandbox -> C11/C10 async fan-out -> (optional) C7 autonomous hygiene.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .behavioral import BehavioralAnalytics, DriftSignal
from .canonicalize import canonicalize
from .clock import CLOCK
from .capability import Token
from .covert_channel import IOC, TimingMonitor, encoding_ioc
from .ddil import DDILController
from .hygiene import HygieneOrchestrator, RevocationList, ThreatRegister
from .identity import SVID
from .pdp import PDP, IRREVERSIBLE
from .recorder import RecorderUnreachable
from .sandbox import Sandbox


@dataclass
class CallOutcome:
    allowed: bool
    decision: str                        # allow | deny | allow-degraded
    reason: str
    steps: list[str] = field(default_factory=list)
    verdict_trace: list[str] = field(default_factory=list)
    output: str = ""
    error: str = ""                      # sandbox/tool error, if execution failed
    resource_attestation: dict | None = None
    iocs: list[IOC] = field(default_factory=list)
    evidence_seq: int | None = None      # flight-recorder seq of the pre-actuation write
    provenance: dict[str, Any] = field(default_factory=dict)


class Gateway:
    def __init__(
        self,
        authority_key: bytes,
        pdp: PDP,
        sandbox: Sandbox,
        ddil: DDILController,
        revocation: RevocationList,
        threat: ThreatRegister,
        behavioral: BehavioralAnalytics,
        timing: TimingMonitor | None = None,
        hygiene: HygieneOrchestrator | None = None,
    ):
        self.authority_key = authority_key
        self.pdp = pdp
        self.sandbox = sandbox
        self.ddil = ddil
        self.revocation = revocation
        self.threat = threat
        self.behavioral = behavioral
        self.timing = timing or TimingMonitor()
        self.hygiene = hygiene
        self._tokens: dict[str, Token] = {}   # last-seen token per agent (for hygiene)

    def call(
        self,
        agent_id: str,
        svid: SVID,
        token: Token,
        tool_name: str,
        raw_args: str,
        confidence: float = 0.9,
        task_id: str = "task-0",
        context_provenance: list[str] | None = None,
        pdp: PDP | None = None,
    ) -> CallOutcome:
        # Per-call PDP override: the mission orchestrator routes each embodied agent
        # through its TYPE's policy bundle (per-type kinetic thresholds). Defaults to
        # the gateway's own PDP, so the hot path is unchanged for single-type callers.
        pdp = pdp or self.pdp
        out = CallOutcome(allowed=False, decision="deny", reason="")
        rec = self.ddil.active_recorder
        tool = self.sandbox.get(tool_name)

        # Step 1 -- intent with task-id + context provenance tags.
        out.provenance = {
            "task_id": task_id, "agent": agent_id, "tool": tool_name,
            "context": context_provenance or [],
        }
        out.steps.append(f"1. intent: agent={agent_id} tool={tool_name} task={task_id}")

        # Step 2 -- canonicalization pre-pass (destroys cheap covert channels).
        canon = canonicalize(raw_args)
        enc_ioc = encoding_ioc(agent_id, canon)
        if enc_ioc:
            out.iocs.append(enc_ioc)
        out.steps.append(
            f"2. canonicalize: changed={canon.changed} "
            f"delta_ioc={canon.delta_is_ioc} "
            + (f"[{'; '.join(canon.notes)}]" if canon.notes else ""))

        # Step 3 -- capability verification (offline) + identity/revocation gates.
        if not svid.valid(self.authority_key):
            out.reason = "SVID invalid or lease expired"
            out.steps.append("3. capability: DENY (SVID invalid)")
            return out
        if self.revocation.is_revoked(agent_id) or self.revocation.is_revoked(token.subject):
            out.reason = "identity is on the revocation list"
            out.steps.append("3. capability: DENY (revoked)")
            return out
        if not token.verify(self.authority_key):
            out.reason = "capability token failed offline verification"
            out.steps.append("3. capability: DENY (token seal invalid)")
            return out
        out.steps.append("3. capability: token chain verified offline (no callback)")

        if tool is None:
            out.reason = f"unknown tool '{tool_name}'"
            out.steps.append("3b. DENY (unknown tool)")
            return out

        # Step 4-5 -- PDP authorization (local bundle) + fail-closed semantics.
        threat_level = max(self.threat.level, self.ddil.threat_level_floor)
        verdict = pdp.evaluate(
            token=token, tool=tool_name, actuation_class=tool.actuation_class,
            data_level=tool.data_level, cost=tool.base_cost, confidence=confidence,
            now=CLOCK.now(), threat_level=threat_level,
        )
        out.verdict_trace = verdict.rule_trace
        out.steps.append(
            f"4-5. PDP verdict={verdict.decision} ({verdict.reason})"
            + (" [FAIL-CLOSED]" if verdict.fail_closed else ""))
        if not verdict.allow:
            out.decision = verdict.decision
            out.reason = verdict.reason
            self._async_fanout(out, agent_id, tool_name, tool.base_cost, canon)
            return out

        # Step 6-7 -- pre-actuation flight-recorder write; ACK gates release.
        try:
            pre = rec.append("pre-actuation", {
                "task_id": task_id, "agent": agent_id, "tool": tool_name,
                "actuation_class": tool.actuation_class,
                "canonical_args": canon.canonical,
                # Stated intent/rationale (canonicalized upstream) recorded as evidence
                # only -- it never entered the verdict above (spec 10.1/10.8). An empty
                # list keeps records identical for callers that pass no provenance.
                "intent": out.provenance.get("context", []),
                "policy_version": verdict.policy_version,
                "verdict": verdict.decision, "rule_trace": verdict.rule_trace,
            })
            out.evidence_seq = pre.seq
            out.steps.append(f"6-7. pre-actuation record seq={pre.seq} ACKed "
                             f"(hash {pre.this_hash[:12]}...) -> release permitted")
        except RecorderUnreachable as e:
            # no-evidence-no-action: irreversible classes DO NOT proceed.
            if tool.actuation_class in IRREVERSIBLE:
                out.decision = "deny"
                out.reason = f"recorder unreachable + irreversible class -> fail-closed: {e}"
                out.steps.append("6-7. recorder UNREACHABLE -> FAIL-CLOSED (no action)")
                return out
            out.decision = "allow-degraded"
            out.reason = f"recorder unreachable; informational class fail-degraded: {e}"
            out.steps.append("6-7. recorder UNREACHABLE -> fail-degraded (informational)")

        # Step 8 -- scoped single-use credential + sandboxed execution.
        verdict_hash = str(hash((tool_name, verdict.policy_version, out.evidence_seq)))
        cred = self.sandbox.scoped_credential(tool_name, verdict_hash)
        result = self.sandbox.execute(tool_name, canon.canonical, cred)
        out.steps.append(f"8. sandbox executed with single-use credential "
                         f"({'ok' if result.ok else 'error: ' + result.error})")

        # Step 9 -- result + resource-usage attestation (kernel ground truth).
        out.output = result.output
        out.error = result.error
        out.resource_attestation = result.attestation.as_dict()
        out.steps.append(f"9. resource attestation: {out.resource_attestation}")
        if result.ok:
            rec.append("result", {"task_id": task_id, "tool": tool_name,
                                   "attestation": result.attestation.as_dict()})

        # Step 10 -- async fan-out (off the hot path): C10 + C11 + autonomous C7.
        self._async_fanout(out, agent_id, tool_name, tool.base_cost, canon)

        # Step 11 -- provenance-tagged response.
        out.allowed = result.ok
        out.decision = "allow" if result.ok else out.decision
        out.reason = verdict.reason if result.ok else out.reason
        out.provenance["evidence_seq"] = out.evidence_seq
        out.steps.append("11. response returned provenance-tagged")
        return out

    # -- Step 10 detail: detection features accrue without adding hot-path latency
    def _async_fanout(self, out: CallOutcome, agent_id: str, tool_name: str,
                      cost: int, canon) -> None:
        # Timing-channel entropy over call cadence.
        t_ioc = self.timing.observe(agent_id, CLOCK.now())
        if t_ioc:
            out.iocs.append(t_ioc)
        # Behavioral drift (corroboration signal).
        drift: DriftSignal = self.behavioral.observe_call(agent_id, tool_name, cost)
        # Autonomous graduated hygiene (W3) -- fire if we have any IOC.
        if self.hygiene and out.iocs and agent_id in self._tokens:
            for ioc in out.iocs:
                self.hygiene.respond(agent_id, self._tokens[agent_id], ioc, drift)

    def remember_token(self, agent_id: str, token: Token) -> None:
        """Register the agent's current token so autonomous hygiene can attenuate it."""
        self._tokens[agent_id] = token

    def _last_token_for(self, agent_id: str) -> Token:
        return self._tokens[agent_id]
