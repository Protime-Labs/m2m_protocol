"""
Drive a real Claude agent whose every tool call transits the AATA gateway.

`LLMAgent.run(goal)` runs a manual Messages-API agentic loop: Claude is offered only
the governed-tool wrappers (`governed_tools`), so it cannot act un-gated. The loop is
transport-injectable -- the default transport calls the Anthropic SDK; tests pass a
stub so the whole thing runs offline and deterministically.

Enablement is gated three ways (env flag + key + importable SDK); with any missing,
`enabled()` is False and callers should take the offline path. Nothing here imports
`anthropic` at module load.
"""
from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass, field

from integrations.anthropic import governed_tools as gt
from integrations.anthropic import constitution
from aata.scenario import Estate

DEFAULT_MODEL = "claude-opus-4-8"   # agent brain; claude-haiku-4-5 for cheap workers
MAX_TOKENS = 16000


class LLMDisabled(RuntimeError):
    """Raised when the Anthropic path is used but not enabled."""


def enabled() -> bool:
    """True only if opted in, keyed, and the SDK is importable."""
    return (
        os.getenv("AATA_LLM_BRAIN") == "1"
        and bool(os.getenv("ANTHROPIC_API_KEY"))
        and importlib.util.find_spec("anthropic") is not None
    )


def _anthropic_transport(model, system, messages, tools):
    """Default transport: one Messages-API turn via the Anthropic SDK."""
    import anthropic  # lazy: never imported unless the live path runs
    client = anthropic.Anthropic()
    return client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},   # Opus 4.8: adaptive thinking
        system=system,
        messages=messages,
        tools=tools,
    )


@dataclass
class RunResult:
    goal: str
    stop: str                       # end_turn | refusal | max_turns | text_only
    turns: int
    calls: list = field(default_factory=list)      # list[gt.ToolCallRecord]
    text: str = ""                                  # final assistant text
    usage: dict = field(default_factory=dict)       # summed token usage


def _block_type(b) -> str:
    return getattr(b, "type", None) or (b.get("type") if isinstance(b, dict) else "")


def _text_of(b) -> str:
    return getattr(b, "text", None) or (b.get("text", "") if isinstance(b, dict) else "")


def _add_usage(acc: dict, usage) -> None:
    if usage is None:
        return
    for k in ("input_tokens", "output_tokens",
              "cache_read_input_tokens", "cache_creation_input_tokens"):
        v = getattr(usage, k, None)
        if v is None and isinstance(usage, dict):
            v = usage.get(k)
        if v:
            acc[k] = acc.get(k, 0) + int(v)


class LLMAgent:
    def __init__(self, estate: Estate, agent: gt.GovernedAgent,
                 model: str = DEFAULT_MODEL, transport=None,
                 objective: str = ""):
        self.estate = estate
        self.agent = agent
        self.model = model
        self.objective = objective
        # Injecting a transport bypasses the enablement gate (used by tests).
        self._injected = transport is not None
        self._transport = transport or _anthropic_transport

    def run(self, goal: str, max_turns: int = 8) -> RunResult:
        if not self._injected and not enabled():
            raise LLMDisabled(
                "Anthropic path disabled. Set AATA_LLM_BRAIN=1, export ANTHROPIC_API_KEY, "
                "and `pip install -r requirements-llm.txt`."
            )

        system = constitution.render_system(self.estate, self.agent, self.objective)
        tools = gt.build_tool_defs(self.estate, self.agent)
        messages = [{"role": "user", "content": goal}]

        result = RunResult(goal=goal, stop="max_turns", turns=0)

        for turn in range(1, max_turns + 1):
            result.turns = turn
            resp = self._transport(self.model, system, messages, tools)
            _add_usage(result.usage, getattr(resp, "usage", None))

            if getattr(resp, "stop_reason", None) == "refusal":
                result.stop = "refusal"
                break

            content = list(getattr(resp, "content", []) or [])
            # Preserve the full assistant content (incl. thinking blocks) in history.
            messages.append({"role": "assistant", "content": content})

            tool_uses = [b for b in content if _block_type(b) == "tool_use"]
            if not tool_uses:
                result.text = "".join(_text_of(b) for b in content
                                      if _block_type(b) == "text")
                result.stop = "end_turn"
                break

            tool_results = []
            for tu in tool_uses:
                name = getattr(tu, "name", None) or tu.get("name")
                tinput = getattr(tu, "input", None)
                if tinput is None and isinstance(tu, dict):
                    tinput = tu.get("input", {})
                tuid = getattr(tu, "id", None) or (tu.get("id") if isinstance(tu, dict) else None)
                text, is_error, rec = gt.dispatch(
                    self.estate, self.agent, name, tinput or {},
                    task_id=f"{self.agent.agent_id}:llm-t{turn}",
                )
                result.calls.append(rec)
                tool_results.append({
                    "type": "tool_result", "tool_use_id": tuid,
                    "content": text, "is_error": is_error,
                })
            messages.append({"role": "user", "content": tool_results})

        return result
