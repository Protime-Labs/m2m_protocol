# Runtime sensor — kernel ground truth vs the agent's self-report (C3)

Spec W1 step 9: after a tool executes, a runtime sensor produces a resource attestation that
is **ground truth independent of the agent**. In production that's eBPF (Tetragon / Falco)
observing syscalls / network / file access under gVisor / Kata. Here the value it adds is
**corroboration**: compare what the tool *claimed* it did against what the kernel *observed*,
and flag any divergence — a tool cannot hide undeclared file access or egress behind an
honest-looking self-report.

```bash
# offline default (no deps): a deterministic simulated sensor
python demos/demo_ebpf.py

# real Tetragon/Falco event source
AATA_EBPF=/var/run/tetragon/events.jsonl python demos/demo_ebpf.py
```

## What it catches

```
claimed  = {cpu_ms: 2, net_bytes: 0,    files_touched: [/dev/sensor0]}
observed = {cpu_ms: 2, net_bytes: 4096, files_touched: [/dev/sensor0, /etc/shadow]}
        -> runtime-divergence IOC: undeclared file access [/etc/shadow]; +4096 bytes egress
        -> hygiene narrows the agent (Tier 1; a second independent signal would quarantine)
```

- **Independent attestation.** The sensor's reading does not come from the agent, so a
  compromised tool that reads files or exfiltrates beyond its self-report is exposed.
- **Corroboration-gated.** The `runtime-divergence` IOC is one signal — a lone signal only
  narrows (Tier 1); it corroborates C10/C11 signals for autonomous quarantine.

## API

```python
from integrations.ebpf import sensor, divergence

s = sensor()                                   # simulated offline, Tetragon when configured
observed = s.observe(agent_id, tool, arg, claimed_attestation)
ioc = divergence(claimed_attestation, observed, agent_id)   # None if the kernel confirms
```

## Sensors

| Sensor | Source | Notes |
|---|---|---|
| `SimulatedSensor` (default, offline) | a per-tool ground-truth model | confirms honest self-reports; a `ground_truth` override models undeclared behavior |
| `TetragonSensor` (opt-in) | a Tetragon/Falco JSONL event stream (`AATA_EBPF`) | maps file / network / exit events to an attestation |

Unlike the S3 / NATS adapters, the Tetragon parser is **stdlib-only**, so it *is* exercised
in CI against a fixture event stream — only a live kernel sensor is out of scope offline.
Offline, `enabled()` is False and `sensor()` returns the simulated sensor.
