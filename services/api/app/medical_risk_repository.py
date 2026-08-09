from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Iterable, Union

from packages.contracts.workbench_contracts.models import RiskCase, RiskStatus

from .medical_monitoring_risk_taxonomy import (
    normalize_risk_case_category,
    validate_risk_case_category_domains,
)


_VOLATILE_MEANING_FIELDS = {
    "risk_id",
    "risk_instance_id",
    "source_batch_id",
    "source_revision",
    "rule_profile_revision",
    "engine_version",
    "batch_delta",
    "created_at",
    "closed_at",
    "closure_evidence",
}


def _strict_bool(value: object, field: str) -> bool:
    """Accept only an actual Boolean at an application write boundary."""

    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _sqlite_bool(value: object, field: str) -> bool:
    """Hydrate a Boolean from SQLite without truthiness coercion."""

    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return value == 1
    raise ValueError(f"{field} must be a SQLite boolean (0/1)")


def _semantic_risk_payload(risks: Iterable[Union[RiskCase, dict]]) -> list[dict]:
    payloads = []
    for risk in risks:
        payload = risk.model_dump(mode="json") if isinstance(risk, RiskCase) else dict(risk)
        payload.pop("created_at", None)
        payloads.append(payload)
    return sorted(payloads, key=lambda item: item.get("risk_instance_id", ""))


