from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "qc"
    / "monitoring_v7_cutover_checkpoint.py"
)
SPEC = importlib.util.spec_from_file_location("monitoring_v7_cutover_checkpoint", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _seed(path: Path, statuses: tuple[str, ...]) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE monitoring_ai_jobs (
                job_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL,
                business_key TEXT NOT NULL,
                input_revision_sha256 TEXT NOT NULL,
                input_payload_sha256 TEXT NOT NULL,
                output_sha256 TEXT NOT NULL,
                failure_code TEXT NOT NULL,
                failure_message TEXT NOT NULL,
                provider TEXT NOT NULL,
                requested_model TEXT NOT NULL,
                response_model TEXT NOT NULL,
                attempt_count INTEGER NOT NULL,
                prompt_version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE monitoring_ai_candidates (
                candidate_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL
            );
            """
        )
        for index, status in enumerate(statuses):
            connection.execute(
                """
                INSERT INTO monitoring_ai_jobs VALUES (
                    ?, 'proj_real', 'listing_field_mapping', ?,
                    ?, 'revision', 'payload', '', '', '', 'provider',
                    'model', 'model', 1, 'monitoring-listing-field-mapping-v7',
                    '2026-07-29T00:00:00Z', '2026-07-29T00:00:00Z'
                )
                """,
                (f"job-{index}", status, f"batch:domain:{index}"),
            )
            if status == "completed":
                connection.execute(
                    "INSERT INTO monitoring_ai_candidates VALUES (?, ?)",
                    (f"candidate-{index}", f"job-{index}"),
                )


def test_v7_summary_marks_only_nonterminal_jobs_pending(tmp_path: Path) -> None:
    database = tmp_path / "monitoring.sqlite3"
    _seed(database, ("completed", "failed", "stale_input", "queued", "running"))

    summary = MODULE._v7_summary(database)

    assert summary["status_counts"] == {
        "completed": 1,
        "failed": 1,
        "queued": 1,
        "running": 1,
        "stale_input": 1,
    }
    assert {item["status"] for item in summary["nonterminal_jobs"]} == {
        "queued",
        "running",
    }
    completed = next(item for item in summary["jobs"] if item["status"] == "completed")
    assert completed["candidate_count"] == 1


def test_online_backup_is_consistent_and_independent(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    destination = tmp_path / "backup" / "copy.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE evidence (value TEXT NOT NULL)")
        connection.execute("INSERT INTO evidence VALUES ('baseline')")

    MODULE._backup_database(source, destination)
    with sqlite3.connect(source) as connection:
        connection.execute("INSERT INTO evidence VALUES ('after-backup')")

    with sqlite3.connect(destination) as connection:
        values = [
            row[0] for row in connection.execute("SELECT value FROM evidence").fetchall()
        ]
    assert values == ["baseline"]
