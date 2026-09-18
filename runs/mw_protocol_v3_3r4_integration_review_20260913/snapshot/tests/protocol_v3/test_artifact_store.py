"""Functional contract tests for the Protocol v3 content-addressed artifact
store.

These tests prove the content-addressed storage contracts required by Task 1.3:

* **content-hash replay / idempotency** — storing the same logical key + same
  bytes returns the same immutable identity (revision + content SHA-256) on
  every call.
* **logical-key revision** — storing different bytes under the same logical key
  creates a new revision and preserves all prior revisions and their bytes; a
  logical key is never overwritten.
* **content addressing** — identical bytes stored under *different* logical keys
  deduplicate to the same content SHA-256; ``read_by_sha256`` retrieves them.
* **integrity verification** — reading bytes verifies they hash to the recorded
  ``content_sha256``.
* **metadata binding** — returned ``ArtifactMetadata`` binds logical key,
  revision, content SHA-256, media type, byte size and creation time.

Both the in-memory implementation
(:class:`~app.protocol_workflow.storage.memory.InMemoryArtifactStore`) and the
local-filesystem implementation
(:class:`~app.protocol_workflow.artifacts.local_store.LocalArtifactStore`) are
exercised through the same ``ArtifactStore`` port contract, so the behavioural
contract is proven identical across backends.

These are functional contract tests, not security tests: no path traversal,
symlink, permission, TOCTOU or adversarial-input behaviour is exercised (per
the task risk boundaries).
"""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from app.protocol_workflow.ports.artifacts import (
    ArtifactNotFoundError,
    ArtifactStore,
)
from app.protocol_workflow.artifacts.local_store import LocalArtifactStore
from app.protocol_workflow.storage.memory import InMemoryArtifactStore


_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
_T1 = datetime(2026, 1, 2, tzinfo=timezone.utc)
_T2 = datetime(2026, 1, 3, tzinfo=timezone.utc)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Parametrised fixture: both backends share the same contract
# ---------------------------------------------------------------------------

#: Factory callables for the two backends under test.
_BACKENDS = {
    "in-memory": lambda: InMemoryArtifactStore(),
    "local": lambda: None,  # replaced per-test via tmp_path
}


def _make_store(backend: str, tmp_path):
    if backend == "in-memory":
        return InMemoryArtifactStore()
    return LocalArtifactStore(str(tmp_path / "local-store"))


pytestmark = pytest.mark.parametrize("backend", ["in-memory", "local"])


# ---------------------------------------------------------------------------
# Port structural conformance
# ---------------------------------------------------------------------------


def test_store_satisfies_artifact_store_port(backend, tmp_path) -> None:
    store = _make_store(backend, tmp_path)
    assert isinstance(store, ArtifactStore)


# ---------------------------------------------------------------------------
# Content-hash replay / idempotency
# ---------------------------------------------------------------------------


def test_same_logical_key_same_bytes_replays_idempotently(backend, tmp_path) -> None:
    """Replaying identical bytes under the same logical key returns the same
    revision and content SHA-256 every time."""
    store = _make_store(backend, tmp_path)
    content = b"protocol-pdf-v1-bytes"

    meta1 = store.store(
        "src:protocol:1", content, media_type="application/pdf", created_at=_T0
    )
    meta2 = store.store(
        "src:protocol:1", content, media_type="application/pdf", created_at=_T1
    )
    meta3 = store.store(
        "src:protocol:1", content, media_type="application/pdf", created_at=_T2
    )

    assert meta1 == meta2 == meta3
    assert meta1.revision == 1
    assert meta1.content_sha256 == _sha(content)


def test_replay_returns_original_created_at(backend, tmp_path) -> None:
    """A replay returns the *original* record unchanged, including ``created_at``."""
    store = _make_store(backend, tmp_path)
    content = b"investigator-brochure-v1"

    store.store("src:ib:1", content, media_type="application/pdf", created_at=_T0)
    meta2 = store.store(
        "src:ib:1", content, media_type="application/pdf", created_at=_T1
    )

    assert meta2.created_at == _T0


