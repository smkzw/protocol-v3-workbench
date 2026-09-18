"""Task 1.10 (Worker 03) — cutover state machine + fail-closed mutation guard.

Focused test for the write side of Task 1.10 Worker 03: the per-project
cutover state machine (CAS/idempotency, forward-only, skip/reverse/unknown-
project-reuse/conflicting-replay rejection, project isolation) and the
two-layer fail-closed mutation guard (route layer + service layer), plus the
AST drift check and the rollback helper.  Pure in-memory: no database, no
runtime singleton, no main.py or v2 module edits; the drift check reads the
checked-in sources with deterministic AST discovery.

Covered contracts:

* cutover ladder — exactly LEGACY_ACTIVE -> SHADOW_READ_ONLY -> NEW_CANONICAL;
  initialisation only at the bottom from ``None``; CAS mismatch, skip,
  reverse, same-state, already-terminal, unknown-project-reuse and
  conflicting-replay are rejected with stable typed codes;
* revision idempotency — re-applying the exact ``(revision, expected, new)``
  triple is an idempotent replay (state/history unchanged), reusing a
  revision with different content is a conflicting replay;
* project isolation — per-project records never interact;
* two-layer guard symmetry — every inventoried ``legacy_write`` operation is
  allowed only in LEGACY_ACTIVE and blocked with the same typed stable error
  (``legacy_mutation_blocked``) at both the route and service layers in
  SHADOW_READ_ONLY and NEW_CANONICAL; unknown state and unclassified
  operations fail closed; read_only operations never block;
* no bypass — iterates *all* inventoried route/service legacy_write
  operations and proves each is guarded;
* AST drift detection — unclassified discovered mutators, stale entries,
  method/path mismatch and read-only/GET routes calling legacy-write services
  all fail the drift check on synthetic source, while the real source passes;
* rollback helper — disabling the new command attachment never reverses
  cutover, never re-enables legacy writes, and retains v3 events untouched.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from services.api.app.protocol_workflow.legacy.cutover_state import (
    CutoverRejected,
    CutoverRejectionCode,
    CutoverStateRegistry,
    CutoverTransitionResult,
    CutoverTransitionStatus,
    ProjectCutoverState,
)
from services.api.app.protocol_workflow.legacy.mutation_guard import (
    LEGACY_MUTATION_BLOCKED_CODE,
    LegacyMutationBlocked,
    MutationGuard,
    MutationGuardConfigurationError,
    RollbackHelper,
)
from services.api.app.protocol_workflow.legacy.mutation_route_inventory import (
    InventoryDriftReport,
    MutatorClassification,
    MutationInventory,
    build_inventory,
    verify_inventory_drift,
)

LEGACY_ACTIVE = ProjectCutoverState.LEGACY_ACTIVE
SHADOW = ProjectCutoverState.SHADOW_READ_ONLY
CANONICAL = ProjectCutoverState.NEW_CANONICAL

ROUTE_LEGACY_WRITE_OPS = build_inventory().legacy_write_route_operation_ids()
SERVICE_LEGACY_WRITE_OPS = build_inventory().legacy_write_service_operation_ids()


# ---------------------------------------------------------------------------
# Cutover state machine
# ---------------------------------------------------------------------------


def _registry_at(state: ProjectCutoverState) -> CutoverStateRegistry:
    registry = CutoverStateRegistry()
    registry.apply(
        "PRJ-1",
        expected_state=None,
        new_state=LEGACY_ACTIVE,
        revision="init",
    )
    if state == SHADOW:
        registry.apply("PRJ-1", expected_state=LEGACY_ACTIVE, new_state=SHADOW, revision="r1")
    elif state == CANONICAL:
        registry.apply("PRJ-1", expected_state=LEGACY_ACTIVE, new_state=SHADOW, revision="r1")
        registry.apply("PRJ-1", expected_state=SHADOW, new_state=CANONICAL, revision="r2")
    return registry


def test_ladder_is_exactly_three_forward_states() -> None:
    assert [s.value for s in ProjectCutoverState] == [
        "legacy_active",
        "shadow_read_only",
        "new_canonical",
    ]


def test_initialisation_only_at_ladder_bottom() -> None:
    registry = CutoverStateRegistry()
    result = registry.apply(
        "PRJ-1", expected_state=None, new_state=LEGACY_ACTIVE, revision="init"
    )
    assert result.status == CutoverTransitionStatus.APPLIED
    assert result.state == LEGACY_ACTIVE
    assert result.transition_number == 1
    # unknown project may never start mid-ladder
    for target in (SHADOW, CANONICAL):
        with pytest.raises(CutoverRejected) as exc:
            registry.apply(
                "PRJ-UNKNOWN", expected_state=None, new_state=target, revision="x"
            )
        assert exc.value.code == CutoverRejectionCode.UNKNOWN_PROJECT_REUSE
    # initialising with a non-None expected state on a fresh project is a CAS mismatch
    with pytest.raises(CutoverRejected) as exc:
        registry.apply(
            "PRJ-UNKNOWN",
            expected_state=LEGACY_ACTIVE,
            new_state=LEGACY_ACTIVE,
            revision="x",
        )
    assert exc.value.code == CutoverRejectionCode.CAS_MISMATCH


def test_forward_transition_and_cas() -> None:
    registry = _registry_at(LEGACY_ACTIVE)
    result = registry.apply(
        "PRJ-1", expected_state=LEGACY_ACTIVE, new_state=SHADOW, revision="r1"
    )
    assert result.status == CutoverTransitionStatus.APPLIED
    assert result.state == SHADOW
    assert registry.state_of("PRJ-1") == SHADOW
    # stale CAS after the advance
    with pytest.raises(CutoverRejected) as exc:
        registry.apply("PRJ-1", expected_state=LEGACY_ACTIVE, new_state=SHADOW, revision="r1b")
    assert exc.value.code == CutoverRejectionCode.CAS_MISMATCH
    # the exact applied transition still replays idempotently
    replay = registry.apply(
        "PRJ-1", expected_state=LEGACY_ACTIVE, new_state=SHADOW, revision="r1"
    )
    assert replay.status == CutoverTransitionStatus.IDEMPOTENT_REPLAY
    assert replay.state == SHADOW
    assert registry.transition_number_of("PRJ-1") == 2  # unchanged by replay


def test_skip_rejected() -> None:
    registry = _registry_at(LEGACY_ACTIVE)
    with pytest.raises(CutoverRejected) as exc:
        registry.apply(
            "PRJ-1", expected_state=LEGACY_ACTIVE, new_state=CANONICAL, revision="skip"
        )
    assert exc.value.code == CutoverRejectionCode.SKIP


def test_reverse_rejected() -> None:
    registry = _registry_at(SHADOW)
    with pytest.raises(CutoverRejected) as exc:
        registry.apply("PRJ-1", expected_state=SHADOW, new_state=LEGACY_ACTIVE, revision="rev")
    assert exc.value.code == CutoverRejectionCode.REVERSE


def test_same_state_and_terminal_rejected() -> None:
    registry = _registry_at(LEGACY_ACTIVE)
    with pytest.raises(CutoverRejected) as exc:
        registry.apply("PRJ-1", expected_state=LEGACY_ACTIVE, new_state=LEGACY_ACTIVE, revision="r")
    assert exc.value.code == CutoverRejectionCode.SAME_STATE

    terminal = _registry_at(CANONICAL)
    with pytest.raises(CutoverRejected) as exc:
        terminal.apply("PRJ-1", expected_state=CANONICAL, new_state=CANONICAL, revision="fresh-1")
    assert exc.value.code == CutoverRejectionCode.ALREADY_TERMINAL
    # nothing may advance a terminal project (fresh revision, same result)
    with pytest.raises(CutoverRejected) as exc:
        terminal.apply("PRJ-1", expected_state=CANONICAL, new_state=CANONICAL, revision="fresh-2")
    assert exc.value.code == CutoverRejectionCode.ALREADY_TERMINAL
    # reusing a consumed revision with different content is a conflicting replay
    with pytest.raises(CutoverRejected) as exc:
        terminal.apply("PRJ-1", expected_state=CANONICAL, new_state=CANONICAL, revision="r2")
    assert exc.value.code == CutoverRejectionCode.CONFLICTING_REPLAY


def test_conflicting_replay_rejected() -> None:
    registry = _registry_at(LEGACY_ACTIVE)
    registry.apply("PRJ-1", expected_state=LEGACY_ACTIVE, new_state=SHADOW, revision="r1")
    # same revision, different transition content
    with pytest.raises(CutoverRejected) as exc:
        registry.apply("PRJ-1", expected_state=SHADOW, new_state=CANONICAL, revision="r1")
    assert exc.value.code == CutoverRejectionCode.CONFLICTING_REPLAY
    # fresh revision with correct CAS still applies
    ok = registry.apply("PRJ-1", expected_state=SHADOW, new_state=CANONICAL, revision="r2")
    assert ok.status == CutoverTransitionStatus.APPLIED
    assert ok.state == CANONICAL


def test_revision_idempotency_never_double_applies() -> None:
    registry = _registry_at(LEGACY_ACTIVE)
    first = registry.apply(
        "PRJ-1", expected_state=LEGACY_ACTIVE, new_state=SHADOW, revision="r1"
    )
    before_history = registry.history_of("PRJ-1")
    replay = registry.apply(
        "PRJ-1", expected_state=LEGACY_ACTIVE, new_state=SHADOW, revision="r1"
    )
    assert replay.status == CutoverTransitionStatus.IDEMPOTENT_REPLAY
    assert replay.state == SHADOW
    assert registry.history_of("PRJ-1") == before_history
    assert registry.revision_of("PRJ-1") == "r1"
    assert first.transition_number == 2
    assert replay.transition_number == 2


def test_project_isolation_for_transitions() -> None:
    registry = CutoverStateRegistry()
    registry.apply("PRJ-A", expected_state=None, new_state=LEGACY_ACTIVE, revision="a0")
    registry.apply("PRJ-B", expected_state=None, new_state=LEGACY_ACTIVE, revision="b0")
    registry.apply("PRJ-A", expected_state=LEGACY_ACTIVE, new_state=SHADOW, revision="a1")
    registry.apply("PRJ-A", expected_state=SHADOW, new_state=CANONICAL, revision="a2")
    assert registry.state_of("PRJ-A") == CANONICAL
    assert registry.state_of("PRJ-B") == LEGACY_ACTIVE
    # B can still advance independently even though A is terminal
    b = registry.apply("PRJ-B", expected_state=LEGACY_ACTIVE, new_state=SHADOW, revision="b1")
    assert b.state == SHADOW
    assert registry.history_of("PRJ-A") != registry.history_of("PRJ-B")


def test_state_revision_tracking() -> None:
    registry = _registry_at(CANONICAL)
    assert registry.revision_of("PRJ-1") == "r2"
    assert registry.transition_number_of("PRJ-1") == 3
    history = registry.history_of("PRJ-1")
    assert history == (
        (1, "init", None, LEGACY_ACTIVE),
        (2, "r1", LEGACY_ACTIVE, SHADOW),
        (3, "r2", SHADOW, CANONICAL),
    )
    assert registry.project_ids() == ("PRJ-1",)


def test_guard_state_helpers_fail_closed_on_unknown() -> None:
    guard = MutationGuard(states=CutoverStateRegistry())
    assert guard.state_of("PRJ-UNKNOWN") is None
    assert guard.is_legacy_write_allowed("PRJ-UNKNOWN") is False
    assert guard.inventory.inventory_sha256  # deterministic hash exists


# ---------------------------------------------------------------------------
# Two-layer guard: symmetry, fail-closed, no bypass
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state", [SHADOW, CANONICAL])
def test_route_and_service_guards_are_symmetric(state: ProjectCutoverState) -> None:
    registry = _registry_at(state)
    guard = MutationGuard(states=registry)
    route_op = ROUTE_LEGACY_WRITE_OPS[0]
    service_op = SERVICE_LEGACY_WRITE_OPS[0]
    with pytest.raises(LegacyMutationBlocked) as route_error:
        guard.check_route_mutation("PRJ-1", route_op)
    with pytest.raises(LegacyMutationBlocked) as service_error:
        guard.check_service_mutation("PRJ-1", service_op)
    route_payload = route_error.value.to_payload()
    service_payload = service_error.value.to_payload()
    assert route_payload["code"] == LEGACY_MUTATION_BLOCKED_CODE
    assert service_payload["code"] == LEGACY_MUTATION_BLOCKED_CODE
    assert route_payload["state"] == service_payload["state"] == state.value
    assert route_payload["project_id"] == service_payload["project_id"] == "PRJ-1"
    assert route_payload["layer"] == "route"
    assert service_payload["layer"] == "service"


def test_legacy_write_allowed_only_in_legacy_active() -> None:
    for state in ALL_STATES_AND_UNKNOWN():
        guard = (
            MutationGuard(states=_registry_at(state))
            if state
            else MutationGuard(states=CutoverStateRegistry())
        )
        assert guard.is_legacy_write_allowed("PRJ-1") == (state == LEGACY_ACTIVE)
        route_op = ROUTE_LEGACY_WRITE_OPS[0]
        service_op = SERVICE_LEGACY_WRITE_OPS[0]
        if state == LEGACY_ACTIVE:
            guard.check_route_mutation("PRJ-1", route_op)
            guard.check_service_mutation("PRJ-1", service_op)
        else:
            with pytest.raises(LegacyMutationBlocked):
                guard.check_route_mutation("PRJ-1", route_op)
            with pytest.raises(LegacyMutationBlocked):
                guard.check_service_mutation("PRJ-1", service_op)


def test_no_bypass_for_all_inventoried_route_operations() -> None:
    guard_shadow = MutationGuard(states=_registry_at(SHADOW))
    guard_canonical = MutationGuard(states=_registry_at(CANONICAL))
    guard_active = MutationGuard(states=_registry_at(LEGACY_ACTIVE))
    assert ROUTE_LEGACY_WRITE_OPS, "route legacy_write inventory must not be empty"
    for op in ROUTE_LEGACY_WRITE_OPS:
        guard_active.check_route_mutation("PRJ-1", op)
        with pytest.raises(LegacyMutationBlocked) as shadow_error:
            guard_shadow.check_route_mutation("PRJ-1", op)
        with pytest.raises(LegacyMutationBlocked) as canonical_error:
            guard_canonical.check_route_mutation("PRJ-1", op)
        assert shadow_error.value.code == LEGACY_MUTATION_BLOCKED_CODE
        assert canonical_error.value.code == LEGACY_MUTATION_BLOCKED_CODE
        assert shadow_error.value.state == SHADOW
        assert canonical_error.value.state == CANONICAL


def test_no_bypass_for_all_inventoried_service_operations() -> None:
    guard_shadow = MutationGuard(states=_registry_at(SHADOW))
    guard_canonical = MutationGuard(states=_registry_at(CANONICAL))
    guard_active = MutationGuard(states=_registry_at(LEGACY_ACTIVE))
    assert SERVICE_LEGACY_WRITE_OPS, "service legacy_write inventory must not be empty"
    for op in SERVICE_LEGACY_WRITE_OPS:
        guard_active.check_service_mutation("PRJ-1", op)
        with pytest.raises(LegacyMutationBlocked) as shadow_error:
            guard_shadow.check_service_mutation("PRJ-1", op)
        with pytest.raises(LegacyMutationBlocked) as canonical_error:
            guard_canonical.check_service_mutation("PRJ-1", op)
        assert shadow_error.value.code == LEGACY_MUTATION_BLOCKED_CODE
        assert canonical_error.value.code == LEGACY_MUTATION_BLOCKED_CODE


def test_unknown_cutover_state_fails_closed() -> None:
    guard = MutationGuard(states=CutoverStateRegistry())
    with pytest.raises(LegacyMutationBlocked) as exc:
        guard.check_route_mutation("PRJ-UNKNOWN", ROUTE_LEGACY_WRITE_OPS[0])
    assert exc.value.state is None
    assert exc.value.code == LEGACY_MUTATION_BLOCKED_CODE


def test_unclassified_operation_fails_closed() -> None:
    guard = MutationGuard(states=_registry_at(LEGACY_ACTIVE))
    with pytest.raises(MutationGuardConfigurationError):
        guard.check_route_mutation("PRJ-1", "route.no_such_operation")
    with pytest.raises(MutationGuardConfigurationError):
        guard.check_service_mutation("PRJ-1", "service.no_such_operation")


def test_read_only_and_excluded_operations_never_block() -> None:
    inventory = build_inventory()
    read_only_routes = [
        e.operation_id
        for e in inventory.route_entries
        if e.classification == MutatorClassification.READ_ONLY
    ]
    excluded_routes = [
        e.operation_id
        for e in inventory.route_entries
        if e.classification == MutatorClassification.EXCLUDED
    ]
    assert read_only_routes, "inventory must contain read_only route entries"
    assert excluded_routes, "inventory must contain excluded route entries"
    guard = MutationGuard(states=_registry_at(CANONICAL))
    for op in read_only_routes:
        guard.check_route_mutation("PRJ-1", op)
    for op in excluded_routes:
        guard.check_route_mutation("PRJ-1", op)


# ---------------------------------------------------------------------------
# P1 repair: medical-writing source-intake must be guarded at both layers
# ---------------------------------------------------------------------------

MEDICAL_WRITING_SOURCE_ROUTE = "route.register_medical_writing_investigator_brochure"
MEDICAL_WRITING_SOURCE_SERVICE = (
    "service.source_intake.SourceRegistryService.register_medical_writing_document"
)


def test_no_project_bound_medical_writing_route_is_excluded() -> None:
    """Deterministic invariant: every project-bound legacy ``/medical-writing``
    mutation route must be classified ``legacy_write`` (never ``excluded``),
    so the cutover guard cannot be bypassed by a medical-writing route."""

    inventory = build_inventory()
    offenders = [
        (entry.operation_id, entry.classification.value)
        for entry in inventory.route_entries
        if "/medical-writing/" in entry.path
        and "{project_id}" in entry.path
        and entry.classification == MutatorClassification.EXCLUDED
    ]
    assert offenders == []


def test_medical_writing_source_route_is_legacy_write_and_blocked() -> None:
    inventory = build_inventory()
    entry = inventory.route_entry(MEDICAL_WRITING_SOURCE_ROUTE)
    assert entry is not None
    assert entry.classification == MutatorClassification.LEGACY_WRITE
    assert entry.http_method == "post"
    assert "/medical-writing/sources/investigator-brochure" in entry.path

    guard_shadow = MutationGuard(states=_registry_at(SHADOW))
    guard_canonical = MutationGuard(states=_registry_at(CANONICAL))
    guard_active = MutationGuard(states=_registry_at(LEGACY_ACTIVE))
    # allowed only in LEGACY_ACTIVE
    guard_active.check_route_mutation("PRJ-1", MEDICAL_WRITING_SOURCE_ROUTE)
    # blocked in both read-only states with the one typed stable error
    for guard in (guard_shadow, guard_canonical):
        with pytest.raises(LegacyMutationBlocked) as exc:
            guard.check_route_mutation("PRJ-1", MEDICAL_WRITING_SOURCE_ROUTE)
        assert exc.value.code == LEGACY_MUTATION_BLOCKED_CODE


def test_medical_writing_source_service_is_legacy_write_and_blocked() -> None:
    inventory = build_inventory()
    entry = inventory.service_entry(MEDICAL_WRITING_SOURCE_SERVICE)
    assert entry is not None
    assert entry.classification == MutatorClassification.LEGACY_WRITE
    assert entry.module == "source_intake"
    assert entry.function == "register_medical_writing_document"

    guard_shadow = MutationGuard(states=_registry_at(SHADOW))
    guard_canonical = MutationGuard(states=_registry_at(CANONICAL))
    guard_active = MutationGuard(states=_registry_at(LEGACY_ACTIVE))
    guard_active.check_service_mutation("PRJ-1", MEDICAL_WRITING_SOURCE_SERVICE)
    for guard in (guard_shadow, guard_canonical):
        with pytest.raises(LegacyMutationBlocked) as exc:
            guard.check_service_mutation("PRJ-1", MEDICAL_WRITING_SOURCE_SERVICE)
        assert exc.value.code == LEGACY_MUTATION_BLOCKED_CODE


def test_generic_source_registry_and_monitoring_routes_stay_excluded() -> None:
    """The P1 repair must NOT broaden the cutover guard into the generic
    source-registry (monitoring/eligibility intake) domain."""

    inventory = build_inventory()
    for operation_id in (
        "route.register_protocol_docx_source",
        "route.register_listing_file_source",
        "route.register_raw_subject_bundle_source",
        "route.submit_monitoring_intake",
        "route.apply_monitoring_risk_disposition",
    ):
        entry = inventory.route_entry(operation_id)
        assert entry is not None, operation_id
        assert entry.classification == MutatorClassification.EXCLUDED, operation_id
    guard = MutationGuard(states=_registry_at(CANONICAL))
    for operation_id in (
        "route.register_protocol_docx_source",
        "route.register_listing_file_source",
        "route.submit_monitoring_intake",
    ):
        guard.check_route_mutation("PRJ-1", operation_id)  # passes: out of scope


def test_generic_source_registry_services_stay_excluded() -> None:
    inventory = build_inventory()
    for operation_id in (
        "service.source_intake.SourceRegistryService.register_protocol_docx",
        "service.source_intake.SourceRegistryService.register_listing_file",
        "service.source_intake.SourceRegistryService.register_raw_subject_bundle",
        "service.source_intake.SourceRegistryStore.append",
    ):
        entry = inventory.service_entry(operation_id)
        assert entry is not None, operation_id
        assert entry.classification == MutatorClassification.EXCLUDED, operation_id
    guard = MutationGuard(states=_registry_at(CANONICAL))
    guard.check_service_mutation(
        "PRJ-1", "service.source_intake.SourceRegistryService.register_protocol_docx"
    )


# ---------------------------------------------------------------------------
# AST drift detection
# ---------------------------------------------------------------------------


def ALL_STATES_AND_UNKNOWN():
    yield LEGACY_ACTIVE
    yield SHADOW
    yield CANONICAL
    yield None


def test_real_source_passes_drift_check() -> None:
    report = verify_inventory_drift()
    assert isinstance(report, InventoryDriftReport)
    assert report.ok, report.findings
    assert report.discovered_route_handlers == 235
    assert report.discovered_route_mutators == 133
    assert report.discovered_service_mutators == 195
    assert report.inventoried_route_mutators == report.discovered_route_mutators
    assert report.inventoried_service_mutators == report.discovered_service_mutators
    assert report.findings == ()


def test_drift_check_is_deterministic() -> None:
    first = verify_inventory_drift()
    second = verify_inventory_drift()
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.inventory_sha256 == second.inventory_sha256


def _write(tmp_path: Path, name: str, source: str) -> Path:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return path


def test_unclassified_route_mutator_fails_drift(tmp_path: Path) -> None:
    main = _write(
        tmp_path,
        "main_drift.py",
        """
