"""Protocol v3 Task 1R.2 — actual-main mount, default-off, durable allowlist.

Red-first composition tests (implement.md step 3). The composition root under
``app.protocol_workflow.api.composition`` is the ONLY new-chain wiring the
shared ``main.py`` may reference (single ``mount_protocol_workflow_router``
call); the router factory, service injection and coordinator semantics are
unchanged.

Contract under test
-------------------
* Default-off: mounting with the flag absent is a no-op — no new routes, no
  database file, no worker thread, legacy 422 behaviour byte-identical.
* Explicit enable without a database path fails closed (names the env var).
* Empty allowlist / non-admitted projects are rejected with the stable
  Chinese not-found envelope BEFORE any product service acquisition — the
  rejection never creates the database file.
* Admitted projects reach the real product SQLite over HTTP (create → get →
  events round-trip against WAL ``FULL`` durability).
* Allowlist rows, aggregate rows and event hashes survive a composition
  restart (rebuild over the same file).
* A pre-1R.2 v1 database migrates to v2 with rows and event hashes intact;
  the admission gate never migrates (read-only, missing/old → not admitted).
* Structural validation inside the new chain uses the Chinese envelope at
  route scope; legacy routes keep the default FastAPI 422 shape on the same
  app, mounted or not.
* No in-memory ``CutoverStateRegistry`` reuse and no banned-surface imports
  (pocs / monitoring / legacy writing / ``app.main``) in the new/changed
  product path.
* Real isolated ``app.main`` entrypoint runs in a subprocess with a temporary
  runtime and sanitized child environment; missing legacy dependencies fail
  with an explicit isolated-venv hint.

No live/model/OCR/translation/Word/service calls. Temporary SQLite only.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from packages.contracts.workbench_contracts.protocol_v3 import (
    ActorType,
    CanonicalState,
    DecisionRecord,
)

ROOT = Path(__file__).resolve().parents[2]
COMPOSITION_PATH = (
    ROOT
    / "services/api/app/protocol_workflow/api/composition.py"
)
SQLITE_PATH = (
    ROOT / "services/api/app/protocol_workflow/storage/sqlite.py"
)
ROUTER_PATH = ROOT / "services/api/app/protocol_workflow/api/router.py"
REGISTRY_PATH = (
    ROOT / "config/medical_writing/protocol_v3/skill_registry.json"
)

ENV_ENABLED = "WORKBENCH_PROTOCOL_V3_WORKFLOW_ENABLED"
ENV_DB = "WORKBENCH_PROTOCOL_V3_WORKFLOW_DB"
ENV_BUSY_MS = "WORKBENCH_PROTOCOL_V3_WORKFLOW_BUSY_TIMEOUT_MS"

_T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_PROJECT = "proj:1r2:admitted"
_OTHER_PROJECT = "proj:1r2:outsider"
_SD_ID = "sd:1r2:1"
_SEED_ID = "seed:1r2:1"
_SEED_SHA = "e" * 64
_FACTS = {
    "picos.population.indication": "中重度活动性溃疡性结肠炎",
    "picos.intervention.dose": "10 mg 每日一次",
}

_PUBLIC_KEYS = {"message", "responsible_area", "can_retry", "next_step"}


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------


def _set_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    enabled: Optional[str] = None,
    db_name: str = "wf_1r2.sqlite",
    no_db: bool = False,
) -> Path:
    """Isolate the composition env; return the configured db path."""
    monkeypatch.setenv("WORKBENCH_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("WORKBENCH_AI_SETTINGS_PATH", str(tmp_path / "ai.json"))
    monkeypatch.setenv(
        "WORKBENCH_AI_ROLE_SETTINGS_PATH", str(tmp_path / "roles.json")
    )
    monkeypatch.setenv(
        "WORKBENCH_ELIGIBILITY_ARTIFACT_DIR", str(tmp_path / "eligibility")
    )
    if enabled is None:
        monkeypatch.delenv(ENV_ENABLED, raising=False)
    else:
        monkeypatch.setenv(ENV_ENABLED, enabled)
    db_path = tmp_path / db_name
    if no_db:
        monkeypatch.delenv(ENV_DB, raising=False)
    else:
        monkeypatch.setenv(ENV_DB, str(db_path))
    monkeypatch.delenv(ENV_BUSY_MS, raising=False)
    return db_path


def _mount(app: FastAPI) -> bool:
    from app.protocol_workflow.api.composition import (
        mount_protocol_workflow_router,
    )

    return mount_protocol_workflow_router(app)


def _config_from_env():
    from app.protocol_workflow.api.composition import (
        protocol_workflow_config_from_env,
    )

    return protocol_workflow_config_from_env()


def _admit(db_path: Path, project_id: str) -> None:
    from app.protocol_workflow.storage.sqlite import admit_project

    admit_project(
        {"backend": "sqlite", "path": str(db_path)}, project_id
    )


def _is_admitted(db_path: Path, project_id: str) -> bool:
    from app.protocol_workflow.storage.sqlite import is_project_admitted

    return is_project_admitted(
        {"backend": "sqlite", "path": str(db_path)}, project_id
    )


def _protocol_paths(app: FastAPI) -> list:
    # Resolve through OpenAPI: this FastAPI version keeps included routers
    # as include-context wrappers in ``app.routes``.
    return [
        path for path in app.openapi()["paths"] if "protocol-workflow" in path
    ]


# ---------------------------------------------------------------------------
# Request-body helpers (genesis create, mirrored from the Task 1.9 contract)
# ---------------------------------------------------------------------------


def _decision(*, snapshot_sha256: str) -> DecisionRecord:
    return DecisionRecord(
        decision_record_id="decision:1r2:create:001",
        decision_key="decision:create",
        snapshot_sha256=snapshot_sha256,
        expected_state_revision=0,
        state_revision=1,
        option_ids=("option:dose:001", "option:dose:002"),
        selected_option_id="option:dose:001",
        actor_type=ActorType.USER,
        actor_id="user:medical-writer",
        reason="接受 AI 推荐的默认剂量设计。",
        decided_at=_T0,
        canonical_state=CanonicalState.CONFIRMED,
    )


def _create_body(
    *,
    project_id: str = _PROJECT,
    study_definition_id: str = _SD_ID,
) -> Dict[str, Any]:
    from app.protocol_workflow.application import (
        study_definition_genesis_snapshot,
    )

    snapshot = study_definition_genesis_snapshot(
        study_definition_id=study_definition_id,
        project_id=project_id,
        normalized_seed_id=_SEED_ID,
        normalized_seed_sha256=_SEED_SHA,
        facts=dict(_FACTS),
        decided_at=_T0,
    )
    dr = _decision(snapshot_sha256=snapshot)
    return {
        "project_id": project_id,
        "study_definition_id": study_definition_id,
        "idempotency_key": "idem:1r2:1",
        "expected_revision": 0,
        "actor_type": "user",
        "actor_id": "user:medical-writer",
        "reason": "接受 AI 推荐的默认剂量设计。",
        "decision_record": dr.model_dump(mode="json"),
        "normalized_seed_id": _SEED_ID,
        "normalized_seed_sha256": _SEED_SHA,
        "initial_facts": dict(_FACTS),
    }


def _base(project_id: str = _PROJECT) -> str:
    return f"/api/projects/{project_id}/protocol-workflow"


class _LegacyBody(BaseModel):
    required_count: int


def _app_with_legacy() -> FastAPI:
    app = FastAPI()

    @app.post("/api/legacy-echo")
    def legacy_echo(body: _LegacyBody) -> dict:
        return {"required_count": body.required_count}

    return app


# ---------------------------------------------------------------------------
# Config: default-off, explicit enable
# ---------------------------------------------------------------------------


class TestMountConfig:
    def test_default_off_when_flag_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_env(monkeypatch, tmp_path, enabled=None)
        config = _config_from_env()
        assert config.enabled is False

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", "On"])
    def test_explicit_truthy_enables(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        db_path = _set_env(monkeypatch, tmp_path, enabled=value)
        config = _config_from_env()
        assert config.enabled is True
        assert config.db_path == db_path

    @pytest.mark.parametrize(
        "value", ["0", "false", "no", "off", "", "  ", "maybe"]
    )
    def test_other_values_stay_off(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        _set_env(monkeypatch, tmp_path, enabled=value)
        assert _config_from_env().enabled is False


# ---------------------------------------------------------------------------
# Default-off: legacy behaviour preserved, no side effects
# ---------------------------------------------------------------------------


class TestDefaultOffMount:
    def test_disabled_chain_ignores_unused_invalid_timeout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db_path = _set_env(monkeypatch, tmp_path, enabled="off")
        monkeypatch.setenv(ENV_BUSY_MS, "not-a-number")
        app = _app_with_legacy()
        assert _mount(app) is False
        assert not db_path.exists()
        assert TestClient(app).post(
            "/api/legacy-echo", json={"required_count": 7}
        ).json() == {"required_count": 7}
        monkeypatch.setenv(ENV_ENABLED, "on")
        with pytest.raises(ValueError, match=ENV_BUSY_MS):
            _mount(app)

    def test_mount_is_noop_without_side_effects(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db_path = _set_env(monkeypatch, tmp_path, enabled=None)
        monkeypatch.chdir(tmp_path)
        before_files = set(tmp_path.rglob("*"))
        before_threads = len(threading.enumerate())
        app = _app_with_legacy()
        assert _mount(app) is False
        assert _protocol_paths(app) == []
        assert set(tmp_path.rglob("*")) == before_files
        assert len(threading.enumerate()) == before_threads
        assert not db_path.exists()
        # Legacy validation shape is the untouched FastAPI default.
        client = TestClient(app)
        response = client.post("/api/legacy-echo", json={"nope": "x"})
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)

    def test_enabled_without_db_path_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_env(monkeypatch, tmp_path, enabled="1", no_db=True)
        app = FastAPI()
        with pytest.raises(ValueError, match=ENV_DB):
            _mount(app)
        assert _protocol_paths(app) == []


# ---------------------------------------------------------------------------
# Empty allowlist / non-admitted projects: reject before any service use
# ---------------------------------------------------------------------------


class TestAdmissionGate:
    def test_empty_allowlist_rejects_without_creating_db(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db_path = _set_env(monkeypatch, tmp_path, enabled="1")
        app = FastAPI()
        assert _mount(app) is True
        assert _protocol_paths(app) != []
        client = TestClient(app)
        get_response = client.get(f"{_base()}/study-definitions/{_SD_ID}")
        assert get_response.status_code == 404
        assert _PUBLIC_KEYS <= set(get_response.json()["detail"])
        post_response = client.post(
            f"{_base()}/study-definitions", json=_create_body()
        )
        assert post_response.status_code == 404
        assert _PUBLIC_KEYS <= set(post_response.json()["detail"])
        # The rejection path never bootstraps the product database.
        assert not db_path.exists()

    def test_non_admitted_project_rejected_after_admitting_another(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db_path = _set_env(monkeypatch, tmp_path, enabled="true")
        _admit(db_path, _PROJECT)
        assert _is_admitted(db_path, _PROJECT) is True
        assert _is_admitted(db_path, _OTHER_PROJECT) is False
        app = FastAPI()
        assert _mount(app) is True
        client = TestClient(app)
        response = client.get(
            f"{_base(_OTHER_PROJECT)}/study-definitions/{_SD_ID}"
        )
        assert response.status_code == 404
        assert _PUBLIC_KEYS <= set(response.json()["detail"])
        rejected_post = client.post(
            f"{_base(_OTHER_PROJECT)}/study-definitions",
            json=_create_body(project_id=_OTHER_PROJECT),
        )
        assert rejected_post.status_code == 404


# ---------------------------------------------------------------------------
# Admitted project: real product SQLite over HTTP + restart durability
# ---------------------------------------------------------------------------


class TestAdmittedProjectRoundTrip:
    def _admitted_client(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[TestClient, Path]:
        db_path = _set_env(monkeypatch, tmp_path, enabled="1")
        _admit(db_path, _PROJECT)
        app = FastAPI()
        assert _mount(app) is True
        return TestClient(app), db_path

    def test_create_get_events_round_trip(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client, db_path = self._admitted_client(tmp_path, monkeypatch)
        created = client.post(
            f"{_base()}/study-definitions", json=_create_body()
        )
        assert created.status_code == 200, created.text
        created_body = created.json()
        assert created_body["revision"] == 1
        assert len(created_body["revision_sha256"]) == 64
        current = client.get(f"{_base()}/study-definitions/{_SD_ID}")
        assert current.status_code == 200
        assert (
            current.json()["revision_sha256"] == created_body["revision_sha256"]
        )
        events = client.get(f"{_base()}/study-definitions/{_SD_ID}/events")
        assert events.status_code == 200
        assert events.json()["event_count"] >= 1
        assert len(events.json()["last_event_sha256"]) == 64
        # Real SQLite file with WAL durability behind the HTTP boundary.
        assert db_path.exists()
        with sqlite3.connect(str(db_path)) as conn:
            assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"

    def test_restart_preserves_allowlist_rows_and_hashes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client, db_path = self._admitted_client(tmp_path, monkeypatch)
        created = client.post(
            f"{_base()}/study-definitions", json=_create_body()
        )
        assert created.status_code == 200, created.text
        first_sha = created.json()["revision_sha256"]
        first_events = client.get(
            f"{_base()}/study-definitions/{_SD_ID}/events"
        ).json()
        # "Restart": a fresh composition over the same product file.
        restarted_app = FastAPI()
        assert _mount(restarted_app) is True
        restarted = TestClient(restarted_app)
        current = restarted.get(f"{_base()}/study-definitions/{_SD_ID}")
        assert current.status_code == 200
        assert current.json()["revision_sha256"] == first_sha
        assert (
            restarted.get(f"{_base()}/study-definitions/{_SD_ID}/events").json()
            == first_events
        )
        outsider = restarted.get(
            f"{_base(_OTHER_PROJECT)}/study-definitions/{_SD_ID}"
        )
        assert outsider.status_code == 404
        assert db_path.exists()


# ---------------------------------------------------------------------------
# v1 → v2 migration: rows and event hashes intact; gate never migrates
# ---------------------------------------------------------------------------


    def test_v1_database_migrates_preserving_rows_and_hashes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.protocol_workflow.storage.sqlite as adapter
        from app.protocol_workflow.application import (
            ApplicationService,
            CreateStudyDefinitionCommand,
            GetStudyDefinitionEventSummaryQuery,
            GetStudyDefinitionQuery,
        )
        db_path = tmp_path / "v1legacy.sqlite"
        config = {"backend": "sqlite", "path": str(db_path)}
        original = adapter._MIGRATIONS
        monkeypatch.setattr(adapter, "_MIGRATIONS", original[:1])
        monkeypatch.setattr(adapter, "SCHEMA_VERSION_LATEST", 1)
        v1_factory = adapter.build_unit_of_work_factory(config)
        service = ApplicationService(unit_of_work_factory=v1_factory)
        body = _create_body()
        result = service.create_study_definition(
            CreateStudyDefinitionCommand(
                project_id=body["project_id"],
                study_definition_id=body["study_definition_id"],
                idempotency_key=body["idempotency_key"],
                expected_revision=body["expected_revision"],
                actor_type=ActorType(body["actor_type"]),
                actor_id=body["actor_id"],
                reason=body["reason"],
                decision_record=DecisionRecord.model_validate(
                    body["decision_record"]
                ),
                normalized_seed_id=body["normalized_seed_id"],
                normalized_seed_sha256=body["normalized_seed_sha256"],
                initial_facts=dict(body["initial_facts"]),
                side_effect=None,
            )
        )
        summary = service.get_study_definition_event_summary(
            GetStudyDefinitionEventSummaryQuery(
                project_id=body["project_id"],
                study_definition_id=body["study_definition_id"],
            )
        )
        v1_revision_sha = result.revision_sha256
        v1_event_sha = summary.last_event_sha256
        v1_event_count = summary.event_count
        # The admission gate is read-only: an un-migrated v1 file is simply
        # not admitted, and the file version is untouched.
        assert _is_admitted(db_path, body["project_id"]) is False
        with sqlite3.connect(str(db_path)) as conn:
            assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[
                0
            ] == 1
        # Real upgrade to the shipped schema.
        monkeypatch.undo()
        upgraded_factory = adapter.build_unit_of_work_factory(config)
        with sqlite3.connect(str(db_path)) as conn:
            assert conn.execute(
                "SELECT version FROM schema_version ORDER BY version"
            ).fetchall() == [(1,), (2,), (3,)]
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        upgraded_service = ApplicationService(
            unit_of_work_factory=upgraded_factory
        )
        current = upgraded_service.get_study_definition(
            GetStudyDefinitionQuery(
                project_id=body["project_id"],
                study_definition_id=body["study_definition_id"],
            )
        )
        assert current.revision_sha256 == v1_revision_sha
        upgraded_summary = upgraded_service.get_study_definition_event_summary(
            GetStudyDefinitionEventSummaryQuery(
                project_id=body["project_id"],
                study_definition_id=body["study_definition_id"],
            )
        )
        assert upgraded_summary.last_event_sha256 == v1_event_sha
        assert upgraded_summary.event_count == v1_event_count
        # The migrated database admits projects durably.
        _admit(db_path, body["project_id"])
        assert _is_admitted(db_path, body["project_id"]) is True

    def test_admission_inputs_rejected_fail_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.protocol_workflow.storage.sqlite import (
            SqliteStorageConfigurationError,
            admit_project,
            is_project_admitted,
        )

        db_path = tmp_path / "inputs.sqlite"
        config = {"backend": "sqlite", "path": str(db_path)}
        for bad in ("", "   "):
            with pytest.raises(SqliteStorageConfigurationError):
                admit_project(config, bad)
            with pytest.raises(SqliteStorageConfigurationError):
                is_project_admitted(config, bad)
        with pytest.raises(SqliteStorageConfigurationError):
            admit_project({"backend": "memory", "path": str(db_path)}, _PROJECT)


# ---------------------------------------------------------------------------
# Route-scoped validation envelope; legacy 422 shape preserved
# ---------------------------------------------------------------------------


class TestRouteScopedValidation:
    def test_new_chain_422_envelope_and_legacy_shape(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_env(monkeypatch, tmp_path, enabled="on")
        _admit(tmp_path / "wf_1r2.sqlite", _PROJECT)
        app = _app_with_legacy()
        assert _mount(app) is True
        client = TestClient(app, raise_server_exceptions=False)
        bad_new = client.post(
            f"{_base()}/study-definitions", json={"project_id": _PROJECT}
        )
        assert bad_new.status_code == 422
        detail = bad_new.json()["detail"]
        assert isinstance(detail, dict)
        assert _PUBLIC_KEYS <= set(detail)
        bad_legacy = client.post("/api/legacy-echo", json={"nope": "x"})
        assert bad_legacy.status_code == 422
        assert isinstance(bad_legacy.json()["detail"], list)

    def test_path_body_mismatch_rejected_before_service(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_env(monkeypatch, tmp_path, enabled="1")
        _admit(tmp_path / "wf_1r2.sqlite", _PROJECT)
        app = FastAPI()
        assert _mount(app) is True
        client = TestClient(app)
        body = _create_body(project_id=_OTHER_PROJECT)
        response = client.post(f"{_base()}/study-definitions", json=body)
        # The admitted path project does not match the body project: the
        # router rejects the shape before any canonical write.
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], dict)


# ---------------------------------------------------------------------------
# No cutover-registry reuse; no banned-surface imports
# ---------------------------------------------------------------------------


_BANNED_MODULE_TOKENS = (
    "app.protocol_workflow.legacy",
    "pocs",
    "app.main",
    "monitoring",
    "medical_writing",
)


class TestNoCutoverReuse:
    @pytest.mark.parametrize(
        "source_path", [COMPOSITION_PATH, SQLITE_PATH, ROUTER_PATH]
    )
    def test_no_cutover_or_banned_surface_references(
        self, source_path: Path
    ) -> None:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    modules.add(node.module)
        assert "CutoverStateRegistry" not in ast.dump(tree), source_path.name
        for module in modules:
            for token in _BANNED_MODULE_TOKENS:
                assert token not in module, (
                    f"{source_path.name} imports banned surface {module!r}"
                )

    def test_composition_import_has_no_filesystem_side_effects(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import importlib

        monkeypatch.chdir(tmp_path)
        importlib.import_module("app.protocol_workflow.api.composition")
        assert list(tmp_path.rglob("*")) == []


# ---------------------------------------------------------------------------
# Real isolated main entrypoint (subprocess; legacy dependencies are required)
# ---------------------------------------------------------------------------

_LEGACY_DEP_SPECS = tuple(
    spec
    for spec in (
        importlib.util.find_spec("fitz"),
        importlib.util.find_spec("xlrd"),
    )
    if spec is None
)
_MISSING_LEGACY_DEPS = tuple(
    name
    for name, present in (
        ("fitz(PyMuPDF)", importlib.util.find_spec("fitz") is not None),
        ("xlrd", importlib.util.find_spec("xlrd") is not None),
    )
    if not present
)

_CHILD_SCRIPT = r"""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.environ["CHECKOUT"])
sys.path.insert(0, os.path.join(os.environ["CHECKOUT"], "services/api"))
sys.path.insert(0, os.path.join(os.environ["CHECKOUT"], "packages"))