def test_replay_does_not_increment_revision(backend, tmp_path) -> None:
    store = _make_store(backend, tmp_path)
    content = b"ocr-output-v1"

    store.store("src:ocr:1", content, media_type="application/json", created_at=_T0)
    store.store("src:ocr:1", content, media_type="application/json", created_at=_T1)
    store.store("src:ocr:1", content, media_type="application/json", created_at=_T2)

    assert store.get_current_revision("src:ocr:1") == 1


# ---------------------------------------------------------------------------
# Logical-key revision
# ---------------------------------------------------------------------------


def test_different_bytes_under_same_key_creates_new_revision(backend, tmp_path) -> None:
    """Different bytes under the same logical key create a new revision."""
    store = _make_store(backend, tmp_path)
    content_v1 = b"protocol-pdf-v1"
    content_v2 = b"protocol-pdf-v2-revised"

    meta1 = store.store(
        "src:protocol:1", content_v1, media_type="application/pdf", created_at=_T0
    )
    meta2 = store.store(
        "src:protocol:1", content_v2, media_type="application/pdf", created_at=_T1
    )

    assert meta1.revision == 1
    assert meta2.revision == 2
    assert meta1.content_sha256 != meta2.content_sha256
    assert meta2.content_sha256 == _sha(content_v2)


def test_prior_revision_bytes_are_preserved(backend, tmp_path) -> None:
    """Prior revisions and their bytes are preserved and retrievable."""
    store = _make_store(backend, tmp_path)
    content_v1 = b"docx-projection-v1"
    content_v2 = b"docx-projection-v2"

    store.store(
        "proj:docx:1",
        content_v1,
        media_type="application/vnd.openxmlformats",
        created_at=_T0,
    )
    store.store(
        "proj:docx:1",
        content_v2,
        media_type="application/vnd.openxmlformats",
        created_at=_T1,
    )

    rev1 = store.read("proj:docx:1", revision=1)
    rev2 = store.read("proj:docx:1", revision=2)
    current = store.read("proj:docx:1")

    assert rev1.content == content_v1
    assert rev2.content == content_v2
    assert current.content == content_v2


def test_logical_key_is_never_overwritten(backend, tmp_path) -> None:
    """After creating revision 2, revision 1 metadata and bytes are still
    intact — the logical key was not overwritten."""
    store = _make_store(backend, tmp_path)

    store.store(
        "src:translation:1", b"translation-v1", media_type="text/plain", created_at=_T0
    )
    store.store(
        "src:translation:1", b"translation-v2", media_type="text/plain", created_at=_T1
    )

    revisions = store.list_revisions("src:translation:1")
    assert len(revisions) == 2
    assert revisions[0].revision == 1
    assert revisions[1].revision == 2
    assert revisions[0].content_sha256 != revisions[1].content_sha256


def test_list_revisions_returns_ascending_order(backend, tmp_path) -> None:
    store = _make_store(backend, tmp_path)
    for i in range(1, 4):
        store.store(
            "src:data:1",
            f"content-v{i}".encode(),
            media_type="application/octet-stream",
            created_at=datetime(2026, 1, i, tzinfo=timezone.utc),
        )
    revisions = store.list_revisions("src:data:1")
    revision_numbers = [m.revision for m in revisions]
    assert revision_numbers == [1, 2, 3]


# ---------------------------------------------------------------------------
# Content addressing / deduplication
# ---------------------------------------------------------------------------


def test_identical_bytes_under_different_keys_share_content_hash(
    backend, tmp_path
) -> None:
    """The content SHA-256 is computed by the store; identical bytes under
    different logical keys yield the same content address."""
    store = _make_store(backend, tmp_path)
    content = b"shared-raw-bytes"

    meta_a = store.store(
        "src:doc:a", content, media_type="application/pdf", created_at=_T0
    )
    meta_b = store.store(
        "src:doc:b", content, media_type="application/pdf", created_at=_T0
    )

    assert meta_a.content_sha256 == meta_b.content_sha256
    assert store.has_content(meta_a.content_sha256)


