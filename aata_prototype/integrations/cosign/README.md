# cosign signed artifact registry — the C4 production swap

The prototype's golden model registry (`aata/identity.py::SignedManifest`) seals a
`{artifact name → sha256 digest}` map with an **HMAC** — a faithful stand-in for the *shape*
of a signed registry, but **symmetric**: whoever verifies a manifest holds the same
`registry_key` that signs it, so the verifier is a forgery risk. This integration is the
real thing: a **detached [cosign](https://github.com/sigstore/cosign)-style signature over
the digest manifest**, on Ed25519.

```bash
pip install -r requirements-cosign.txt   # cryptography
python demos/demo_cosign.py
```

## What the asymmetric primitive adds over the HMAC stand-in

| Property | HMAC manifest (core) | cosign signature (this) |
|---|---|---|
| Sign | `registry_key` | registry **secret** key |
| Verify | **same** key as sign | registry **public** key only — verifier can't forge |
| Swapped/backdoored artifact | caught (sha256 changes) | caught (sha256 changes) |
| Tampered prompt = tampered weights | yes (both signed artifacts) | yes (both signed artifacts) |
| A foreign party's signed manifest | indistinguishable if it holds the shared key | **rejected** — trust is bound to the specific public key |

## API

```python
from integrations.cosign import generate_signing_key, SignedManifest

sk, pub = generate_signing_key()                       # registry keypair
m = SignedManifest.sign_artifacts(sk, {"weights.safetensors": b"...", "system.prompt": b"..."})
ok, mism = m.check(pub, actual_artifacts)              # verify signature + re-hash each artifact
digests  = m.verify(pub)                               # -> the signed map, or raise CosignError
```

`check` verifies the signature with the **public key alone**, then re-hashes each supplied
artifact against the signed digest: a swapped/backdoored file (changed digest), a missing
artifact, or an extra unsigned artifact is reported; a forged or edited manifest raises
before any content is trusted.

The canonical signed payload is **byte-identical** to `aata/identity.py::SignedManifest._sign`,
so this is a genuine drop-in — the same golden manifest, a real signature instead of a shared
secret. Additive and offline-default: the core keeps its HMAC manifest; `cryptography` is
imported lazily and gated on `enabled()`, so `run_all.py`/CI stay dependency-free. Tests skip
when `cryptography` is absent; the CI `integrations-extra` job installs it and runs them.

**Honest limitation (spec 10.2):** a signature proves **provenance, not safety**. A model
backdoored during training signs and verifies perfectly. This proves you are running the
signed artifacts; it cannot prove those artifacts are benign. Pair with the *weights/prompt
digest attestor* (the core's differentiated piece) and Keylime/TPM for the hardware root.
