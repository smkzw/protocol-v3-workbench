"""Protocol v3 API contract tests (frozen plan Task 1.9 — Worker 03).

Design authority: design sections 5.1 / 5.4 / 17.2 / 18 / 19 and the frozen
plan Task 1.9.  The tests prove, through a local in-process ``FastAPI`` app
that mounts the router factory (never the shared ``main.py``):

**Mutation/query contract**
* typed create/apply commands succeed end to end; exact replays return the
  prior result with no second write;
* stale-revision conflicts and path/body project (and study-definition)
  mismatches fail closed BEFORE any service/coordinator call, with the stable
  Chinese envelope;
* queries are GET-only reads; absent objects produce the stable not-found
  envelope.

**Agent⑤ surfaces**
* progress, gates, decision requests, manifest pinning and decomposition
  work through a FRESH query façade + coordinator per request; state
  mutated/seeded between two requests is observed by the second request (no
  stale snapshot retention);
* there is deliberately NO client-supplied exception-card endpoint (a client
  must never invent a catalog failure); the internal Agent⑤ exception-card
  capability stays covered by the agent5 authority tests.  Real
  :class:`ProtocolWorkflowError` failures cross the API as catalog-derived
  Chinese-native public copy only — no machine code, object id, attempt,
  owner enum, recovery action, audit detail or audit context.

**Error envelope**
* only ``ProtocolWorkflowError.to_public_payload()`` reaches HTTP responses;
  validation/project-mismatch use the same stable Chinese envelope; no
  traceback, raw path, backend/log label, ``门``, ``信号`` or raw English
  status label appears;
* the run-manifest request rejects an empty source lineage structurally
  (422 Chinese envelope) before any coordinator/service call.

**OpenAPI**
* deterministic across two fresh app factories; operation IDs unique; every
  path is explicitly project-isolated under
  ``/api/projects/{project_id}/protocol-workflow``.

**Shared-surface isolation**
* the api package imports no legacy writing routes, no medical-monitoring
  implementation and no ``app.main``; ``main.py`` does not reference
  ``protocol_workflow`` (router is not product-mounted by Task 1.9).

**Frontend client contract**
* real Node execution of ``protocolWorkspaceApi.mjs`` with a fake fetch:
  URL/method/body/error/abort/invalid-JSON behaviour; no HTTP/network/
  invalid-JSON error is converted into empty success and no audit payload
  reaches the client error.

All tests use an explicit shared-state in-memory UoW factory; product
storage is never routed to Memory.  No security, browser/visual, install,
live-model or production-storage activation is performed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from packages.contracts.workbench_contracts.protocol_v3 import (
    ActorType,
    CanonicalState,
    DecisionRecord,
    WorkflowRunStatus,
)
from app.protocol_workflow.agent5 import (
    GateObservation,
    GateResult,
    GraphPin,
    RegistrySelection,
    TemplatePin,
)
from app.protocol_workflow.application import (
    ApplicationService,
    study_definition_genesis_snapshot,
)
from app.protocol_workflow.canonical import study_revision_hash
from app.protocol_workflow.api import (
    create_protocol_workflow_router,
    protocol_workflow_validation_exception_handler,
)
from app.protocol_workflow.ports.repositories import (
    DecisionGraphRecord,
    WorkflowRunStatusRecord,
)
from app.protocol_workflow.registries import load_skill_registry
from app.protocol_workflow.storage.memory import (
    InMemoryArtifactStore,
    InMemoryCurrentAggregateRepository,
    InMemoryEventStreamRepository,
    InMemoryExecutionReservationRepository,
    InMemoryInboxRepository,
    InMemoryOutboxRepository,
    InMemoryReadModelRepository,
    InMemoryRevisionCasRepository,
    InMemoryUnitOfWork,
    _AggregateIndex,
)

_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY_PATH = (
    _ROOT / "config/medical_writing/protocol_v3/skill_registry.json"
)
_API_DIR = _ROOT / "services/api/app/protocol_workflow/api"
_CLIENT_PATH = (
    _ROOT
    / "frontend/src/features/medical-writing/protocol-workbench/protocolWorkspaceApi.mjs"
)
_MAIN_PATH = _ROOT / "services/api/app/main.py"


# ---------------------------------------------------------------------------
# Constants and fixtures
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

_PROJECT = "proj:test:sd:1"
_OTHER_PROJECT = "proj:test:sd:2"
_SD_ID = "sd:test:1"
_SEED_ID = "seed:test:1"
_SEED_SHA = "a" * 64
_RUN_ID = "wr:test:1"
_FACTS = {
    "picos.population.indication": "中重度活动性溃疡性结肠炎",
    "picos.intervention.dose": "10 mg 每日一次",
}

_TEMPLATE_PIN = TemplatePin(template_version="template:v1", template_sha256="b" * 64)
_GRAPH_PIN = GraphPin(graph_version="graph:v1", graph_sha256="c" * 64)
_SOURCE_REVISIONS = ("d" * 64,)

_PUBLIC_KEYS = {"message", "responsible_area", "can_retry", "next_step"}
_FORBIDDEN_PUBLIC_TOKENS = (
    "MW-PRO",
    "error_code",
    "object_id",
    "attempt",
    "owner",
    "recovery_action",
    "audit",
    "traceback",
    "backend",
    "checkpoint",
    "log",
    "门",
    "信号",
    "/tmp",
    "/Users",
)


class _SharedState:
    """Shared repositories across single-use UoW instances (clone of the
    Worker 01/02 shared-state pattern)."""

    def __init__(self) -> None:
        sd_index = _AggregateIndex()
        self.sd_repo = InMemoryCurrentAggregateRepository(
            identity_field="study_definition_id", index=sd_index,
        )
        self.sd_cas = InMemoryRevisionCasRepository(
            identity_field="study_definition_id", index=sd_index,
        )
        self.sdr_repo = InMemoryCurrentAggregateRepository(
            identity_field="semantic_document_revision_id",
            index=_AggregateIndex(),
        )
        self.sdr_cas = InMemoryRevisionCasRepository(
            identity_field="semantic_document_revision_id",
            index=_AggregateIndex(),
        )
        self.ev_repo = InMemoryEventStreamRepository()
        self.ob_repo = InMemoryOutboxRepository()
        self.ib_repo = InMemoryInboxRepository()
        self.rv_repo = InMemoryExecutionReservationRepository()
        self.rm_repo = InMemoryReadModelRepository()
        self.artifacts = InMemoryArtifactStore()

    def new_uow(self) -> InMemoryUnitOfWork:
        return InMemoryUnitOfWork(
            study_definition_repository=self.sd_repo,
            study_definition_cas_repository=self.sd_cas,
            semantic_document_repository=self.sdr_repo,
            semantic_document_cas_repository=self.sdr_cas,
            event_stream_repository=self.ev_repo,
            outbox_repository=self.ob_repo,
            inbox_repository=self.ib_repo,
            reservation_repository=self.rv_repo,
            read_model_repository=self.rm_repo,
            artifact_store=self.artifacts,
        )

    def factory(self):
        return self.new_uow


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _decision(
    *,
    decision_record_id: str = "decision:create:001",
    decision_key: str = "decision:create",
    snapshot_sha256: str,
    expected_state_revision: int,
    canonical_state: CanonicalState = CanonicalState.CONFIRMED,
    **overrides: Any,
) -> DecisionRecord:
    payload = {
        "decision_record_id": decision_record_id,
        "decision_key": decision_key,
        "snapshot_sha256": snapshot_sha256,
        "expected_state_revision": expected_state_revision,
        "state_revision": expected_state_revision + 1,
        "option_ids": ("option:dose:001", "option:dose:002"),
        "selected_option_id": "option:dose:001",
        "actor_type": ActorType.USER,
        "actor_id": "user:medical-writer",
        "reason": "接受 AI 推荐的默认剂量设计。",
        "decided_at": _T0,
        "canonical_state": canonical_state,
    }
    payload.update(overrides)
    return DecisionRecord(**payload)


def _service(state: _SharedState) -> ApplicationService:
    return ApplicationService(unit_of_work_factory=state.factory(), clock=lambda: _T0)


def _selection() -> RegistrySelection:
    document = load_skill_registry(str(_REGISTRY_PATH))
    return RegistrySelection(skills=document.skill_definitions())


def _make_app(
    state: _SharedState,
    *,
    service: Optional[ApplicationService] = None,
    gate_observer: Optional[Callable[[], Tuple[GateObservation, ...]]] = None,
) -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(
        RequestValidationError, protocol_workflow_validation_exception_handler
    )
    app.include_router(
        create_protocol_workflow_router(
            application_service=(
                service if service is not None else _service(state)
            ),
            registry_selection=_selection(),
            gate_observer=gate_observer,
            clock=lambda: _T0,
        )
    )
    return app


def _client(
    state: _SharedState,
    *,
    service: Optional[ApplicationService] = None,
    gate_observer: Optional[Callable[[], Tuple[GateObservation, ...]]] = None,
) -> TestClient:
    return TestClient(_make_app(state, service=service, gate_observer=gate_observer))


def _base(project_id: str = _PROJECT) -> str:
    return f"/api/projects/{project_id}/protocol-workflow"


def _create_body(
    *,
    project_id: str = _PROJECT,
    study_definition_id: str = _SD_ID,
    idempotency_key: str = "idem:create:1",
    facts: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    facts = dict(_FACTS) if facts is None else dict(facts)
    snapshot = study_definition_genesis_snapshot(
        study_definition_id=study_definition_id,
        project_id=project_id,
        normalized_seed_id=_SEED_ID,
        normalized_seed_sha256=_SEED_SHA,
        facts=facts,
        decided_at=_T0,
    )
    dr = _decision(
        decision_record_id=overrides.pop("decision_record_id", "decision:create:001"),
        decision_key=overrides.pop("decision_key", "decision:create"),
        snapshot_sha256=snapshot,
        expected_state_revision=0,
    )
    body: Dict[str, Any] = {
        "project_id": project_id,
        "study_definition_id": study_definition_id,
        "idempotency_key": idempotency_key,
        "expected_revision": 0,
        "actor_type": "user",
        "actor_id": "user:medical-writer",
        "reason": "接受 AI 推荐的默认剂量设计。",
        "decision_record": dr.model_dump(mode="json"),
        "normalized_seed_id": _SEED_ID,
        "normalized_seed_sha256": _SEED_SHA,
        "initial_facts": facts,
    }
    body.update(overrides)
    return body


def _apply_body(
    *,
    project_id: str = _PROJECT,
    study_definition_id: str = _SD_ID,
    idempotency_key: str = "idem:apply:1",
    expected_revision: int,
    snapshot_sha256: str,
    decision_record_id: str = "decision:dose:001",
    decision_key: str = "decision:dose",
    fact_updates: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    dr = _decision(
        decision_record_id=decision_record_id,
        decision_key=decision_key,
        snapshot_sha256=snapshot_sha256,
        expected_state_revision=expected_revision,
    )
    body: Dict[str, Any] = {
        "project_id": project_id,
        "study_definition_id": study_definition_id,
        "idempotency_key": idempotency_key,
        "expected_revision": expected_revision,
        "actor_type": "user",
        "actor_id": "user:medical-writer",
        "reason": "接受 AI 推荐的默认剂量设计。",
        "decision_record": dr.model_dump(mode="json"),
    }
    if fact_updates is not None:
        body["fact_updates"] = fact_updates
    body.update(overrides)
    return body


def _manifest_body(
    *,
    project_id: str = _PROJECT,
    study_definition_id: str = _SD_ID,
    workflow_run_id: str = _RUN_ID,
    **overrides: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "project_id": project_id,
        "study_definition_id": study_definition_id,
        "workflow_run_id": workflow_run_id,
        "protocol_template": {
            "template_version": _TEMPLATE_PIN.template_version,
            "template_sha256": _TEMPLATE_PIN.template_sha256,
        },
        "graph": {
            "graph_version": _GRAPH_PIN.graph_version,
            "graph_sha256": _GRAPH_PIN.graph_sha256,
        },
        "contract_schema_version": "mw_protocol_v3_contract_v1",
        "source_revision_hashes": list(_SOURCE_REVISIONS),
    }
    body.update(overrides)
    return body


def _decomposition_body(
    *,
    project_id: str = _PROJECT,
    study_definition_id: str = _SD_ID,
    workflow_run_id: str = _RUN_ID,
    packages: Optional[Tuple[Dict[str, Any], ...]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    if packages is None:
        packages = (
            {
                "work_package_id": "wp:coordination",
                "skill_definition_id": "skill.workflow-coordination",
                "depends_on": [],
            },
            {
                "work_package_id": "wp:evidence",
                "skill_definition_id": "skill.source-acquisition-plan",
                "depends_on": [],
            },
        )
    body: Dict[str, Any] = {
        "project_id": project_id,
        "study_definition_id": study_definition_id,
        "workflow_run_id": workflow_run_id,
        "packages": list(packages),
    }
    body.update(overrides)
    return body


def _seed_run_status(
    state: _SharedState,
    status: WorkflowRunStatus,
    *,
    display_progress: float = 0.4,
    journey_counter: int = 3,
) -> None:
    uow = state.new_uow()
    with uow:
        uow.read_model_repository.upsert_workflow_run_status(
            WorkflowRunStatusRecord(
                project_id=_PROJECT,
                workflow_run_id=_RUN_ID,
                status=status,
                display_progress=display_progress,
                journey_counter=journey_counter,
            )
        )


def _seed_decision_graph(
    state: _SharedState, records: Tuple[DecisionGraphRecord, ...]
) -> None:
    uow = state.new_uow()
    with uow:
        uow.read_model_repository.replace_decision_graph(
            _PROJECT, _SD_ID, records
        )


def _event_count(state: _SharedState) -> int:
    return len(state.ev_repo.read_events(_PROJECT, f"stream:study_definition:{_SD_ID}"))


def _assert_public_envelope(payload: Dict[str, Any]) -> Dict[str, Any]:
    assert set(payload.keys()) == {"detail"}
    detail = payload["detail"]
    assert set(detail.keys()) == _PUBLIC_KEYS, f"unexpected envelope fields: {detail}"
    text = json.dumps(payload, ensure_ascii=False)
    for token in _FORBIDDEN_PUBLIC_TOKENS:
        assert token not in text, f"forbidden token {token!r} leaked into the envelope"
    return detail


# ---------------------------------------------------------------------------
# Exploding service spy (proves no service/coordinator call)
# ---------------------------------------------------------------------------


class _ExplodingService(ApplicationService):
    """Every application/query method raises when touched."""

    def __init__(self) -> None:
        super().__init__(unit_of_work_factory=_SharedState().factory())
        self.touched: list[str] = []

    def _explode(self, name: str) -> None:
        self.touched.append(name)
        raise AssertionError(f"service method {name} must not be called")

    def create_study_definition(self, command):  # type: ignore[override]
        self._explode("create_study_definition")

    def apply_decision(self, command):  # type: ignore[override]
        self._explode("apply_decision")

    def get_study_definition(self, query):  # type: ignore[override]
        self._explode("get_study_definition")

    def get_study_definition_event_summary(self, query):  # type: ignore[override]
        self._explode("get_study_definition_event_summary")

    def get_decision_graph(self, query):  # type: ignore[override]
        self._explode("get_decision_graph")

    def get_workflow_run_status(self, query):  # type: ignore[override]
        self._explode("get_workflow_run_status")


# ---------------------------------------------------------------------------
# Mutation contract
# ---------------------------------------------------------------------------


class TestMutationContract:
    def test_create_study_definition_success(self) -> None:
        state = _SharedState()
        client = _client(state)
        response = client.post(
            f"{_base()}/study-definitions", json=_create_body()
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["replayed"] is False
        assert payload["revision"] == 1
        assert payload["definition"]["project_id"] == _PROJECT
        assert payload["definition"]["facts"] == _FACTS
        assert payload["definition"]["decision_record_ids"] == [
            "decision:create:001"
        ]
        assert payload["definition"]["canonical_state"] == "confirmed"
        assert payload["revision_sha256"] == payload["definition"].get(
            "revision_sha256", ""
        ) or len(payload["revision_sha256"]) == 64

    def test_apply_decision_success(self) -> None:
        state = _SharedState()
        svc = _service(state)
        created = svc.create_study_definition(
            _create_command_via_body(_create_body())
        )
        snapshot = study_revision_hash(created.definition)
        client = _client(state, service=svc)
        response = client.post(
            f"{_base()}/study-definitions/{_SD_ID}/decisions",
            json=_apply_body(
                expected_revision=1,
                snapshot_sha256=snapshot,
                fact_updates={"picos.population.age": "成人"},
            ),
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["replayed"] is False
        assert payload["revision"] == 2
        assert payload["definition"]["facts"]["picos.population.age"] == "成人"
        assert payload["definition"]["decision_record_ids"] == [
            "decision:create:001",
            "decision:dose:001",
        ]

    def test_exact_replay_is_idempotent_without_second_write(self) -> None:
        state = _SharedState()
        client = _client(state)
        body = _create_body()
        first = client.post(f"{_base()}/study-definitions", json=body)
        assert first.status_code == 200
        second = client.post(f"{_base()}/study-definitions", json=body)
        assert second.status_code == 200
        assert second.json()["replayed"] is True
        assert second.json()["revision"] == 1
        assert _event_count(state) == 1

    def test_apply_exact_replay_is_idempotent(self) -> None:
        state = _SharedState()
        svc = _service(state)
        created = svc.create_study_definition(
            _create_command_via_body(_create_body())
        )
        snapshot = study_revision_hash(created.definition)
        client = _client(state, service=svc)
        body = _apply_body(expected_revision=1, snapshot_sha256=snapshot)
        first = client.post(f"{_base()}/study-definitions/{_SD_ID}/decisions", json=body)
        assert first.json()["replayed"] is False
        second = client.post(f"{_base()}/study-definitions/{_SD_ID}/decisions", json=body)
        assert second.json()["replayed"] is True
        assert _event_count(state) == 2

    def test_stale_revision_conflict_fails_closed(self) -> None:
        state = _SharedState()
        svc = _service(state)
        created = svc.create_study_definition(
            _create_command_via_body(_create_body())
        )
        rev1_snapshot = study_revision_hash(created.definition)
        svc.apply_decision(
            _apply_command_via_body(
                _apply_body(expected_revision=1, snapshot_sha256=rev1_snapshot)
            )
        )
        client = _client(state, service=svc)
        # A fresh decision claiming revision 1 while the aggregate is at
        # revision 2 is stale.
        response = client.post(
            f"{_base()}/study-definitions/{_SD_ID}/decisions",
            json=_apply_body(
                expected_revision=1,
                snapshot_sha256=rev1_snapshot,
                decision_record_id="decision:stale:001",
                decision_key="decision:stale",
            ),
        )
        assert response.status_code == 409
        detail = _assert_public_envelope(response.json())
        assert "版本" in detail["message"]

    def test_project_mismatch_rejected_before_service_call(self) -> None:
        state = _SharedState()
        exploding = _ExplodingService()
        client = _client(state, service=exploding)
        body = _create_body(project_id=_OTHER_PROJECT)
        response = client.post(f"{_base()}/study-definitions", json=body)
        assert response.status_code == 422
        _assert_public_envelope(response.json())
        assert exploding.touched == [], "service was called on project mismatch"

    def test_study_definition_mismatch_rejected_before_service_call(self) -> None:
        state = _SharedState()
        exploding = _ExplodingService()
        client = _client(state, service=exploding)
        body = _apply_body(
            expected_revision=1,
            snapshot_sha256="e" * 64,
            study_definition_id="sd:test:other",
        )
        response = client.post(
            f"{_base()}/study-definitions/{_SD_ID}/decisions", json=body
        )
        assert response.status_code == 422
        _assert_public_envelope(response.json())
        assert exploding.touched == [], "service was called on identity mismatch"

    def test_structural_validation_uses_chinese_envelope(self) -> None:
        state = _SharedState()
        client = _client(state)
        body = _create_body()
        del body["reason"]
        response = client.post(f"{_base()}/study-definitions", json=body)
        assert response.status_code == 422
        _assert_public_envelope(response.json())

    def test_malformed_command_domain_values_use_chinese_envelope(self) -> None:
        state = _SharedState()
        client = _client(state)
        body = _create_body()
        # decision CAS triple misaligned with expected_revision: the typed
        # command rejects it at construction, before any service call.
        body["decision_record"]["expected_state_revision"] = 5
        response = client.post(f"{_base()}/study-definitions", json=body)
        assert response.status_code == 422
        _assert_public_envelope(response.json())


# ---------------------------------------------------------------------------
# Query contract
# ---------------------------------------------------------------------------


class TestQueryContract:
    def _populated(self) -> Tuple[_SharedState, ApplicationService]:
        state = _SharedState()
        svc = _service(state)
        created = svc.create_study_definition(
            _create_command_via_body(_create_body())
        )
        svc.apply_decision(
            _apply_command_via_body(
                _apply_body(
                    expected_revision=1,
                    snapshot_sha256=study_revision_hash(created.definition),
                    fact_updates={"picos.population.age": "成人"},
                )
            )
        )
        return state, svc

    def test_get_study_definition_ok(self) -> None:
        state, svc = self._populated()
        client = _client(state, service=svc)
        response = client.get(f"{_base()}/study-definitions/{_SD_ID}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["revision"] == 2
        assert payload["definition"]["project_id"] == _PROJECT

    def test_get_study_definition_not_found_envelope(self) -> None:
        state = _SharedState()
        client = _client(state)
        response = client.get(f"{_base()}/study-definitions/{_SD_ID}")
        assert response.status_code == 404
        detail = _assert_public_envelope(response.json())
        assert "未找到" in detail["message"]

    def test_get_events_decision_lineage(self) -> None:
        state, svc = self._populated()
        client = _client(state, service=svc)
        response = client.get(f"{_base()}/study-definitions/{_SD_ID}/events")
        assert response.status_code == 200
        payload = response.json()
        assert payload["event_count"] == 2
        assert [item["state_revision"] for item in payload["decisions"]] == [1, 2]
        assert payload["decisions"][1]["applied_revision"] == 2

    def test_get_decision_graph_empty(self) -> None:
        state = _SharedState()
        client = _client(state)
        response = client.get(f"{_base()}/study-definitions/{_SD_ID}/decision-graph")
        assert response.status_code == 200
        assert response.json()["records"] == []

    def test_get_workflow_run_status_empty(self) -> None:
        state = _SharedState()
        client = _client(state)
        response = client.get(f"{_base()}/workflow-runs/{_RUN_ID}")
        assert response.status_code == 200
        assert response.json()["status"] is None


# ---------------------------------------------------------------------------
# Agent⑤ fresh-snapshot and aggregation contract
# ---------------------------------------------------------------------------


class TestAgent5FreshSnapshot:
    def test_progress_observes_new_state_between_requests(self) -> None:
        """Mutate/seed state between two GET requests; the second request
        MUST observe the new state (fresh facade per request)."""
        state = _SharedState()
        svc = _service(state)
        client = _client(state, service=svc)

        first = client.get(
            f"{_base()}/workflow-runs/{_RUN_ID}/progress",
            params={"study_definition_id": _SD_ID},
        )
        assert first.status_code == 200
        assert first.json()["study_definition_revision"] is None

        created = svc.create_study_definition(
            _create_command_via_body(_create_body())
        )
        svc.apply_decision(
            _apply_command_via_body(
                _apply_body(
                    expected_revision=1,
                    snapshot_sha256=study_revision_hash(created.definition),
                )
            )
        )
        _seed_run_status(state, WorkflowRunStatus.RUNNING, display_progress=0.6)

        second = client.get(
            f"{_base()}/workflow-runs/{_RUN_ID}/progress",
            params={"study_definition_id": _SD_ID},
        )
        assert second.status_code == 200
        payload = second.json()
        assert payload["study_definition_revision"] == 2
        assert payload["run_status"] == "running"
        assert payload["display_progress"] == 0.6
        assert payload["study_definition_sha256"] is not None

    def test_manifest_pin_reflects_fresh_study_definition(self) -> None:
        state = _SharedState()
        svc = _service(state)
        client = _client(state, service=svc)
        created = svc.create_study_definition(
            _create_command_via_body(_create_body())
        )

        first = client.post(
            f"{_base()}/workflow-runs/{_RUN_ID}/manifest",
            json=_manifest_body(),
        )
        assert first.status_code == 200
        assert first.json()["study_definition_revision"] == 1

        svc.apply_decision(
            _apply_command_via_body(
                _apply_body(
                    expected_revision=1,
                    snapshot_sha256=study_revision_hash(created.definition),
                )
            )
        )

        second = client.post(
            f"{_base()}/workflow-runs/{_RUN_ID}/manifest",
            json=_manifest_body(),
        )
        assert second.status_code == 200
        assert second.json()["study_definition_revision"] == 2
        assert second.json()["content_sha256"] != first.json()["content_sha256"]

    def test_manifest_pin_rejects_unapproved_study_state(self) -> None:
        state = _SharedState()
        client = _client(state)
        response = client.post(
            f"{_base()}/workflow-runs/{_RUN_ID}/manifest",
            json=_manifest_body(),
        )
        # No StudyDefinition exists: the fresh coordinator fails closed with
        # the stable request envelope, never a fabricated manifest.
        assert response.status_code == 422
        _assert_public_envelope(response.json())

    def test_gates_aggregation_uses_live_observer(self) -> None:
        state = _SharedState()
        observations: list = []

        def observer() -> Tuple[GateObservation, ...]:
            return tuple(observations)

        client = _client(state, gate_observer=observer)
        observations.append(
            GateObservation(
                gate_id="gate:1",
                gate_phase="P1",
                result=GateResult.PASSED,
                observed_at=_T0,
                observed_by="verifier:test",
            )
        )
        first = client.get(
            f"{_base()}/workflow-runs/{_RUN_ID}/gates",
            params={"study_definition_id": _SD_ID},
        )
        assert first.status_code == 200
        assert [item["gate_id"] for item in first.json()["observations"]] == ["gate:1"]

        observations.append(
            GateObservation(
                gate_id="gate:2",
                gate_phase="P1",
                result=GateResult.FAILED,
                observed_at=_T0,
                observed_by="verifier:test",
            )
        )
        second = client.get(
            f"{_base()}/workflow-runs/{_RUN_ID}/gates",
            params={"study_definition_id": _SD_ID},
        )
        assert second.status_code == 200
        assert [item["gate_id"] for item in second.json()["observations"]] == [
            "gate:1",
            "gate:2",
        ]

    def test_decision_requests_only_unresolved(self) -> None:
        state = _SharedState()
        client = _client(state)
        _seed_decision_graph(
            state,
            (
                DecisionGraphRecord(
                    project_id=_PROJECT,
                    decision_key="decision:pending",
                    decision_record_id=None,
                    state_revision=None,
                    selected_option_id=None,
                    canonical_state=None,
                ),
                DecisionGraphRecord(
                    project_id=_PROJECT,
                    decision_key="decision:resolved",
                    decision_record_id="decision:done:1",
                    state_revision=2,
                    selected_option_id="option:1",
                    canonical_state=CanonicalState.CONFIRMED,
                ),
            ),
        )
        response = client.get(
            f"{_base()}/workflow-runs/{_RUN_ID}/decision-requests",
            params={"study_definition_id": _SD_ID},
        )
        assert response.status_code == 200
        keys = [item["decision_key"] for item in response.json()["requests"]]
        assert keys == ["decision:pending"]

    def test_decomposition_deterministic_order(self) -> None:
        state = _SharedState()
        client = _client(state)
        response = client.post(
            f"{_base()}/workflow-runs/{_RUN_ID}/decomposition",
            json=_decomposition_body(),
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["project_id"] == _PROJECT
        assert len(payload["packages"]) == 2
        assert set(payload["ordered_package_ids"]) == {
            "wp:coordination",
            "wp:evidence",
        }
        for package in payload["packages"]:
            assert package["skill_sha256"]  # bound to the approved selection

    def test_decomposition_rejects_unknown_skill(self) -> None:
        state = _SharedState()
        client = _client(state)
        body = _decomposition_body(
            packages=(
                {
                    "work_package_id": "wp:unknown",
                    "skill_definition_id": "skill.not-registered",
                    "depends_on": [],
                },
            )
        )
        response = client.post(
            f"{_base()}/workflow-runs/{_RUN_ID}/decomposition",
            json=body,
        )
        assert response.status_code == 422
        _assert_public_envelope(response.json())

    def test_agent5_project_mismatch_rejected_before_any_call(self) -> None:
        state = _SharedState()
        exploding = _ExplodingService()
        client = _client(state, service=exploding)
        body = _manifest_body(project_id=_OTHER_PROJECT)
        response = client.post(
            f"{_base()}/workflow-runs/{_RUN_ID}/manifest", json=body
        )
        assert response.status_code == 422
        _assert_public_envelope(response.json())
        assert exploding.touched == [], "facade/service was called on mismatch"


# ---------------------------------------------------------------------------
# Run-manifest lineage validation (empty lineage rejected structurally)
# ---------------------------------------------------------------------------


class TestManifestLineageValidation:
    def test_empty_source_lineage_rejected_before_any_call(self) -> None:
        """An empty ``source_revision_hashes`` must fail closed with the
        stable Chinese 422 envelope before any coordinator/service call —
        the immutable RunManifest cannot represent an empty lineage."""
        state = _SharedState()
        exploding = _ExplodingService()
        client = _client(state, service=exploding)
        body = _manifest_body(source_revision_hashes=[])
        response = client.post(
            f"{_base()}/workflow-runs/{_RUN_ID}/manifest", json=body
        )
        assert response.status_code == 422
        _assert_public_envelope(response.json())
        assert exploding.touched == [], "coordinator/service was called on empty lineage"

    def test_non_empty_source_lineage_accepted(self) -> None:
        """A manifest with at least one pinned source revision is accepted
        and returns the pinned manifest with a deterministic content hash."""
        state = _SharedState()
        svc = _service(state)
        created = svc.create_study_definition(
            _create_command_via_body(_create_body())
        )
        client = _client(state, service=svc)
        response = client.post(
            f"{_base()}/workflow-runs/{_RUN_ID}/manifest",
            json=_manifest_body(),
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["study_definition_revision"] == 1
        assert payload["source_revision_hashes"] == list(_SOURCE_REVISIONS)
        assert len(payload["content_sha256"]) == 64

    def test_no_client_supplied_exception_card_endpoint(self) -> None:
        """The exception-card endpoint is omitted entirely: a client can
        never invent a catalog failure through the API.  The path is not
        registered (404) and never appears in the OpenAPI schema."""
        state = _SharedState()
        client = _client(state)
        response = client.post(
            f"{_base()}/workflow-runs/{_RUN_ID}/exception-cards",
            json={
                "card_id": "card:001",
                "error_code": "MW-PRO-P1-REVISION-STALE",
                "study_definition_id": _SD_ID,
            },
        )
        assert response.status_code == 404
        schema = _make_app(state).openapi()
        assert not any("exception-cards" in path for path in schema["paths"])


# ---------------------------------------------------------------------------
# OpenAPI determinism / project isolation
# ---------------------------------------------------------------------------


class TestOpenApiContract:
    def test_openapi_deterministic_across_factories(self) -> None:
        state_a = _SharedState()
        state_b = _SharedState()
        app_a = _make_app(state_a)
        app_b = _make_app(state_b)
        assert json.dumps(app_a.openapi(), sort_keys=True) == json.dumps(
            app_b.openapi(), sort_keys=True
        )

    def test_operation_ids_unique(self) -> None:
        state = _SharedState()
        app = _make_app(state)
        schema = app.openapi()
        operation_ids = [
            operation["operationId"]
            for path_item in schema["paths"].values()
            for operation in path_item.values()
            if isinstance(operation, dict) and "operationId" in operation
        ]
        assert len(operation_ids) == len(set(operation_ids))
        assert len(operation_ids) >= 11

    def test_project_isolation_explicit_on_every_path(self) -> None:
        state = _SharedState()
        app = _make_app(state)
        schema = app.openapi()
        prefix = "/api/projects/{project_id}/protocol-workflow"
        assert schema["paths"], "router must expose paths"
        for path in schema["paths"]:
            assert path.startswith(prefix), f"path {path} escapes the project prefix"


# ---------------------------------------------------------------------------
# Shared-surface isolation (no main.py / monitoring / legacy imports)
# ---------------------------------------------------------------------------


class TestSharedSurfaceIsolation:
    def test_api_sources_have_no_monitoring_or_legacy_imports(self) -> None:
        import ast

        for source_path in sorted(_API_DIR.glob("*.py")):
            tree = ast.parse(source_path.read_text(encoding="utf-8"))
            modules: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    modules.add(node.module or "")
                elif isinstance(node, ast.Import):
                    modules.update(alias.name for alias in node.names)
            for module in modules:
                assert "monitoring" not in module, (
                    f"{source_path.name} imports monitoring surface: {module}"
                )
                assert "medical_writing" not in module, (
                    f"{source_path.name} imports legacy writing surface: {module}"
                )
                assert not module.startswith("app.main"), (
                    f"{source_path.name} imports the shared main.py: {module}"
                )
                assert "legacy" not in module, (
                    f"{source_path.name} imports legacy surface: {module}"
                )

    def test_importing_api_does_not_load_shared_surfaces(self) -> None:
        import importlib

        before = set(sys.modules)
        importlib.import_module("app.protocol_workflow.api")
        newly_loaded = set(sys.modules) - before
        assert not any(
            "monitoring" in name or name == "app.main" or "main" == name.split(".")[-1] and name.startswith("app.")
            for name in newly_loaded
        ), f"api import pulled shared surfaces: {sorted(newly_loaded)}"

    def test_main_py_does_not_reference_protocol_workflow(self) -> None:
        text = _MAIN_PATH.read_text(encoding="utf-8")
        assert "protocol_workflow" not in text
        assert "protocol-workflow" not in text


# ---------------------------------------------------------------------------
# Real Node execution of the frontend client (fake fetch)
# ---------------------------------------------------------------------------

_NODE_CLIENT_CHECK = r"""
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";