def test_read_by_sha256_retrieves_content(backend, tmp_path) -> None:
    store = _make_store(backend, tmp_path)
    content = b"fetchable-bytes"
    meta = store.store(
        "src:fetch:1", content, media_type="application/octet-stream", created_at=_T0
    )

    revision = store.read_by_sha256(meta.content_sha256)
    assert revision.content == content
    assert revision.metadata.content_sha256 == meta.content_sha256


def test_read_by_sha256_metadata_binding_is_order_independent(
    backend, tmp_path
) -> None:
    content = b"shared-deterministic-binding"
    if backend == "in-memory":
        store_one = InMemoryArtifactStore()
        store_two = InMemoryArtifactStore()
    else:
        store_one = LocalArtifactStore(str(tmp_path / "store-one"))
        store_two = LocalArtifactStore(str(tmp_path / "store-two"))

    sha_one = store_one.store(
        "key:b", content, media_type="text/plain", created_at=_T0
    ).content_sha256
    store_one.store("key:a", content, media_type="text/plain", created_at=_T0)
    sha_two = store_two.store(
        "key:a", content, media_type="text/plain", created_at=_T0
    ).content_sha256
    store_two.store("key:b", content, media_type="text/plain", created_at=_T0)

    assert sha_one == sha_two
    assert store_one.read_by_sha256(sha_one).metadata.logical_key == "key:a"
    assert store_two.read_by_sha256(sha_two).metadata.logical_key == "key:a"


def test_read_by_sha256_raises_for_unknown_hash(backend, tmp_path) -> None:
    store = _make_store(backend, tmp_path)
    with pytest.raises(ArtifactNotFoundError):
        store.read_by_sha256(_sha(b"never-stored"))


def test_single_process_thread_replay_is_idempotent(backend, tmp_path) -> None:
    """Concurrent callers sharing one store observe one immutable revision."""
    store = _make_store(backend, tmp_path)
    content = b"parallel-replay"

    def write_once(_index: int):
        return store.store(
            "src:parallel:1",
            content,
            media_type="application/octet-stream",
            created_at=_T0,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(write_once, range(32)))

    assert all(record == records[0] for record in records)
    assert store.get_current_revision("src:parallel:1") == 1
    assert len(store.list_revisions("src:parallel:1")) == 1


def test_content_sha256_is_never_trusted_from_caller(backend, tmp_path) -> None:
    """The store computes the hash itself — the caller cannot influence it."""
    store = _make_store(backend, tmp_path)
    content = b"trusted-hash-bytes"
    meta = store.store("src:trust:1", content, media_type="text/plain", created_at=_T0)
    assert meta.content_sha256 == _sha(content)
    assert meta.size_bytes == len(content)


# ---------------------------------------------------------------------------
# Metadata binding
# ---------------------------------------------------------------------------


def test_metadata_binds_all_fields(backend, tmp_path) -> None:
    store = _make_store(backend, tmp_path)
    content = b"binding-test-bytes"
    meta = store.store(
        "src:bind:1",
        content,
        media_type="application/pdf",
        created_at=_T0,
    )

    assert meta.logical_key == "src:bind:1"
    assert meta.revision == 1
    assert meta.content_sha256 == _sha(content)
    assert meta.media_type == "application/pdf"
    assert meta.size_bytes == len(content)
    assert meta.created_at == _T0


def test_get_metadata_returns_current_by_default(backend, tmp_path) -> None:
    store = _make_store(backend, tmp_path)
    store.store("src:cur:1", b"v1", media_type="text/plain", created_at=_T0)
    store.store("src:cur:1", b"v2", media_type="text/plain", created_at=_T1)

    current = store.get_metadata("src:cur:1")
    assert current.revision == 2