from fastapi import FastAPI
app = FastAPI()

@app.post("/api/projects/{project_id}/drift-added-route")
def drift_added_route(project_id: str):
    return {"ok": True}
""",
    )
    report = verify_inventory_drift(main_path=main)
    assert not report.ok
    codes = {f.code for f in report.findings}
    assert "unclassified_route_mutator" in codes
    finding = next(
        f for f in report.findings if f.code == "unclassified_route_mutator"
    )
    assert finding.operation_id == "route.drift_added_route"


def test_stale_route_entry_fails_drift(tmp_path: Path) -> None:
    main = _write(
        tmp_path,
        "main_drift.py",
        """
from fastapi import FastAPI
app = FastAPI()

@app.get("/api/health")
def health_drift():
    return {"status": "ok"}
""",
    )
    report = verify_inventory_drift(main_path=main)
    assert not report.ok
    codes = {f.code for f in report.findings}
    assert "stale_route_entry" in codes
    assert "unclassified_route_mutator" not in codes  # no mutation verbs present


def test_read_only_route_calling_legacy_write_fails_drift(tmp_path: Path) -> None:
    main = _write(
        tmp_path,
        "main_drift.py",
        """
from fastapi import FastAPI
app = FastAPI()

@app.post("/api/projects/{project_id}/medical-writing/authoring-journey/impact-preview")
def preview_medical_writing_authoring_impact(project_id: str):
    return medical_writing_authoring_journey_service.commit_stage(project_id)
