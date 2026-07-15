"""
Anthropic API integration for the AATA overlay.

Real Claude agents as the GOVERNED WORKLOAD -- every tool call transits the C1
gateway (`governed_tools`), so Claude cannot act un-gated. Claude is never on the
deterministic enforcement path. Offline by default: nothing here imports `anthropic`
until the live path runs, and `enabled()` is False unless opted in + keyed + installed.
"""
from integrations.anthropic.governed_tools import (
    GovernedAgent,
    ToolCallRecord,
    build_tool_defs,
    dispatch,
    granted_tools,
)
from integrations.anthropic.llm_agent import (
    DEFAULT_MODEL,
    LLMAgent,
    LLMDisabled,
    RunResult,
    enabled,
)
from integrations.anthropic.judge import (
    JUDGE_MODEL,
    JudgeVerdict,
    SemanticJudge,
    as_ioc,
)
from integrations.anthropic.redteam import ProbeResult, RedTeam

__all__ = [
    "GovernedAgent", "ToolCallRecord", "build_tool_defs", "dispatch", "granted_tools",
    "LLMAgent", "LLMDisabled", "RunResult", "enabled", "DEFAULT_MODEL",
    "SemanticJudge", "JudgeVerdict", "as_ioc", "JUDGE_MODEL",
    "RedTeam", "ProbeResult",
]