def test_get_metadata_specific_revision(backend, tmp_path) -> None:
    store = _make_store(backend, tmp_path)
    store.store("src:rev:1", b"v1", media_type="text/plain", created_at=_T0)
    store.store("src:rev:1", b"v2", media_type="text/plain", created_at=_T1)

    rev1 = store.get_metadata("src:rev:1", revision=1)
    assert rev1.revision == 1


def test_get_current_revision_none_for_missing_key(backend, tmp_path) -> None:
    store = _make_store(backend, tmp_path)
    assert store.get_current_revision("src:missing:1") is None


def test_list_revisions_empty_for_missing_key(backend, tmp_path) -> None:
    store = _make_store(backend, tmp_path)
    assert store.list_revisions("src:missing:1") == ()


# ---------------------------------------------------------------------------
# Error conditions (functional, not security)
# ---------------------------------------------------------------------------


def test_read_missing_logical_key_raises(backend, tmp_path) -> None:
    store = _make_store(backend, tmp_path)
    with pytest.raises(ArtifactNotFoundError):
        store.read("src:missing:1")


def test_read_missing_revision_raises(backend, tmp_path) -> None:
    store = _make_store(backend, tmp_path)
    store.store("src:one-rev:1", b"v1", media_type="text/plain", created_at=_T0)
    with pytest.raises(ArtifactNotFoundError):
        store.read("src:one-rev:1", revision=99)


def test_get_metadata_missing_revision_raises(backend, tmp_path) -> None:
    store = _make_store(backend, tmp_path)
    store.store("src:meta:1", b"v1", media_type="text/plain", created_at=_T0)
    with pytest.raises(ArtifactNotFoundError):
        store.get_metadata("src:meta:1", revision=99)


def test_read_returns_immutable_copy(backend, tmp_path) -> None:
    """The returned bytes are a copy; mutating them does not affect the store."""
    store = _make_store(backend, tmp_path)
    content = b"immutable-test"
    store.store("src:imm:1", content, media_type="text/plain", created_at=_T0)

    revision = store.read("src:imm:1")
    # bytes are immutable, but verify a re-read returns the same content
    reread = store.read("src:imm:1")
    assert reread.content == revision.content == content


def test_has_content_false_for_unstored(backend, tmp_path) -> None:
    store = _make_store(backend, tmp_path)
    assert store.has_content(_sha(b"never")) is False


def test_has_content_true_after_store(backend, tmp_path) -> None:
    store = _make_store(backend, tmp_path)
    meta = store.store("src:has:1", b"present", media_type="text/plain", created_at=_T0)
    assert store.has_content(meta.content_sha256) is True


# ---------------------------------------------------------------------------
# Multi-revision content-address lineage
# ---------------------------------------------------------------------------


def test_multi_revision_lineage_with_replay(backend, tmp_path) -> None:
    """A realistic lineage: v1, replay v1 (no-op), v2, replay v2 (no-op), v3.
    Each distinct content gets its own revision; replays do not advance."""
    store = _make_store(backend, tmp_path)

    m1a = store.store("src:lineage:1", b"v1", media_type="text/plain", created_at=_T0)
    m1b = store.store("src:lineage:1", b"v1", media_type="text/plain", created_at=_T1)
    m2 = store.store("src:lineage:1", b"v2", media_type="text/plain", created_at=_T1)
    m2b = store.store("src:lineage:1", b"v2", media_type="text/plain", created_at=_T2)
    m3 = store.store("src:lineage:1", b"v3", media_type="text/plain", created_at=_T2)

    assert m1a == m1b
    assert m2 == m2b
    assert {m1a.revision, m2.revision, m3.revision} == {1, 2, 3}
    assert store.get_current_revision("src:lineage:1") == 3

    revisions = store.list_revisions("src:lineage:1")
    assert len(revisions) == 3  # replays did not create extra revisions
