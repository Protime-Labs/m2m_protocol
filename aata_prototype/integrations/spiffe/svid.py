"""
Real SPIFFE X.509 SVIDs on Ed25519.

  * `new_ca(trust_domain)`        -> a self-signed trust-domain CA (key, cert).
  * `issue_svid(ca, workload, lease_seconds)` -> a short-lived leaf cert whose SPIFFE ID is
                                     a URI SAN `spiffe://<trust domain>/<workload>`, signed
                                     by the CA.
  * `verify_svid(ca_cert, leaf, now)` -> the SPIFFE ID, or raise `SvidError` (bad signature,
                                     outside the validity window, or missing SPIFFE SAN).

The lease is the certificate's `notAfter`; verification takes only the CA's public cert.
`cryptography` is imported lazily so the module imports cleanly when the package is absent.
"""
from __future__ import annotations

import importlib.util


class SvidError(Exception):
    """Invalid SVID: bad signature chain, expired/not-yet-valid, or no SPIFFE ID."""


def enabled() -> bool:
    return importlib.util.find_spec("cryptography") is not None


def _mods():
    from cryptography import x509                                       # lazy
    from cryptography.hazmat.primitives.asymmetric import ed25519
    return x509, ed25519


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def spiffe_id_of(cert) -> str:
    """Extract the spiffe:// URI SAN, or raise if absent."""
    from cryptography import x509
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        for uri in san.get_values_for_type(x509.UniformResourceIdentifier):
            if uri.startswith("spiffe://"):
                return uri
    except x509.ExtensionNotFound:
        pass
    raise SvidError("certificate carries no SPIFFE ID (spiffe:// URI SAN)")


def new_ca(trust_domain: str = "example.org"):
    """A self-signed trust-domain CA. Returns (ca_private_key, ca_cert)."""
    x509, ed25519 = _mods()
    from cryptography.x509.oid import NameOID
    key = ed25519.Ed25519PrivateKey.generate()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"{trust_domain} CA")])
    now = _now()
    from datetime import timedelta
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName(
            [x509.UniformResourceIdentifier(f"spiffe://{trust_domain}")]), critical=False)
        .sign(key, algorithm=None)                                      # Ed25519 -> algorithm=None
    )
    return key, cert


def issue_svid(ca_key, ca_cert, workload: str, lease_seconds: int = 300):
    """Issue a short-lived leaf SVID for `spiffe://<trust domain>/<workload>`.

    Returns (leaf_private_key, leaf_cert). A negative lease yields an already-expired cert
    (useful for exercising expiry).
    """
    x509, ed25519 = _mods()
    from cryptography.x509.oid import NameOID
    from datetime import timedelta
    trust_domain = spiffe_id_of(ca_cert).removeprefix("spiffe://")
    spiffe_id = f"spiffe://{trust_domain}/{workload.lstrip('/')}"
    leaf_key = ed25519.Ed25519PrivateKey.generate()
    now = _now()
    # notAfter is the lease; keep notBefore strictly earlier even for a negative (already
    # expired) lease, so the certificate is well-formed but outside its validity window.
    not_after = now + timedelta(seconds=lease_seconds)
    not_before = min(now - timedelta(seconds=1), not_after - timedelta(seconds=1))
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, workload)]))
        .issuer_name(ca_cert.subject)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName(
            [x509.UniformResourceIdentifier(spiffe_id)]), critical=True)
        .sign(ca_key, algorithm=None)
    )
    return leaf_key, cert


def _valid_range(cert):
    # cryptography >= 42 exposes tz-aware *_utc accessors; prefer them.
    nb = getattr(cert, "not_valid_before_utc", None) or cert.not_valid_before
    na = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after
    return nb, na


def verify_svid(ca_cert, leaf_cert, now=None) -> str:
    """Verify the leaf is CA-signed and currently valid; return its SPIFFE ID."""
    from cryptography.exceptions import InvalidSignature
    now = now or _now()
    # 1) signature: the leaf must be signed by the CA's key (asymmetric -- CA public cert only)
    try:
        ca_cert.public_key().verify(leaf_cert.signature, leaf_cert.tbs_certificate_bytes)
    except InvalidSignature as e:
        raise SvidError(f"SVID not signed by this CA: {e}") from e
    # 2) lease window (the short lease is the cert notAfter)
    nb, na = _valid_range(leaf_cert)
    if now < nb:
        raise SvidError("SVID not yet valid")
    if now > na:
        raise SvidError("SVID lease expired")
    # 3) identity
    return spiffe_id_of(leaf_cert)
