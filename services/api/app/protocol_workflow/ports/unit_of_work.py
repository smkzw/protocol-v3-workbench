"""Unit-of-work port for the Protocol v3 authority kernel.

The unit of work (UoW) owns transactional commit/rollback semantics and is the
*only* composition path through which the application service obtains
repository and artifact-store handles.  It enforces the design-section-18
invariant that canonical mutation and outbox enqueue commit in the same
transaction, so that either both are durable or neither is.

Boundary rule (design section 17.2 / 18): the repository and artifact handles
exposed by a UoW are *application-service dependencies*.  They MUST NOT appear
on ``NodeExecutionContract``, agent input/output, the harness runtime or any
worker surface.  Only the application service — never an agent — may open a UoW
and read/write through it.

The port is a ``typing.Protocol``: it prescribes no SQLite, PostgreSQL or
filesystem transaction behaviour.  Concrete adapters implement one
``UnitOfWork`` per storage backend (in-memory, SQLite, PostgreSQL, object
store, ...) and may share or isolate transactions across the repositories they
hand out.
"""

from __future__ import annotations

from typing import (
    Optional,
    Protocol,
    TypeVar,
    runtime_checkable,
)

from packages.contracts.workbench_contracts.protocol_v3 import (
    ProtocolV3Model,
)

from app.protocol_workflow.ports.artifacts import ArtifactStore
from app.protocol_workflow.ports.repositories import (
    CurrentAggregateRepository,
    EventStreamRepository,
    ExecutionReservationRepository,
    InboxRepository,
    OutboxRepository,
    ReadModelRepository,
    RevisionCasRepository,
)

__all__ = [
    "UnitOfWork",
    "IsolationContext",
    "UnitOfWorkClosedError",
]


#: Bound to the immutable Protocol v3 value-contract base, mirroring
#: :data:`app.protocol_workflow.ports.repositories.AggregateT`.
AggregateT = TypeVar("AggregateT", bound=ProtocolV3Model)


# ---------------------------------------------------------------------------
# Isolation context
# ---------------------------------------------------------------------------


class IsolationContext:
    """Marker base for transaction isolation scope.

    A concrete UoW adapter may subclass this to carry backend-specific
    isolation metadata (e.g. PostgreSQL snapshot identity, SQLite connection
    handle).  The base class deliberately carries nothing so the port stays
    storage-agnostic.  The application service never inspects its contents; it
    only threads it back into the UoW when asked.
    """

    __slots__ = ()


class UnitOfWorkClosedError(RuntimeError):
    """Raised when a mutator is reused after its UoW scope has closed."""


# ---------------------------------------------------------------------------
# Port — unit of work
# ---------------------------------------------------------------------------


