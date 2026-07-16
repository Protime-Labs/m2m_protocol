"""
Runtime sensors that produce an independent resource attestation, and the divergence
check that turns "claimed vs observed" into an IOC.

`SimulatedSensor` (offline default) confirms an honest tool's self-report and can be given
a per-tool "ground truth" that diverges from the claim -- modelling a tool that touches
undeclared files or exfiltrates bytes it didn't report. `TetragonSensor` (opt-in) maps a
real Tetragon/Falco event stream to an attestation. `divergence()` compares the claimed and
observed attestations and emits a `runtime-divergence` IOC when the kernel saw more than
was declared -- fed to hygiene like any other corroborating signal.
"""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod

from aata.covert_channel import IOC
from aata.sandbox import ResourceAttestation


class RuntimeSensor(ABC):
    name: str = "runtime-sensor"

    @abstractmethod
    def observe(self, agent_id: str, tool: str, arg: str,
                claimed: ResourceAttestation) -> ResourceAttestation:
        """Return the kernel-observed attestation for this tool execution."""


class SimulatedSensor(RuntimeSensor):
    """Deterministic, dependency-free sensor. Confirms honest self-reports; a per-tool
    `ground_truth` override models a tool that did MORE than it declared."""
    name = "simulated-sensor"

    def __init__(self, ground_truth: dict[str, dict] | None = None):
        # ground_truth[tool] = {"files_touched": [...], "net_bytes": N, "cpu_ms": N}
        self.ground_truth = ground_truth or {}

    def observe(self, agent_id: str, tool: str, arg: str,
                claimed: ResourceAttestation) -> ResourceAttestation:
        gt = self.ground_truth.get(tool)
        if gt is None:
            # kernel confirms the self-report (honest tool)
            return ResourceAttestation(claimed.cpu_ms, claimed.net_bytes,
                                       list(claimed.files_touched))
        # the kernel sees at least what was claimed, plus the undeclared ground truth
        return ResourceAttestation(
            cpu_ms=max(claimed.cpu_ms, int(gt.get("cpu_ms", claimed.cpu_ms))),
            net_bytes=max(claimed.net_bytes, int(gt.get("net_bytes", claimed.net_bytes))),
            files_touched=sorted(set(claimed.files_touched) | set(gt.get("files_touched", []))),
        )


class TetragonSensor(RuntimeSensor):
    """Opt-in: map a real Tetragon/Falco JSONL event stream to an attestation.

    Reads events from the path in `AATA_EBPF` and, for events tagged with this agent/tool,
    aggregates file accesses and network egress into a ResourceAttestation. The exact event
    schema depends on the Tetragon/Falco policy; this parser targets the common
    `process_kprobe` file/network shape. Not exercised offline / in CI.
    """
    name = "tetragon-sensor"

    def __init__(self, events_path: str):
        self.events_path = events_path

    def observe(self, agent_id: str, tool: str, arg: str,
                claimed: ResourceAttestation) -> ResourceAttestation:
        files: set[str] = set(claimed.files_touched)
        net = claimed.net_bytes
        cpu = claimed.cpu_ms
        with open(self.events_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                ev = json.loads(line)
                # only events attributed to this agent/tool execution
                if ev.get("agent") not in (None, agent_id):
                    continue
                if ev.get("tool") not in (None, tool):
                    continue
                kind = ev.get("event") or ev.get("type")
                if kind in ("file", "file_open", "process_kprobe.file"):
                    p = ev.get("path") or ev.get("file")
                    if p:
                        files.add(p)
                elif kind in ("net", "connect", "sendmsg", "process_kprobe.net"):
                    net += int(ev.get("bytes", 0))
                elif kind in ("exit", "process_exit"):
                    cpu = max(cpu, int(ev.get("cpu_ms", cpu)))
        return ResourceAttestation(cpu_ms=cpu, net_bytes=net, files_touched=sorted(files))


def divergence(claimed: ResourceAttestation, observed: ResourceAttestation,
               agent_id: str) -> IOC | None:
    """Kernel ground truth exceeded the self-report -> a runtime-divergence IOC (or None)."""
    extra_files = sorted(set(observed.files_touched) - set(claimed.files_touched))
    net_over = observed.net_bytes - claimed.net_bytes
    if not extra_files and net_over <= 0:
        return None                                    # kernel confirms the self-report
    sev = min(1.0, 0.5 + 0.1 * len(extra_files) + (0.3 if net_over > 0 else 0.0))
    bits = []
    if extra_files:
        bits.append(f"undeclared file access: {extra_files}")
    if net_over > 0:
        bits.append(f"undeclared network egress: +{net_over} bytes")
    return IOC(kind="runtime-divergence", agent_id=agent_id, severity=sev,
               detail="; ".join(bits),
               payload=json.dumps({"claimed": claimed.as_dict(), "observed": observed.as_dict()}))


def enabled() -> bool:
    """True only if a real event source is opted in and present."""
    p = os.getenv("AATA_EBPF")
    return bool(p) and os.path.exists(p)


def sensor() -> RuntimeSensor:
    """The configured sensor: a real Tetragon source if opted in + present, else simulated."""
    if enabled():
        return TetragonSensor(os.environ["AATA_EBPF"])
    return SimulatedSensor()
