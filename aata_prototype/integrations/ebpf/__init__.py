"""
Runtime sensor (C3) -- kernel ground truth independent of the agent's self-report.

Spec W1 step 9: after a tool executes, a runtime sensor produces a resource attestation
that is *ground truth independent of the agent*. In production this is eBPF (Tetragon /
Falco) observing syscalls/network/file access under gVisor/Kata; here the value it adds is
**corroboration**: compare what the tool *claimed* it did (the sandbox's self-reported
attestation) against what the kernel *observed*, and flag any divergence -- extra files
touched, undeclared network egress -- as a `runtime-divergence` IOC. A tool cannot hide
undeclared behavior behind an honest-looking self-report.

Offline by default: a deterministic simulated sensor (no external deps) so the whole suite
stays offline. A real Tetragon/Falco event source is opt-in via AATA_EBPF.
"""
from integrations.ebpf.sensor import (
    RuntimeSensor,
    SimulatedSensor,
    TetragonSensor,
    divergence,
    enabled,
    sensor,
)

__all__ = [
    "RuntimeSensor", "SimulatedSensor", "TetragonSensor",
    "divergence", "enabled", "sensor",
]