@runtime_checkable
class UnitOfWork(Protocol):
    """Transactional scope bundling all Protocol v3 repositories.

    A UoW is opened, repositories are read/written through it, and then it is
    either committed or rolled back.  Once committed or rolled back, the
    transaction scope is closed and MUST NOT accept further mutations through
    that scope.  Whether an adapter keeps repository handles readable for
    deterministic post-commit inspection is adapter-specific; callers MUST NOT
    infer that such handles remain transaction-bound.  A concrete adapter MAY
    support reuse by resetting on a fresh ``__enter__``, but the port treats
    each commit/rollback as terminal for the current transaction scope.

    The repositories handed out by a single UoW share one transaction: a
    canonical CAS save and the corresponding outbox enqueue either commit
    together or roll back together (design section 18).

    The handles below are ``Optional`` only to express that a concrete adapter
    may scope a UoW to a subset of aggregates (e.g. a document-scoped UoW that
    does not touch reservations).  When a handle is non-``None``, it is the
    live, transaction-bound repository.  Application code SHOULD use the typed
    accessor helpers rather than reaching into the properties directly.
    """

    # -- repository handles --------------------------------------------------
    #
    # These are exposed to the *application service* as transaction-bound
    # dependencies.  They are deliberately NOT generic over aggregate type at
    # this level: a concrete adapter binds each property to the aggregate type
    # it persists (e.g. ``CurrentAggregateRepository[StudyDefinitionV3]``).
    # The application service obtains the correctly-typed handle and narrows
    # it at the call site.

    @property
    def study_definition_repository(
        self,
    ) -> Optional[CurrentAggregateRepository]:
        """Current-aggregate lookup for ``StudyDefinitionV3``, or ``None`` if
        this UoW scope does not cover it."""
        ...

    @property
    def study_definition_cas_repository(
        self,
    ) -> Optional[RevisionCasRepository]:
        """Revision CAS save for ``StudyDefinitionV3``, or ``None``."""
        ...

    @property
    def semantic_document_repository(
        self,
    ) -> Optional[CurrentAggregateRepository]:
        """Current-aggregate lookup for ``SemanticDocumentRevision``, or
        ``None``."""
        ...

    @property
    def semantic_document_cas_repository(
        self,
    ) -> Optional[RevisionCasRepository]:
        """Revision CAS save for ``SemanticDocumentRevision``, or ``None``."""
        ...

    @property
    def event_stream_repository(self) -> Optional[EventStreamRepository]:
        """Append-only event stream, or ``None`` if out of scope."""
        ...

    @property
    def outbox_repository(self) -> Optional[OutboxRepository]:
        """Transactional outbox, or ``None`` if out of scope."""
        ...

    @property
    def inbox_repository(self) -> Optional[InboxRepository]:
        """Idempotent inbox, or ``None`` if out of scope."""
        ...

    @property
    def reservation_repository(
        self,
    ) -> Optional[ExecutionReservationRepository]:
        """Execution reservations, or ``None`` if out of scope."""
        ...

    @property
    def read_model_repository(self) -> Optional[ReadModelRepository]:
        """Read-model projections, or ``None`` if out of scope."""
        ...

    @property
    def artifact_store(self) -> Optional[ArtifactStore]:
        """Content-addressed artifact store, or ``None`` if out of scope.

        Artifact writes are typically committed in their own content-addressed
        namespace (immutable by construction), but the decision to bind them
        into the relational transaction is adapter-specific.  The application
        service treats the returned store as the transaction-bound handle.
        """
        ...

    # -- transaction lifecycle ----------------------------------------------

    @property
    def is_active(self) -> bool:
        """Whether the caller is currently inside an open transaction scope.

        Application coordinators use this before the first write so a caller
        cannot accidentally perform part of an atomic mutation without the
        rollback boundary established by ``with uow:``.
        """
        ...

    def commit(self) -> None:
        """Atomically commit all repository mutations performed in this UoW.

        After commit, the transaction scope is closed.  An adapter may retain
        read-only handles for deterministic inspection, but application code
        must not issue further mutations through the closed scope.  On failure
        (e.g. CAS conflict detected at commit), the adapter rolls back
        and surfaces the originating repository-layer exception (e.g.
        :class:`~app.protocol_workflow.ports.repositories.RevisionConflictError`).
        """
        ...

    def rollback(self) -> None:
        """Roll back all repository mutations performed in this UoW.

        Idempotent: rolling back an already-rolled-back or committed UoW is a
        no-op.  After rollback, the transaction scope is closed; any handles
        retained by an adapter are inspection-only and no longer
        transaction-bound.
        """
        ...

    def __enter__(self) -> "UnitOfWork":
        """Enter the transactional scope and return ``self``.

        On a clean adapter, this begins the transaction.  A UoW SHOULD support
        nested ``with`` blocks within a single logical transaction by tracking
        depth, committing only when the outermost block exits.
        """
        ...

    def __exit__(self, exc_type, exc, tb) -> None:
        """Exit the transactional scope.

        If an exception propagated through the ``with`` body, roll back.
        Otherwise commit when the outermost scope exits.  Never swallows the
        exception (returns ``None`` / falsy).
        """
        ...
