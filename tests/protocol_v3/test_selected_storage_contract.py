"""Contract tests for the Task 1.8 selected-storage surface.

These tests prove, without touching a live database and without importing the
PoC adapters:

* **selection identity** — the frozen backend, version gate, licence and
  evidence digests, cross-checked against the recorded candidate JSON;
* **capabilities** — evidence-backed capability record with fail-closed
  ``require``;
* **explicit test-memory route** — the in-memory implementation is reachable
  only through the named test function and is rejected by the production
  factory;
* **fail-closed configuration** — absent/empty/unknown configuration raises
  instead of defaulting;
* **no silent fallback** — the production factory never switches backend and
  never degrades to memory or to the non-selected PostgreSQL candidate;
* **factory injection** — an injected/fake builder is honoured when the product
  driver is intentionally unavailable, and a missing builder fails closed with
  the exact blocker;
* **no database-private leakage** — ``selected.py`` contains no driver imports,
  no SQL text, no journal-file semantics and no PoC imports.

These are functional contract tests, not security tests (per the Task 1.8 risk
boundaries).
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from packages.contracts.workbench_contracts.protocol_v3 import StudyDefinitionV3

from app.protocol_workflow.storage.selected import (
    BackendRoles,
    StorageCapabilityError,
    StorageConfigurationError,
    StorageNotReadyError,
    StorageSelectionError,
    create_test_memory_unit_of_work_factory,
    create_unit_of_work_factory,
    get_selected_storage,
    readiness_report,
)
from pocs.protocol_v3.storage.memory_adapter import (
    UnsupportedCapabilityError,
    build_memory_backend,
)

_SELECTED_MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "services"
    / "api"
    / "app"
    / "protocol_workflow"
    / "storage"
    / "selected.py"
)
_POC_RESULTS = (
    Path(__file__).resolve().parents[2] / "pocs" / "protocol_v3" / "storage" / "results"
)

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
_PROJ = "proj:selected:001"


def _sha(n: int = 0) -> str:
    return f"{n:064x}"


def _study(*, study_id: str = "sd:selected:1", revision: int = 1) -> StudyDefinitionV3:
    return StudyDefinitionV3(
        study_definition_id=study_id,
        project_id=_PROJ,
        revision=revision,
        previous_revision_sha256=None if revision == 1 else _sha(revision - 1),
        normalized_seed_id="seed:selected:1",
        normalized_seed_sha256=_sha(1),
        facts={"indication": "selected-storage"},
        updated_at=_T0,
    )


# ---------------------------------------------------------------------------
# Selection identity and capabilities
# ---------------------------------------------------------------------------


def test_selected_backend_identity() -> None:
    selected = get_selected_storage()
    assert selected.backend == "sqlite"
    assert selected.candidate_identity == "sqlite_3_53_1"
    assert selected.engine_name == "SQLite"
    assert selected.engine_version == "3.53.1"
    # 3.51.0-3.51.2 contain the multi-connection reset defect; the gate is
    # the fail-closed minimum.
    assert selected.min_engine_version == (3, 51, 3)
    assert selected.driver
    assert selected.license == "public domain (SQLite)"
    assert Path(selected.decision_path).is_file()
    assert selected.evidence_digests["sqlite"].startswith("64a56f66")
    assert selected.evidence_digests["postgresql"].startswith("fce59b62")
    # The decision record exists and declares the selection.
    decision_text = Path(selected.decision_path).read_text(encoding="utf-8")
    assert "SQLite 3.53.1" in decision_text
    assert "64a56f66e4300b318f6586803151f475e2ad8de9a74d0acfad14fe46a81adad8" in decision_text
    assert "fce59b62be3dc94d069affe9c76cdd0d9f41e8340459cb9fc9336ff96fde8630" in decision_text
    # Roles are documented for every known backend.
    assert BackendRoles[selected.backend]
    assert "postgresql" in BackendRoles
    assert "memory" in BackendRoles


def test_selected_identity_matches_recorded_candidate_evidence() -> None:
    """The surface's identity and digests match the recorded PoC result JSON.

    Also proves the cross-candidate consistency claim: all eight deterministic
    invariant bodies are byte-equal between the SQLite and PostgreSQL
    candidates, so the selection is grounded in identical semantics.
    """
    selected = get_selected_storage()
    sqlite_json = json.loads((_POC_RESULTS / "sqlite_candidate.json").read_text(encoding="utf-8"))
    postgres_json = json.loads(
        (_POC_RESULTS / "postgresql_candidate.json").read_text(encoding="utf-8")
    )

    assert sqlite_json["all_passed"] is True
    assert postgres_json["all_passed"] is True
    assert sqlite_json["deterministic_digest"] == selected.evidence_digests["sqlite"]
    assert postgres_json["deterministic_digest"] == selected.evidence_digests["postgresql"]

    frozen_workload = {"writers": 8, "cas_operations": 1000, "events": 10000}
    for name in frozen_workload:
        assert sqlite_json["workload"][name] == frozen_workload[name]
        assert postgres_json["workload"][name] == frozen_workload[name]

    sqlite_det = {inv["name"]: inv["deterministic"] for inv in sqlite_json["invariants"]}
    postgres_det = {inv["name"]: inv["deterministic"] for inv in postgres_json["invariants"]}
    assert set(sqlite_det) == set(postgres_det) == {
        "cas_concurrency",
        "event_chain",
        "transaction_outbox_atomicity",
        "checkpoint_isolation",
        "migration_quarantine",
        "crash_recovery",
        "backup_restore_replay",
        "rollback_to_snapshot",
    }
    for name, payload in sqlite_det.items():
        assert payload == postgres_det[name], f"deterministic body differs for {name}"


def test_capabilities_are_evidence_backed() -> None:
    caps = get_selected_storage().capabilities
    # Bound to accepted PoC evidence (8/8 invariants; RPO 0; SIGKILL-verified
    # crash recovery; exact backup/restore/replay hash; 100% migration
    # accounting with quarantine).
    assert caps.durable is True
    assert caps.backup_restore is True
    assert caps.crash_recovery is True
    assert caps.rollback_to_snapshot is True
    assert caps.migration_accounting is True
    assert caps.rpo_zero is True
    assert caps.cross_process is True
    # SQLite is a correct single-writer serialized model, not true MVCC.
    assert caps.concurrent_writers is False

    caps.require(
        "durable",
        "backup_restore",
        "crash_recovery",
        "rollback_to_snapshot",
        "migration_accounting",
        "rpo_zero",
        "cross_process",
    )
    # Fail closed: unsupported and unknown capabilities must not silently pass.
    with pytest.raises(StorageCapabilityError):
        caps.require("concurrent_writers")
    with pytest.raises(StorageConfigurationError):
        caps.require("no_such_capability")


# ---------------------------------------------------------------------------
# Factory: explicit test-memory route
# ---------------------------------------------------------------------------


def test_explicit_test_memory_route_is_functional() -> None:
    factory = create_test_memory_unit_of_work_factory()
    uow = factory()
    assert uow.is_active is False

    with uow:
        assert uow.is_active is True
        cas = uow.study_definition_cas_repository
        assert cas is not None
        cas.save_with_expected_revision(_PROJ, _study(), expected_revision=0)

    # Commit path: the saved aggregate is readable after the scope closes.
    repo = uow.study_definition_repository
    assert repo is not None
    assert repo.get_current_revision(_PROJ, "sd:selected:1") == 1

    # Rollback path: an exception inside the scope discards the mutation.
    uow2 = factory()
    with pytest.raises(ValueError):
        with uow2:
            cas2 = uow2.study_definition_cas_repository
            assert cas2 is not None
            cas2.save_with_expected_revision(
                _PROJ, _study(study_id="sd:selected:2"), expected_revision=0
            )
            raise ValueError("force rollback")
    repo2 = uow2.study_definition_repository
    assert repo2 is not None
    assert repo2.get_current_revision(_PROJ, "sd:selected:2") is None


def test_production_factory_rejects_memory_backend() -> None:
    # The test-memory route is explicit; the production factory must refuse
    # 'memory' even when handed a builder, so a test fallback can never leak
    # into production wiring.
    with pytest.raises(StorageSelectionError):
        create_unit_of_work_factory(
            config={"backend": "memory"},
            adapter_builder=lambda config: create_test_memory_unit_of_work_factory(),
        )


# ---------------------------------------------------------------------------
# Factory: fail-closed configuration
# ---------------------------------------------------------------------------


def test_absent_config_fail_closed() -> None:
    with pytest.raises(StorageConfigurationError):
        create_unit_of_work_factory()  # no config at all
    with pytest.raises(StorageConfigurationError):
        create_unit_of_work_factory(config={})
    with pytest.raises(StorageConfigurationError):
        create_unit_of_work_factory(config={"path": "/tmp/whatever.db"})  # no 'backend'


def test_unknown_backend_fail_closed() -> None:
    with pytest.raises(StorageConfigurationError):
        create_unit_of_work_factory(config={"backend": "oracle"})
    # Even a builder that would happily return a factory must not be invoked
    # for an unknown backend.
    def explode_builder(config):
        raise AssertionError("builder must not be invoked for a non-selected backend")

    with pytest.raises(StorageConfigurationError):
        create_unit_of_work_factory(
            config={"backend": "unknown"},
            adapter_builder=explode_builder,
        )


def test_no_silent_fallback_to_postgresql_candidate() -> None:
    # PostgreSQL passed the PoC thresholds but is NOT the selected backend;
    # requesting it must fail closed even when a builder is supplied.
    with pytest.raises(StorageSelectionError):
        create_unit_of_work_factory(
            config={"backend": "postgresql", "dsn": "host=/tmp"},
            adapter_builder=lambda config: create_test_memory_unit_of_work_factory(),
        )


def test_no_silent_fallback_without_builder() -> None:
    # The product adapter is intentionally unavailable in Task 1.8: the
    # factory must raise an actionable blocker instead of degrading to memory.
    with pytest.raises(StorageNotReadyError) as excinfo:
        create_unit_of_work_factory(config={"backend": "sqlite", "path": "/tmp/x.db"})
    message = str(excinfo.value)
    assert "sqlite.py" in message
    assert "pocs" in message
    assert "Codex follow-up" in message


def test_factory_with_injected_builder() -> None:
    calls: list = []

    def fake_builder(config):
        calls.append(dict(config))
        return lambda: "fake-uow-factory"

    factory = create_unit_of_work_factory(
        config={"backend": "sqlite", "path": "/tmp/x.db"},
        adapter_builder=fake_builder,
    )
    assert factory() == "fake-uow-factory"
    assert calls == [{"backend": "sqlite", "path": "/tmp/x.db"}]

    # A builder returning None is treated as not ready — fail closed.
    with pytest.raises(StorageNotReadyError):
        create_unit_of_work_factory(
            config={"backend": "sqlite"},
            adapter_builder=lambda config: None,
        )


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


def test_readiness_report_fail_closed_until_wired() -> None:
    report = readiness_report()
    assert report["backend"] == "sqlite"
    assert report["status"] == "not_ready"
    assert report["blockers"]
    assert "sqlite.py" in report["blockers"][0]
    assert report["candidate_identity"] == "sqlite_3_53_1"

    ready = readiness_report(adapter_builder=lambda config: lambda: "fake")
    assert ready["status"] == "ready"
    assert ready["blockers"] == []


# ---------------------------------------------------------------------------
# No database-private leakage from selected.py
# ---------------------------------------------------------------------------


def test_no_database_private_leakage_from_selected_surface() -> None:
    """``selected.py`` must stay storage-neutral: no driver imports at module
    level, no SQL text, no journal-file semantics, no PoC imports."""
    source = _SELECTED_MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    def enclosing_function(node: ast.AST) -> str | None:
        for candidate in ast.walk(tree):
            if isinstance(candidate, ast.FunctionDef) and any(
                child is node for child in ast.walk(candidate)
            ):
                return candidate.name
        return None

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        modules = (
            [alias.name for alias in node.names]
            if isinstance(node, ast.Import)
            else [node.module or ""]
        )
        fn = enclosing_function(node)
        if fn is None:
            # Module scope (top level or the TYPE_CHECKING block): must be
            # storage-neutral — no driver, no PoC, no in-memory import.
            for module in modules:
                assert not (module == "sqlite3" or module.startswith("sqlite3.")), module
                assert not (module == "psycopg" or module.startswith("psycopg.")), module
                assert not module.startswith("pocs"), module
                assert not module.startswith("app.protocol_workflow.storage.memory"), module
        else:
            # Function scope: the ONLY permitted function-level import is the
            # explicit test-memory route.
            assert fn == "create_test_memory_unit_of_work_factory", (fn, modules)
            for module in modules:
                assert module == "app.protocol_workflow.storage.memory", module

    # No SQL or driver tokens anywhere in the module source.
    for token in (
        "psycopg",
        "import sqlite3",
        "from sqlite3",
        "pocs.protocol_v3",
        "WAL",
        "SHM",
        "BEGIN ",
        "SELECT ",
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "CREATE TABLE",
        "SAVEPOINT",
        "COMMIT",
        ".wal",
        ".shm",
    ):
        assert token not in source, f"database-private token {token!r} leaked into selected.py"


# ---------------------------------------------------------------------------
# Memory candidate executable receipt (Repair B / C)
# ---------------------------------------------------------------------------

_MEMORY_CANDIDATE_JSON = _POC_RESULTS / "memory_candidate.json"
_MEMORY_EXPECTED_DIGEST = (
    "8fc8a060a7ab1d27f1f780287e0895c97c7f76b49f8bb5b5226ee7423fc84a7b"
)
_MEMORY_UNSUPPORTED = {
    "crash_recovery",
    "backup_restore_replay",
    "rollback_to_snapshot",
}
_MEMORY_SUPPORTED = {
    "cas_concurrency",
    "event_chain",
    "transaction_outbox_atomicity",
    "checkpoint_isolation",
    "migration_quarantine",
}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _recompute_digest(receipt: dict) -> str:
    """Same payload recipe as ``BenchmarkResult.deterministic_digest``."""
    evidence = {
        "candidate": receipt["candidate"],
        "workload": receipt["workload"],
        "invariants": [
            {
                "name": inv["name"],
                "passed": inv["passed"],
                "deterministic": inv["deterministic"],
                "error": inv["error"],
            }
            for inv in receipt["invariants"]
        ],
    }
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_memory_receipt_digest_recomputes_exactly() -> None:
    """The emitted memory candidate receipt is deterministic and its digest
    recomputes exactly (Repair C requirement 1)."""
    assert _MEMORY_CANDIDATE_JSON.is_file(), "missing results/memory_candidate.json"
    receipt = _load_json(_MEMORY_CANDIDATE_JSON)
    assert receipt["candidate"] == "memory"
    assert receipt["all_passed"] is False
    assert receipt["deterministic_digest"] == _MEMORY_EXPECTED_DIGEST
    assert _recompute_digest(receipt) == receipt["deterministic_digest"]
    # Workload matches the frozen threshold, same as the durable candidates.
    for name, value in (("writers", 8), ("cas_operations", 1000), ("events", 10000)):
        assert receipt["workload"][name] == value


def test_memory_candidate_exactly_three_durable_invariants_fail_closed() -> None:
    """Exactly the three named durable invariants fail closed with stable
    unsupported-capability errors; the five supported ones pass; nothing is
    skipped or silently passed (Repair C requirement 2)."""
    receipt = _load_json(_MEMORY_CANDIDATE_JSON)
    by_name = {inv["name"]: inv for inv in receipt["invariants"]}
    assert set(by_name) == _MEMORY_SUPPORTED | _MEMORY_UNSUPPORTED

    failed = {name for name, inv in by_name.items() if not inv["passed"]}
    passed = {name for name, inv in by_name.items() if inv["passed"]}
    assert failed == _MEMORY_UNSUPPORTED
    assert passed == _MEMORY_SUPPORTED

    for name in sorted(_MEMORY_UNSUPPORTED):
        inv = by_name[name]
        assert inv["passed"] is False
        assert inv["deterministic"] == {}
        assert isinstance(inv["error"], str) and inv["error"].startswith(
            "UnsupportedCapabilityError:"
        )

    # The fail-closed errors are stable across the adapter and the receipt
    # (the suite prefixes the recorded error with the exception type name).
    backend = build_memory_backend()
    with pytest.raises(UnsupportedCapabilityError) as excinfo:
        backend.backup_to(Path("/tmp/unused.db"))
    assert f"UnsupportedCapabilityError: {excinfo.value}" == by_name["backup_restore_replay"]["error"]
    assert f"UnsupportedCapabilityError: {excinfo.value}" == by_name["rollback_to_snapshot"]["error"]
    with pytest.raises(UnsupportedCapabilityError) as excinfo:
        backend.spawn_crash_child({}, Path("/tmp"))
    assert f"UnsupportedCapabilityError: {excinfo.value}" == by_name["crash_recovery"]["error"]
    # The three messages are stable and explicit.  backup_restore_replay and
    # rollback_to_snapshot both fail on the same first unsupported call
    # (backup_to), so their recorded errors are identical by design — stability
    # per invariant is what matters, not pairwise distinctness.
    errors = {by_name[n]["error"] for n in _MEMORY_UNSUPPORTED}
    assert all(errors)
    assert "spawn_crash_child" in by_name["crash_recovery"]["error"]
    assert "backup_to" in by_name["backup_restore_replay"]["error"]
    assert "backup_to" in by_name["rollback_to_snapshot"]["error"]


def test_memory_supported_bodies_do_not_contradict_durable_candidates() -> None:
    """The five supported memory deterministic bodies match the accepted
    SQLite/PostgreSQL bodies field-for-field (JSON-normalised).  Any
    backend-specific observation would have to be documented here, not
    deleted from the suite (Repair C requirement 3)."""
    memory = _load_json(_MEMORY_CANDIDATE_JSON)
    sqlite = _load_json(_POC_RESULTS / "sqlite_candidate.json")
    postgres = _load_json(_POC_RESULTS / "postgresql_candidate.json")

    def bodies(receipt: dict) -> dict:
        return {inv["name"]: inv["deterministic"] for inv in receipt["invariants"]}

    mem, sq, pg = bodies(memory), bodies(sqlite), bodies(postgres)
    for name in sorted(_MEMORY_SUPPORTED):
        assert mem[name] == sq[name], f"memory vs sqlite deterministic differs for {name}"
        assert mem[name] == pg[name], f"memory vs postgres deterministic differs for {name}"


def test_no_product_file_imports_pocs() -> None:
    """No product (services/api, packages) file imports the PoC package
    (Repair C requirement 5, product side)."""
    root = Path(__file__).resolve().parents[2]
    pattern = re.compile(r"^\s*(?:import pocs\b|from pocs\b)", re.MULTILINE)
    offenders: list[str] = []
    for base in ("services/api", "packages"):
        base_path = root / base
        if not base_path.is_dir():
            continue
        for path in base_path.rglob("*.py"):
            if "__pycache__" in str(path):
                continue
            if pattern.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(root)))
    assert offenders == [], f"product files importing pocs: {offenders}"
