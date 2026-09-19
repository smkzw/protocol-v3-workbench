"""Actual-main composition root for the Protocol v3 workflow (Task 1R.2).

This module is the ONLY new-chain wiring the shared ``main.py`` may
reference — a single :func:`mount_protocol_workflow_router` call.  It mounts
the existing router factory on the real product SQLite backend behind an
explicit default-off switch and a durable per-project allowlist:

* :func:`protocol_workflow_config_from_env` reads the switch with NO side
  effects (no database, directory, worker or service is created at import
  or mount time — construction is lazy down to the first admitted request).
* :func:`mount_protocol_workflow_router` returns ``False`` without touching
  the app when the switch is off (default), so legacy routes and error
  handling stay byte-identical.  An explicit enable without a database path
  fails closed.
* Only admitted projects reach the product service: a router-level admission
  dependency checks the durable allowlist over a read-only connection
  BEFORE any endpoint runs, so rejected projects never acquire a unit of
  work and never create or migrate the database file.  Rejection reuses the
  stable Chinese not-found envelope — never a new error shape.
* Structural validation inside the new chain stays inside the same Chinese
  envelope at route scope (custom route class); legacy handlers are unchanged.
* Admission itself is out-of-band (see ``storage.sqlite.admit_project``):
  there is no HTTP activation endpoint and no automatic enrollment in this
  phase, and the in-memory cutover-transition record is never consulted
  (it does not survive restarts and is not an admission authority).

    WORKBENCH_PROTOCOL_V3_WORKFLOW_ENABLED=1|true|yes|on  (default: off)
    WORKBENCH_PROTOCOL_V3_WORKFLOW_DB=<product sqlite path>  (required iff on)
    WORKBENCH_PROTOCOL_V3_WORKFLOW_BUSY_TIMEOUT_MS=<ms>  (optional, default 5000)
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Dict, Mapping, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from app.protocol_workflow.agent5 import RegistrySelection
from app.protocol_workflow.api.router import (
    create_protocol_workflow_router,
    protocol_workflow_not_found_envelope,
    protocol_workflow_validation_exception_handler,
)
from app.protocol_workflow.application import ApplicationService
from app.protocol_workflow.application.manuscript_documents import ManuscriptDocumentService
from app.protocol_workflow.agent1.source_identity import SourceIdentityService
from app.protocol_workflow.artifacts.local_store import LocalArtifactStore
from app.protocol_workflow.api.sources import create_source_router
from app.protocol_workflow.api.research_intake import create_research_intake_router
from app.protocol_workflow.agent1.seed_coordinator import SeedCoordinator
from app.protocol_workflow.agent1.seed_product import lazy_product_seed_factory
from app.protocol_workflow.agent2.coordinator import RegimenCoordinator
from app.protocol_workflow.runtime.product_profile_bindings import resolve_product_profile
from app.protocol_workflow.agent2.product import (
    lazy_product_regimen_factory,
    lazy_product_design_elements_factory,
)
from app.protocol_workflow.api.design import create_design_router, create_design_elements_router
from app.protocol_workflow.api.manuscript_sources import create_manuscript_source_router
from app.protocol_workflow.agent3.source_preparation import build_source_preparation
from app.protocol_workflow.agent3.product import lazy_product_chapter_factory
from app.protocol_workflow.api.chapter_drafts import create_chapter_draft_router
from app.protocol_workflow.api.manuscript_drafts import create_manuscript_draft_router
from app.protocol_workflow.agent3.manuscript_coordinator import build_manuscript_coordinator
from app.protocol_workflow.errors import OWNER_PUBLIC_LABEL, ProtocolErrorOwner
from app.protocol_workflow.registries import load_skill_registry
from app.protocol_workflow.registries.template_runtime import (
    default_template_root,
    load_current_template,
)
from app.protocol_workflow.storage.selected import (
    UnitOfWorkFactory,
    create_product_unit_of_work_factory,
)
from app.protocol_workflow.storage.sqlite import SqliteStorageError, is_project_admitted, build_committed_reservation_repository_factory

__all__ = [
    "ENV_BUSY_TIMEOUT_MS",
    "ENV_DB_PATH",
    "ENV_ENABLED",
    "ProtocolWorkflowMountConfig",
    "mount_protocol_workflow_router",
    "protocol_workflow_config_from_env",
]

#: Explicit master switch.  Absent or any non-truthy value keeps the new
#: chain fully unmounted (legacy behaviour, zero side effects).
ENV_ENABLED = "WORKBENCH_PROTOCOL_V3_WORKFLOW_ENABLED"

#: Product SQLite path.  Required when (and only when) explicitly enabled.
ENV_DB_PATH = "WORKBENCH_PROTOCOL_V3_WORKFLOW_DB"

#: Optional busy-timeout override (milliseconds).
ENV_BUSY_TIMEOUT_MS = "WORKBENCH_PROTOCOL_V3_WORKFLOW_BUSY_TIMEOUT_MS"

_TRUTHY = frozenset({"1", "true", "yes", "on"})

_DEFAULT_BUSY_TIMEOUT_MS = 5000


@dataclass(frozen=True)
class ProtocolWorkflowMountConfig:
    """Validated mount configuration — pure data, no I/O performed."""

    enabled: bool
    db_path: Optional[Path]
    busy_timeout_ms: int = _DEFAULT_BUSY_TIMEOUT_MS

    def adapter_config(self) -> Dict[str, Any]:
        """Storage-adapter mapping for the configured product database."""
        if self.db_path is None:
            raise ValueError(
                f"{ENV_DB_PATH} must be set when the Protocol v3 workflow "
                "chain is explicitly enabled"
            )
        return {
            "backend": "sqlite",
            "path": str(self.db_path),
            "busy_timeout_ms": self.busy_timeout_ms,
        }


def protocol_workflow_config_from_env(
    env: Optional[Mapping[str, str]] = None,
) -> ProtocolWorkflowMountConfig:
    """Build the mount configuration from the environment — no side effects."""
    source: Mapping[str, str] = os.environ if env is None else env
    raw_flag = source.get(ENV_ENABLED, "")
    enabled = str(raw_flag).strip().lower() in _TRUTHY
    if not enabled:
        return ProtocolWorkflowMountConfig(enabled=False, db_path=None)
    raw_db = source.get(ENV_DB_PATH, "")
    db_path = (
        Path(str(raw_db).strip()).expanduser()
        if isinstance(raw_db, str) and str(raw_db).strip()
        else None
    )
    raw_busy = source.get(ENV_BUSY_TIMEOUT_MS, "")
    busy_timeout_ms = _DEFAULT_BUSY_TIMEOUT_MS
    if isinstance(raw_busy, str) and raw_busy.strip():
        try:
            busy_timeout_ms = int(raw_busy.strip())
        except ValueError as exc:
            raise ValueError(
                f"{ENV_BUSY_TIMEOUT_MS} must be a positive integer "
                f"(milliseconds), got {raw_busy!r}"
            ) from exc
        if busy_timeout_ms <= 0:
            raise ValueError(
                f"{ENV_BUSY_TIMEOUT_MS} must be a positive integer "
                f"(milliseconds), got {raw_busy!r}"
            )
    return ProtocolWorkflowMountConfig(
        enabled=enabled,
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
    )


def _default_registry_path() -> Path:
    """Locate the frozen skill registry from this file's repo anchor."""
    return (
        Path(__file__).resolve().parents[5]
        / "config/medical_writing/protocol_v3/skill_registry.json"
    )


