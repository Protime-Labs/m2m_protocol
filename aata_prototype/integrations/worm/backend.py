"""
WORM backends: write-once record storage + an immutable Merkle-anchor location.

Interface every backend preserves:
  * `put_record(seq, record)` -- WRITE-ONCE: re-writing an existing seq raises
    `WormViolation` (the defining WORM property).
  * `all_records()` -- the durable records, ordered by seq.
  * `put_anchor(merkle_root, meta)` / `anchors()` -- append the external Merkle anchor.

`InMemoryWormBackend` (default, offline, hermetic) and `LocalFileWormBackend` (filesystem)
are dependency-free and enforce write-once themselves. `S3ObjectLockBackend` is opt-in
(needs `boto3` + a bucket with Object-Lock) and gets true immutability from S3 retention;
it is lazily imported and not exercised offline/in CI.
"""
from __future__ import annotations

import importlib.util
import json
import os
from abc import ABC, abstractmethod


class WormViolation(Exception):
    """Raised on an attempt to overwrite an already-written record (WORM: write-once)."""


def _frozen_copy(record: dict) -> dict:
    # store a canonical, detached copy so the caller can't mutate what's "durable"
    return json.loads(json.dumps(record, sort_keys=True))


class WormBackend(ABC):
    name: str = "worm"

    @abstractmethod
    def put_record(self, seq: int, record: dict) -> None: ...

    @abstractmethod
    def get_record(self, seq: int) -> dict | None: ...

    @abstractmethod
    def all_records(self) -> list[dict]: ...

    @abstractmethod
    def put_anchor(self, merkle_root: str, meta: dict) -> None: ...

    @abstractmethod
    def anchors(self) -> list[dict]: ...


class InMemoryWormBackend(WormBackend):
    """Hermetic, dependency-free, write-once. The offline default and test backend."""
    name = "in-memory-worm"

    def __init__(self):
        self._records: dict[int, dict] = {}
        self._anchors: list[dict] = []

    def put_record(self, seq: int, record: dict) -> None:
        if seq in self._records:
            raise WormViolation(f"record seq={seq} already written (WORM: write-once)")
        self._records[seq] = _frozen_copy(record)

    def get_record(self, seq: int) -> dict | None:
        r = self._records.get(seq)
        return _frozen_copy(r) if r is not None else None

    def all_records(self) -> list[dict]:
        return [_frozen_copy(self._records[k]) for k in sorted(self._records)]

    def put_anchor(self, merkle_root: str, meta: dict) -> None:
        self._anchors.append(_frozen_copy({"merkle_root": merkle_root, **meta}))

    def anchors(self) -> list[dict]:
        return [_frozen_copy(a) for a in self._anchors]


class LocalFileWormBackend(WormBackend):
    """Filesystem WORM: one write-once file per record + an append-only anchors log.

    Write-once is enforced by refusing to open an existing record path. (A real
    deployment layers OS/immutable-storage controls under this; here it demonstrates
    the semantics without external services.)
    """
    name = "local-file-worm"

    def __init__(self, root: str):
        self.root = root
        self._rec_dir = os.path.join(root, "records")
        self._anchor_path = os.path.join(root, "anchors.jsonl")
        os.makedirs(self._rec_dir, exist_ok=True)

    def _path(self, seq: int) -> str:
        return os.path.join(self._rec_dir, f"{seq:08d}.json")

    def put_record(self, seq: int, record: dict) -> None:
        path = self._path(seq)
        if os.path.exists(path):
            raise WormViolation(f"record seq={seq} already written (WORM: write-once)")
        with open(path, "x", encoding="utf-8") as f:              # "x" = exclusive create
            json.dump(_frozen_copy(record), f, sort_keys=True)

    def get_record(self, seq: int) -> dict | None:
        path = self._path(seq)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def all_records(self) -> list[dict]:
        out = []
        for name in sorted(os.listdir(self._rec_dir)):
            if name.endswith(".json"):
                with open(os.path.join(self._rec_dir, name), encoding="utf-8") as f:
                    out.append(json.load(f))
        return out

    def put_anchor(self, merkle_root: str, meta: dict) -> None:
        with open(self._anchor_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"merkle_root": merkle_root, **meta}, sort_keys=True) + "\n")

    def anchors(self) -> list[dict]:
        if not os.path.exists(self._anchor_path):
            return []
        with open(self._anchor_path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]