""",
    )
    report = verify_inventory_drift(main_path=main)
    assert not report.ok
    codes = {f.code for f in report.findings}
    assert "read_only_route_calls_legacy_write" in codes


def test_get_route_calling_legacy_write_fails_drift(tmp_path: Path) -> None:
    main = _write(
        tmp_path,
        "main_drift.py",
        """
from fastapi import FastAPI
app = FastAPI()

@app.get("/api/projects/{project_id}/drift-read")
def drift_read_route(project_id: str):
    return medical_writing_authoring_journey_service.commit_stage(project_id)
""",
    )
    report = verify_inventory_drift(main_path=main)
    assert not report.ok
    codes = {f.code for f in report.findings}
    assert "read_route_calls_legacy_write" in codes
    assert "unclassified_route_mutator" in codes


def test_unclassified_service_mutator_fails_drift(tmp_path: Path) -> None:
    service = _write(
        tmp_path,
        "drift_service.py",
        """
import sqlite3

def drift_writer(conn: sqlite3.Connection, project_id: str) -> None:
    conn.execute("INSERT INTO drift_rows (project_id) VALUES (?)", (project_id,))
""",
    )
    report = verify_inventory_drift(service_modules=[service])
    assert not report.ok
    codes = {f.code for f in report.findings}
    assert "unclassified_service_mutator" in codes
    finding = next(f for f in report.findings if f.code == "unclassified_service_mutator")
    assert finding.operation_id == "service.drift_service.drift_writer"
    assert "stale_service_entry" in codes


def test_route_entry_mismatch_fails_drift(tmp_path: Path) -> None:
    # the inventoried function save_medical_writing_working_copy is registered
    # here with a different method/path than its curated entry
    main = _write(
        tmp_path,
        "main_drift.py",
        """
