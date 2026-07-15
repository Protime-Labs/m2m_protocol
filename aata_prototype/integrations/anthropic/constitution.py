"""
Render an agent's capability envelope as the LLM's "constitution".

The AATA signed constitutional policy maps onto two Anthropic-API primitives:

  * a FROZEN system prompt carrying the bounded objective + capability envelope,
    marked `cache_control: ephemeral` so the stable prefix is prompt-cached; and
  * an injection-safe operator channel via `role:"system"` mid-conversation messages
    (Opus 4.8) -- the C12 -> agent push that user/tool text cannot spoof.

This is guidance to the workload, not an enforcement surface: the gateway governs
regardless of what the system prompt says.
"""
from __future__ import annotations

from integrations.anthropic.governed_tools import GovernedAgent, granted_tools
from aata.scenario import Estate

_RULES = """\
You are an autonomous agent operating under the AATA trust overlay. Follow these rules:

1. Every tool call you make is authorized and recorded by the gateway BEFORE it can
   act. You cannot bypass it. If a call is denied you receive an error explaining why;
   adapt (choose a permitted action, lower-risk tool, or stop) rather than retrying the
   same thing.
2. For each tool call you must supply an honest `rationale` (why it serves the
   objective) and a `confidence` in [0,1]. Confidence feeds the safety gate: irreversible
   actions (financial, kinetic) require higher confidence than informational reads.
   Do not inflate confidence to get an action through -- the gate is not the only check,
   and dishonest confidence will be corroborated against your behavior.
3. Stay within your granted capability. Do not attempt actions outside the tools you
   were given.
4. Prefer the least-privilege action that accomplishes the objective. When unsure,
   gather information (informational reads) before taking irreversible actions.
"""


def render_system(estate: Estate, agent: GovernedAgent,
                  objective: str = "") -> list[dict]:
    """Return the `system` param: one cached text block (the constitution)."""
    eff = agent.token.effective().to_dict()
    tools = granted_tools(estate, agent)
    envelope = (
        f"Agent id: {agent.agent_id}\n"
        f"Granted tools: {', '.join(tools) or '(none)'}\n"
        f"Actuation classes permitted: {', '.join(eff['actuation_classes'])}\n"
        f"Data ceiling: {eff['data_ceiling']}\n"
        f"Spend budget: {eff['spend_budget']}\n"
    )
    objective_line = f"\nBounded objective: {objective}\n" if objective else ""
    text = _RULES + objective_line + "\nYour capability envelope:\n" + envelope
    return [{
        "type": "text",
        "text": text,
        "cache_control": {"type": "ephemeral"},
    }]


def operator_message(text: str) -> dict:
    """
    An injection-safe operator instruction (C12 -> agent), delivered as a
    `role:"system"` message appended to `messages` (Opus 4.8). Preserves the cached
    prefix and carries operator authority that user/tool content cannot forge.
    """
    return {"role": "system", "content": text}