class _LazyProductUnitOfWorkFactory:
    """Defer product bootstrap (file creation/migration) to first use.

    Constructing this holder — and therefore mounting the router — performs
    no database I/O.  The real product factory (via the ONLY product route,
    ``create_product_unit_of_work_factory``) is built once, thread-safely,
    on the first admitted request's first unit-of-work acquisition.
    """

    __slots__ = ("_config", "_lock", "_real")

    def __init__(self, config: Mapping[str, Any]) -> None:
        self._config: Dict[str, Any] = dict(config)
        self._lock = Lock()
        self._real: Optional[UnitOfWorkFactory] = None

    def __call__(self):  # type: ignore[no-untyped-def]
        real = self._real
        if real is None:
            with self._lock:
                real = self._real
                if real is None:
                    real = create_product_unit_of_work_factory(
                        config=dict(self._config)
                    )
                    self._real = real
        return real()


class _ValidationEnvelopeRoute(APIRoute):
    """Keep structural validation inside the Chinese envelope at route scope.

    Only :class:`RequestValidationError` is translated; every other
    exception (including the admission gate's ``HTTPException``) propagates
    untouched.  Legacy apps never register this handler globally, so their
    422 shape is unaffected.
    """

    def get_route_handler(self) -> Callable[..., Any]:
        inner = super().get_route_handler()

        async def handler(request: Request) -> Any:
            try:
                return await inner(request)
            except RequestValidationError as exc:
                return protocol_workflow_validation_exception_handler(
                    request, exc
                )

        return handler


