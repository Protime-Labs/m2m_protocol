# NATS JetStream store-and-forward — the DDIL disconnection transport (C8 / W4)

Faithful to the spec's C8/W4 (*"NATS JetStream leaf nodes (store-and-forward)"*): while
the overlay is Degraded/Isolated, evidence accrues to a durable **store-and-forward** bus;
on reconnect it **replays into the authoritative recorder with custody transfer** — one
continuous audit chain, zero evidence loss — gated on fleet re-attestation.

```bash
# offline default (no deps): a durable in-memory bus
python demos/demo_nats.py

# real NATS JetStream (server with -js enabled)
pip install -e ".[nats]"   # nats-py  (or: pip install -r requirements-nats.txt)
AATA_NATS=nats://localhost:4222 python demos/demo_nats.py
```

## What it preserves (pinned by `tests/test_ddil.py`)

The reconciliation invariants a real bus must not break — now enforced by tests here too:

- **FIFO order** — records replay in publish order (out-of-order delivery would break the
  zero-gap chain invariant).
- **Zero-gap replay** — draining the bus re-chains each record into the authoritative
  recorder as `reconciled:<kind>`; both chains still `verify()`.
- **Origin provenance** — each replayed record carries `origin="nats-jetstream"` +
  `origin_seq`/`origin_hash` pointing at the durable message.
- **Reentry gate** — replay refuses without fleet re-attestation (no silent rejoin); the
  bus is not drained.
- **Fail-closed** — the write-through `ForwardingLedger` still raises `RecorderUnreachable`
  when the recorder is offline (no-evidence-no-action).

## API

```python
from integrations.nats import LedgerForwarder, make_forwarding, bus

make_forwarding(estate, bus())          # DDIL ledger write-throughs each record to the bus
# ... go isolated, accrue evidence (durably held on the bus) ...
fwd = LedgerForwarder(bus())
fwd.replay(estate.authoritative, fleet_reattests_ok=True)   # custody-transfer replay on reconnect
```

## Backends

| Backend | Deps | Store-and-forward |
|---|---|---|
| `InMemoryBus` (default, offline) | none | ordered durable log + ack cursor |
| `NatsJetStreamBus` (opt-in) | `nats-py` + a JetStream server | a real stream; publish/consume with ack |

Offline, `enabled()` is False and `bus()` returns the in-memory bus — nothing imports
`nats`, so `run_all.py`/CI stay offline. The JetStream adapter is written against `nats-py`
but, like the S3/OTel adapters, is **not exercised in CI** (no server offline); the
in-memory bus fully tests the forwarder logic and the store-and-forward semantics.