if not os.environ.get("WORKBENCH_PROTOCOL_V3_WORKFLOW_ENABLED"):
    from pathlib import Path
    import threading
    before = set(threading.enumerate())
    if os.environ.get("BASELINE_WITHOUT_V3_MOUNT"):
        import app.protocol_workflow.api.composition as composition
        composition.mount_protocol_workflow_router = lambda app: False
    import app.main as main_module
    started_threads = sorted(
        (thread.name, getattr(getattr(thread, "_target", None), "__qualname__", ""))
        for thread in set(threading.enumerate()) - before
    )
    from fastapi.testclient import TestClient
    assert not any(
        "protocol-workflow" in getattr(route, "path", "")
        for route in main_module.app.routes
    )
    response = TestClient(main_module.app).get(
        "/api/projects/proj:1r2:admitted/protocol-workflow/study-definitions/sd:x"
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
    assert not Path(os.environ["WORKBENCH_PROTOCOL_V3_WORKFLOW_DB"]).exists()
    print(json.dumps({"disabled": True, "started_threads": started_threads}))
    sys.exit(0)

from app.protocol_workflow.storage.sqlite import admit_project

db_path = os.environ["WORKBENCH_PROTOCOL_V3_WORKFLOW_DB"]
admit_project({"backend": "sqlite", "path": db_path}, "proj:1r2:admitted")

from fastapi.testclient import TestClient
import app.main as main_module

app = main_module.app
paths = sorted(
    {getattr(route, "path", "") for route in app.routes}
)
assert any("protocol-workflow" in path for path in paths), (
    f"protocol-workflow routes missing with flag on: {paths}"
)
client = TestClient(app)
body = json.loads(sys.stdin.read())
base = "/api/projects/proj:1r2:admitted/protocol-workflow/study-definitions"
created = client.post(base, json=body)
assert created.status_code == 200, created.text
current = client.get(base + "/" + body["study_definition_id"])
assert current.status_code == 200, current.text
assert current.json()["revision_sha256"] == created.json()["revision_sha256"]
assert current.json()["revision"] == 1
events = client.get(base + "/" + body["study_definition_id"] + "/events")
assert events.status_code == 200, events.text
assert events.json()["event_count"] >= 1
admitted = client.get(
    "/api/projects/proj:1r2:admitted/protocol-workflow"
    "/study-definitions/sd:missing"
)
outsider = client.get(
    "/api/projects/proj:1r2:outsider/protocol-workflow"
    "/study-definitions/sd:missing"
)
print(json.dumps({
    "created": created.json(),
    "current": current.json(),
    "events": events.json(),
    "admitted_status": admitted.status_code,
    "admitted_detail": admitted.json(),
    "outsider_status": outsider.status_code,
    "outsider_detail": outsider.json(),
}))
"""


@pytest.mark.parametrize("enabled", [False, True], ids=["default-off", "enabled"])
def test_real_main_isolated_entrypoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    assert not _MISSING_LEGACY_DEPS, (
        f"Missing {_MISSING_LEGACY_DEPS}; use the isolated integration venv"
    )
    runtime = tmp_path / "child_runtime"
    runtime.mkdir()
    db_path = tmp_path / "real_main.sqlite"
    child_env = dict(os.environ)
    for key in (
        "WORKBENCH_AI_SETTINGS_PATH",
        "WORKBENCH_AI_ROLE_SETTINGS_PATH",
        "WORKBENCH_ELIGIBILITY_ARTIFACT_DIR",
    ):
        child_env.pop(key, None)
    child_env.update(
        {
            "CHECKOUT": str(ROOT),
            "WORKBENCH_RUNTIME_DIR": str(runtime),
            "WORKBENCH_AI_SETTINGS_PATH": str(runtime / "ai.json"),
            "WORKBENCH_AI_ROLE_SETTINGS_PATH": str(runtime / "roles.json"),
            "WORKBENCH_ELIGIBILITY_ARTIFACT_DIR": str(runtime / "eligibility"),
            "WORKBENCH_PROTOCOL_V3_WORKFLOW_ENABLED": "1",
            "WORKBENCH_PROTOCOL_V3_WORKFLOW_DB": str(db_path),
        }
    )
    if not enabled:
        child_env.pop(ENV_ENABLED, None)
    completed = subprocess.run(
        [sys.executable, "-c", _CHILD_SCRIPT],
        env=child_env,
        input=json.dumps(_create_body()),
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, (
        f"real-main child failed rc={completed.returncode}\n"
        f"STDOUT:\n{completed.stdout[-4000:]}\n"
        f"STDERR:\n{completed.stderr[-4000:]}"
    )
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    if not enabled:
        assert payload["disabled"] is True
        assert not db_path.exists()
        baseline = subprocess.run(
            [sys.executable, "-c", _CHILD_SCRIPT],
            env={**child_env, "BASELINE_WITHOUT_V3_MOUNT": "1"},
            cwd=str(tmp_path), capture_output=True, text=True, timeout=300,
        )
        assert baseline.returncode == 0, baseline.stderr
        baseline_payload = json.loads(baseline.stdout.strip().splitlines()[-1])
        assert payload == baseline_payload
        return
    assert payload["created"]["revision"] == 1
    assert payload["current"]["revision_sha256"] == payload["created"]["revision_sha256"]
    assert len(payload["events"]["last_event_sha256"]) == 64
    assert payload["admitted_status"] == 404
    assert _PUBLIC_KEYS <= set(payload["admitted_detail"]["detail"])
    assert payload["outsider_status"] == 404
    assert _PUBLIC_KEYS <= set(payload["outsider_detail"]["detail"])
    assert db_path.exists()
