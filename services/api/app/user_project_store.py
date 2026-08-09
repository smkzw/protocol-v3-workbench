from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Iterable, Optional
from uuid import uuid4

from packages.contracts.workbench_contracts import UserProjectCreateRequest


@dataclass(frozen=True)
class UserProjectRecord:
    project_id: str
    project_code: str
    project_name: str
    indication: str
    product_name: str
    study_phase: str
    protocol_id: str
    protocol_version: str
    protocol_date: str
    entry_mode: str
    status: str
    created_by: str
    created_at: str
    updated_at: str


class UserProjectStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def create(self, request: UserProjectCreateRequest) -> UserProjectRecord:
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM user_projects WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                return self._record(existing)
            duplicate = connection.execute(
                "SELECT project_id FROM user_projects WHERE lower(project_code) = lower(?)",
                (request.project_code,),
            ).fetchone()
            if duplicate is not None:
                raise ValueError(f"项目编号已存在：{request.project_code}")
            now = datetime.now(timezone.utc).isoformat()
            project_id = f"proj_user_{uuid4().hex[:12]}"
            connection.execute(
                """
                INSERT INTO user_projects (
                    project_id, project_code, project_name, indication, product_name,
                    study_phase, protocol_id, protocol_version, protocol_date,
                    entry_mode, status, created_by, idempotency_key, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
                """,
                (
                    project_id,
                    request.project_code,
                    request.project_name,
                    request.indication,
                    request.product_name,
                    request.study_phase,
                    request.protocol_id,
                    request.protocol_version,
                    request.protocol_date,
                    request.entry_mode,
                    request.actor,
                    request.idempotency_key,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM user_projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            return self._record(row)

    def get(self, project_id: str) -> Optional[UserProjectRecord]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM user_projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        return self._record(row) if row is not None else None

    def records(self) -> Iterable[UserProjectRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM user_projects ORDER BY created_at DESC, project_id"
            ).fetchall()
        return [self._record(row) for row in rows]

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_projects (
                    project_id TEXT PRIMARY KEY,
                    project_code TEXT NOT NULL,
                    project_name TEXT NOT NULL,
                    indication TEXT NOT NULL,
                    product_name TEXT NOT NULL,
                    study_phase TEXT NOT NULL,
                    protocol_id TEXT NOT NULL,
                    protocol_version TEXT NOT NULL,
                    protocol_date TEXT NOT NULL,
                    entry_mode TEXT NOT NULL CHECK(entry_mode IN ('from_zero', 'synopsis_import')),
                    status TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS user_projects_code_ci ON user_projects(lower(project_code))"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _record(row: sqlite3.Row) -> UserProjectRecord:
        return UserProjectRecord(**{
            field: row[field]
            for field in UserProjectRecord.__dataclass_fields__
        })
