# WORM evidence store — durable, write-once, externally anchored (C9)

Faithful to the spec's C9 (*"immudb / S3 Object-Lock WORM + hash-chain + Merkle anchor"*):
the hash chain in [`aata/recorder.py`](../../aata/recorder.py) stays the **integrity spine**,
and this package adds durable **write-once** persistence plus an external **Merkle anchor** —
and can round-trip the chain back out of the store and re-verify it.

```bash
# offline default (no deps): evidence mirrors to an in-memory write-once backend
python demos/demo_worm.py

# real S3 Object-Lock (bucket must have Object-Lock enabled)
pip install -e ".[worm]"   # boto3  (or: pip install -r requirements-worm.txt)
AATA_WORM=s3 AATA_WORM_S3_BUCKET=my-object-lock-bucket python demos/demo_worm.py
```

## Why this is the low-risk faithful design

The scoping analysis found the recorder's **synchronous fail-closed ACK** (no-evidence-no-
action), `verify()`, `merkle_root()`, and the logical-clock byte-stability are load-bearing
(now pinned by `tests/test_ddil.py`). So we **don't replace** the hash chain — we persist it:

- **`WormArchiver`** mirrors the chain to a write-once store, `anchor()`s the Merkle root to
  an immutable location, and `load_and_verify()` reconstructs the chain **from the store** and
  re-verifies it — proving the durable copy is intact and tamper-evident independently.
- **`DurableRecorder` / `make_durable(estate)`** is the "behind the recorder" form: it
  write-throughs every `append` to the WORM backend **while preserving the in-memory
  recorder's synchronous fail-closed ACK** (append still raises `RecorderUnreachable` when
  offline). Verified by `test_durable_recorder_preserves_fail_closed`.

## Backends

| Backend | Deps | WORM enforcement |
|---|---|---|
| `InMemoryWormBackend` (default, offline) | none | in-process; re-writing a seq raises `WormViolation` |
| `LocalFileWormBackend` | none | exclusive-create per record file (`open(..., "x")`) |
| `S3ObjectLockBackend` (opt-in) | `boto3` + Object-Lock bucket | COMPLIANCE retention — true immutability |
| immudb | `immudb-py` | documented alternative (immutable, verifiable KV) |

Offline, `enabled()` is False and `worm_backend()` returns the in-memory backend — nothing
imports `boto3`, so `run_all.py`/CI stay offline. Real backends are opt-in via `AATA_WORM`.

> The S3 adapter is written against the boto3 Object-Lock API but, like the OTel exporter,
> is **not exercised in CI** (no bucket in the offline environment). The in-memory and local-
> file backends fully test the archiver/durable-recorder logic and the WORM semantics.

## Usage

```python
from integrations.worm import WormArchiver, make_durable, worm_backend

arch = WormArchiver(worm_backend())        # in-memory offline, or S3 when configured
arch.archive(estate.authoritative)          # mirror the chain (write-once)
arch.anchor(estate.authoritative)           # write the merkle root to the anchor location
report = arch.load_and_verify()             # reconstruct from WORM + re-verify

make_durable(estate)                        # or: write-through every append at write time
```
