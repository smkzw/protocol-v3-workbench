#!/usr/bin/env python3
"""Archive and remove user-created E2E projects from local runtime stores.

The static real-project catalog is code-backed and is never touched. Downloaded,
content-addressed reference artifacts are retained as a reusable local cache.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def project_ids(project_db: Path) -> list[str]:
    with sqlite3.connect(project_db) as connection:
        return [
            str(row[0])
            for row in connection.execute(
                "SELECT project_id FROM user_projects ORDER BY created_at, project_id"
            )
        ]


def project_manifest(project_db: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(project_db) as connection:
        connection.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM user_projects ORDER BY created_at, project_id"
            )
        ]


def project_tables(connection: sqlite3.Connection) -> list[str]:
    tables = [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    return [
        table
        for table in tables
        if any(
            str(row[1]) == "project_id"
            for row in connection.execute(f'PRAGMA table_info("{table}")')
        )
    ]


def child_first_project_tables(connection: sqlite3.Connection) -> list[str]:
    tables = project_tables(connection)
    table_set = set(tables)
    edges: dict[str, set[str]] = {table: set() for table in tables}
    indegree = {table: 0 for table in tables}
    for child in tables:
        for row in connection.execute(f'PRAGMA foreign_key_list("{child}")'):
            parent = str(row[2])
            if parent in table_set and parent != child and parent not in edges[child]:
                edges[child].add(parent)
                indegree[parent] += 1
    ready = sorted(table for table, degree in indegree.items() if degree == 0)
    ordered: list[str] = []
    while ready:
        child = ready.pop(0)
        ordered.append(child)
        for parent in sorted(edges[child]):
            indegree[parent] -= 1
            if indegree[parent] == 0:
                ready.append(parent)
                ready.sort()
    if len(ordered) != len(tables):
        cyclic = sorted(table_set.difference(ordered))
        raise RuntimeError(f"cyclic project-table foreign keys in database: {cyclic}")
    return ordered


def matching_counts(db_path: Path, ids: list[str]) -> dict[str, int]:
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    with sqlite3.connect(db_path) as connection:
        counts: dict[str, int] = {}
        for table in project_tables(connection):
            count = int(
                connection.execute(
                    f'SELECT COUNT(*) FROM "{table}" '
                    f"WHERE project_id IN ({placeholders})",
                    ids,
                ).fetchone()[0]
            )
            if count:
                counts[table] = count
        return counts


def delete_protected_tables(connection: sqlite3.Connection) -> dict[str, str]:
    protected: dict[str, str] = {}
    for trigger_name, table_name, sql in connection.execute(
        "SELECT name, tbl_name, COALESCE(sql, '') FROM sqlite_master "
        "WHERE type='trigger'"
    ):
        normalized = str(sql).upper()
        if "BEFORE DELETE" in normalized and "RAISE(" in normalized:
            protected[str(table_name)] = str(trigger_name)
    return protected


def retained_dependency_tables(
    connection: sqlite3.Connection,
    protected: dict[str, str],
) -> dict[str, str]:
    project_scoped = set(project_tables(connection))
    all_tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    parents_by_child: dict[str, set[str]] = {table: set() for table in all_tables}
    incoming_from_unscoped: dict[str, set[str]] = {
        table: set() for table in project_scoped
    }
    for child in all_tables:
        for row in connection.execute(f'PRAGMA foreign_key_list("{child}")'):
            parent = str(row[2])
            if parent in all_tables:
                parents_by_child[child].add(parent)
                if child not in project_scoped and parent in project_scoped:
                    incoming_from_unscoped[parent].add(child)

    retained = {
        table: f"delete protected by trigger {trigger}"
        for table, trigger in protected.items()
        if table in project_scoped
    }
    for parent, children in incoming_from_unscoped.items():
        if children:
            retained[parent] = (
                "referenced by non-project-scoped table(s): "
                + ", ".join(sorted(children))
            )

    queue = list(retained)
    while queue:
        child = queue.pop()
        for parent in parents_by_child.get(child, set()):
            if parent in project_scoped and parent not in retained:
                retained[parent] = f"required parent of retained table {child}"
                queue.append(parent)
    return retained


def backup_database(db_path: Path, backup_dir: Path) -> dict[str, Any]:
    backup_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=backup_dir) as temp_dir:
        raw_backup = Path(temp_dir) / db_path.name
        with sqlite3.connect(db_path) as source:
            with sqlite3.connect(raw_backup) as target:
                source.backup(target)
        output = backup_dir / f"{db_path.name}.gz"
        with raw_backup.open("rb") as source, gzip.open(output, "wb", compresslevel=6) as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
    return {
        "source": str(db_path),
        "archive": str(output),
        "source_sha256": sha256(db_path),
        "archive_sha256": sha256(output),
        "archive_bytes": output.stat().st_size,
    }


def delete_matches(db_path: Path, ids: list[str]) -> dict[str, Any]:
    placeholders = ",".join("?" for _ in ids)
    deleted: dict[str, int] = {}
    retained_immutable: dict[str, str] = {}
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        protected = delete_protected_tables(connection)
        retained_dependencies = retained_dependency_tables(connection, protected)
        connection.execute("BEGIN IMMEDIATE")
        try:
            for table in child_first_project_tables(connection):
                if table in retained_dependencies:
                    retained_immutable[table] = retained_dependencies[table]
                    continue
                connection.execute("SAVEPOINT purge_table")
                try:
                    cursor = connection.execute(
                        f'DELETE FROM "{table}" WHERE project_id IN ({placeholders})',
                        ids,
                    )
                except sqlite3.IntegrityError as exc:
                    connection.execute("ROLLBACK TO purge_table")
                    connection.execute("RELEASE purge_table")
                    if "immutable" not in str(exc).lower():
                        raise
                    retained_immutable[table] = str(exc)
                    continue
                connection.execute("RELEASE purge_table")
                if cursor.rowcount:
                    deleted[table] = int(cursor.rowcount)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {
        "deleted_rows": deleted,
        "retained_immutable_rows": retained_immutable,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform the deletion. Without this flag the command is read-only.",
    )
    args = parser.parse_args()

    runtime = args.runtime.resolve()
    project_db = runtime / "user_projects.sqlite3"
    ids = project_ids(project_db)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_dir = args.archive_root.resolve() / f"user_test_projects_{stamp}"

    databases: list[dict[str, Any]] = []
    for db_path in sorted(runtime.glob("*.sqlite3")):
        counts = matching_counts(db_path, ids)
        if counts:
            databases.append(
                {
                    "path": str(db_path),
                    "matching_rows": counts,
                    "matching_total": sum(counts.values()),
                }
            )

    report: dict[str, Any] = {
        "schema": "workbench_user_test_project_purge_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if args.apply else "dry_run",
        "runtime": str(runtime),
        "project_count": len(ids),
        "project_ids": ids,
        "projects": project_manifest(project_db),
        "databases": databases,
        "retained": [
            "code-backed static real-project catalog",
            "content-addressed writing_reference_artifacts cache",
            "durable records, evidence, reviews, runs, and handoff logs outside runtime databases",
        ],
    }

    if args.apply:
        archive_dir.mkdir(parents=True, exist_ok=False)
        backups = []
        for item in databases:
            backups.append(backup_database(Path(item["path"]), archive_dir))
        report["backups"] = backups

        deletion_results = []
        for item in databases:
            db_path = Path(item["path"])
            deletion_results.append(
                {"path": str(db_path), **delete_matches(db_path, ids)}
            )
        report["deletion_results"] = deletion_results

        remaining = project_ids(project_db)
        report["remaining_user_project_ids"] = remaining
        if remaining:
            raise RuntimeError(f"user projects remain after purge: {remaining[:5]}")

    output_dir = archive_dir if args.apply else args.archive_root.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / (
        "purge_manifest.json" if args.apply else "purge_dry_run.json"
    )
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"report": str(output_path), "project_count": len(ids)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
