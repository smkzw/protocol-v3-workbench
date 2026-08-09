#!/usr/bin/env python3
"""Create a lossless, privacy-minimized checkpoint before V7 -> V10 cutover."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_DATABASES = (
    "medical_monitoring_ai.sqlite3",
    "medical_monitoring_batches.sqlite3",
    "medical_monitoring_daily_runs.sqlite3",
    "medical_risks.sqlite3",
    "monitoring_protocol_rules.sqlite3",
)
TERMINAL_STATUSES = frozenset({"completed", "failed", "blocked", "cancelled", "stale_input"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def _v7_summary(ai_db: Path) -> dict[str, Any]:
    with _connect(ai_db) as connection:
        rows = connection.execute(
            """
            SELECT
                job_id,
                project_id,
                business_key,
                status,
                input_revision_sha256,
                input_payload_sha256,
                output_sha256,
                failure_code,
                provider,
                requested_model,
                response_model,
                attempt_count,
                created_at,
                updated_at
            FROM monitoring_ai_jobs
            WHERE task_type = 'listing_field_mapping'
              AND prompt_version = 'monitoring-listing-field-mapping-v7'
            ORDER BY project_id, business_key
            """
        ).fetchall()
        candidate_counts = {
            row["job_id"]: row["candidate_count"]
            for row in connection.execute(
                """
                SELECT job_id, COUNT(*) AS candidate_count
                FROM monitoring_ai_candidates
                GROUP BY job_id
                """
            ).fetchall()
        }

    jobs = []
    status_counts: dict[str, int] = {}
    project_counts: dict[str, dict[str, int]] = {}
    nonterminal = []
    for row in rows:
        item = dict(row)
        item["candidate_count"] = candidate_counts.get(row["job_id"], 0)
        jobs.append(item)
        status = str(row["status"])
        project = str(row["project_id"])
        status_counts[status] = status_counts.get(status, 0) + 1
        project_status = project_counts.setdefault(project, {})
        project_status[status] = project_status.get(status, 0) + 1
        if status not in TERMINAL_STATUSES:
            nonterminal.append(
                {
                    "job_id": row["job_id"],
                    "project_id": project,
                    "business_key": row["business_key"],
                    "status": status,
                    "updated_at": row["updated_at"],
                }
            )
    return {
        "prompt_version": "monitoring-listing-field-mapping-v7",
        "job_count": len(jobs),
        "status_counts": status_counts,
        "project_status_counts": project_counts,
        "nonterminal_jobs": nonterminal,
        "jobs": jobs,
    }


def _backup_database(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source, timeout=30) as source_connection:
        with sqlite3.connect(destination, timeout=30) as destination_connection:
            source_connection.backup(destination_connection)
            destination_connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Write the audit summary and online database backups.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    runtime_dir = args.runtime_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    ai_db = runtime_dir / "medical_monitoring_ai.sqlite3"
    if not ai_db.is_file():
        raise SystemExit(f"missing monitoring AI database: {ai_db}")

    summary = _v7_summary(ai_db)
    readiness = {
        "ready": not summary["nonterminal_jobs"],
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "runtime_dir": str(runtime_dir),
        "output_dir": str(output_dir),
        "status_counts": summary["status_counts"],
        "project_status_counts": summary["project_status_counts"],
        "nonterminal_count": len(summary["nonterminal_jobs"]),
    }
    print(json.dumps(readiness, ensure_ascii=False, indent=2))
    if not args.execute:
        return 0 if readiness["ready"] else 2
    if not readiness["ready"]:
        raise SystemExit("V7 queue is not terminal; checkpoint was not written")

    output_dir.mkdir(parents=True, exist_ok=False)
    summary_path = output_dir / "v7_mapping_audit_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    manifest: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_runtime_dir": str(runtime_dir),
        "files": {},
    }
    for name in DEFAULT_DATABASES:
        source = runtime_dir / name
        if not source.is_file():
            continue
        destination = output_dir / "sqlite" / name
        _backup_database(source, destination)
        manifest["files"][str(destination.relative_to(output_dir))] = {
            "sha256": _sha256(destination),
            "bytes": destination.stat().st_size,
        }
    manifest["files"][summary_path.name] = {
        "sha256": _sha256(summary_path),
        "bytes": summary_path.stat().st_size,
    }
    manifest_path = output_dir / "MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"checkpoint={output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
