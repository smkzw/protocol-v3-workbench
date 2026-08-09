from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping, Optional


FIELD_PROFILE_CACHE_MANIFEST_VERSION = (
    "monitoring_ai_field_profile_cache_manifest_v1"
)
FIELD_PROFILE_CACHE_KEY_VERSION = "monitoring_ai_field_profile_cache_key_v1"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class FieldProfileCacheLookup:
    status: str
    cache_key: str
    reason_code: str
    snapshot_payload: Optional[dict[str, Any]] = None

    @property
    def hit(self) -> bool:
        return self.status == "hit" and self.snapshot_payload is not None


class MonitoringFieldProfileCache:
    """Content-addressed, integrity-checked field-profile snapshot cache."""

    def __init__(self, root: Path):
        self.root = Path(root)

    @staticmethod
    def cache_key(
        *,
        batch_identity: Mapping[str, Any],
        profiler_contract: Mapping[str, Any],
    ) -> str:
        return _payload_sha256(
            {
                "cache_key_version": FIELD_PROFILE_CACHE_KEY_VERSION,
                "batch_identity": dict(batch_identity),
                "profiler_contract": dict(profiler_contract),
            }
        )

    def load(
        self,
        *,
        batch_identity: Mapping[str, Any],
        profiler_contract: Mapping[str, Any],
    ) -> FieldProfileCacheLookup:
        cache_key = self.cache_key(
            batch_identity=batch_identity,
            profiler_contract=profiler_contract,
        )
        manifest_path, snapshot_path = self._paths(cache_key)
        if not manifest_path.is_file() or not snapshot_path.is_file():
            return FieldProfileCacheLookup(
                status="miss",
                cache_key=cache_key,
                reason_code="cache_entry_absent",
            )
        try:
            manifest_bytes = manifest_path.read_bytes()
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            if not isinstance(manifest, dict):
                raise ValueError("cache manifest is not an object")
            manifest_sha256 = _required_sha256(
                manifest.pop("manifest_sha256", None),
                "manifest_sha256",
            )
            if manifest_sha256 != _payload_sha256(manifest):
                raise ValueError("cache manifest digest mismatch")
            if (
                manifest.get("manifest_version")
                != FIELD_PROFILE_CACHE_MANIFEST_VERSION
            ):
                raise ValueError("cache manifest version mismatch")
            if manifest.get("cache_key") != cache_key:
                raise ValueError("cache key mismatch")
            if manifest.get("batch_identity") != dict(batch_identity):
                raise ValueError("cache batch identity mismatch")
            if manifest.get("profiler_contract") != dict(profiler_contract):
                raise ValueError("cache profiler contract mismatch")

            snapshot_bytes = snapshot_path.read_bytes()
            if int(manifest.get("snapshot_size_bytes", -1)) != len(snapshot_bytes):
                raise ValueError("cache snapshot size mismatch")
            snapshot_sha256 = _required_sha256(
                manifest.get("snapshot_sha256"),
                "snapshot_sha256",
            )
            if snapshot_sha256 != sha256(snapshot_bytes).hexdigest():
                raise ValueError("cache snapshot digest mismatch")
            snapshot = json.loads(snapshot_bytes.decode("utf-8"))
            if not isinstance(snapshot, dict):
                raise ValueError("cache snapshot is not an object")
            snapshot_profile_sha256 = _required_sha256(
                snapshot.get("profile_sha256"),
                "profile_sha256",
            )
            manifest_profile_sha256 = _required_sha256(
                manifest.get("profile_sha256"),
                "manifest.profile_sha256",
            )
            if snapshot_profile_sha256 != manifest_profile_sha256:
                raise ValueError("cache profile digest binding mismatch")
            snapshot_input_sha256 = _required_sha256(
                snapshot.get("input_sha256"),
                "input_sha256",
            )
            manifest_input_sha256 = _required_sha256(
                manifest.get("input_sha256"),
                "manifest.input_sha256",
            )
            if snapshot_input_sha256 != manifest_input_sha256:
                raise ValueError("cache input digest binding mismatch")
            return FieldProfileCacheLookup(
                status="hit",
                cache_key=cache_key,
                reason_code="cache_entry_verified",
                snapshot_payload=snapshot,
            )
        except (
            json.JSONDecodeError,
            OSError,
            TypeError,
            UnicodeDecodeError,
            ValueError,
        ):
            return FieldProfileCacheLookup(
                status="invalid",
                cache_key=cache_key,
                reason_code="cache_integrity_validation_failed",
            )

    def store(
        self,
        *,
        batch_identity: Mapping[str, Any],
        profiler_contract: Mapping[str, Any],
        snapshot_payload: Mapping[str, Any],
    ) -> str:
        cache_key = self.cache_key(
            batch_identity=batch_identity,
            profiler_contract=profiler_contract,
        )
        snapshot = dict(snapshot_payload)
        profile_sha256 = _required_sha256(
            snapshot.get("profile_sha256"),
            "profile_sha256",
        )
        input_sha256 = _required_sha256(
            snapshot.get("input_sha256"),
            "input_sha256",
        )
        snapshot_bytes = _canonical_json(snapshot).encode("utf-8")
        manifest = {
            "manifest_version": FIELD_PROFILE_CACHE_MANIFEST_VERSION,
            "cache_key_version": FIELD_PROFILE_CACHE_KEY_VERSION,
            "cache_key": cache_key,
            "batch_identity": dict(batch_identity),
            "profiler_contract": dict(profiler_contract),
            "profile_sha256": profile_sha256,
            "input_sha256": input_sha256,
            "snapshot_sha256": sha256(snapshot_bytes).hexdigest(),
            "snapshot_size_bytes": len(snapshot_bytes),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        manifest["manifest_sha256"] = _payload_sha256(manifest)
        manifest_bytes = _canonical_json(manifest).encode("utf-8")

        manifest_path, snapshot_path = self._paths(cache_key)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(snapshot_path, snapshot_bytes)
        _atomic_write(manifest_path, manifest_bytes)
        return cache_key

    def _paths(self, cache_key: str) -> tuple[Path, Path]:
        entry_root = self.root / cache_key[:2] / cache_key
        return entry_root / "manifest.json", entry_root / "snapshot.json"


def _atomic_write(path: Path, payload: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=str(path.parent),
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary_path.unlink(missing_ok=True)


def _required_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field} must be a SHA-256 digest")
    return value


def _payload_sha256(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
