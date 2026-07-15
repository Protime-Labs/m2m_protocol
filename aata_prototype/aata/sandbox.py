"""
C3 -- Runtime Sensor + sandboxed tool execution.
Controls: AATA-EX-01 (mediated tool proxies), AATA-EX-02 (reflex interlocks).

Production tooling: Tetragon/Falco (eBPF) for kernel ground truth; gVisor/Kata
sandboxes for tool execution.

Two W1 guarantees:
  * Step 8 -- the gateway releases a SCOPED, SINGLE-USE credential to the tool
    proxy; the agent never holds tool credentials. Blast radius bounded by the
    sandbox.
  * Step 9 -- the result returns with a RESOURCE-USAGE ATTESTATION (cpu, network,
    files) measured by the sandbox itself -- ground truth independent of what the
    agent claims it did.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable

from .clock import CLOCK


@dataclass
class ResourceAttestation:
    """Kernel-level ground truth about what the tool call actually consumed."""
    cpu_ms: int
    net_bytes: int
    files_touched: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"cpu_ms": self.cpu_ms, "net_bytes": self.net_bytes,
                "files_touched": sorted(self.files_touched)}


@dataclass
class ToolResult:
    ok: bool
    output: str
    attestation: ResourceAttestation
    error: str = ""


@dataclass
class Tool:
    """A registered tool. `run` returns (output, ResourceAttestation)."""
    name: str
    actuation_class: str          # informational | reversible | financial | kinetic
    data_level: str               # data classification touched
    base_cost: int
    run: Callable[[str], tuple[str, ResourceAttestation]]


class Sandbox:
    """gVisor/Kata stand-in: runs a tool under a single-use scoped credential."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._issued: set[str] = set()   # single-use credential ledger

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def scoped_credential(self, tool_name: str, verdict_hash: str) -> str:
        """Mint a single-use credential bound to this specific verdict."""
        cred = hashlib.sha256(f"{tool_name}|{verdict_hash}|{CLOCK.tick()}".encode()).hexdigest()
        self._issued.add(cred)
        return cred

    def execute(self, tool_name: str, arg: str, credential: str) -> ToolResult:
        """Run the tool iff the single-use credential is valid; then burn it."""
        if credential not in self._issued:
            return ToolResult(False, "", ResourceAttestation(0, 0),
                              error="invalid or reused credential")
        self._issued.discard(credential)  # single use
        tool = self._tools.get(tool_name)
        if tool is None:
            return ToolResult(False, "", ResourceAttestation(0, 0),
                              error=f"no such tool '{tool_name}'")
        try:
            output, att = tool.run(arg)
            return ToolResult(True, output, att)
        except Exception as e:  # sandbox contains the blast radius
            return ToolResult(False, "", ResourceAttestation(0, 0),
                              error=f"sandboxed exception: {e}")