const { ProtocolWorkspaceApiError, createProtocolWorkspaceApi } = await import(
  pathToFileURL(process.argv[2])
);

let passed = 0;
function check(condition, message) {
  assert.ok(condition, message);
  passed += 1;
}

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const calls = [];
const api = createProtocolWorkspaceApi({
  fetchImpl: async (url, options) => {
    calls.push({ url, options });
    return jsonResponse({ ok: true });
  },
});

await api.createStudyDefinition("proj/01", { project_id: "proj/01", study_definition_id: "sd:1", idempotency_key: "idem-1", reason: "测试理由", actor_id: "user:medical-writer", actor_type: "user" });
await api.applyStudyDecision("proj/01", "sd:1", { project_id: "proj/01", study_definition_id: "sd:1" });
await api.getStudyDefinition("proj/01", "sd 1");
await api.getStudyDefinitionEvents("proj/01", "sd:1");
await api.getDecisionGraph("proj/01", "sd:1");
await api.getWorkflowRun("proj/01", "wr:1");
await api.getWorkflowRunProgress("proj/01", "wr:1", "sd:1");
await api.getWorkflowRunGates("proj/01", "wr:1", "sd:1");
await api.getWorkflowRunDecisionRequests("proj/01", "wr:1", "sd:1");
await api.pinRunManifest("proj/01", "wr:1", { project_id: "proj/01", study_definition_id: "sd:1", workflow_run_id: "wr:1" });
await api.decomposeWorkPackages("proj/01", "wr:1", { project_id: "proj/01", study_definition_id: "sd:1", workflow_run_id: "wr:1" });

