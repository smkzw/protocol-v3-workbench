"""Read-only product binding to the existing omp credential source."""

import json
import sqlite3

import pytest

from app.protocol_workflow.runtime.omp_credentials import (
    OmpCredentialError, resolve_omp_opencode_go_key, resolve_omp_zhipu_key,
)


def _database(tmp_path, rows, blocks=()):
    path = tmp_path / "synthetic-agent.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE auth_credentials (id INTEGER PRIMARY KEY, provider TEXT, credential_type TEXT, data TEXT, disabled_cause TEXT)")
        db.execute("CREATE TABLE auth_credential_blocks (credential_id INTEGER, provider_key TEXT, block_scope TEXT, blocked_until_ms INTEGER, updated_at INTEGER)")
        for number, provider, key, source, disabled in rows:
            db.execute("INSERT INTO auth_credentials VALUES (?, ?, 'api_key', ?, ?)", (
                number, provider, json.dumps({"key": key, "source": source}), disabled,
            ))
        for number, expiry in blocks:
            db.execute("INSERT INTO auth_credential_blocks VALUES (?, 'zhipu-coding-plan:api_key', '', ?, 0)", (number, expiry))
    return path


def test_same_provider_login_binding_order_and_readonly_database(tmp_path):
    path = _database(tmp_path, [
        (1, "unrelated-provider", "unrelated", "login", None),
        (2, "zhipu-coding-plan", "static", "static", None),
        (3, "zhipu-coding-plan", "disabled", "login", "disabled"),
        (4, "zhipu-coding-plan", "first-login", "login", None),
        (5, "zhipu-coding-plan", "second-login", "login", None),
    ])
    before = path.read_bytes()
    assert resolve_omp_zhipu_key(path, now_ms=1000) == "first-login"
    assert path.read_bytes() == before


def test_bound_pool_respects_active_block_and_expiry(tmp_path):
    path = _database(tmp_path, [
        (1, "zhipu-coding-plan", "first-login", "login", None),
        (2, "zhipu-coding-plan", "second-login", "login", None),
    ], blocks=[(1, 2000)])
    assert resolve_omp_zhipu_key(path, now_ms=1000) == "second-login"
    assert resolve_omp_zhipu_key(path, now_ms=3000) == "first-login"


def test_missing_store_is_not_created(tmp_path):
    path = tmp_path / "absent.db"
    with pytest.raises(OmpCredentialError, match="omp_credentials_unavailable"):
        resolve_omp_zhipu_key(path)
    assert not path.exists()


def test_all_blocked_does_not_substitute_static_or_other_provider(tmp_path):
    path = _database(tmp_path, [
        (1, "zhipu-coding-plan", "login", "login", None),
        (2, "zhipu-coding-plan", "static", "static", None),
    ], blocks=[(1, 2000)])
    with pytest.raises(OmpCredentialError, match="omp_credentials_temporarily_blocked"):
        resolve_omp_zhipu_key(path, now_ms=1000)


def test_explicit_environment_reference_resolves_in_memory(tmp_path):
    path = _database(tmp_path, [(1, "zhipu-coding-plan", "SYNTHETIC_KEY", "login", None)])
    assert resolve_omp_zhipu_key(path, environ={"SYNTHETIC_KEY": "synthetic-value"}) == "synthetic-value"


def test_empty_resolved_binding_reports_unavailable_before_dispatch(tmp_path):
    path = _database(tmp_path, [(1, "zhipu-coding-plan", "SYNTHETIC_KEY", "login", None)])
    with pytest.raises(OmpCredentialError, match="omp_credentials_unavailable"):
        resolve_omp_zhipu_key(path, environ={"SYNTHETIC_KEY": ""})


def test_opencode_go_binding_reads_only_named_omp_env_assignment(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "UNRELATED=do-not-use\nexport OPENCODE_API_KEY='synthetic-opencode'\n",
        encoding="utf-8",
    )
    before = path.read_bytes()
    assert resolve_omp_opencode_go_key(path, environ={}) == "synthetic-opencode"
    assert path.read_bytes() == before


def test_opencode_go_process_binding_wins_without_reading_file(tmp_path):
    absent = tmp_path / "absent.env"
    assert resolve_omp_opencode_go_key(
        absent, environ={"OPENCODE_API_KEY": "process-only"}
    ) == "process-only"
    assert not absent.exists()


def test_opencode_go_missing_or_ambiguous_binding_fails_closed(tmp_path):
    path = tmp_path / ".env"
    path.write_text("OPENCODE_API_KEY=one\nOPENCODE_API_KEY=two\n", encoding="utf-8")
    with pytest.raises(OmpCredentialError, match="omp_credentials_unavailable"):
        resolve_omp_opencode_go_key(path, environ={})
