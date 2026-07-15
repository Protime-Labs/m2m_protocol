"""
AATA reference prototype
========================

A runnable, dependency-free (Python >=3.10 stdlib only) prototype of the
Autonomous Agent Trust Architecture (AATA-2026-001).

It is deliberately small and *explainable*: every module maps 1:1 to a component
(C1..C12) or workflow (W1..W4) from the AATA Part II / Part III specs, and every
module names the real production tool it stands in for. See README.md for the map.

The prototype's purpose is to make the architecture's load-bearing GUARANTEES
executable and observable:

    * no-evidence-no-action           (W1 step 6-7  -> recorder.py + gateway.py)
    * monotone capability attenuation (C5           -> capability.py)
    * fail-closed kinetic actions     (C6           -> pdp.py)
    * covert-channel destruction      (C10          -> canonicalize.py)
    * autonomous graduated hygiene    (C7 / W3       -> hygiene.py)
    * DDIL survival + zero evidence loss (W4         -> ddil.py)

Nothing here is production crypto. Where the spec calls for public-key crypto
(Biscuit=Ed25519, SPIRE SVID=X.509, cosign) the prototype uses HMAC/BLAKE2 from
the stdlib as an honest, clearly-labelled stand-in. The security *shape* --
offline verifiability, append-only chaining, monotone attenuation -- is real.
"""

__version__ = "0.1.0"
