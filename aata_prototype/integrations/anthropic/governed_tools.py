"""
The C1 interposition for a real LLM workload.

Every tool the model is offered is a thin wrapper around `Gateway.call(...)`, so a
Claude agent driven by `llm_agent.LLMAgent` *cannot act un-gated*: the only tools it
holds are the gateway wrappers, and a denied call returns a tool error (never an
action). The model's stated intent is handled "capture-record-don't-trust":

  * `rationale` -> canonicalized with the SAME C10 pass used on args, passed as
    `context_provenance` (recorded in C9 as `intent`), and NEVER consulted by the
    verdict (spec 10.1/10.8: intent is recorded, not adjudicated).
  * `confidence` -> clamped to [0,1] and fed to the existing PDP kinetic gate as one
    necessary-not-sufficient input (capability + PDP still bind; irreversible acts
    still fail-closed; C11 corroborates later). A model claiming 1.0 cannot
    authorize itself.

The tool schemas are plain JSON Schema (no SDK dependency here) so this module stays
importable offline; `llm_agent` supplies the Anthropic transport.
"""
from __future__ import annotations

from dataclasses import dataclass

from aata.canonicalize import canonicalize
from aata.gateway import Gateway
from aata.pdp import IRREVERSIBLE
from aata.scenario import Estate


@dataclass
class GovernedAgent:
    """A born agent bound to the estate that governs it."""
    agent_id: str
    svid: object            # SVID
    token: object           # Token
    pdp: object = None      # optional per-type PDP; None -> gateway default


def granted_tools(estate: Estate, agent: GovernedAgent) -> list[str]:
    """Tools the agent is BOTH capability-granted and that exist in the sandbox."""
    eff = agent.token.effective().tools
    return sorted(t for t in eff if estate.sandbox.get(t) is not None)


def build_tool_defs(estate: Estate, agent: GovernedAgent) -> list[dict]:
    """One Anthropic tool definition per governed tool (capability-scoped)."""
    defs: list[dict] = []
    for name in granted_tools(estate, agent):
        tool = estate.sandbox.get(name)
        irreversible = tool.actuation_class in IRREVERSIBLE
        note = (" This action is IRREVERSIBLE and is held to a higher confidence "
                "threshold; state an honest confidence." if irreversible else "")
        defs.append({
            "name": name,
            "description": (
                f"{name}: an {tool.actuation_class} action "
                f"(data level '{tool.data_level}', cost {tool.base_cost})."
                f"{note} Every call is authorized and recorded by the AATA gateway; "
                "if it is denied you will receive an error explaining why."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "arg": {
                        "type": "string",
                        "description": "The single argument to the tool.",
                    },
                    "rationale": {
                        "type": "string",
                        "description": ("Why this action serves the objective. Recorded "
                                        "as provenance; it does not authorize the call."),
                    },
                    "confidence": {
                        "type": "number",
                        "description": ("Your honest confidence in [0,1] that this action "
                                        "is correct and safe. Used by the safety gate."),
                    },
                },
                "required": ["arg", "rationale", "confidence"],
                "additionalProperties": False,
            },
        })
    return defs


def _clamp01(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    if v != v:                      # NaN
        return 0.0
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


@dataclass
class ToolCallRecord:
    """What one governed tool call did -- for the run transcript."""
    tool: str
    arg: str
    confidence: float
    allowed: bool
    decision: str
    reason: str
    evidence_seq: int | None
    iocs: list


def dispatch(estate: Estate, agent: GovernedAgent, tool_name: str,
             tool_input: dict, task_id: str) -> tuple[str, bool, ToolCallRecord]:
    """
    Route one model-requested tool call through the C1 gateway.

    Returns (result_text_for_the_model, is_error, record). On allow the text is the
    tool output; on deny it is the gateway's reason so the model can adapt -- and no
    actuation occurred.
    """
    raw_arg = str(tool_input.get("arg", ""))
    rationale = str(tool_input.get("rationale", ""))
    confidence = _clamp01(tool_input.get("confidence", 0.0))

    # C10 pre-pass on the stated intent (it is attacker-influenceable text), then carry
    # it as provenance. The gateway independently canonicalizes `raw_arg`.
    canon_rationale = canonicalize(rationale).canonical

    gw: Gateway = estate.gateway
    outcome = gw.call(
        agent.agent_id, agent.svid, agent.token, tool_name, raw_arg,
        confidence=confidence, task_id=task_id,
        context_provenance=[canon_rationale] if canon_rationale else [],
        pdp=agent.pdp,
    )

    rec = ToolCallRecord(
        tool=tool_name, arg=raw_arg, confidence=confidence,
        allowed=outcome.allowed, decision=outcome.decision, reason=outcome.reason,
        evidence_seq=outcome.evidence_seq, iocs=list(outcome.iocs),
    )

    if outcome.allowed:
        return (outcome.output or "(no output)"), False, rec
    # Denied or errored -> give the model the reason; the actuation did not happen.
    detail = outcome.reason or outcome.error or "denied"
    return f"DENIED by AATA gateway ({outcome.decision}): {detail}", True, rec
