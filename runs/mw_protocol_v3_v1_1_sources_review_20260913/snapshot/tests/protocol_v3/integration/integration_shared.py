"""Shared synthetic builders for Protocol v3 Task 1R.3 integration tests.

Scope: real product SQLite adapter (``storage.sqlite``) + ``ApplicationService``
only.  All identities are synthetic (``proj:1r3:*`` / ``sd:1r3:*``) and every
database lives in a pytest tmp directory.  No live, monitoring, model, OCR,
translation, Word, network or history surfaces are touched.

This module deliberately imports no pytest so that separate-process readers
(subprocess reopen checks) can reuse the fingerprint helpers.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

ROOT = Path(__file__).resolve().parents[3]

T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

SEED_ID = "seed:1r3:1"
SEED_SHA = "c" * 64
FACTS: Dict[str, Any] = {
    "picos.population.indication": "中重度活动性溃疡性结肠炎",
    "picos.intervention.dose": "10 mg 每日一次",
}
NEW_FACT: Dict[str, Any] = {"picos.population.age": "成人"}
ACTOR_ID = "user:medical-writer"
REASON = "接受 AI 推荐的默认剂量设计。"
ADMITTED_AT = "2026-01-01T00:00:00+00:00"

BUSINESS_TABLES = (
    "schema_version",
    "aggregate_revision",
    "event_stream",
    "outbox_message",
    "inbox_result",
    "execution_reservation",
    "read_chapter_coverage",
    "read_decision_graph",
    "read_workflow_run_status",
    "protocol_workflow_project_allowlist",
)

PUBLIC_ENVELOPE_KEYS = {"message", "responsible_area", "can_retry", "next_step"}


def make_factory(db_path: Path) -> Callable[[], Any]:
    """Product SQLite unit-of-work factory over a test-owned tmp file."""

    from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory

    return build_unit_of_work_factory(
        {"backend": "sqlite", "path": str(db_path)}
    )


def make_service(factory: Callable[[], Any], clock: Optional[Callable[[], datetime]] = None) -> Any:
    """ApplicationService with a fixed clock for deterministic evidence."""

    from app.protocol_workflow.application import ApplicationService

    return ApplicationService(
        unit_of_work_factory=factory, clock=clock or (lambda: T0)
    )


def admit(db_path: Path, project_id: str, admitted_at: str = ADMITTED_AT) -> bool:
    """Durably admit a synthetic project with a fixed timestamp."""

    from app.protocol_workflow.storage.sqlite import admit_project

    return admit_project(
        {"backend": "sqlite", "path": str(db_path)},
        project_id,
        admitted_at=admitted_at,
    )


def genesis_snapshot(
    *,
    study_definition_id: str,
    project_id: str,
    facts: Optional[Mapping[str, Any]] = None,
) -> str:
    from app.protocol_workflow.application import (
        study_definition_genesis_snapshot,
    )

    return study_definition_genesis_snapshot(
        study_definition_id=study_definition_id,
        project_id=project_id,
        normalized_seed_id=SEED_ID,
        normalized_seed_sha256=SEED_SHA,
        facts=dict(facts) if facts is not None else dict(FACTS),
        decided_at=T0,
    )


def make_decision(
    *,
    decision_record_id: str,
    decision_key: str,
    snapshot_sha256: str,
    expected_state_revision: int,
    reason: str = REASON,
    selected_option_id: str = "option:dose:001",
) -> Any:
    from packages.contracts.workbench_contracts.protocol_v3 import (
        ActorType,
        CanonicalState,
        DecisionRecord,
    )

    return DecisionRecord(
        decision_record_id=decision_record_id,
        decision_key=decision_key,
        snapshot_sha256=snapshot_sha256,
        expected_state_revision=expected_state_revision,
        state_revision=expected_state_revision + 1,
        option_ids=("option:dose:001", "option:dose:002"),
        selected_option_id=selected_option_id,
        actor_type=ActorType.USER,
        actor_id=ACTOR_ID,
        reason=reason,
        decided_at=T0,
        canonical_state=CanonicalState.CONFIRMED,
    )


def side_effect_spec(
    *,
    workflow_run_id: str = "wr:1r3:1",
) -> Any:
    from packages.contracts.workbench_contracts.protocol_v3 import SideEffectKind
    from app.protocol_workflow.application.commands import SideEffectSpec

    return SideEffectSpec(
        workflow_run_id=workflow_run_id,
        side_effect_kind=SideEffectKind.CANONICAL_PROPOSAL,
    )


def create_command(
    *,
    project_id: str,
    study_definition_id: str,
    idempotency_key: str,
    facts: Optional[Mapping[str, Any]] = None,
    side_effect: Any = None,
    decision_record_id: str = "decision:1r3:create:001",
    decision_key: str = "decision:create",
    reason: str = REASON,
) -> Any:
    from app.protocol_workflow.application import CreateStudyDefinitionCommand
    from packages.contracts.workbench_contracts.protocol_v3 import ActorType

    snapshot = genesis_snapshot(
        study_definition_id=study_definition_id,
        project_id=project_id,
        facts=facts,
    )
    decision = make_decision(
        decision_record_id=decision_record_id,
        decision_key=decision_key,
        snapshot_sha256=snapshot,
        expected_state_revision=0,
        reason=reason,
    )
    return CreateStudyDefinitionCommand(
        project_id=project_id,
        study_definition_id=study_definition_id,
        idempotency_key=idempotency_key,
        expected_revision=0,
        actor_type=ActorType.USER,
        actor_id=ACTOR_ID,
        reason=reason,
        decision_record=decision,
        normalized_seed_id=SEED_ID,
        normalized_seed_sha256=SEED_SHA,
        initial_facts=dict(facts) if facts is not None else dict(FACTS),
        side_effect=side_effect,
    )


def apply_command(
    *,
    project_id: str,
    study_definition_id: str,
    idempotency_key: str,
    expected_revision: int,
    snapshot_sha256: str,
    decision_record_id: str,
    decision_key: str = "decision:dose",
    fact_updates: Optional[Mapping[str, Any]] = None,
    side_effect: Any = None,
    reason: str = REASON,
) -> Any:
    from app.protocol_workflow.application import ApplyStudyDecisionCommand
    from packages.contracts.workbench_contracts.protocol_v3 import ActorType

    decision = make_decision(
        decision_record_id=decision_record_id,
        decision_key=decision_key,
        snapshot_sha256=snapshot_sha256,
        expected_state_revision=expected_revision,
        reason=reason,
    )
    return ApplyStudyDecisionCommand(
        project_id=project_id,
        study_definition_id=study_definition_id,
        idempotency_key=idempotency_key,
        expected_revision=expected_revision,
        actor_type=ActorType.USER,
        actor_id=ACTOR_ID,
        reason=reason,
        decision_record=decision,
        fact_updates=dict(fact_updates) if fact_updates is not None else None,
        side_effect=side_effect,
    )


def fingerprint_dict(service: Any, project_id: str, study_definition_id: str) -> Dict[str, Any]:
    """JSON-safe canonical fingerprint: revision hash, state, lineage, stream head."""

    from app.protocol_workflow.application import (
        GetStudyDefinitionEventSummaryQuery,
        GetStudyDefinitionQuery,
    )

    current = service.get_study_definition(
        GetStudyDefinitionQuery(
            project_id=project_id, study_definition_id=study_definition_id
        )
    )
    summary = service.get_study_definition_event_summary(
        GetStudyDefinitionEventSummaryQuery(
            project_id=project_id, study_definition_id=study_definition_id
        )
    )
    definition = current.definition
    return {
        "project_id": project_id,
        "study_definition_id": study_definition_id,
        "revision": current.revision,
        "revision_sha256": current.revision_sha256,
        "canonical_state": (
            None if definition is None else definition.canonical_state.value
        ),
        "facts": None if definition is None else dict(definition.facts),
        "decision_record_ids": (
            None if definition is None else list(definition.decision_record_ids)
        ),
        "event_count": summary.event_count,
        "last_sequence": summary.last_sequence,
        "last_event_sha256": summary.last_event_sha256,
        "decisions": [
            {
                "cas_identity": item.cas_identity,
                "decision_record_id": item.decision_record_id,
                "decision_key": item.decision_key,
                "selected_option_id": item.selected_option_id,
                "state_revision": item.state_revision,
                "applied_revision": item.applied_revision,
                "canonical_state": item.canonical_state.value,
                "decided_at": item.decided_at.isoformat(),
            }
            for item in summary.decisions
        ],
    }


def outbox_rows(db_path: Path, project_id: str) -> List[tuple]:
    """Raw outbox rows for a project: (logical_key, payload_sha256, status)."""

    conn = sqlite3.connect(str(db_path))
    try:
        return [
            tuple(row)
            for row in conn.execute(
                "SELECT logical_key, payload_sha256, status FROM outbox_message "
                "WHERE project_id=? ORDER BY logical_key",
                (project_id,),
            ).fetchall()
        ]
    finally:
        conn.close()


def dump_business_tables(db_path: Path) -> Dict[str, List[tuple]]:
    """Ordered raw dump of every product-owned table (logical content)."""

    conn = sqlite3.connect(str(db_path))
    try:
        dump: Dict[str, List[tuple]] = {}
        for table in BUSINESS_TABLES:
            dump[table] = [
                tuple(row)
                for row in conn.execute(
                    f'SELECT * FROM "{table}" ORDER BY rowid'
                ).fetchall()
            ]
        return dump
    finally:
        conn.close()


def integrity_check(db_path: Path) -> str:
    conn = sqlite3.connect(str(db_path))
    try:
        return str(
            conn.execute("PRAGMA integrity_check").fetchone()[0]
        )
    finally:
        conn.close()


def wal_path(db_path: Path) -> Path:
    return Path(str(db_path) + "-wal")


def db_file_names(db_path: Path) -> List[str]:
    """Names of the database file family in its directory (db/-wal/-shm)."""

    return sorted(
        entry.name
        for entry in db_path.parent.iterdir()
        if entry.name == db_path.name or entry.name.startswith(db_path.name + "-")
    )