def _make_admission_dependency(
    adapter_config: Mapping[str, Any],
) -> Callable[..., None]:
    """Build the router-level admission gate over a read-only check."""
    config = dict(adapter_config)

    def _admission_gate(project_id: str) -> None:
        try:
            admitted = is_project_admitted(config, project_id)
        except (SqliteStorageError, sqlite3.Error, OSError) as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "message": "暂时无法读取项目存储，本次操作未执行。",
                    "responsible_area": OWNER_PUBLIC_LABEL[ProtocolErrorOwner.APPLICATION_SERVICE],
                    "can_retry": False,
                    "next_step": "请检查项目存储是否可用，恢复后刷新页面。",
                },
            ) from exc
        if not admitted:
            raise HTTPException(
                status_code=404,
                detail=protocol_workflow_not_found_envelope(),
            )

    return _admission_gate


def _object_revision_worker_factory(adapter_config):
    """Per-study AI object-revision workers (T12), sharing the artifact store."""
    from app.protocol_workflow.agent3.object_revision import ObjectRevisionWorker
    instances = {}

    def build(project_id: str, study_definition_id: str):
        key = (project_id, study_definition_id)
        instance = instances.get(key)
        if instance is None:
            instance = ObjectRevisionWorker(
                storage_path=adapter_config['path'],
                product_profile=resolve_product_profile())
            instances[key] = instance
        return instance

    return build


def _chapter_facts_deriver_factory(adapter_config):
    """Per-study deriver registry (B09): progress, locks and restart recovery
    are study-scoped.  The receipt artifact store stays shared so idempotent
    content-hash replay still works across instances."""
    from app.protocol_workflow.agent3.chapter_facts import ChapterFactsDeriver
    instances = {}

    def build(project_id: str, study_definition_id: str):
        key = (project_id, study_definition_id)
        instance = instances.get(key)
        if instance is None:
            instance = ChapterFactsDeriver(
                storage_path=adapter_config['path'],
                product_profile=resolve_product_profile())
            instances[key] = instance
        return instance

    return build


