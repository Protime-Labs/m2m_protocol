# Biscuit Ed25519 capability tokens — the C5 production swap

The prototype's core capability token (`aata/capability.py`) is an **HMAC** hash-chain
seal — a faithful stand-in for the *shape* of monotone attenuation, but **symmetric**:
whoever can verify a token holds the same key that mints it, so the verifier is a forgery
risk and there is no rollback resistance. This integration is the real thing: **Biscuit v2
on Ed25519**.

```bash
pip install -r requirements-biscuit.txt   # cryptography
python demos/demo_biscuit.py
```

## What the asymmetric primitive adds over the HMAC stand-in

| Property | HMAC seal (core) | Biscuit Ed25519 (this) |
|---|---|---|
| Mint | authority key | authority **secret** key |
| Verify | **same** key as mint | authority **public** key only — verifier can't mint |
| Attenuate offline | holder re-seals with a shared key | holder appends a signed block with **no authority secret** |
| Broadening | blocked by intersect-at-verify | blocked by intersect-at-verify |
| Tamper | detected (hash chain) | detected (signature chain) |
| Truncation / rollback | not resisted | **resisted** — a per-block key-rotation + a proof over the last key make stripping a caveat require an intermediate secret the holder lacks |

## Construction

An append-only chain of signed blocks with key rotation:
- **Block 0** carries the root grant + a *next* public key, signed by the authority secret.
- **Attenuation** generates a fresh key pair, appends a block (a narrowing caveat + the new
  next key) signed by the *current* block's key, and the holder carries the new secret key.
- A **proof** signature by the last secret key over the chain of signatures makes truncation
  detectable.
- **Verification** takes only the authority *public* key, walks the chain (each block
  verified by the previous block's public key), checks the proof under the last key, and
  returns the **effective grant = root ∩ all caveats** — so verification can only ever
  narrow.

Additive and offline-default: the core keeps its HMAC token; `cryptography` is imported
lazily and gated on `enabled()`, so `run_all.py`/CI stay dependency-free. The tests skip
when `cryptography` is absent; the CI `integrations-extra` job installs it and runs them.