class S3ObjectLockBackend(WormBackend):
    """Opt-in: S3 with Object-Lock (retention) for true WORM immutability.

    Requires `boto3` and a bucket created with Object-Lock enabled. Records are PUT under
    `records/{seq}.json` and anchors under `anchors/{n}.json`, each with a retention date so
    they cannot be overwritten or deleted until it passes. Lazily imported; never touched
    offline / in CI.
    """
    name = "s3-object-lock"

    def __init__(self, bucket: str, prefix: str = "aata", retain_days: int = 3650):
        import boto3                                             # lazy
        from datetime import datetime, timedelta, timezone
        self._s3 = boto3.client("s3")
        self._bucket = bucket
        self._prefix = prefix.rstrip("/")
        self._retain_until = datetime.now(timezone.utc) + timedelta(days=retain_days)

    def _key(self, kind: str, ident) -> str:
        return f"{self._prefix}/{kind}/{ident}"

    def _put(self, key: str, obj: dict) -> None:
        self._s3.put_object(
            Bucket=self._bucket, Key=key,
            Body=json.dumps(obj, sort_keys=True).encode(),
            ObjectLockMode="COMPLIANCE",
            ObjectLockRetainUntilDate=self._retain_until,
        )

    def put_record(self, seq: int, record: dict) -> None:
        key = self._key("records", f"{seq:08d}.json")
        # write-once: refuse if the object already exists
        try:
            self._s3.head_object(Bucket=self._bucket, Key=key)
            raise WormViolation(f"record seq={seq} already written (S3 Object-Lock)")
        except self._s3.exceptions.ClientError as e:            # 404 -> ok to write
            if e.response.get("Error", {}).get("Code") not in ("404", "NoSuchKey", "NotFound"):
                raise
        self._put(key, record)

    def get_record(self, seq: int) -> dict | None:
        try:
            obj = self._s3.get_object(Bucket=self._bucket, Key=self._key("records", f"{seq:08d}.json"))
            return json.loads(obj["Body"].read())
        except self._s3.exceptions.NoSuchKey:
            return None

    def all_records(self) -> list[dict]:
        keys = self._s3.list_objects_v2(Bucket=self._bucket, Prefix=self._key("records", ""))
        out = []
        for item in sorted(keys.get("Contents", []), key=lambda c: c["Key"]):
            obj = self._s3.get_object(Bucket=self._bucket, Key=item["Key"])
            out.append(json.loads(obj["Body"].read()))
        return out

    def put_anchor(self, merkle_root: str, meta: dict) -> None:
        n = len(self.anchors())
        self._put(self._key("anchors", f"{n:08d}.json"), {"merkle_root": merkle_root, **meta})

    def anchors(self) -> list[dict]:
        keys = self._s3.list_objects_v2(Bucket=self._bucket, Prefix=self._key("anchors", ""))
        out = []
        for item in sorted(keys.get("Contents", []), key=lambda c: c["Key"]):
            obj = self._s3.get_object(Bucket=self._bucket, Key=item["Key"])
            out.append(json.loads(obj["Body"].read()))
        return out


def enabled() -> bool:
    """True only if a real WORM backend is opted in and its client lib is importable."""
    which = os.getenv("AATA_WORM")
    if which == "s3":
        return importlib.util.find_spec("boto3") is not None
    return False


def worm_backend() -> WormBackend:
    """The configured backend: a real one if opted in + available, else in-memory."""
    if os.getenv("AATA_WORM") == "s3" and enabled():
        bucket = os.environ["AATA_WORM_S3_BUCKET"]
        return S3ObjectLockBackend(bucket, prefix=os.getenv("AATA_WORM_S3_PREFIX", "aata"))
    return InMemoryWormBackend()