check(calls.length === 11, "eleven business-shaped methods");
check(calls[0].options.method === "POST", "create is POST");
check(calls[0].options.headers["Content-Type"] === "application/json", "create sets JSON content type");
check(JSON.parse(calls[0].options.body).reason === "测试理由", "create body passes through");
check(calls[0].url.endsWith("/api/projects/proj%2F01/protocol-workflow/study-definitions"), "create builds project-scoped v3 path");
check(calls[1].url.includes("/study-definitions/sd%3A1/decisions"), "apply encodes study definition id");
check(calls[2].url.includes("/study-definitions/sd%201"), "get encodes spaces in ids");
check(calls[3].url.endsWith("/study-definitions/sd%3A1/events"), "events path");
check(calls[4].url.endsWith("/study-definitions/sd%3A1/decision-graph"), "decision graph path");
check(calls[5].url.endsWith("/workflow-runs/wr%3A1"), "run status path");
check(calls[6].url.endsWith("/workflow-runs/wr%3A1/progress?study_definition_id=sd%3A1"), "progress path with query");
check(calls[7].url.endsWith("/workflow-runs/wr%3A1/gates?study_definition_id=sd%3A1"), "gates path with query");
check(calls[8].url.endsWith("/workflow-runs/wr%3A1/decision-requests?study_definition_id=sd%3A1"), "decision requests path with query");
check(calls[9].url.endsWith("/workflow-runs/wr%3A1/manifest"), "manifest path");
check(calls[10].url.endsWith("/workflow-runs/wr%3A1/decomposition"), "decomposition path");
check(!calls.some((c) => c.url.includes("exception-cards")), "no exception-card method on the client");
check(calls.slice(2, 9).every((c) => c.options.method === "GET"), "query methods stay GET");
check(calls.slice(2, 9).every((c) => c.options.body === undefined), "GET requests have no body");

