from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import sqlite3
import stat
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/qc/mw_isolated_runtime_baseline.py"
SPEC = importlib.util.spec_from_file_location("mw_isolated_runtime_baseline", SCRIPT)
assert SPEC and SPEC.loader
BASELINE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASELINE)


def make_source(root: Path) -> tuple[Path, dict[str, bytes]]:
    source = root / "source-runtime"
    source.mkdir()
    payloads = {
        "ai_provider_settings.json": b'{"provider":"test"}\n',
        "ai_provider_secrets.json": b'{"secret":"SUPER_SECRET_DO_NOT_LEAK"}\n',
        "ai_provider_master.key": b"test-master-key-material\n",
        "ai_role_bindings.json": b'{"role":"independent_ai"}\n',
    }
    for filename, payload in payloads.items():
        path = source / filename
        path.write_bytes(payload)
        path.chmod(0o640)
    return source, payloads


def prepare_in_temp(tmp_path: Path) -> tuple[Path, Path, dict[str, bytes]]:
    source, payloads = make_source(tmp_path)
    target = tmp_path / "isolated-runtime"
    BASELINE.prepare_baseline(
        source_runtime=source,
        target_runtime=target,
        test_source_root=tmp_path,
        test_target_root=tmp_path,
    )
    return source, target, payloads


def add_startup_sqlite(target: Path, *, project_rows: int = 0) -> None:
    with sqlite3.connect(target / "user_projects.sqlite3") as connection:
        connection.execute(
            "CREATE TABLE user_projects "
            "(project_id TEXT PRIMARY KEY, project_name TEXT)"
        )
        for index in range(project_rows):
            connection.execute(
                "INSERT INTO user_projects VALUES (?, ?)",
                (f"project-{index}", f"Project {index}"),
            )
    with sqlite3.connect(target / "workbench_runtime.sqlite3") as connection:
        connection.execute(
            "CREATE TABLE project_records "
            "(record_id TEXT PRIMARY KEY, project_id TEXT)"
        )
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY)"
        )
        connection.execute("INSERT INTO schema_migrations VALUES (16)")
    with sqlite3.connect(target / "medical_writing_shared_corpus.sqlite3") as connection:
        connection.execute(
            "CREATE TABLE shared_corpus_items "
            "(item_id TEXT PRIMARY KEY, payload TEXT)"
        )
        connection.execute(
            "INSERT INTO shared_corpus_items VALUES ('system-item', 'allowed')"
        )


def startup_api_payloads() -> dict[str, object]:
    roles = [
        {
            "role_id": role_id,
            "ready": True,
            "current_runnable": True,
            **identity,
        }
        for role_id, identity in BASELINE.EXPECTED_ROLES.items()
    ]
    return {
        "/api/health": {
            "status": "ok",
            "runtime_store": {
                "status": "ok",
                "schema_version": 16,
                "integrity_check": "ok",
                "foreign_key_violations": 0,
            },
        },
        "/api/projects": [],
        "/api/ai-gateway/roles/status": {"roles": roles},
    }


def startup_http_getter(payloads: dict[str, object]):
    def get(url: str):
        path = "/" + url.split("/", 3)[-1]
        return copy.deepcopy(payloads[path])

    return get


def startup_process_receipt(target: Path, **overrides):
    environment = {
        "WORKBENCH_RUNTIME_DIR": str(target.resolve()),
        "WORKBENCH_INCLUDE_REFERENCE_PROJECTS": "false",
    }
    environment.update(overrides)
    return {"pid": 32123, "environment": environment}


def test_default_source_runtime_is_product_runtime_not_workbench_runtime() -> None:
    resolved = BASELINE.resolve_source_runtime()
    expected = Path(
        "/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/runtime"
    )
    assert resolved == expected
    assert resolved != ROOT / "runtime"


