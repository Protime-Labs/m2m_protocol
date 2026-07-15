"""
OpenTelemetry emission for the AATA overlay -- a real signal pipeline (C8).

ADDITIVE: it reads the signals the overlay already produces (W1 verdicts, C10 IOCs,
evidence records, the merkle anchor) and emits them as real OpenTelemetry spans -- it
does NOT replace the deterministic hash chain, so it disturbs none of the load-bearing
invariants (fail-closed ACK, verify(), merkle, the logical clock).

Offline by default: with the OTel path disabled, emissions go to an in-memory capture
backend (no `opentelemetry` import) so the whole suite stays offline and deterministic.
Enabled only when AATA_OTEL=1 and `opentelemetry` is importable; then spans export to the
OTLP endpoint (OTEL_EXPORTER_OTLP_ENDPOINT) or the console. Every signal carries the
`agent_id` join key -- the sole correlator across the overlay's observability controls.
"""
from integrations.otel.emitter import Signal, TelemetryEmitter, enabled

__all__ = ["TelemetryEmitter", "Signal", "enabled"]
