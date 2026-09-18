"""Selected storage surface for the Protocol v3 authority kernel — Task 1.8.

This module is the storage-neutral selection / factory / capabilities surface
locked by the Task 1.8 decision record
(``pocs/protocol_v3/storage/decision.md``).  It answers three questions for
domain and application consumers:

* **selection** — :func:`get_selected_storage` returns the frozen backend
  identity, version gate, licence and evidence digests;
* **capabilities** — :class:`StorageCapabilities` declares, per backend, which
  operations are supported (durability, backup/restore, crash recovery,
  rollback, migration accounting, cross-process, true concurrent writers,
  RPO 0) and fails closed on any required capability that is not supported;
* **factory** — :func:`create_unit_of_work_factory` builds a unit-of-work
  factory for exactly the selected backend, or fails closed.

Boundary rules (identical for every backend):

* no driver imports, no SQL text and no journal-file semantics live here —
  those are adapter-internal and never visible to consumers;
* the PoC modules under ``pocs/`` are evidence, never a runtime dependency;
* there is no fallback: the production factory never switches backend and
  never degrades to the in-memory implementation.  Memory is reachable only
  through the explicitly named test route
  :func:`create_test_memory_unit_of_work_factory`.

Product activation is explicit (Task 1R.1): the product adapter for the
selected backend is wired through
:func:`create_product_unit_of_work_factory` — the ONLY route that supplies
the real builder.  The storage-neutral :func:`create_unit_of_work_factory`
keeps its injection hook and still fails closed with
:class:`StorageNotReadyError` when no builder is supplied, and memory stays
reachable only through :func:`create_test_memory_unit_of_work_factory`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, Mapping, Optional, Protocol, Tuple

if TYPE_CHECKING:
    from app.protocol_workflow.ports.unit_of_work import UnitOfWork

from app.protocol_workflow.storage.sqlite import (
    build_unit_of_work_factory as _product_sqlite_builder,
)

__all__ = [
    "AdapterBuilder",
    "BackendRoles",
    "SelectedStorage",
    "StorageCapabilities",
    "StorageCapabilityError",
    "StorageConfigurationError",
    "StorageNotReadyError",
    "StorageSelectionError",
    "UnitOfWorkFactory",
    "create_product_unit_of_work_factory",
    "create_test_memory_unit_of_work_factory",
    "create_unit_of_work_factory",
    "get_selected_storage",
    "readiness_report",
]

# ---------------------------------------------------------------------------
# Selection identity — frozen at decision time (2026-08-11)
# ---------------------------------------------------------------------------

#: Backend selected for the local/private deployment target.
SELECTED_BACKEND: str = "sqlite"

#: Candidate identity recorded in the accepted PoC evidence.
SELECTED_CANDIDATE_IDENTITY: str = "sqlite_3_53_1"

#: Engine version linked into the eligible runtime at decision time.
SELECTED_ENGINE_NAME: str = "SQLite"
SELECTED_ENGINE_VERSION: str = "3.53.1"

#: Minimum linked engine version (the multi-connection reset defect is fixed
#: upstream in 3.51.3+; official SQLite documentation notes it may also affect
#: earlier versions, so the gate requires >= 3.51.3 rather than enumerating
#: affected versions).  The concrete adapter enforces this gate fail-closed;
#: this surface exposes it as declarative metadata.
SELECTED_MIN_ENGINE_VERSION: Tuple[int, int, int] = (3, 51, 3)

#: Driver and licence recorded in the decision record.
SELECTED_DRIVER: str = "stdlib sqlite3 (Python 3.12)"
SELECTED_LICENSE: str = "public domain (SQLite)"

#: Decision record path (relative to the repository root).
DECISION_PATH: str = "pocs/protocol_v3/storage/decision.md"

#: Deterministic digests of the two accepted PoC candidates
#: (``pocs/protocol_v3/storage/results/*_candidate.json``).  The digests differ
#: only because the candidate name participates in the digest payload; the
#: eight deterministic invariant bodies are byte-equal across candidates.
SELECTED_EVIDENCE_DIGESTS: Dict[str, str] = {
    "sqlite": "64a56f66e4300b318f6586803151f475e2ad8de9a74d0acfad14fe46a81adad8",
    "postgresql": "fce59b62be3dc94d069affe9c76cdd0d9f41e8340459cb9fc9336ff96fde8630",
}


#: Human-readable role of every known backend.
BackendRoles: Dict[str, str] = {
    "sqlite": "selected target for the local/private deployment",
    "postgresql": "not selected; accepted PoC candidate retained as the documented scale-up path (evidence only)",
    "memory": "test/reference only; reachable exclusively via create_test_memory_unit_of_work_factory",
}


# ---------------------------------------------------------------------------
# Exceptions — fail closed
# ---------------------------------------------------------------------------


class StorageSelectionError(RuntimeError):
    """Base class for selection/factory failures."""


class StorageConfigurationError(StorageSelectionError):
    """Raised when configuration is absent, empty or declares an unknown backend."""


class StorageNotReadyError(StorageSelectionError):
    """Raised when the selected backend cannot be constructed (product
    adapter not wired, or the builder returned no factory)."""


class StorageCapabilityError(StorageSelectionError):
    """Raised when a required capability is not supported by the selected backend."""


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StorageCapabilities:
    """Declarative, evidence-backed capability record for the selected backend.

    All booleans are bound to the accepted Task 1.8 PoC evidence (see the
    decision record).  ``concurrent_writers`` is ``False`` for SQLite because
    the accepted evidence proves a correct single-writer serialized model
    (zero lost/duplicate effects at 8 writers) rather than true MVCC.
    """

    #: Committed mutations survive process death (fsync-on-commit discipline).
    durable: bool = True
    #: Online backup then restore to a fresh store reproduces exact state.
    backup_restore: bool = True
    #: A killed writer leaves committed events replayable with RPO 0.
    crash_recovery: bool = True
    #: Restoring a pre-switch snapshot reverts state exactly.
    rollback_to_snapshot: bool = True
    #: Migration accounting is 100% with explicit quarantine for unmappables.
    migration_accounting: bool = True
    #: Multiple processes may open the store concurrently (single writer).
    cross_process: bool = True
    #: True MVCC with concurrent writers (PostgreSQL); False = single-writer
    #: serialized but correct (SQLite).
    concurrent_writers: bool = False
    #: Committed-event recovery point objective is zero.
    rpo_zero: bool = True

    def require(self, *capabilities: str) -> None:
        """Fail closed if any named capability is not supported.

        Unknown capability names raise :class:`StorageConfigurationError`
        rather than silently passing.
        """
        for name in capabilities:
            if name not in self.__dataclass_fields__:
                raise StorageConfigurationError(f"unknown capability {name!r}")
            if not getattr(self, name):
                raise StorageCapabilityError(
                    f"capability {name!r} is not supported by the selected backend"
                )


# ---------------------------------------------------------------------------
# Selection record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SelectedStorage:
    """Frozen storage selection locked by the Task 1.8 decision record."""

    backend: str
    candidate_identity: str
    engine_name: str
    engine_version: str
    min_engine_version: Tuple[int, int, int]
    driver: str
    license: str
    decision_path: str
    evidence_digests: Mapping[str, str]
    capabilities: StorageCapabilities

    def require(self, *capabilities: str) -> None:
        """Convenience guard: fail closed unless all named capabilities hold."""
        self.capabilities.require(*capabilities)


_SELECTED: Optional[SelectedStorage] = None


def get_selected_storage() -> SelectedStorage:
    """Return the frozen storage selection for Protocol v3 (Task 1.8)."""
    global _SELECTED
    if _SELECTED is None:
        _SELECTED = SelectedStorage(
            backend=SELECTED_BACKEND,
            candidate_identity=SELECTED_CANDIDATE_IDENTITY,
            engine_name=SELECTED_ENGINE_NAME,
            engine_version=SELECTED_ENGINE_VERSION,
            min_engine_version=SELECTED_MIN_ENGINE_VERSION,
            driver=SELECTED_DRIVER,
            license=SELECTED_LICENSE,
            decision_path=DECISION_PATH,
            evidence_digests=dict(SELECTED_EVIDENCE_DIGESTS),
            capabilities=StorageCapabilities(),
        )
    return _SELECTED


# ---------------------------------------------------------------------------
# Factory — fail closed, no fallback
# ---------------------------------------------------------------------------


class UnitOfWorkFactory(Protocol):
    """Callable that opens a fresh, ready-to-use unit of work."""

    def __call__(self) -> "UnitOfWork": ...


#: Product wiring hook: builds the concrete adapter factory for a backend
#: from its configuration (e.g. ``{"backend": "sqlite", "path": "..."}``).
AdapterBuilder = Callable[[Mapping[str, Any]], Optional[UnitOfWorkFactory]]


def create_unit_of_work_factory(
    *,
    config: Optional[Mapping[str, Any]] = None,
    adapter_builder: Optional[AdapterBuilder] = None,
) -> UnitOfWorkFactory:
    """Return a unit-of-work factory for the SELECTED backend, fail closed.

    * ``config`` MUST declare the backend (``{"backend": "sqlite", ...}``).
      Absent or empty config raises :class:`StorageConfigurationError`; there
      is no default backend.
    * An unknown backend raises :class:`StorageConfigurationError`; any
      known-but-not-selected backend raises :class:`StorageSelectionError` —
      the surface never switches and never falls back (memory is test-only;
      the PostgreSQL candidate is retained as evidence, not as an activation
      path).
    * ``adapter_builder`` is the injection hook.  When no builder is
      supplied — i.e. everywhere except the explicit product route
      :func:`create_product_unit_of_work_factory` — this function raises
      :class:`StorageNotReadyError` with the exact blocker.  The PoC adapters
      under ``pocs/`` are evidence and must not be imported by product code.
    * A builder that returns ``None`` is treated as not ready (fail closed).
    """
    if not config:
        raise StorageConfigurationError(
            "storage config is required; there is no default backend"
        )
    backend = config.get("backend")
    if not isinstance(backend, str) or not backend:
        raise StorageConfigurationError("config must declare a non-empty 'backend'")
    if backend not in BackendRoles:
        raise StorageConfigurationError(
            f"unknown backend {backend!r}; known backends: {sorted(BackendRoles)}"
        )
    if backend != SELECTED_BACKEND:
        raise StorageSelectionError(
            f"backend {backend!r} is not the selected storage "
            f"{SELECTED_BACKEND!r}; no fallback or automatic switch is permitted"
        )
    if adapter_builder is None:
        raise StorageNotReadyError(
            "selected storage is not yet activated through this call: no "
            "adapter builder was supplied. Product route: use "
            "create_product_unit_of_work_factory (wired to the real builder "
            "in services/api/app/protocol_workflow/storage/sqlite.py), or "
            "pass that builder via adapter_builder. The PoC adapters under "
            "pocs/ are evidence only and must not be imported by product "
            "code. Codex follow-up: the 1R.2 composition-root switch remains "
            "the activation gate. Engine version gate >= "
            f"{'.'.join(map(str, SELECTED_MIN_ENGINE_VERSION))}, durable "
            "commit discipline, CAS/outbox/backup."
        )
    factory = adapter_builder(config)
    if factory is None:
        raise StorageNotReadyError(
            f"adapter builder for {SELECTED_BACKEND!r} returned no factory; "
            "product activation remains fail-closed"
        )
    return factory


def create_product_unit_of_work_factory(
    *,
    config: Optional[Mapping[str, Any]] = None,
) -> UnitOfWorkFactory:
    """Explicitly enabled product route to the selected SQLite backend.

    This is the ONLY product activation path: it supplies the real product
    adapter builder to the fail-closed :func:`create_unit_of_work_factory`,
    so every selection rule still applies — the config must declare
    ``backend="sqlite"`` and the adapter validates the rest of the
    configuration (path, timeouts, durability) with typed errors.

    Adapter configuration keys (validated by the product adapter):
    ``path`` (required, non-empty), ``busy_timeout_ms`` (optional, positive
    int, default 5000), ``synchronous`` (optional, only ``"FULL"``).

    Absent/empty config, a non-selected backend, and an invalid adapter
    configuration all fail closed; there is no default and no fallback.
    """
    return create_unit_of_work_factory(
        config=config,
        adapter_builder=_product_sqlite_builder,
    )


def create_test_memory_unit_of_work_factory() -> UnitOfWorkFactory:
    """Explicit, test-only in-memory unit-of-work factory.

    This is the ONLY route to the in-memory implementation from this surface.
    It is named and documented as test-only; the production factory rejects
    ``backend="memory"``.  In-memory storage is the reference implementation
    for tests and functional verification — it is not durable and not
    cross-process, so it is never a production target.
    """
    from app.protocol_workflow.storage.memory import build_in_memory_unit_of_work

    return build_in_memory_unit_of_work


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


def readiness_report(
    *,
    adapter_builder: Optional[AdapterBuilder] = None,
) -> Dict[str, Any]:
    """Structured, non-raising readiness status for the selected backend.

    Product activation is NOT complete until a product adapter is wired; with
    no builder the report therefore returns ``status="not_ready"`` and the
    exact blocker.  Injecting a working builder flips it to ``"ready"``.
    """
    selected = get_selected_storage()
    try:
        create_unit_of_work_factory(
            config={"backend": selected.backend},
            adapter_builder=adapter_builder,
        )
    except StorageSelectionError as exc:  # includes not-ready
        return {
            "backend": selected.backend,
            "status": "not_ready",
            "blockers": [str(exc)],
            "decision": selected.decision_path,
            "candidate_identity": selected.candidate_identity,
        }
    return {
        "backend": selected.backend,
        "status": "ready",
        "blockers": [],
        "decision": selected.decision_path,
        "candidate_identity": selected.candidate_identity,
    }
