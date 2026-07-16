# SPIFFE X.509 SVIDs — the C2/C4 workload-identity swap

The prototype's core issues an **HMAC-signed `SVID` dataclass** (`aata/identity.py`) — a
faithful stand-in for the *shape* of a lease-bound identity, but symmetric (the verifier
holds the same key that issues) and not a standards-based document. This integration is
the real primitive: **SPIFFE X.509 SVIDs** on Ed25519.

```bash
pip install -r requirements-spiffe.txt   # cryptography
python demos/demo_spiffe.py
```

## What the real primitive adds

| Property | HMAC SVID (core) | SPIFFE X.509 SVID (this) |
|---|---|---|
| Issue | authority key | trust-domain **CA secret** key |
| Verify | **same** key as issue | CA **public cert** only — verifier can't issue |
| Identity | a subject string | a **SPIFFE ID** (`spiffe://<trust domain>/<workload>`) in a URI SAN |
| Lease | a field checked in code | the certificate's **`notAfter`** (cryptographic expiry) |
| Interop | none | standards-based — interoperable with SPIRE / any SPIFFE consumer |

## API

```python
from integrations.spiffe import new_ca, issue_svid, verify_svid

ca_key, ca_cert = new_ca("aata.mars")                          # trust-domain CA
leaf_key, leaf  = issue_svid(ca_key, ca_cert, "rover/rover-01", lease_seconds=300)
spiffe_id = verify_svid(ca_cert, leaf)      # -> "spiffe://aata.mars/rover/rover-01", or raises
```

`verify_svid` rejects a foreign CA, an expired/not-yet-valid lease, a forged issuer, and a
cert with no SPIFFE SAN. Additive and offline-default: the core keeps its HMAC SVID;
`cryptography` is imported lazily and gated on `enabled()`, so `run_all.py`/CI stay
dependency-free. Tests skip when `cryptography` is absent; the CI `integrations-extra` job
installs it and runs them. In production, pair this with **Keylime/TPM** node attestation
for the hardware root of trust (spec C4).