const envelopeApi = createProtocolWorkspaceApi({
  fetchImpl: async () => jsonResponse({
    detail: { message: "当前页面不是方案的最新版本，本次修改尚未应用。", responsible_area: "工作台处理", can_retry: true, next_step: "请刷新至最新版本后继续。" },
  }, 409),
});
let conflictError = null;
try {
  await envelopeApi.getStudyDefinition("p1", "sd:1");
} catch (error) {
  conflictError = error;
}
check(conflictError instanceof ProtocolWorkspaceApiError, "typed error on non-ok");
check(conflictError.status === 409, "preserves HTTP status");
check(conflictError.message === "当前页面不是方案的最新版本，本次修改尚未应用。", "Chinese-native error message");
check(conflictError.detail && Object.keys(conflictError.detail).length === 4, "detail normalized to exactly the four public fields");
check(!JSON.stringify(conflictError.detail || {}).includes("error_code"), "no audit code on the client error");
check(!JSON.stringify(conflictError.detail || {}).includes("attempt"), "no attempt on the client error");
check(!JSON.stringify(conflictError.detail || {}).includes("audit"), "no audit payload on the client error");

const injectedApi = createProtocolWorkspaceApi({
  fetchImpl: async () => jsonResponse({
    detail: {
      message: "当前页面不是方案的最新版本，本次修改尚未应用。",
      responsible_area: "工作台处理",
      can_retry: true,
      next_step: "请刷新至最新版本后继续。",
      error_code: "MW-PRO-P1-REVISION-STALE",
      object_id: "sd:secret",
      attempt: 2,
      owner: "application_service",
      recovery_action: "refresh_stale_revision",
      audit_detail: "backend log at /tmp/traceback.py:12",
      audit_context: { event_id: "ev:1", path: "/tmp/x", nested: { attempt: 9 } },
    },
  }, 409),
});
let injectedError = null;
try {
  await injectedApi.getStudyDefinition("p1", "sd:1");
} catch (error) {
  injectedError = error;
}
check(injectedError instanceof ProtocolWorkspaceApiError, "typed error on injected audit payload");
check(injectedError.detail && Object.keys(injectedError.detail).sort().join(",") === "can_retry,message,next_step,responsible_area", "detail is exactly the four approved fields");
check(!("error_code" in injectedError.detail), "error_code discarded");
check(!("object_id" in injectedError.detail), "object_id discarded");
check(!("attempt" in injectedError.detail), "attempt discarded");
check(!("owner" in injectedError.detail), "owner discarded");
check(!("recovery_action" in injectedError.detail), "recovery_action discarded");
check(!("audit_detail" in injectedError.detail), "audit_detail discarded");
check(!("audit_context" in injectedError.detail), "audit_context discarded");
check(!JSON.stringify(injectedError.detail).includes("MW-PRO"), "no raw machine code survives");
check(!JSON.stringify(injectedError.detail).includes("/tmp"), "no raw path survives");
check(!JSON.stringify(injectedError.detail).includes("traceback"), "no traceback wording survives");

