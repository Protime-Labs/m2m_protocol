# Live validation (S3 Object-Lock + NATS JetStream)

The offline suite (`python run_all.py`, CI-enforced) exercises every adapter through an
in-memory backend. Two adapters have a real-service form that CI cannot host: the **S3
Object-Lock** WORM store (C9) and the **NATS JetStream** store-and-forward bus (C8/W4). This
runbook validates them against real services on your own infrastructure.

It is **opt-in and off the CI path**: `run_live.py` is not called by `run_all.py`, is gated on
`AATA_LIVE=1`, and skips (exit 0) when a service, library, or env var is absent.

## What it proves

| Check | Guarantee |
|---|---|
| S3 Object-Lock | the hash chain reconstructs **from the write-once store** and re-verifies; **deleting a retained object version is refused** by the service (true immutability, not just an app-level guard) |
| NATS JetStream | isolated-mode evidence published to a durable stream **survives a reconnect** and replays with **custody transfer** — the reconciled chain verifies, keeps origin provenance, and preserves `agent_id`; a reconnect that fails fleet re-attestation is refused |

## 1. Start the services

```bash
docker compose up -d          # MinIO (S3 + Object-Lock) on :9000, NATS JetStream on :4222
# the `createbucket` one-shot makes bucket `aata-worm` WITH object-lock enabled
```

## 2. Install the service extras

```bash
cd aata_prototype
pip install -e ".[worm]" -e ".[nats]"      # boto3 + nats-py  (or ".[all]")
```

## 3. Point the adapters at the local services

```bash
# S3 / MinIO
export AWS_ACCESS_KEY_ID=aata
export AWS_SECRET_ACCESS_KEY=aata-secret
export AWS_ENDPOINT_URL=http://localhost:9000     # boto3 >= 1.28 honors this
export AWS_REGION=us-east-1
export AATA_WORM=s3
export AATA_WORM_S3_BUCKET=aata-worm

# NATS
export AATA_NATS=nats://localhost:4222

# turn on live validation
export AATA_LIVE=1
```

## 4. Run

```bash
python run_live.py
```

Expected (abbreviated):

```
== S3 OBJECT-LOCK WORM STORE (C9)
  durable reload+verify: ok records=3 merkle=....
  Object-Lock immutability: delete of retained version refused (AccessDenied)
  app-level write-once: duplicate seq refused
  S3 Object-Lock live validation PASSED
== NATS JETSTREAM STORE-AND-FORWARD (C8/W4)
  published 5 isolated-mode records to NATS JetStream (stream AATA_LIVE_0)
  reconnect replay: 5 records re-chained, verify ok, origin+agent_id preserved
  NATS JetStream live validation PASSED
== LIVE RESULT
  LIVE OK
```

Set `AATA_LIVE_RUN=<n>` to namespace a fresh run (distinct bucket prefix + JetStream stream)
so repeats don't collide on keys or a durable consumer cursor.

## 5. Tear down

```bash
docker compose down -v         # -v also removes the MinIO volume
```

## Notes
- **Object-Lock needs versioning**; `mc mb --with-lock` enables both. Records are written in
  `COMPLIANCE` mode with a long retention, so even the root account cannot delete a retained
  version until it expires — which is exactly what the immutability check asserts.
- The core stays offline: `run_all.py` never imports these clients, and `run_live.py` skips
  cleanly if you run it without the services up.
- AWS instead of MinIO: drop `AWS_ENDPOINT_URL`, use a real Object-Lock bucket, and a managed
  NATS/JetStream endpoint for `AATA_NATS`.
