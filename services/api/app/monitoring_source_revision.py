from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from pathlib import Path


@dataclass(frozen=True)
class MonitoringSourceSnapshot:
    content: bytes
    _content_revision: str

    @property
    def cache_key(self) -> str:
        return self._content_revision


def read_monitoring_source(path: Path) -> MonitoringSourceSnapshot:
    source_path = Path(path).resolve(strict=True)
    for _ in range(2):
        before = source_path.stat()
        snapshot = _read_monitoring_source_cached(
            str(source_path),
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        after = source_path.stat()
        if _stat_key(before) == _stat_key(after):
            return snapshot
    raise OSError(f"monitoring source changed while it was read: {source_path.name}")


def public_monitoring_source_revision(
    listing_snapshot: MonitoringSourceSnapshot,
    protocol_snapshot: MonitoringSourceSnapshot,
    batch_context_id: str = "",
) -> str:
    digest = sha256()
    digest.update(b"monitoring-source-revision-v2\0")
    digest.update(listing_snapshot.cache_key.encode("ascii"))
    digest.update(b"\0")
    digest.update(protocol_snapshot.cache_key.encode("ascii"))
    digest.update(b"\0")
    digest.update(batch_context_id.strip().encode("utf-8"))
    return f"monsrcv_{digest.hexdigest()[:24]}"


@lru_cache(maxsize=64)
def _read_monitoring_source_cached(
    path: str,
    size_bytes: int,
    mtime_ns: int,
    ctime_ns: int,
) -> MonitoringSourceSnapshot:
    del size_bytes, mtime_ns, ctime_ns
    content = Path(path).read_bytes()
    return MonitoringSourceSnapshot(
        content=content,
        _content_revision=sha256(content).hexdigest(),
    )


def _stat_key(stat_result) -> tuple[int, int, int]:
    return (
        stat_result.st_size,
        stat_result.st_mtime_ns,
        stat_result.st_ctime_ns,
    )
