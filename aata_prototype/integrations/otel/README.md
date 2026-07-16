# OpenTelemetry emission — a real signal pipeline (C8)

The overlay's signals (W1 verdicts, C10 IOCs, evidence records, the merkle anchor) emitted
as **real OpenTelemetry spans** for a collector to ingest.

```bash
# offline default (no deps): emissions go to an in-memory capture backend
python demos/demo_otel.py

# real OpenTelemetry -> console
pip install -e ".[otel]"   # (or: pip install -r requirements-otel.txt)
AATA_OTEL=1 python demos/demo_otel.py

# ship to a collector (e.g. an OTLP/HTTP endpoint)
AATA_OTEL=1 OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 python demos/demo_otel.py
```

## Design — additive, offline-default

- **Additive.** It *reads* the signals the overlay already produces and emits them; it does
  **not** replace the deterministic hash chain. So it disturbs **none** of the load-bearing
  invariants — synchronous fail-closed ACK, `verify()`, `merkle_root()`, the logical clock.
- **`agent_id` is on every per-agent signal** (`aata.agent`). It is the sole join key across
  the overlay's observability controls, so a collector can correlate a W1 verdict, its IOCs,
  and its evidence records by agent.
- **Offline by default.** With the OTel path disabled, emissions go to an in-memory capture
  backend and **nothing imports `opentelemetry`** — so `run_all.py`, the tests, and CI stay
  offline and deterministic. The real SDK is an opt-in dependency (`requirements-otel.txt`),
  enabled only when `AATA_OTEL=1` and `opentelemetry` is importable.

## Signals emitted

| Span name | agent | Attributes (`aata.*`) |
|---|---|---|
| `aata.w1` | agent_id | tool, decision, allowed, evidence_seq, iocs, confidence |
| `aata.ioc` | agent_id | kind, severity, detail |
| `aata.record` | payload agent | seq, kind, t, hash |
| `aata.evidence` | — (fleet-wide) | scenario, merkle_root, chain_ok, records, ledger_records |

## Usage

```python
from integrations.otel import TelemetryEmitter
em = TelemetryEmitter()                       # offline capture, or real OTel when enabled
em.emit_call(agent_id, tool, decision, allowed, evidence_seq, ioc_kinds, confidence)
em.emit_ioc(agent_id, kind, severity, detail)
em.emit_chain(estate, scenario="run")         # summary (merkle) + one signal per record
em.flush()
# offline: em.signals is the captured list (used by tests/demo)
```

## Scope

This is the first, lowest-risk real-signal step (see the scoping analysis). The higher-risk
swaps — a real WORM backend (immudb / S3 Object-Lock) behind the recorder, or a NATS
JetStream store-and-forward transport for the DDIL ledger — are deferred to their own slices
because they touch the fail-closed ACK / hash-chain / determinism invariants directly.