def _semantic_payload_hash(risks: Iterable[Union[RiskCase, dict]]) -> str:
    return sha256(
        json.dumps(
            _semantic_risk_payload(risks),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _medical_meaning_payload(risk: RiskCase) -> dict:
    payload = risk.model_dump(mode="json")
    for field in _VOLATILE_MEANING_FIELDS:
        payload.pop(field, None)
    return payload


def _snapshot_instance_identity(risk_key: str, source_revision: str, batch_delta: str) -> tuple[str, str]:
    digest = sha256(f"{risk_key}|{source_revision}|{batch_delta}".encode("utf-8")).hexdigest()[:20]
    return f"risk_{digest}", f"riskinst_{digest}"


@dataclass(frozen=True)
class MedicalRiskSnapshot:
    snapshot_id: str
    project_id: str
    source_batch_id: str | None
    source_revision: str
    rule_profile_revision: str
    engine_version: str
    risk_count: int
    evaluated_subject_count: int
    created_at: datetime
    previous_snapshot_id: str | None = None
    resolution_complete: bool = False
    resolution_eligible_risk_keys: tuple[str, ...] = ()


class MedicalRiskRepository:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS medical_risk_snapshots (
                    snapshot_seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id TEXT NOT NULL UNIQUE,
                    project_id TEXT NOT NULL,
                    source_batch_id TEXT,
                    source_revision TEXT NOT NULL,
                    rule_profile_revision TEXT NOT NULL,
                    engine_version TEXT NOT NULL,
                    risk_count INTEGER NOT NULL,
                    evaluated_subject_count INTEGER NOT NULL DEFAULT 0,
                    previous_snapshot_id TEXT,
                    resolution_complete INTEGER NOT NULL DEFAULT 0,
                    resolution_eligible_risk_keys_json TEXT NOT NULL DEFAULT '[]',
                    payload_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(project_id, source_revision, rule_profile_revision, engine_version)
                );

                CREATE TABLE IF NOT EXISTS medical_risk_instances (
                    snapshot_id TEXT NOT NULL,
                    risk_instance_id TEXT NOT NULL,
                    risk_key TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    scope_type TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    primary_category TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    status TEXT NOT NULL,
                    batch_delta TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY(snapshot_id, risk_instance_id),
                    FOREIGN KEY(snapshot_id) REFERENCES medical_risk_snapshots(snapshot_id)
                );

                CREATE INDEX IF NOT EXISTS idx_medical_risk_snapshot_project
                    ON medical_risk_snapshots(project_id, snapshot_seq DESC);
                CREATE INDEX IF NOT EXISTS idx_medical_risk_instance_filter
                    ON medical_risk_instances(snapshot_id, scope_type, scope_id, primary_category, severity, status);
                CREATE INDEX IF NOT EXISTS idx_medical_risk_key
                    ON medical_risk_instances(project_id, risk_key);
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(medical_risk_snapshots)").fetchall()
            }
            if "evaluated_subject_count" not in columns:
                connection.execute(
                    "ALTER TABLE medical_risk_snapshots "
                    "ADD COLUMN evaluated_subject_count INTEGER NOT NULL DEFAULT 0"
                )
            if "source_batch_id" not in columns:
                connection.execute(
                    "ALTER TABLE medical_risk_snapshots ADD COLUMN source_batch_id TEXT"
                )
            if "previous_snapshot_id" not in columns:
                connection.execute(
                    "ALTER TABLE medical_risk_snapshots ADD COLUMN previous_snapshot_id TEXT"
                )
            if "resolution_complete" not in columns:
                connection.execute(
                    "ALTER TABLE medical_risk_snapshots "
                    "ADD COLUMN resolution_complete INTEGER NOT NULL DEFAULT 0"
                )
            if "resolution_eligible_risk_keys_json" not in columns:
                connection.execute(
                    "ALTER TABLE medical_risk_snapshots "
                    "ADD COLUMN resolution_eligible_risk_keys_json TEXT NOT NULL DEFAULT '[]'"
                )

    @staticmethod
    def _validate_snapshot_risks(
        *,
        project_id: str,
        source_batch_id: str | None,
        source_revision: str,
        rule_profile_revision: str,
        engine_version: str,
        risks: list[RiskCase],
    ) -> list[RiskCase]:
        normalized: list[RiskCase] = []
        seen_risk_keys: set[str] = set()
        for risk in risks:
            risk = normalize_risk_case_category(risk)
            validate_risk_case_category_domains(risk)
            if risk.project_id != project_id:
                raise ValueError(f"risk project mismatch: expected {project_id}, got {risk.project_id}")
            if (
                source_batch_id
                and risk.source_batch_id
                and risk.source_batch_id != source_batch_id
            ):
                raise ValueError("risk source batch does not match snapshot")
            if risk.source_revision and risk.source_revision != source_revision:
                raise ValueError("risk source revision does not match snapshot")
            if risk.rule_profile_revision and risk.rule_profile_revision != rule_profile_revision:
                raise ValueError("risk rule profile revision does not match snapshot")
            if risk.engine_version and risk.engine_version != engine_version:
                raise ValueError("risk engine version does not match snapshot")
            if risk.risk_key in seen_risk_keys:
                raise ValueError(f"duplicate risk_key in snapshot: {risk.risk_key}")
            seen_risk_keys.add(risk.risk_key)
            normalized.append(
                risk.model_copy(
                    update={
                        "source_revision": source_revision,
                        "source_batch_id": source_batch_id or risk.source_batch_id,
                        "rule_profile_revision": rule_profile_revision,
                        "engine_version": engine_version,
                    }
                )
            )
        return normalized

    @staticmethod
    def _previous_snapshot_row(
        connection: sqlite3.Connection,
        *,
        project_id: str,
        before_snapshot_seq: int | None = None,
    ) -> sqlite3.Row | None:
        if before_snapshot_seq is None:
            return connection.execute(
                """
                SELECT * FROM medical_risk_snapshots
                WHERE project_id = ?
                ORDER BY snapshot_seq DESC
                LIMIT 1
                """,
                (project_id,),
            ).fetchone()
        return connection.execute(
            """
            SELECT * FROM medical_risk_snapshots
            WHERE project_id = ? AND snapshot_seq < ?
            ORDER BY snapshot_seq DESC
            LIMIT 1
            """,
            (project_id, before_snapshot_seq),
        ).fetchone()

    @staticmethod
    def _load_snapshot_risks(
        connection: sqlite3.Connection,
        snapshot_id: str,
    ) -> list[RiskCase]:
        rows = connection.execute(
            """
            SELECT payload_json FROM medical_risk_instances
            WHERE snapshot_id = ?
            ORDER BY risk_instance_id
            """,
            (snapshot_id,),
        ).fetchall()
        return [RiskCase.model_validate_json(row["payload_json"]) for row in rows]

    @staticmethod
    def _carried_risk(
        previous: RiskCase,
        *,
        source_revision: str,
        rule_profile_revision: str,
        engine_version: str,
        batch_delta: str,
        status: RiskStatus,
        closure_evidence: str,
    ) -> RiskCase:
        risk_id, risk_instance_id = _snapshot_instance_identity(
            previous.risk_key,
            source_revision,
            batch_delta,
        )
        return previous.model_copy(
            update={
                "risk_id": risk_id,
                "risk_instance_id": risk_instance_id,
                "source_batch_id": None,
                "source_revision": source_revision,
                "rule_profile_revision": rule_profile_revision,
                "engine_version": engine_version,
                "batch_delta": batch_delta,
                "status": status,
                "closed_at": None,
                "closure_evidence": closure_evidence,
            }
        )

    @classmethod
    def _classify_batch_deltas(
        cls,
        *,
        current_risks: list[RiskCase],
        previous_risks: list[RiskCase],
        previous_snapshot_id: str | None,
        source_revision: str,
        rule_profile_revision: str,
        engine_version: str,
        resolution_complete: bool,
        resolution_eligible_risk_keys: set[str],
    ) -> list[RiskCase]:
        if not previous_risks:
            return [risk.model_copy(update={"batch_delta": "baseline"}) for risk in current_risks]

        previous_by_key = {risk.risk_key: risk for risk in previous_risks}
        current_by_key = {risk.risk_key: risk for risk in current_risks}
        current_episode_groups = {
            (risk.scope_type, risk.scope_id, risk.rule_id)
            for risk in current_risks
            if risk.aggregation_scope == "episode"
        }
        classified: list[RiskCase] = []
        rule_or_engine_changed = any(
            previous.rule_profile_revision != rule_profile_revision
            or previous.engine_version != engine_version
            for previous in previous_risks
        )

        for risk in current_risks:
            previous = previous_by_key.get(risk.risk_key)
            if previous is None:
                batch_delta = "new"
            elif previous.status in {RiskStatus.RESOLVED, RiskStatus.CLOSED} or previous.batch_delta == "resolved_by_data":
                batch_delta = "reopened"
            elif (
                previous.rule_profile_revision != rule_profile_revision
                or previous.engine_version != engine_version
            ):
                batch_delta = "requires_rereview"
            elif _medical_meaning_payload(previous) != _medical_meaning_payload(risk):
                batch_delta = "changed"
            else:
                batch_delta = "persisting"
            classified.append(risk.model_copy(update={"batch_delta": batch_delta}))

        for risk_key, previous in previous_by_key.items():
            if risk_key in current_by_key:
                continue
            prior_reference = f"previous_snapshot_id={previous_snapshot_id or 'none'}"
            episode_group = (previous.scope_type, previous.scope_id, previous.rule_id)
            if (
                previous.status == RiskStatus.SUPERSEDED
                or previous.batch_delta == "superseded_by_engine"
            ):
                classified.append(
                    cls._carried_risk(
                        previous,
                        source_revision=source_revision,
                        rule_profile_revision=rule_profile_revision,
                        engine_version=engine_version,
                        batch_delta="superseded_by_engine",
                        status=RiskStatus.SUPERSEDED,
                        closure_evidence=previous.closure_evidence,
                    )
                )
            elif (
                rule_or_engine_changed
                and previous.aggregation_scope == "rule_scope"
                and episode_group in current_episode_groups
            ):
                classified.append(
                    cls._carried_risk(
                        previous,
                        source_revision=source_revision,
                        rule_profile_revision=rule_profile_revision,
                        engine_version=engine_version,
                        batch_delta="superseded_by_engine",
                        status=RiskStatus.SUPERSEDED,
                        closure_evidence=(
                            "engine_identity_migration: aggregate rule-scope risk "
                            "replaced by episode-level risks for the same scope and rule; "
                            f"{prior_reference}"
                        ),
                    )
                )
            elif previous.status == RiskStatus.RESOLVED or previous.batch_delta == "resolved_by_data":
                classified.append(
                    cls._carried_risk(
                        previous,
                        source_revision=source_revision,
                        rule_profile_revision=rule_profile_revision,
                        engine_version=engine_version,
                        batch_delta="resolved_by_data",
                        status=RiskStatus.RESOLVED,
                        closure_evidence=previous.closure_evidence,
                    )
                )
            elif (
                resolution_complete
                and risk_key in resolution_eligible_risk_keys
                and not rule_or_engine_changed
            ):
                classified.append(
                    cls._carried_risk(
                        previous,
                        source_revision=source_revision,
                        rule_profile_revision=rule_profile_revision,
                        engine_version=engine_version,
                        batch_delta="resolved_by_data",
                        status=RiskStatus.RESOLVED,
                        closure_evidence=(
                            "complete_source_reconciliation: risk absent from "
                            f"source_revision={source_revision}; {prior_reference}"
                        ),
                    )
                )
            else:
                reason = "rule_or_engine_changed" if rule_or_engine_changed else "incomplete_source_reconciliation"
                classified.append(
                    cls._carried_risk(
                        previous,
                        source_revision=source_revision,
                        rule_profile_revision=rule_profile_revision,
                        engine_version=engine_version,
                        batch_delta="requires_rereview",
                        status=previous.status,
                        closure_evidence=(
                            f"{reason}: risk absence not treated as resolution; "
                            f"source_revision={source_revision}; {prior_reference}"
                        ),
                    )
                )
        return classified

    def save_snapshot(
        self,
        *,
        project_id: str,
        source_batch_id: str | None = None,
        source_revision: str,
        rule_profile_revision: str,
        engine_version: str,
        evaluated_subject_count: int,
        risks: Iterable[RiskCase],
        resolution_complete: bool = False,
        resolution_eligible_risk_keys: Iterable[str] = (),
    ) -> MedicalRiskSnapshot:
        resolution_complete = _strict_bool(
            resolution_complete,
            "resolution_complete",
        )
        risk_list = self._validate_snapshot_risks(
            project_id=project_id,
            source_batch_id=source_batch_id,
            source_revision=source_revision,
            rule_profile_revision=rule_profile_revision,
            engine_version=engine_version,
            risks=list(risks),
        )
        snapshot_identity = (
            f"{project_id}|{source_revision}|{rule_profile_revision}|{engine_version}"
            + (f"|batch:{source_batch_id}" if source_batch_id else "")
        )
        snapshot_hash = sha256(snapshot_identity.encode("utf-8")).hexdigest()[:20]
        snapshot_id = f"risksnap_{snapshot_hash}"
        created_at = datetime.now(timezone.utc)
        eligible_risk_keys = tuple(sorted(set(resolution_eligible_risk_keys)))
        eligible_risk_keys_json = json.dumps(eligible_risk_keys, ensure_ascii=False)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM medical_risk_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
            if existing is not None:
                previous_snapshot = self._previous_snapshot_row(
                    connection,
                    project_id=project_id,
                    before_snapshot_seq=existing["snapshot_seq"],
                )
            else:
                previous_snapshot = self._previous_snapshot_row(connection, project_id=project_id)
            previous_snapshot_id = (
                previous_snapshot["snapshot_id"] if previous_snapshot is not None else None
            )
            if previous_snapshot is not None:
                self._verify_snapshot_integrity(connection, previous_snapshot)
            previous_risks = (
                self._load_snapshot_risks(connection, previous_snapshot_id)
                if previous_snapshot_id
                else []
            )
            classified_risks = self._classify_batch_deltas(
                current_risks=risk_list,
                previous_risks=previous_risks,
                previous_snapshot_id=previous_snapshot_id,
                source_revision=source_revision,
                rule_profile_revision=rule_profile_revision,
                engine_version=engine_version,
                resolution_complete=resolution_complete,
                resolution_eligible_risk_keys=set(eligible_risk_keys),
            )
            if source_batch_id:
                classified_risks = [
                    risk.model_copy(
                        update={"source_batch_id": source_batch_id}
                    )
                    for risk in classified_risks
                ]
            payload_hash = _semantic_payload_hash(classified_risks)
            if existing is not None:
                if _sqlite_bool(
                    existing["resolution_complete"],
                    "medical_risk_snapshots.resolution_complete",
                ) != resolution_complete:
                    raise ValueError(
                        "snapshot resolution completeness conflict for identical source/rule/engine revisions"
                    )
                if existing["resolution_eligible_risk_keys_json"] != eligible_risk_keys_json:
                    raise ValueError(
                        "snapshot resolution eligibility conflict for identical source/rule/engine revisions"
                    )
                if existing["payload_hash"] != payload_hash:
                    stored_rows = connection.execute(
                        "SELECT payload_json FROM medical_risk_instances WHERE snapshot_id = ?",
                        (snapshot_id,),
                    ).fetchall()
                    stored_hash = _semantic_payload_hash(
                        json.loads(stored_row["payload_json"])
                        for stored_row in stored_rows
                    )
                    if stored_hash != payload_hash:
                        raise ValueError("snapshot payload conflict for identical source/rule/engine revisions")
                    connection.execute(
                        "UPDATE medical_risk_snapshots SET payload_hash = ? WHERE snapshot_id = ?",
                        (payload_hash, snapshot_id),
                    )
                self._verify_snapshot_integrity(connection, existing)
                return self._snapshot(existing)
            connection.execute(
                """
                INSERT INTO medical_risk_snapshots(
                    snapshot_id, project_id, source_batch_id,
                    source_revision, rule_profile_revision,
                    engine_version, risk_count, evaluated_subject_count, previous_snapshot_id,
                    resolution_complete, resolution_eligible_risk_keys_json, payload_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    project_id,
                    source_batch_id,
                    source_revision,
                    rule_profile_revision,
                    engine_version,
                    len(classified_risks),
                    evaluated_subject_count,
                    previous_snapshot_id,
                    int(resolution_complete),
                    eligible_risk_keys_json,
                    payload_hash,
                    created_at.isoformat(),
                ),
            )
            for risk in classified_risks:
                connection.execute(
                    """
                    INSERT INTO medical_risk_instances(
                        snapshot_id, risk_instance_id, risk_key, project_id,
                        scope_type, scope_id, primary_category, severity, status,
                        batch_delta, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        risk.risk_instance_id,
                        risk.risk_key,
                        project_id,
                        risk.scope_type,
                        risk.scope_id,
                        risk.primary_category,
                        risk.severity.value,
                        risk.status.value,
                        risk.batch_delta,
                        risk.model_dump_json(),
                    ),
                )
        return MedicalRiskSnapshot(
            snapshot_id=snapshot_id,
            project_id=project_id,
            source_batch_id=source_batch_id,
            source_revision=source_revision,
            rule_profile_revision=rule_profile_revision,
            engine_version=engine_version,
            risk_count=len(classified_risks),
            evaluated_subject_count=evaluated_subject_count,
            created_at=created_at,
            previous_snapshot_id=previous_snapshot_id,
            resolution_complete=resolution_complete,
            resolution_eligible_risk_keys=eligible_risk_keys,
        )

    def current_snapshot(self, project_id: str) -> MedicalRiskSnapshot:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM medical_risk_snapshots
                WHERE project_id = ?
                ORDER BY snapshot_seq DESC
                LIMIT 1
                """,
                (project_id,),
            ).fetchone()
        if row is None:
            raise KeyError(project_id)
        self._verify_snapshot_integrity(connection, row)
        return self._snapshot(row)

    def snapshot(
        self,
        project_id: str,
        snapshot_id: str,
    ) -> MedicalRiskSnapshot:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM medical_risk_snapshots
                WHERE project_id = ? AND snapshot_id = ?
                """,
                (project_id, snapshot_id),
            ).fetchone()
        if row is None:
            raise KeyError((project_id, snapshot_id))
        self._verify_snapshot_integrity(connection, row)
        return self._snapshot(row)

    def record_evaluated_subject_count_if_unknown(
        self,
        snapshot_id: str,
        evaluated_subject_count: int,
    ) -> MedicalRiskSnapshot:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE medical_risk_snapshots
                SET evaluated_subject_count = ?
                WHERE snapshot_id = ? AND evaluated_subject_count = 0
                """,
                (evaluated_subject_count, snapshot_id),
            )
            row = connection.execute(
                "SELECT * FROM medical_risk_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            raise KeyError(snapshot_id)
        self._verify_snapshot_integrity(connection, row)
        return self._snapshot(row)

    def list_risks(self, project_id: str, snapshot_id: str | None = None) -> list[RiskCase]:
        selected_snapshot_id = snapshot_id or self.current_snapshot(project_id).snapshot_id
        with self._connect() as connection:
            snapshot_row = connection.execute(
                "SELECT * FROM medical_risk_snapshots "
                "WHERE project_id = ? AND snapshot_id = ?",
                (project_id, selected_snapshot_id),
            ).fetchone()
            if snapshot_row is None:
                raise KeyError((project_id, selected_snapshot_id))
            self._verify_snapshot_integrity(connection, snapshot_row)
            rows = connection.execute(
                """
                SELECT payload_json FROM medical_risk_instances
                WHERE snapshot_id = ? AND project_id = ?
                ORDER BY risk_instance_id
                """,
                (selected_snapshot_id, project_id),
            ).fetchall()
        return [RiskCase.model_validate_json(row["payload_json"]) for row in rows]

    def risk_history(
        self,
        project_id: str,
        risk_key: str,
    ) -> list[tuple[MedicalRiskSnapshot, RiskCase]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT snapshots.*, instances.payload_json
                FROM medical_risk_instances AS instances
                JOIN medical_risk_snapshots AS snapshots
                  ON snapshots.snapshot_id = instances.snapshot_id
                WHERE instances.project_id = ? AND instances.risk_key = ?
                ORDER BY snapshots.snapshot_seq, instances.risk_instance_id
                """,
                (project_id, risk_key),
            ).fetchall()
            for row in rows:
                self._verify_snapshot_integrity(connection, row)
        return [
            (
                self._snapshot(row),
                RiskCase.model_validate_json(row["payload_json"]),
            )
            for row in rows
        ]

    def risk_instance(
        self,
        project_id: str,
        risk_instance_id: str,
        snapshot_id: str = "",
    ) -> tuple[MedicalRiskSnapshot, RiskCase]:
        snapshot_clause = " AND snapshots.snapshot_id = ?" if snapshot_id else ""
        params = (
            (project_id, risk_instance_id, snapshot_id)
            if snapshot_id
            else (project_id, risk_instance_id)
        )
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT snapshots.*, instances.payload_json
                FROM medical_risk_instances AS instances
                JOIN medical_risk_snapshots AS snapshots
                  ON snapshots.snapshot_id = instances.snapshot_id
                WHERE instances.project_id = ?
                  AND instances.risk_instance_id = ?
                  {snapshot_clause}
                ORDER BY snapshots.snapshot_seq DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        if row is None:
            raise KeyError((project_id, risk_instance_id))
        self._verify_snapshot_integrity(connection, row)
        return (
            self._snapshot(row),
            RiskCase.model_validate_json(row["payload_json"]),
        )

    @staticmethod
    def _verify_snapshot_integrity(
        connection: sqlite3.Connection,
        snapshot_row: sqlite3.Row,
    ) -> None:
        source_batch_id = (
            snapshot_row["source_batch_id"]
            if "source_batch_id" in snapshot_row.keys()
            else None
        )
        snapshot_identity = (
            f"{snapshot_row['project_id']}|{snapshot_row['source_revision']}|"
            f"{snapshot_row['rule_profile_revision']}|{snapshot_row['engine_version']}"
            + (f"|batch:{source_batch_id}" if source_batch_id else "")
        )
        expected_snapshot_id = (
            "risksnap_"
            + sha256(snapshot_identity.encode("utf-8")).hexdigest()[:20]
        )
        if snapshot_row["snapshot_id"] != expected_snapshot_id:
            raise ValueError("medical risk snapshot identity mismatch")
        try:
            resolution_keys = tuple(
                json.loads(snapshot_row["resolution_eligible_risk_keys_json"])
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("medical risk snapshot resolution metadata is invalid") from exc
        if (
            any(not isinstance(item, str) or not item.strip() for item in resolution_keys)
            or resolution_keys != tuple(sorted(set(resolution_keys)))
        ):
            raise ValueError("medical risk snapshot resolution metadata is invalid")
        _sqlite_bool(
            snapshot_row["resolution_complete"],
            "medical_risk_snapshots.resolution_complete",
        )
        rows = connection.execute(
            "SELECT * FROM medical_risk_instances "
            "WHERE snapshot_id = ? ORDER BY risk_instance_id",
            (snapshot_row["snapshot_id"],),
        ).fetchall()
        risks: list[RiskCase] = []
        seen_risk_keys: set[str] = set()
        for instance_row in rows:
            try:
                risk = RiskCase.model_validate_json(instance_row["payload_json"])
            except (TypeError, ValueError) as exc:
                raise ValueError("medical risk snapshot instance payload is invalid") from exc
            risk_payload = risk.model_dump(mode="json")
            for field in (
                "project_id",
                "risk_instance_id",
                "risk_key",
                "scope_type",
                "scope_id",
                "primary_category",
                "severity",
                "status",
                "batch_delta",
            ):
                if risk_payload.get(field) != instance_row[field]:
                    raise ValueError(
                        "medical risk snapshot instance row identity mismatch"
                    )
            if risk_payload.get("project_id") != snapshot_row["project_id"]:
                raise ValueError("medical risk snapshot instance project mismatch")
            if risk_payload.get("source_revision") != snapshot_row["source_revision"]:
                raise ValueError("medical risk snapshot instance source mismatch")
            if risk_payload.get("rule_profile_revision") != snapshot_row["rule_profile_revision"]:
                raise ValueError("medical risk snapshot instance rule mismatch")
            if risk_payload.get("engine_version") != snapshot_row["engine_version"]:
                raise ValueError("medical risk snapshot instance engine mismatch")
            if source_batch_id and risk_payload.get("source_batch_id") != source_batch_id:
                raise ValueError("medical risk snapshot instance batch mismatch")
            if risk.risk_key in seen_risk_keys:
                raise ValueError("medical risk snapshot contains duplicate risk_key")
            seen_risk_keys.add(risk.risk_key)
            risks.append(risk)
        if len(risks) != int(snapshot_row["risk_count"]):
            raise ValueError("medical risk snapshot risk count mismatch")
        if _semantic_payload_hash(risks) != snapshot_row["payload_hash"]:
            raise ValueError("medical risk snapshot payload hash mismatch")

    @staticmethod
    def _snapshot(row: sqlite3.Row) -> MedicalRiskSnapshot:
        return MedicalRiskSnapshot(
            snapshot_id=row["snapshot_id"],
            project_id=row["project_id"],
            source_batch_id=(
                str(row["source_batch_id"])
                if "source_batch_id" in row.keys()
                and row["source_batch_id"] is not None
                else None
            ),
            source_revision=row["source_revision"],
            rule_profile_revision=row["rule_profile_revision"],
            engine_version=row["engine_version"],
            risk_count=row["risk_count"],
            evaluated_subject_count=row["evaluated_subject_count"],
            created_at=datetime.fromisoformat(row["created_at"]),
            previous_snapshot_id=row["previous_snapshot_id"],
            resolution_complete=_sqlite_bool(
                row["resolution_complete"],
                "medical_risk_snapshots.resolution_complete",
            ),
            resolution_eligible_risk_keys=tuple(
                json.loads(row["resolution_eligible_risk_keys_json"])
            ),
        )
