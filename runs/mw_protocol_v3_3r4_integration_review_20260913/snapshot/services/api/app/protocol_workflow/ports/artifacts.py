"""Content-addressed artifact port for the Protocol v3 authority kernel.

Raw and derived files (investigator brochures, downloaded protocols, OCR/parse
output, translations, DOCX/PDF projections, ...) enter an *immutable,
content-addressed* artifact store.  The store is a staging side-effect surface,
never canonical clinical truth: only the immutable value contracts in
``packages.contracts.workbench_contracts.protocol_v3`` (``SourceArtifact``,
``ProjectionArtifact``, ...) and the append-only event stream hold canonical
identity.  The application service is responsible for promoting artifact
content into canonical contracts via the reducer.

Identity discipline (design section 6.1 / 18):

* ``logical_source_key`` + identical bytes replay to the *same immutable
  identity* — ``content_sha256`` is the content address, so replaying the same
  bytes under the same logical key returns the existing record unchanged.
* ``logical_source_key`` + *different* bytes creates a *new revision* under that
  logical key; prior revisions and their bytes are preserved and remain
  retrievable.  A logical key is never overwritten.

Returned metadata binds the logical key, the monotonically increasing revision,
the content SHA-256, the media type, the byte size and the creation time.  The
port is a ``typing.Protocol``: it prescribes no SQLite, PostgreSQL, object
storage or filesystem behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import (
    Optional,
    Protocol,
    Sequence,
    TypeVar,
    runtime_checkable,
)

from packages.contracts.workbench_contracts.protocol_v3 import (
    NonEmptyText,
    PositiveRevision,
    Sha256,
)

__all__ = [
    # records
    "ArtifactMetadata",
    "ArtifactRevision",
    # exceptions
    "ArtifactStoreError",
    "ArtifactNotFoundError",
    "ContentIntegrityError",
    # port
    "ArtifactStore",
]


# ---------------------------------------------------------------------------
# Immutable records
# ---------------------------------------------------------------------------


#: Bound for the raw bytes payload handled by the store.  ``bytes`` is the
#: canonical immutable container; implementations MUST NOT retain a reference to
#: a caller-supplied mutable buffer.
BytesT = TypeVar("BytesT", bound=bytes)


@dataclass(frozen=True)
class ArtifactMetadata:
    """Immutable identity + descriptor for one content-addressed revision.

    Every field is part of the binding that the application service audits when
    promoting artifact content into a canonical value contract.  The store
    guarantees that two writes with the same ``(logical_key, content_sha256)``
    yield structurally equal metadata (same revision, same size, same media
    type) — only ``created_at`` may differ across the two calls when the second
    is a replay, and even then a replay returns the *original* record unchanged.
    """

    logical_key: NonEmptyText
    revision: PositiveRevision
    content_sha256: Sha256
    media_type: NonEmptyText
    size_bytes: int
    created_at: datetime


@dataclass(frozen=True)
class ArtifactRevision:
    """A stored revision pair: descriptor + bytes.

    Returned by read operations that materialise content.  ``metadata`` binds
    the identity; ``content`` is the raw immutable bytes.
    """

    metadata: ArtifactMetadata
    content: bytes


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
#
# The artifact layer raises these lightweight, storage-agnostic exceptions.
# They carry the logical key and content identity context that disambiguates
# the failure.  The application service is responsible for translating them
# into the stable ``ProtocolWorkflowError`` types defined in
# ``protocol_workflow.errors``.


class ArtifactStoreError(RuntimeError):
    """Base class for all artifact-store failures.

    Carries the ``logical_key`` and, when relevant, the content SHA-256 so the
    application service can attach them to audit context.
    """

    __slots__ = ("logical_key", "content_sha256", "detail")

    def __init__(
        self,
        logical_key: str,
        *,
        content_sha256: Optional[str] = None,
        detail: str = "",
    ) -> None:
        self.logical_key = logical_key
        self.content_sha256 = content_sha256
        self.detail = detail
        label = f"logical_key={logical_key}"
        if content_sha256 is not None:
            label += f" content_sha256={content_sha256}"
        if detail:
            label += f" detail={detail}"
        super().__init__(label)


class ArtifactNotFoundError(ArtifactStoreError):
    """Raised when a read targets a logical key or revision that does not exist."""


class ContentIntegrityError(ArtifactStoreError):
    """Raised when stored bytes fail a content-address integrity check.

    A content-addressed store MUST be able to verify that the bytes retrieved
    for ``content_sha256`` hash to that same value.  Any mismatch is a storage
    corruption signal and surfaces here — it is never silently returned.
    """


# ---------------------------------------------------------------------------
# Port — content-addressed artifact store
# ---------------------------------------------------------------------------


@runtime_checkable
class ArtifactStore(Protocol):
    """Content-addressed, immutable, revisioned artifact storage.

    The store is addressed by ``logical_key`` (the stable source/projection
    identity, e.g. an IB source key or a DOCX projection key) and
    ``content_sha256`` (the SHA-256 of the raw bytes).  Writes are idempotent on
    content: the same logical key + same bytes always return the same
    ``ArtifactMetadata``; the same logical key + different bytes creates a new
    revision and preserves the prior content (design section 6.1 / 18).

    Implementations MUST be thread-compatible for single-process use; they need
    not be safe for concurrent multi-process access unless declared by the
    concrete adapter.
    """

    def store(
        self,
        logical_key: NonEmptyText,
        content: bytes,
        *,
        media_type: NonEmptyText,
        created_at: datetime,
    ) -> ArtifactMetadata:
        """Idempotently store ``content`` under ``logical_key``.

        If the logical key already holds the same ``content_sha256``, return the
        existing revision metadata unchanged (idempotent replay).  If the
        logical key exists with different bytes, create the next revision and
        return its metadata; prior revisions and their bytes are preserved.

        The implementation MUST compute ``content_sha256`` from ``content``
        itself — it is never trusted from the caller — and MUST NOT retain a
        reference to a caller-supplied mutable buffer.
        """
        ...

    def get_metadata(
        self,
        logical_key: NonEmptyText,
        *,
        revision: Optional[PositiveRevision] = None,
    ) -> ArtifactMetadata:
        """Return metadata for ``logical_key``.

        ``revision=None`` (the default) returns the *current* (highest) revision
        metadata.  A positive ``revision`` returns that historical revision.
        Raises :class:`ArtifactNotFoundError` if the logical key or revision
        does not exist.
        """
        ...

    def get_current_revision(
        self,
        logical_key: NonEmptyText,
    ) -> Optional[PositiveRevision]:
        """Return the current (highest) revision number, or ``None`` if the
        logical key has no revisions.

        This is the cheap probe used to decide whether a store call will create
        a new revision or replay idempotently.
        """
        ...

    def read(
        self,
        logical_key: NonEmptyText,
        *,
        revision: Optional[PositiveRevision] = None,
    ) -> ArtifactRevision:
        """Return the descriptor + bytes for ``logical_key``.

        ``revision=None`` returns the current revision.  Implementations MUST
        verify that the retrieved bytes hash to the recorded ``content_sha256``
        and raise :class:`ContentIntegrityError` on any mismatch.

        The returned ``content`` is the stored immutable copy; callers MAY
        mutate it without affecting the store.
        """
        ...

    def read_by_sha256(
        self,
        content_sha256: Sha256,
    ) -> ArtifactRevision:
        """Return the descriptor + bytes for a content address.

        Because the store is content-addressed, any SHA-256 that has been stored
        under *any* logical key is directly retrievable.  Raises
        :class:`ArtifactNotFoundError` if no bytes have ever been stored with
        that hash.  Because identical bytes may belong to several logical
        keys, the returned metadata is one deterministic retrieval binding,
        not unique provenance.  Callers that need a specific lineage MUST use
        ``read(logical_key, revision=...)`` or a canonical artifact reference.

        Implementations MUST verify the retrieved bytes hash to
        ``content_sha256``.
        """
        ...

    def list_revisions(
        self,
        logical_key: NonEmptyText,
    ) -> Sequence[ArtifactMetadata]:
        """Return all revisions for ``logical_key`` in ascending revision order.

        Returns an empty sequence if the logical key does not exist.  This is
        the lineage view used when promoting a specific revision into a
        canonical ``SourceArtifact`` / ``ProjectionArtifact`` contract.
        """
        ...

    def has_content(
        self,
        content_sha256: Sha256,
    ) -> bool:
        """Return ``True`` iff bytes with ``content_sha256`` have been stored.

        A cheap existence probe that avoids materialising content.
        """
        ...