from fastapi import FastAPI
app = FastAPI()

@app.put("/api/projects/{project_id}/wrong-path")
def save_medical_writing_working_copy(project_id: str):
    return {"ok": True}
""",
    )
    report = verify_inventory_drift(main_path=main)
    assert not report.ok
    codes = {f.code for f in report.findings}
    assert "route_entry_mismatch" in codes


# ---------------------------------------------------------------------------
# Rollback helper
# ---------------------------------------------------------------------------


def test_rollback_helper_never_reverses_cutover() -> None:
    registry = _registry_at(CANONICAL)
    guard = MutationGuard(states=registry)
    helper = RollbackHelper()

    assert helper.is_new_command_attachment_enabled() is True
    helper.disable_new_command_attachment()
    assert helper.is_new_command_attachment_enabled() is False

    # cutover state untouched by the rollback helper
    assert registry.state_of("PRJ-1") == CANONICAL
    assert registry.transition_number_of("PRJ-1") == 3
    assert registry.revision_of("PRJ-1") == "r2"

    # legacy fact writes remain blocked after rollback
    with pytest.raises(LegacyMutationBlocked):
        guard.check_route_mutation("PRJ-1", ROUTE_LEGACY_WRITE_OPS[0])

    # the helper exposes no cutover-reversal capability at all
    for forbidden in ("apply", "reverse", "reactivate", "rollback_state", "advance"):
        assert not hasattr(helper, forbidden)


def test_rollback_helper_retains_v3_events() -> None:
    helper = RollbackHelper()
    events = [
        {"event_type": "study_definition.created", "revision": 1, "payload": {"a": 1}},
        {"event_type": "study_definition.decision_applied", "revision": 2},
    ]
    snapshot = copy.deepcopy(events)
    retained = helper.retain_v3_events(events)
    assert retained == tuple(events)
    assert events == snapshot  # caller input untouched
    # returned events are immutable
    with pytest.raises(TypeError):
        retained[0]["revision"] = 99  # type: ignore[index]
    with pytest.raises(TypeError):
        retained[0]["payload"].update({"b": 2})  # type: ignore[attr-defined]


def test_rollback_helper_does_not_reactivate_legacy_writes() -> None:
    registry = _registry_at(SHADOW)
    guard = MutationGuard(states=registry)
    helper = RollbackHelper()
    helper.disable_new_command_attachment()
    # even with the attachment disabled, the service layer still blocks
    with pytest.raises(LegacyMutationBlocked):
        guard.check_service_mutation("PRJ-1", SERVICE_LEGACY_WRITE_OPS[0])
    with pytest.raises(LegacyMutationBlocked):
        guard.check_route_mutation("PRJ-1", ROUTE_LEGACY_WRITE_OPS[0])


# ---------------------------------------------------------------------------
# Inventory integrity
# ---------------------------------------------------------------------------


def test_inventory_entry_shape_and_stability() -> None:
    inventory = build_inventory()
    entries = inventory.route_entries + inventory.service_entries
    assert entries
    ids = [entry.operation_id for entry in entries]
    assert len(ids) == len(set(ids)), "operation ids must be unique"
    for entry in entries:
        assert entry.justification  # every entry resolves a stable justification
        assert entry.classification in {
            MutatorClassification.LEGACY_WRITE,
            MutatorClassification.READ_ONLY,
            MutatorClassification.EXCLUDED,
        }
    # deterministic inventory hash (permutation-stable)
    again = build_inventory()
    assert inventory.inventory_sha256 == again.inventory_sha256


def test_cutover_transition_result_is_strict() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CutoverTransitionResult(
            project_id="",
            state=LEGACY_ACTIVE,
            status=CutoverTransitionStatus.APPLIED,
            revision="r",
            transition_number=1,
        )
    with pytest.raises(ValidationError):
        CutoverTransitionResult(
            project_id="PRJ-1",
            state=LEGACY_ACTIVE,
            status=CutoverTransitionStatus.APPLIED,
            revision="",
            transition_number=1,
        )
