"""Local-filesystem content-addressed artifact store for Protocol v3.

This is a controlled local-filesystem implementation of
:class:`~app.protocol_workflow.ports.artifacts.ArtifactStore`.  It stores raw
bytes in a content-addressed layout (sharded by SHA-256 prefix) and records a
per-logical-key revision manifest.  It is a staging surface for raw/derived
files; it is NEVER canonical clinical truth.  Only the immutable value
contracts (``SourceArtifact``, ``ProjectionArtifact``, ...) and the append-only
event stream hold canonical identity (design section 5.2 / 6.1).

Identity discipline:

* ``logical_key`` + identical bytes replay to the same immutable identity
  (idempotent) — the content SHA-256 is the content address, computed by the
  store, never trusted from the caller.
* ``logical_key`` + different bytes creates a new revision under that logical
  key; prior revisions and their bytes are preserved.  A logical key is never
  overwritten.
* Returned :class:`ArtifactMetadata` binds logical key, revision, content
  SHA-256, media type, byte size and creation time.

The store verifies that bytes retrieved for a recorded ``content_sha256`` hash
to that value; any mismatch raises :class:`ContentIntegrityError`.  This is a
functional integrity check, not a security audit — it does not perform
adversarial path, symlink, TOCTOU, permission or malicious-input testing (those
are out of scope per the task risk boundaries).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from threading import RLock
from typing import Dict, List, Optional, Sequence

from app.protocol_workflow.ports.artifacts import (
    ArtifactMetadata,
    ArtifactNotFoundError,
    ArtifactRevision,
    ContentIntegrityError,
)

__all__ = ["LocalArtifactStore"]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest_name(logical_key: str) -> str:
    """Return a filesystem-safe manifest filename derived from ``logical_key``.

    The logical key is hashed (not used directly) so that arbitrary logical-key
    text maps to a stable, flat filename without filesystem path or length
    hazards.  This is a basic-correctness measure, not a security control.
    """
    digest = hashlib.sha256(logical_key.encode("utf-8")).hexdigest()
    return f"{digest}.json"


class LocalArtifactStore:
    """Local-filesystem content-addressed artifact store.

    Directory layout under ``root``::

        root/
          content/<sha[:2]>/<sha[2:]>      # raw bytes, sharded
          manifests/<sha-of-logical-key>.json  # revision manifest

    The content directory deduplicates identical bytes across logical keys
    (content addressing).  The manifest is a JSON object recording the ordered
    revision list for one logical key.
    """

    __slots__ = ("_root", "_content_dir", "_manifest_dir", "_lock")

    def __init__(self, root: str) -> None:
        if not isinstance(root, str) or not root:
            raise ValueError("root must be a non-empty string path")
        self._root = os.path.abspath(root)
        self._content_dir = os.path.join(self._root, "content")
        self._manifest_dir = os.path.join(self._root, "manifests")
        self._lock = RLock()
        os.makedirs(self._content_dir, exist_ok=True)
        os.makedirs(self._manifest_dir, exist_ok=True)

    # -- path helpers -------------------------------------------------------

    def _content_path(self, content_sha256: str) -> str:
        return os.path.join(self._content_dir, content_sha256[:2], content_sha256[2:])

    def _manifest_path(self, logical_key: str) -> str:
        return os.path.join(self._manifest_dir, _manifest_name(logical_key))

    # -- manifest I/O -------------------------------------------------------

    @staticmethod
    def _serialize_meta(meta: ArtifactMetadata) -> Dict[str, object]:
        return {
            "logical_key": meta.logical_key,
            "revision": meta.revision,
            "content_sha256": meta.content_sha256,
            "media_type": meta.media_type,
            "size_bytes": meta.size_bytes,
            "created_at": meta.created_at.isoformat(),
        }

    @staticmethod
    def _deserialize_meta(obj: Dict[str, object]) -> ArtifactMetadata:
        return ArtifactMetadata(
            logical_key=str(obj["logical_key"]),
            revision=int(obj["revision"]),
            content_sha256=str(obj["content_sha256"]),
            media_type=str(obj["media_type"]),
            size_bytes=int(obj["size_bytes"]),
            created_at=datetime.fromisoformat(str(obj["created_at"])),
        )

    def _read_manifest(self, logical_key: str) -> List[ArtifactMetadata]:
        path = self._manifest_path(logical_key)
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return [self._deserialize_meta(item) for item in payload["revisions"]]

    def _write_manifest(
        self, logical_key: str, revisions: List[ArtifactMetadata]
    ) -> None:
        path = self._manifest_path(logical_key)
        payload = {
            "logical_key": logical_key,
            "revisions": [self._serialize_meta(m) for m in revisions],
        }
        # Atomic write via temp file + replace.
        directory = os.path.dirname(path)
        fd, tmp_path = tempfile.mkstemp(prefix=".manifest-", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            os.replace(tmp_path, path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # -- content I/O --------------------------------------------------------

    def _write_content(self, content_sha256: str, content: bytes) -> None:
        path = self._content_path(content_sha256)
        if os.path.exists(path):
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".content-", dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
            os.replace(tmp_path, path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _read_content(self, content_sha256: str) -> bytes:
        path = self._content_path(content_sha256)
        if not os.path.exists(path):
            raise ArtifactNotFoundError("<by-sha>", content_sha256=content_sha256)
        with open(path, "rb") as handle:
            return handle.read()

    # -- ArtifactStore ------------------------------------------------------

    def store(
        self,
        logical_key: str,
        content: bytes,
        *,
        media_type: str,
        created_at: datetime,
    ) -> ArtifactMetadata:
        if not isinstance(content, (bytes, bytearray)):
            raise TypeError("content must be bytes")
        content = bytes(content)
        content_sha256 = _sha256(content)
        with self._lock:
            revisions = self._read_manifest(logical_key)
            for existing in revisions:
                if existing.content_sha256 == content_sha256:
                    return existing
            latest = revisions[-1] if revisions else None
            revision = (latest.revision + 1) if latest is not None else 1
            meta = ArtifactMetadata(
                logical_key=logical_key,
                revision=revision,
                content_sha256=content_sha256,
                media_type=media_type,
                size_bytes=len(content),
                created_at=created_at,
            )
            self._write_content(content_sha256, content)
            revisions.append(meta)
            self._write_manifest(logical_key, revisions)
            return meta

    def get_metadata(
        self,
        logical_key: str,
        *,
        revision: Optional[int] = None,
    ) -> ArtifactMetadata:
        with self._lock:
            revisions = self._read_manifest(logical_key)
            if not revisions:
                raise ArtifactNotFoundError(logical_key)
            if revision is None:
                return revisions[-1]
            for meta in revisions:
                if meta.revision == revision:
                    return meta
            raise ArtifactNotFoundError(
                logical_key, detail=f"revision {revision} not found"
            )

    def get_current_revision(self, logical_key: str) -> Optional[int]:
        with self._lock:
            revisions = self._read_manifest(logical_key)
            if not revisions:
                return None
            return revisions[-1].revision

    def read(
        self,
        logical_key: str,
        *,
        revision: Optional[int] = None,
    ) -> ArtifactRevision:
        with self._lock:
            meta = self.get_metadata(logical_key, revision=revision)
            content = self._read_content(meta.content_sha256)
            if _sha256(content) != meta.content_sha256:
                raise ContentIntegrityError(
                    logical_key, content_sha256=meta.content_sha256
                )
            return ArtifactRevision(metadata=meta, content=content)

    def read_by_sha256(self, content_sha256: str) -> ArtifactRevision:
        with self._lock:
            content = self._read_content(content_sha256)
            if _sha256(content) != content_sha256:
                raise ContentIntegrityError("<by-sha>", content_sha256=content_sha256)
            # Locate a stable metadata binding.  One content hash may be linked
            # to several logical keys, so make the scan deterministic rather
            # than depending on filesystem enumeration order.
            matches: List[ArtifactMetadata] = []
            for manifest_file in sorted(os.listdir(self._manifest_dir)):
                if not manifest_file.endswith(".json"):
                    continue
                path = os.path.join(self._manifest_dir, manifest_file)
                with open(path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                for item in payload["revisions"]:
                    meta = self._deserialize_meta(item)
                    if meta.content_sha256 == content_sha256:
                        matches.append(meta)
            if not matches:
                raise ContentIntegrityError("<by-sha>", content_sha256=content_sha256)
            meta = min(
                matches,
                key=lambda item: (item.created_at, item.logical_key, item.revision),
            )
            return ArtifactRevision(metadata=meta, content=content)

    def list_revisions(self, logical_key: str) -> Sequence[ArtifactMetadata]:
        with self._lock:
            return tuple(self._read_manifest(logical_key))

    def has_content(self, content_sha256: str) -> bool:
        with self._lock:
            return os.path.exists(self._content_path(content_sha256))