def test_prepare_copies_only_whitelist_and_writes_secret_free_manifest(
    tmp_path: Path,
) -> None:
    source, payloads = make_source(tmp_path)
    (source / "user_projects.sqlite3").write_bytes(b"project data")
    (source / "user_projects.sqlite3-wal").write_bytes(b"wal data")
    (source / "events.jsonl").write_bytes(b'{"project":"secret"}\n')
    (source / "writing_reference_artifacts").mkdir()
    (source / "writing_reference_artifacts/source.pdf").write_bytes(b"%PDF")
    target = tmp_path / "isolated-runtime"

    result = BASELINE.prepare_baseline(
        source_runtime=source,
        target_runtime=target,
        test_source_root=tmp_path,
        test_target_root=tmp_path,
    )

    assert result["status"] == "BASELINE_PREPARED"
    assert {item.name for item in target.iterdir()} == set(
        BASELINE.BASELINE_FILES
    ) | {BASELINE.MANIFEST_NAME}
    for filename, payload in payloads.items():
        assert (target / filename).read_bytes() == payload
    manifest_text = (target / BASELINE.MANIFEST_NAME).read_text(encoding="utf-8")
    assert "SUPER_SECRET_DO_NOT_LEAK" not in manifest_text
    assert "test-master-key-material" not in manifest_text
    manifest = json.loads(manifest_text)
    assert manifest["source_runtime_resolved"] == str(source.resolve())
    assert manifest["target_runtime_resolved"] == str(target.resolve())
    assert manifest["zero_project_state"] == {
        "status": "PENDING_STARTUP_VERIFICATION",
        "display_status": "\u5f85\u542f\u52a8\u9a8c\u8bc1",
        "verified": False,
        "project_count": None,
    }
    assert manifest["service_started"] is False
    assert manifest["product_api_called"] is False
    assert manifest["pass_created"] is False


def test_prepare_rejects_missing_required_file_without_creating_target(
    tmp_path: Path,
) -> None:
    source, _ = make_source(tmp_path)
    (source / "ai_provider_master.key").unlink()
    target = tmp_path / "isolated-runtime"

    with pytest.raises(BASELINE.BaselineError, match="required source file is missing"):
        BASELINE.prepare_baseline(
            source_runtime=source,
            target_runtime=target,
            test_source_root=tmp_path,
            test_target_root=tmp_path,
        )
    assert not target.exists()


@pytest.mark.parametrize("symlink_kind", ["source_runtime", "source_file", "target"])
def test_prepare_rejects_symbolic_links(
    tmp_path: Path,
    symlink_kind: str,
) -> None:
    real_source, _ = make_source(tmp_path)
    source = real_source
    target = tmp_path / "isolated-runtime"
    if symlink_kind == "source_runtime":
        source = tmp_path / "source-link"
        source.symlink_to(real_source, target_is_directory=True)
    elif symlink_kind == "source_file":
        settings = real_source / "ai_provider_settings.json"
        real_settings = tmp_path / "real-settings.json"
        settings.rename(real_settings)
        settings.symlink_to(real_settings)
    else:
        target.symlink_to(tmp_path / "missing-target", target_is_directory=True)

    with pytest.raises(BASELINE.BaselineError, match="symbolic link|symbolic links"):
        BASELINE.prepare_baseline(
            source_runtime=source,
            target_runtime=target,
            test_source_root=tmp_path,
            test_target_root=tmp_path,
        )


def test_prepare_rejects_existing_nonempty_target_and_any_reuse(
    tmp_path: Path,
) -> None:
    source, _ = make_source(tmp_path)
    target = tmp_path / "isolated-runtime"
    target.mkdir()
    (target / "existing.sqlite3").write_bytes(b"do not overwrite")

    with pytest.raises(BASELINE.BaselineError, match="already exists"):
        BASELINE.prepare_baseline(
            source_runtime=source,
            target_runtime=target,
            test_source_root=tmp_path,
            test_target_root=tmp_path,
        )
    assert (target / "existing.sqlite3").read_bytes() == b"do not overwrite"

    second_target = tmp_path / "second-runtime"
    BASELINE.prepare_baseline(
        source_runtime=source,
        target_runtime=second_target,
        test_source_root=tmp_path,
        test_target_root=tmp_path,
    )
    with pytest.raises(BASELINE.BaselineError, match="already exists"):
        BASELINE.prepare_baseline(
            source_runtime=source,
            target_runtime=second_target,
            test_source_root=tmp_path,
            test_target_root=tmp_path,
        )


