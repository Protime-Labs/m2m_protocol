# M2M fleet console — estate-side capture + cloud publisher

The estate side of the hosted single pane ("Intune-style management surface,
assume-breach security core"). `ConsoleFeed` captures the overlay's event stream through
the existing `Backends` seams; sinks are a JSONL spool (offline default) or Supabase
(opt-in). The console is a **read-model**: it never sits on the enforcement path, and a
feed/publisher fault can never change a gateway outcome (blanket-hardened, tested by
fault injection in `tests/test_console.py`).

## Wire an estate into the console

```python
from aata.scenario import build_estate, birth
from console import ConsoleFeed

feed = ConsoleFeed("/var/aata/spool", label="site-a")   # offline: JSONL spool
est = build_estate(backends=feed.backends())            # tee + observer attached
birth(est, "rover-01", {"sensor_read"})                 # -> instantly registered
```

Every C9 record (birth, pre-actuation, result, hygiene, task-outcome, mode,
reconciled:\*) and every call outcome — **including early denies** by revoked/expired
identities, which write no record — becomes one event line keyed `(src, agent)`.
`src` is unique per run, so two estates birthing the same `agent_id` never merge.

## Publish to the hosted console (Supabase)

```bash
export AATA_CONSOLE_URL=https://<project>.supabase.co
export AATA_CONSOLE_ANON=<anon/publishable key>          # public transport key
export AATA_CONSOLE_WRITE_KEY=<write key>                # private ingest credential
```

```python
from console.publish import sink_from_env
feed = ConsoleFeed("/var/aata/spool", label="site-a", sink=sink_from_env())
```

or backfill an existing spool:  `python -m console.publish spool.jsonl`

The publisher is non-blocking (bounded store-and-forward buffer + background flush,
drop-oldest-with-counter on overflow) and stdlib-only.

**Write key**: writes go through the `console_ingest` RPC, which checks the key against
the private `console_config` table (RLS: invisible to the API). The anon key alone can
neither read (reads need an authenticated console user) nor write. Retrieve/rotate in
the Supabase SQL editor:

```sql
select value from console_config where key = 'write_key';           -- retrieve
update console_config set value = '<new>' where key = 'write_key';  -- rotate
```

## Server-side model (created by the `m2m_console_*` migrations)

- `console_events` — the stream; `id` is the global cursor; Realtime-published.
- `console_sources` / `console_agents` — roster, derived by trigger from events.
- `console_agent_posture` (view) — the **authoritative** posture logic:
  `quarantined` (hygiene tier ≥ 3 — revocation is inferred, and labeled as such) ·
  `out-of-scope` (tier 2) · `drifting` (denies/IOCs) · `stale` (no event > 300 s,
  wall clock) · `compliant`; plus `assurance` = `crypto-attested` only when real
  SPIFFE+cosign birth fields are present (never implied).
- `console_fleet_rollup`, `console_denials`, `console_detections` (judge events are
  categorized **recorded-not-adjudicated** — surfaced, never shown as clean).

`console/registry.py` is the deterministic CI mirror of these rules (`run_all.py`
exercises it offline; CI needs no cloud secrets).
