"""
Normalize the overlay's signals and emit them as OpenTelemetry spans.

Every `emit_*` builds a normalized `Signal` (name + agent_id + attributes) and hands it to
a backend. Two backends share the same interface:

  * `_CaptureBackend` (default, offline) -- appends signals to an in-memory list. No
    `opentelemetry` import. This is what `run_all.py`, the tests, and the offline demo use.
  * `_OTelBackend` (opt-in) -- builds a real OTel TracerProvider and emits a span per
    signal (attributes prefixed `aata.`), exporting to OTLP or the console.

`agent_id` is attached to every signal as `aata.agent` -- it is the sole join key across
the overlay's observability controls, so a real collector can correlate by it.
"""
from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass, field
from typing import Any

RESOURCE_SERVICE = "aata-overlay"


def enabled() -> bool:
    """True only if opted in and the OpenTelemetry SDK is importable."""
    return (
        os.getenv("AATA_OTEL") == "1"
        and importlib.util.find_spec("opentelemetry") is not None
    )


@dataclass
class Signal:
    """A normalized telemetry signal (backend-agnostic)."""
    name: str                       # e.g. "aata.w1", "aata.ioc", "aata.record", "aata.evidence"
    agent: str | None               # the agent_id join key (None for fleet-wide summaries)
    attrs: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- backends

class _CaptureBackend:
    """Offline: keep emitted signals in memory (no OpenTelemetry dependency)."""
    def __init__(self):
        self.signals: list[Signal] = []

    def emit(self, sig: Signal) -> None:
        self.signals.append(sig)

    def flush(self) -> None:
        pass


class _OTelBackend:
    """Opt-in: emit one OpenTelemetry span per signal."""
    def __init__(self, exporter=None):
        from opentelemetry.sdk.resources import Resource                  # lazy
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

        if exporter is None:                                             # injectable for tests
            if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )
                exporter = OTLPSpanExporter()
            else:
                exporter = ConsoleSpanExporter()

        provider = TracerProvider(resource=Resource.create({"service.name": RESOURCE_SERVICE}))
        provider.add_span_processor(BatchSpanProcessor(exporter))
        self._provider = provider
        # Bind the tracer to THIS provider (not the global no-op one), or spans would be
        # created on a tracer whose processor/exporter we never flush -> silently dropped.
        self._tracer = provider.get_tracer("aata.overlay")
        self.signals: list[Signal] = []      # also retained for parity with capture

    def emit(self, sig: Signal) -> None:
        self.signals.append(sig)
        with self._tracer.start_as_current_span(sig.name) as span:
            if sig.agent is not None:
                span.set_attribute("aata.agent", sig.agent)
            for k, v in sig.attrs.items():
                span.set_attribute(f"aata.{k}", v if isinstance(v, (str, int, float, bool))
                                   else str(v))

    def flush(self) -> None:
        self._provider.force_flush()


# --------------------------------------------------------------------------- emitter

class TelemetryEmitter:
    def __init__(self, backend=None):
        if backend is not None:
            self._backend = backend
        elif enabled():
            self._backend = _OTelBackend()
        else:
            self._backend = _CaptureBackend()

    @property
    def signals(self) -> list[Signal]:
        return getattr(self._backend, "signals", [])

    def flush(self) -> None:
        self._backend.flush()

    # -- emit one governed W1 call (from a CallOutcome + ToolCallRecord) ----
    def emit_call(self, agent_id: str, tool: str, decision: str, allowed: bool,
                  evidence_seq: int | None, ioc_kinds: list[str] | None = None,
                  confidence: float | None = None,
                  irreversibility: float | None = None) -> Signal:
        attrs = {"tool": tool, "decision": decision, "allowed": allowed,
                 "evidence_seq": -1 if evidence_seq is None else evidence_seq,
                 "iocs": ",".join(ioc_kinds or [])}
        if confidence is not None:
            attrs["confidence"] = confidence
        if irreversibility is not None:            # graded irreversibility (spec 10.11)
            attrs["irreversibility"] = irreversibility
        return self._emit(Signal("aata.w1", agent_id, attrs))

    def emit_ioc(self, agent_id: str, kind: str, severity: float, detail: str = "") -> Signal:
        return self._emit(Signal("aata.ioc", agent_id,
                                 {"kind": kind, "severity": severity, "detail": detail}))

    def emit_record(self, record) -> Signal:
        return self._emit(Signal("aata.record", record.payload.get("agent"),
                                 {"seq": record.seq, "kind": record.kind,
                                  "t": record.t, "hash": record.this_hash[:16]}))

    def emit_chain(self, estate, scenario: str = "scenario") -> Signal:
        """Emit a fleet-wide evidence summary + one signal per authoritative record."""
        auth = estate.authoritative
        ok, _ = auth.verify()
        led_ok, _ = estate.ddil.ledger.verify()
        summary = self._emit(Signal("aata.evidence", None, {
            "scenario": scenario, "merkle_root": auth.merkle_root(),
            "chain_ok": ok and led_ok, "records": len(auth.records),
            "ledger_records": len(estate.ddil.ledger.records),
        }))
        for r in auth.records:
            self.emit_record(r)
        return summary

    def _emit(self, sig: Signal) -> Signal:
        self._backend.emit(sig)
        return sig