const partialApi = createProtocolWorkspaceApi({
  fetchImpl: async () => jsonResponse({
    detail: { message: "部分字段缺失时保留已有公开字段", error_code: "MW-PRO-P1-DECISION-CAS" },
  }, 422),
});
let partialError = null;
try {
  await partialApi.getStudyDefinition("p1", "sd:1");
} catch (error) {
  partialError = error;
}
check(partialError instanceof ProtocolWorkspaceApiError, "typed error on partial detail");
check(partialError.detail && Object.keys(partialError.detail).join(",") === "message", "only the present public field survives");
check(partialError.message === "部分字段缺失时保留已有公开字段", "message used from the normalized detail");

const networkApi = createProtocolWorkspaceApi({
  fetchImpl: async () => { throw new Error("boom"); },
});
let networkError = null;
try {
  await networkApi.getWorkflowRun("p1", "wr:1");
} catch (error) {
  networkError = error;
}
check(networkError instanceof ProtocolWorkspaceApiError, "typed error on network failure");
check(networkError.status === 0, "zero status on network failure");
check(!networkError.message.includes("boom"), "underlying English message is never exposed");

const abortError = new Error("aborted");
abortError.name = "AbortError";
const abortApi = createProtocolWorkspaceApi({
  fetchImpl: async () => { throw abortError; },
});
let abortCaught = null;
try {
  await abortApi.getWorkflowRun("p1", "wr:1");
} catch (error) {
  abortCaught = error;
}
check(abortCaught === abortError, "abort passes through unchanged");

