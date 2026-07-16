"""
LIVE: the WORM store on a real S3 Object-Lock bucket (C9). Opt-in; needs MinIO/S3 + boto3.

Proves the two things CI's in-memory backend cannot: (1) the hash chain reconstructs FROM the
write-once store and re-verifies, and (2) the store enforces true immutability -- an attempt to
DELETE the locked object *version* (the real Object-Lock guarantee) is refused by the service.
"""
from __future__ import annotations

import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))     # for _live
from _live import LiveSkip, require, run_id


def run() -> None:
    require(importlib.util.find_spec("boto3") is not None,
            "boto3 not installed (pip install -e '.[worm]')")
    bucket = os.getenv("AATA_WORM_S3_BUCKET")
    require(bool(bucket), "AATA_WORM_S3_BUCKET not set")

    from aata.recorder import FlightRecorder
    from aata.scenario import Backends, birth, build_estate
    from integrations.worm.archiver import DurableRecorder, WormArchiver
    from integrations.worm.backend import S3ObjectLockBackend, WormViolation

    prefix = f"aata-live-{run_id()}"
    backend = S3ObjectLockBackend(bucket, prefix=prefix)
    try:                                                            # connectivity preflight
        backend._s3.list_buckets()
    except Exception as e:                                         # noqa: BLE001
        raise LiveSkip(f"cannot reach S3/MinIO (set AWS_* + AWS_ENDPOINT_URL): {e}")

    # Run the overlay with the S3-backed durable recorder on the hot path.
    est = build_estate(backends=Backends(
        recorder_factory=lambda: DurableRecorder(FlightRecorder(name="authoritative"), backend)))
    svid, token = birth(est, "rover-live", {"sensor_read"})
    est.gateway.call("rover-live", svid, token, "sensor_read", "ping")

    # (1) Durability: reconstruct the chain FROM the write-once store and re-verify.
    res = WormArchiver(backend).load_and_verify()
    assert res["ok"], f"reload+verify failed: {res}"
    assert res["records"] == len(est.authoritative.records), \
        f"S3 has {res['records']} records, chain has {len(est.authoritative.records)}"
    print(f"  durable reload+verify: ok records={res['records']} "
          f"merkle={res['merkle_root'][:16]}...")

    # (2) Immutability: deleting the LOCKED version must be refused by Object-Lock. (A same-key
    # PUT would only add a version; the guarantee is that the retained version cannot be removed.)
    seq0 = est.authoritative.records[0].seq
    key = f"{prefix}/records/{seq0:08d}.json"
    vid = backend._s3.head_object(Bucket=bucket, Key=key).get("VersionId")
    try:
        backend._s3.delete_object(Bucket=bucket, Key=key, VersionId=vid)
        assert False, "deleted a locked object version -- Object-Lock NOT enforced!"
    except backend._s3.exceptions.ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        assert code in ("AccessDenied", "InvalidRequest"), f"unexpected S3 error: {code}"
        print(f"  Object-Lock immutability: delete of retained version refused ({code})")

    # (3) The app-level write-once guard also holds (defense in depth).
    try:
        backend.put_record(seq0, {"tamper": True})
        assert False, "duplicate seq accepted"
    except WormViolation:
        print("  app-level write-once: duplicate seq refused")

    print("  S3 Object-Lock live validation PASSED")


if __name__ == "__main__":
    try:
        run()
    except LiveSkip as e:
        print(f"  SKIP: {e}")