def test_prepare_rejects_source_equal_target_and_target_outside_boundary(
    tmp_path: Path,
) -> None:
    source, _ = make_source(tmp_path)
    with pytest.raises(BASELINE.BaselineError, match="must differ"):
        BASELINE.prepare_baseline(
            source_runtime=source,
            target_runtime=source,
            test_source_root=tmp_path,
            test_target_root=tmp_path,
        )

    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    with pytest.raises(BASELINE.BaselineError, match="target must stay under"):
        BASELINE.prepare_baseline(
            source_runtime=source,
            target_runtime=outside,
            test_source_root=tmp_path,
            test_target_root=tmp_path,
        )


def test_hashes_modes_and_verify_files_are_repeatable(tmp_path: Path) -> None:
    source, target, payloads = prepare_in_temp(tmp_path)
    manifest = json.loads(
        (target / BASELINE.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    entries = {item["filename"]: item for item in manifest["files"]}

    for filename, payload in payloads.items():
        path = target / filename
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert entries[filename]["bytes"] == len(payload)
        assert entries[filename]["sha256"] == hashlib.sha256(payload).hexdigest()
        assert entries[filename]["mode"] == "0600"
        assert entries[filename]["source_path"] == str((source / filename).resolve())
        assert entries[filename]["target_path"] == str(path.resolve())
    assert stat.S_IMODE((target / BASELINE.MANIFEST_NAME).stat().st_mode) == 0o600

    first = BASELINE.verify_files(
        source_runtime=source,
        target_runtime=target,
        test_source_root=tmp_path,
        test_target_root=tmp_path,
    )
    second = BASELINE.verify_files(
        source_runtime=source,
        target_runtime=target,
        test_source_root=tmp_path,
        test_target_root=tmp_path,
    )
    assert first == second
    assert first["status"] == "FILES_VERIFIED_PROJECT_STATE_PENDING_STARTUP"


@pytest.mark.parametrize("tamper", ["content", "mode", "extra"])
def test_verify_files_rejects_tamper_and_non_whitelist_content(
    tmp_path: Path,
    tamper: str,
) -> None:
    source, target, _ = prepare_in_temp(tmp_path)
    if tamper == "content":
        (target / "ai_provider_settings.json").write_bytes(b"tampered")
        (target / "ai_provider_settings.json").chmod(0o600)
    elif tamper == "mode":
        (target / "ai_provider_settings.json").chmod(0o644)
    else:
        (target / "project.sqlite3").write_bytes(b"forbidden")
        (target / "project.sqlite3").chmod(0o600)

    with pytest.raises(BASELINE.BaselineError):
        BASELINE.verify_files(
            source_runtime=source,
            target_runtime=target,
            test_source_root=tmp_path,
            test_target_root=tmp_path,
        )


def test_cli_prepare_and_verify_files(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    source, _ = make_source(tmp_path)
    target = tmp_path / "cli-runtime"
    common = [
        "--source",
        str(source),
        "--target",
        str(target),
        "--test-source-root",
        str(tmp_path),
        "--test-target-root",
        str(tmp_path),
    ]
    assert BASELINE.main(["prepare", *common]) == 0
    prepare_output = json.loads(capsys.readouterr().out)
    assert prepare_output["status"] == "BASELINE_PREPARED"

    assert BASELINE.main(["verify-files", *common]) == 0
    verify_output = json.loads(capsys.readouterr().out)
    assert (
        verify_output["status"]
        == "FILES_VERIFIED_PROJECT_STATE_PENDING_STARTUP"
    )


def test_fixed_run_roots_allow_current_and_historical_final_harnesses_only() -> None:
    assert len(BASELINE.ALLOWED_RUN_ROOTS) == 3
    names = {path.name for path in BASELINE.ALLOWED_RUN_ROOTS}
    assert names == {
        "mw_final_5x3_harness_20260728",
        "mw_final_4x3_harness_20260727",
        "mw_final_release_matrix_20260727",
    }
    for root in BASELINE.ALLOWED_RUN_ROOTS:
        candidate = root / "round-01/perspective/runtime"
        assert BASELINE._validate_boundary(
            candidate,
            test_target_root=None,
        ) == Path(os.path.abspath(candidate))

    execution_root = BASELINE.WORKSPACE_ROOT / "runs/execution"
    for adjacent in (
        execution_root / "mw_final_release_matrix_20260727_evil/runtime",
        execution_root / "mw_final_release_matrix_202607270/runtime",
        execution_root / "unrelated/runtime",
    ):
        with pytest.raises(BASELINE.BaselineError, match="fixed run roots"):
            BASELINE._validate_boundary(adjacent, test_target_root=None)


def test_each_fixed_root_applies_symlink_component_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_root = tmp_path / "real-root"
    real_root.mkdir()
    symlink_root = tmp_path / "symlink-root"
    symlink_root.symlink_to(real_root, target_is_directory=True)
    second_root = tmp_path / "second-root"
    second_root.mkdir()
    monkeypatch.setattr(
        BASELINE,
        "ALLOWED_RUN_ROOTS",
        (symlink_root, second_root),
    )
    with pytest.raises(BASELINE.BaselineError, match="symbolic links"):
        BASELINE._validate_boundary(
            symlink_root / "perspective/runtime",
            test_target_root=None,
        )


def test_verify_startup_writes_atomic_0600_secret_free_clean_receipt(
    tmp_path: Path,
) -> None:
    source, target, _ = prepare_in_temp(tmp_path)
    add_startup_sqlite(target)
    (target / "source_registry.jsonl").write_text(
        '{"system_source":"startup-created"}\n',
        encoding="utf-8",
    )
    payloads = startup_api_payloads()

    result = BASELINE.verify_startup(
        source_runtime=source,
        target_runtime=target,
        base_url="http://127.0.0.1:18911",
        test_source_root=tmp_path,
        test_target_root=tmp_path,
        http_getter=startup_http_getter(payloads),
        process_inspector=lambda base_url, pid: startup_process_receipt(target),
    )

    assert result["status"] == "CLEAN_STATE_VERIFIED"
    receipt_path = tmp_path / BASELINE.RECEIPT_NAME
    assert result["receipt"] == str(receipt_path)
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600
    assert not list(tmp_path.glob(f".{BASELINE.RECEIPT_NAME}.*.tmp"))
    receipt_text = receipt_path.read_text(encoding="utf-8")
    assert "SUPER_SECRET_DO_NOT_LEAK" not in receipt_text
    assert "test-master-key-material" not in receipt_text
    receipt = json.loads(receipt_text)
    assert receipt["status"] == "CLEAN_STATE_VERIFIED"
    assert receipt["api"]["projects"] == {
        "exact_empty_array": True,
        "project_count": 0,
    }
    assert {
        item["role_id"] for item in receipt["api"]["roles"]
    } == set(BASELINE.EXPECTED_ROLES)
    assert receipt["sqlite_inventory"]["total_project_rows"] == 0
    assert receipt["sqlite_inventory"]["known_project_table_count"] == 2
    assert receipt["secret_content_embedded"] is False
    assert receipt["pass_created"] is False


def test_verify_startup_supports_declared_receipt_inside_fixed_test_root(
    tmp_path: Path,
) -> None:
    source, target, _ = prepare_in_temp(tmp_path)
    add_startup_sqlite(target)
    evidence = tmp_path / "perspective"
    evidence.mkdir()
    output = evidence / BASELINE.RECEIPT_NAME

    result = BASELINE.verify_startup(
        source_runtime=source,
        target_runtime=target,
        base_url="http://localhost:18911",
        output_path=output,
        test_source_root=tmp_path,
        test_target_root=tmp_path,
        http_getter=startup_http_getter(startup_api_payloads()),
        process_inspector=lambda base_url, pid: startup_process_receipt(target),
    )
    assert result["receipt"] == str(output)


def test_verify_startup_accepts_declared_comprehensive_ai_identity(
    tmp_path: Path,
) -> None:
    source, target, _ = prepare_in_temp(tmp_path)
    add_startup_sqlite(target)
    expected_roles = copy.deepcopy(BASELINE.EXPECTED_ROLES)
    expected_roles["independent_ai"] = {
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
    }
    payloads = startup_api_payloads()
    for role in payloads["/api/ai-gateway/roles/status"]["roles"]:
        if role["role_id"] == "independent_ai":
            role.update(expected_roles["independent_ai"])

    result = BASELINE.verify_startup(
        source_runtime=source,
        target_runtime=target,
        base_url="http://127.0.0.1:18911",
        test_source_root=tmp_path,
        test_target_root=tmp_path,
        http_getter=startup_http_getter(payloads),
        process_inspector=lambda base_url, pid: startup_process_receipt(target),
        expected_roles=expected_roles,
    )

    assert result["status"] == "CLEAN_STATE_VERIFIED"


@pytest.mark.parametrize(
    ("gate", "error_match"),
    [
        ("health", "health failed"),
        ("projects", "exact empty JSON array"),
        ("role_ready", "not ready"),
        ("role_identity", "identity mismatch"),
    ],
)
def test_verify_startup_api_gates_fail_closed_without_receipt(
    tmp_path: Path,
    gate: str,
    error_match: str,
) -> None:
    source, target, _ = prepare_in_temp(tmp_path)
    add_startup_sqlite(target)
    payloads = startup_api_payloads()
    if gate == "health":
        payloads["/api/health"]["runtime_store"]["schema_version"] = 15
    elif gate == "projects":
        payloads["/api/projects"] = [{"project_id": "unexpected"}]
    elif gate == "role_ready":
        payloads["/api/ai-gateway/roles/status"]["roles"][0]["ready"] = False
    else:
        payloads["/api/ai-gateway/roles/status"]["roles"][2][
            "model"
        ] = "wrong-translation-model"

    with pytest.raises(BASELINE.BaselineError, match=error_match):
        BASELINE.verify_startup(
            source_runtime=source,
            target_runtime=target,
            base_url="http://127.0.0.1:18911",
            test_source_root=tmp_path,
            test_target_root=tmp_path,
            http_getter=startup_http_getter(payloads),
            process_inspector=lambda base_url, pid: startup_process_receipt(target),
        )
    assert not (tmp_path / BASELINE.RECEIPT_NAME).exists()


@pytest.mark.parametrize(
    ("environment_override", "error_match"),
    [
        (
            {"WORKBENCH_RUNTIME_DIR": "/tmp/not-the-target"},
            "does not resolve|does not equal",
        ),
        (
            {"WORKBENCH_INCLUDE_REFERENCE_PROJECTS": "true"},
            "must equal false",
        ),
    ],
)
def test_verify_startup_process_environment_fails_closed(
    tmp_path: Path,
    environment_override: dict[str, str],
    error_match: str,
) -> None:
    source, target, _ = prepare_in_temp(tmp_path)
    add_startup_sqlite(target)

    with pytest.raises(BASELINE.BaselineError, match=error_match):
        BASELINE.verify_startup(
            source_runtime=source,
            target_runtime=target,
            base_url="http://127.0.0.1:18911",
            test_source_root=tmp_path,
            test_target_root=tmp_path,
            http_getter=startup_http_getter(startup_api_payloads()),
            process_inspector=lambda base_url, pid: startup_process_receipt(
                target,
                **environment_override,
            ),
        )
    assert not (tmp_path / BASELINE.RECEIPT_NAME).exists()


def test_process_inspection_tolerates_non_utf8_macos_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_kwargs = []
    runtime_hash = hashlib.sha256(
        str(Path("/tmp/runtime")).encode("utf-8")
    ).hexdigest()

    def fake_run(command, **kwargs):
        observed_kwargs.append(kwargs)
        return type(
            "Result",
            (),
            {
                "stdout": (
                    "WORKBENCH_RUNTIME_DIR=/tmp/\ufffdM^S\ufffd "
                    f"WORKBENCH_RUNTIME_DIR_SHA256={runtime_hash} "
                    "WORKBENCH_INCLUDE_REFERENCE_PROJECTS=false "
                    "BROKEN=\ufffd"
                )
            },
        )()

    monkeypatch.setattr(BASELINE.subprocess, "run", fake_run)
    monkeypatch.setattr(BASELINE, "_discover_listener_pid", lambda port: 32123)

    receipt = BASELINE._inspect_server_process(
        "http://127.0.0.1:18911",
        32123,
    )

    assert all(item["encoding"] == "utf-8" for item in observed_kwargs)
    assert all(item["errors"] == "replace" for item in observed_kwargs)
    assert all(item["env"]["LC_ALL"] == "C.UTF-8" for item in observed_kwargs)
    assert receipt["environment"]["WORKBENCH_INCLUDE_REFERENCE_PROJECTS"] == "false"
    assert receipt["environment"]["WORKBENCH_RUNTIME_DIR_SHA256"] == runtime_hash


def test_validate_process_receipt_uses_open_sqlite_for_lossy_macos_path(
    tmp_path: Path,
) -> None:
    target = tmp_path / "康哲运行目录"
    target.mkdir()

    receipt = BASELINE._validate_process_receipt(
        {
            "pid": 32123,
            "environment": {
                "WORKBENCH_RUNTIME_DIR": "/tmp/\ufffdM^S\ufffd",
                "WORKBENCH_RUNTIME_DIR_SHA256": hashlib.sha256(
                    str(target.resolve()).encode("utf-8")
                ).hexdigest(),
                "WORKBENCH_INCLUDE_REFERENCE_PROJECTS": "false",
            },
        },
        target.resolve(),
    )

    assert receipt["runtime_evidence"] == (
        "runtime_path_hash_after_lossy_ps"
    )
    assert receipt["environment"]["WORKBENCH_RUNTIME_DIR"] == str(target.resolve())


def test_validate_process_receipt_rejects_lossy_path_without_runtime_hash(
    tmp_path: Path,
) -> None:
    target = tmp_path / "康哲运行目录"
    target.mkdir()

    with pytest.raises(
        BASELINE.BaselineError,
        match="runtime hash evidence is missing",
    ):
        BASELINE._validate_process_receipt(
            {
                "pid": 32123,
                "environment": {
                    "WORKBENCH_RUNTIME_DIR": "/tmp/\ufffdM^S\ufffd",
                    "WORKBENCH_INCLUDE_REFERENCE_PROJECTS": "false",
                },
            },
            target.resolve(),
        )


def test_verify_startup_rejects_nonzero_project_sqlite_rows(
    tmp_path: Path,
) -> None:
    source, target, _ = prepare_in_temp(tmp_path)
    add_startup_sqlite(target, project_rows=1)

    with pytest.raises(BASELINE.BaselineError, match="zero rows"):
        BASELINE.verify_startup(
            source_runtime=source,
            target_runtime=target,
            base_url="http://127.0.0.1:18911",
            test_source_root=tmp_path,
            test_target_root=tmp_path,
            http_getter=startup_http_getter(startup_api_payloads()),
            process_inspector=lambda base_url, pid: startup_process_receipt(target),
        )
    assert not (tmp_path / BASELINE.RECEIPT_NAME).exists()


def test_receipt_output_rejects_escape_wrong_name_and_reuse(
    tmp_path: Path,
) -> None:
    source, target, _ = prepare_in_temp(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside" / BASELINE.RECEIPT_NAME
    with pytest.raises(BASELINE.BaselineError, match="fixed run roots"):
        BASELINE.resolve_new_receipt_path(
            target,
            outside,
            test_target_root=tmp_path,
        )
    with pytest.raises(BASELINE.BaselineError, match="filename"):
        BASELINE.resolve_new_receipt_path(
            target,
            tmp_path / "other.json",
            test_target_root=tmp_path,
        )
    existing = tmp_path / BASELINE.RECEIPT_NAME
    existing.write_text("do not overwrite", encoding="utf-8")
    with pytest.raises(BASELINE.BaselineError, match="already exists"):
        BASELINE.resolve_new_receipt_path(
            target,
            existing,
            test_target_root=tmp_path,
        )


def test_verify_startup_cli_reports_only_failed_on_gate_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    source, target, _ = prepare_in_temp(tmp_path)
    add_startup_sqlite(target)
    result = BASELINE.main(
        [
            "verify-startup",
            "--source",
            str(source),
            "--target",
            str(target),
            "--base-url",
            "https://127.0.0.1:18911",
            "--test-source-root",
            str(tmp_path),
            "--test-target-root",
            str(tmp_path),
        ]
    )
    assert result == 2
    error = json.loads(capsys.readouterr().err)
    assert error["status"] == "FAILED"
    assert not (tmp_path / BASELINE.RECEIPT_NAME).exists()