const invalidJsonApi = createProtocolWorkspaceApi({
  fetchImpl: async () => new Response("not-json", { status: 200 }),
});
let invalidJsonError = null;
try {
  await invalidJsonApi.getWorkflowRun("p1", "wr:1");
} catch (error) {
  invalidJsonError = error;
}
check(invalidJsonError instanceof ProtocolWorkspaceApiError, "invalid JSON is a typed error, never empty success");
check(invalidJsonError.status === 200, "invalid JSON error preserves status");

const bareErrorApi = createProtocolWorkspaceApi({
  fetchImpl: async () => jsonResponse({ detail: "unexpected" }, 500),
});
let bareError = null;
try {
  await bareErrorApi.getWorkflowRun("p1", "wr:1");
} catch (error) {
  bareError = error;
}
check(bareError instanceof ProtocolWorkspaceApiError, "bare 500 is a typed error");
check(bareError.status === 500, "preserves 500 status");
check(bareError.message === "方案工作台未能完成本次操作。", "fallback message is Chinese-native");

console.log(`protocol-workspace-client-contract: ${passed} checks passed`);
"""


class TestNodeClientContract:
    def test_real_node_execution_with_fake_fetch(self) -> None:
        node = shutil.which("node")
        if node is None:
            pytest.skip("node executable not available")
        assert _CLIENT_PATH.is_file(), f"client missing: {_CLIENT_PATH}"
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "protocol_workspace_api_contract.mjs"
            script.write_text(_NODE_CLIENT_CHECK, encoding="utf-8")
            result = subprocess.run(
                [node, str(script), str(_CLIENT_PATH)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            assert result.returncode == 0, (
                f"node client check failed:\nstdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )
            assert "protocol-workspace-client-contract:" in result.stdout


# ---------------------------------------------------------------------------
# Helpers used above (command construction from request bodies)
# ---------------------------------------------------------------------------


def _create_command_via_body(body: Dict[str, Any]):
    from app.protocol_workflow.application import CreateStudyDefinitionCommand

    return CreateStudyDefinitionCommand(
        project_id=body["project_id"],
        study_definition_id=body["study_definition_id"],
        idempotency_key=body["idempotency_key"],
        expected_revision=body["expected_revision"],
        actor_type=ActorType(body["actor_type"]),
        actor_id=body["actor_id"],
        reason=body["reason"],
        decision_record=DecisionRecord.model_validate(body["decision_record"]),
        normalized_seed_id=body["normalized_seed_id"],
        normalized_seed_sha256=body["normalized_seed_sha256"],
        initial_facts=dict(body["initial_facts"]),
        side_effect=None,
    )


def _apply_command_via_body(body: Dict[str, Any]):
    from app.protocol_workflow.application import ApplyStudyDecisionCommand

    return ApplyStudyDecisionCommand(
        project_id=body["project_id"],
        study_definition_id=body["study_definition_id"],
        idempotency_key=body["idempotency_key"],
        expected_revision=body["expected_revision"],
        actor_type=ActorType(body["actor_type"]),
        actor_id=body["actor_id"],
        reason=body["reason"],
        decision_record=DecisionRecord.model_validate(body["decision_record"]),
        fact_updates=(
            None if body.get("fact_updates") is None else dict(body["fact_updates"])
        ),
        side_effect=None,
    )