def create_mounted_protocol_workflow_router(
    config: ProtocolWorkflowMountConfig,
    *,
    registry_path: Optional[Path] = None,
    seed_coordinator_factory: Optional[Callable[[str], SeedCoordinator]] = None,
    regimen_coordinator_factory: Optional[Callable[[str], RegimenCoordinator]] = None,
    design_elements_coordinator_factory: Optional[Callable] = None,
    chapter_coordinator_factory: Optional[Callable] = None,
) -> Optional[APIRouter]:
    """Build the mounted new-chain router, or ``None`` when disabled.

    Disabled returns ``None`` with zero side effects.  Enabled builds the
    application service over the lazy product factory (no database is
    opened here) and layers the admission gate plus the route-scoped
    validation envelope over the unchanged router factory.
    """
    if not config.enabled:
        return None
    adapter_config = config.adapter_config()  # fail closed without a db path
    registry_document = load_skill_registry(
        str(registry_path) if registry_path is not None
        else str(_default_registry_path())
    )
    uow_factory = _LazyProductUnitOfWorkFactory(adapter_config)
    service = ApplicationService(
        unit_of_work_factory=uow_factory,
        # Template-bound adoption (3R.4D) always reloads the current authored
        # template source-bound at adoption time; nothing is cached across
        # requests and legacy commands never touch this loader.
        current_template_loader=lambda: load_current_template(
            default_template_root()
        ),
    )
    inner = create_protocol_workflow_router(
        application_service=service,
        registry_selection=RegistrySelection(
            skills=registry_document.skill_definitions()
        ),
        route_class=_ValidationEnvelopeRoute,
    )
    outer = APIRouter()
    outer.include_router(
        inner,
        dependencies=[Depends(_make_admission_dependency(adapter_config))],
    )
    # Do not create files at mount time. Source bytes share the configured
    # product database's directory and are opened only on an actual request.
    artifact_root = Path(str(adapter_config['path']) + '.artifacts')
    outer.include_router(
        create_source_router(
            lambda: SourceIdentityService(uow_factory, LocalArtifactStore(str(artifact_root))),
            route_class=_ValidationEnvelopeRoute,
        ),
        dependencies=[Depends(_make_admission_dependency(adapter_config))],
    )
    seeds = seed_coordinator_factory or lazy_product_seed_factory(adapter_config)
    outer.include_router(
        create_research_intake_router(
            lambda: SourceIdentityService(uow_factory, LocalArtifactStore(str(artifact_root))),
            seeds,
            route_class=_ValidationEnvelopeRoute,
        ),
        dependencies=[Depends(_make_admission_dependency(adapter_config))],
    )
    outer.include_router(
        create_design_router(seeds, regimen_coordinator_factory or lazy_product_regimen_factory(adapter_config),
                             application_service=service, route_class=_ValidationEnvelopeRoute),
        dependencies=[Depends(_make_admission_dependency(adapter_config))],
    )
    outer.include_router(
        create_design_elements_router(seeds,
            design_elements_coordinator_factory or lazy_product_design_elements_factory(adapter_config),
            application_service=service, route_class=_ValidationEnvelopeRoute),
        dependencies=[Depends(_make_admission_dependency(adapter_config))],
    )
    def preparations(project_id):
        return build_source_preparation(project_id=project_id,branch_id='main',
                uow_factory=uow_factory,
                reservation_repository_factory=build_committed_reservation_repository_factory(adapter_config),
                source_service=SourceIdentityService(uow_factory,LocalArtifactStore(str(artifact_root))))
    outer.include_router(
        create_manuscript_source_router(seeds, preparations,
            application_service=service,route_class=_ValidationEnvelopeRoute),
        dependencies=[Depends(_make_admission_dependency(adapter_config))],
    )
    chapters = chapter_coordinator_factory or lazy_product_chapter_factory(adapter_config)
    outer.include_router(
        create_chapter_draft_router(chapters,
            preparations, application_service=service, route_class=_ValidationEnvelopeRoute),
        dependencies=[Depends(_make_admission_dependency(adapter_config))],
    )
    def manuscripts(project_id):
        return build_manuscript_coordinator(project_id=project_id, branch_id='main',
            uow_factory=uow_factory,
            reservation_repository_factory=build_committed_reservation_repository_factory(adapter_config),
            chapter_factory=chapters)
    outer.include_router(
        create_manuscript_draft_router(manuscripts, preparations,
            application_service=service, template_loader=lambda: load_current_template(default_template_root()),
            documents=ManuscriptDocumentService(uow_factory, lambda: datetime.now(timezone.utc)),
            chapter_facts_deriver_factory=_chapter_facts_deriver_factory(adapter_config),
            object_revision_worker_factory=_object_revision_worker_factory(adapter_config),
            route_class=_ValidationEnvelopeRoute),
        dependencies=[Depends(_make_admission_dependency(adapter_config))],
    )
    return outer


def mount_protocol_workflow_router(
    app: FastAPI,
    config: Optional[ProtocolWorkflowMountConfig] = None,
    *,
    registry_path: Optional[Path] = None,
    seed_coordinator_factory: Optional[Callable[[str], SeedCoordinator]] = None,
    regimen_coordinator_factory: Optional[Callable[[str], RegimenCoordinator]] = None,
    design_elements_coordinator_factory: Optional[Callable] = None,
    chapter_coordinator_factory: Optional[Callable] = None,
) -> bool:
    """Mount the Protocol v3 chain on *app* iff explicitly enabled.

    Returns ``True`` when mounted, ``False`` when the switch is off (the
    app is then untouched).  Narrow enough to be the single ``main.py``
    wiring line for Task 1R.2.
    """
    resolved = (
        config
        if config is not None
        else protocol_workflow_config_from_env()
    )
    router = create_mounted_protocol_workflow_router(
        resolved, registry_path=registry_path, seed_coordinator_factory=seed_coordinator_factory,
        regimen_coordinator_factory=regimen_coordinator_factory,
        design_elements_coordinator_factory=design_elements_coordinator_factory,
        chapter_coordinator_factory=chapter_coordinator_factory
    )
    if router is None:
        return False
    app.include_router(router)
    return True
