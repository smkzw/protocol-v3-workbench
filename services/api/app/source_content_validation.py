from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from packages.contracts.workbench_contracts import (
    ListingSheetPayload,
    SourceContentValidationCheck,
    SourceContentValidationConfirmationRequest,
    SourceContentValidationRecord,
)
from .protocol_text_extractor import ProtocolTextDocument
from .raw_subject_bundle import RawSubjectBundleInventory


VALIDATOR_VERSION = "source_content_consistency_v2"
STUDY_ID_FIELDS = {
    "STUDYID",
    "STUDY_ID",
    "STUDYOID",
    "__STUDYOID",
    "PSTUDYID",
    "PROJECTID",
    "PROJECT_ID",
    "项目编号",
}
SUBJECT_ID_FIELDS = {"USUBJID", "SUBJID", "SUBJECT_ID", "受试者编号", "受试者筛选号"}
CLINICAL_DATA_FIELDS = {
    "VISIT",
    "VISITNUM",
    "AETERM",
    "AEDECOD",
    "MHTERM",
    "MHDECOD",
    "CMTRT",
    "LBTEST",
    "QSTEST",
    "DOMAIN",
}
SAFETY_CORE_FIELDS = {"AETERM", "AEDECOD", "AESER", "AESEV", "AEREL"}
SAFETY_CONTEXT_GROUPS = {
    "medical_history": {
        "label": "病史",
        "header_prefixes": ("MH",),
        "payload_tokens": ("TERM", "DECOD", "DAT", "STDAT", "ENDAT", "DESC"),
    },
    "concomitant_medication": {
        "label": "非试验用药（CM）",
        "header_prefixes": ("CM",),
        "payload_tokens": ("TRT", "INDC", "STDAT", "ENDAT", "DOSE", "AEMH"),
    },
    "study_treatment_change": {
        "label": "试验用药/剂量调整",
        "header_prefixes": ("EX",),
        "payload_tokens": ("TRT", "DOSE", "ADJ", "STDAT", "ENDAT", "FRQ"),
    },
    "laboratory_or_vital_signs": {
        "label": "实验室/生命体征/心电图",
        "header_prefixes": ("LB", "VS", "EG"),
        "payload_tokens": ("TEST", "RES", "DAT", "SIG", "ORRES", "STRES", "PERF"),
    },
}


class SourceContentValidationConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceExpectedContext:
    project_identifiers: tuple[str, ...] = ()
    indication_terms: tuple[str, ...] = ()
    expected_file_role: str = ""
    expected_protocol_version: str = ""
    expected_subject_id: str = ""

    @property
    def context_hash(self) -> str:
        return _sha256_json(asdict(self))


class SourceContentValidationStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def current(self, project_id: str, source_entry_id: str) -> SourceContentValidationRecord:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT record.payload_json
                FROM source_content_validation_state AS state
                JOIN source_content_validation_records AS record
                  ON record.project_id=state.project_id
                 AND record.source_entry_id=state.source_entry_id
                 AND record.revision=state.revision
                WHERE state.project_id=? AND state.source_entry_id=?
                """,
                (project_id, source_entry_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"source validation not found: {project_id}/{source_entry_id}")
        return SourceContentValidationRecord.model_validate_json(row["payload_json"])

    def current_or_none(
        self,
        project_id: str,
        source_entry_id: str,
    ) -> SourceContentValidationRecord | None:
        try:
            return self.current(project_id, source_entry_id)
        except KeyError:
            return None

    def history(
        self,
        project_id: str,
        source_entry_id: str,
    ) -> list[SourceContentValidationRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json
                FROM source_content_validation_records
                WHERE project_id=? AND source_entry_id=?
                ORDER BY revision DESC
                """,
                (project_id, source_entry_id),
            ).fetchall()
        return [
            SourceContentValidationRecord.model_validate_json(row["payload_json"])
            for row in rows
        ]

    def save_assessment(self, record: SourceContentValidationRecord) -> SourceContentValidationRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = self._current_with(connection, record.project_id, record.source_entry_id)
            if current is not None and _same_assessment(current, record):
                connection.rollback()
                return current
            expected_revision = current.revision if current is not None else 0
            if record.revision != expected_revision + 1:
                connection.rollback()
                raise SourceContentValidationConflict(
                    f"source validation revision mismatch: expected={expected_revision + 1}, actual={record.revision}"
                )
            self._insert_record(connection, "assessment", record)
            self._advance_state(connection, record, expected_revision)
            connection.commit()
            return record

    def confirm_after_warning(
        self,
        project_id: str,
        source_entry_id: str,
        request: SourceContentValidationConfirmationRequest,
    ) -> SourceContentValidationRecord:
        request_payload = request.model_dump(mode="json")
        request_hash = _sha256_json(request_payload)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = connection.execute(
                """
                SELECT request_hash, validation_id
                FROM source_content_validation_idempotency
                WHERE project_id=? AND operation='confirmation' AND idempotency_key=?
                """,
                (project_id, request.idempotency_key),
            ).fetchone()
            if replay is not None:
                if replay["request_hash"] != request_hash:
                    connection.rollback()
                    raise SourceContentValidationConflict("idempotency key was reused with a different request")
                row = connection.execute(
                    "SELECT payload_json FROM source_content_validation_records WHERE validation_id=?",
                    (replay["validation_id"],),
                ).fetchone()
                connection.rollback()
                return SourceContentValidationRecord.model_validate_json(row["payload_json"])

            current = self._current_with(connection, project_id, source_entry_id)
            if current is None:
                connection.rollback()
                raise KeyError(f"source validation not found: {project_id}/{source_entry_id}")
            if current.revision != request.expected_revision:
                connection.rollback()
                raise SourceContentValidationConflict(
                    f"stale source validation revision: expected={request.expected_revision}, actual={current.revision}"
                )
            if current.technical_status != "ready" or current.use_status == "blocked_technical_failure":
                connection.rollback()
                raise ValueError("technical failure cannot be confirmed for downstream use")
            if current.content_status not in {"warning", "mismatch"} or current.use_status != "requires_confirmation":
                connection.rollback()
                raise ValueError("only a current warning or mismatch can be confirmed")
            reason = request.reason.strip()
            if len(reason) < 10:
                connection.rollback()
                raise ValueError("confirmation reason must contain at least 10 characters")
            unresolved = {
                check.check_code
                for check in current.checks
                if check.outcome in {"warning", "mismatch"}
            }
            if any(
                not check.overridable
                for check in current.checks
                if check.check_code in unresolved
            ):
                connection.rollback()
                raise ValueError("a non-overridable validation failure is present")
            acknowledged = set(request.acknowledged_check_codes)
            if acknowledged != unresolved:
                connection.rollback()
                raise ValueError("all current warning or mismatch checks must be acknowledged exactly")

            confirmed = current.model_copy(
                update={
                    "validation_id": _validation_id(
                        project_id,
                        source_entry_id,
                        current.revision + 1,
                        current.file_sha256,
                        current.expected_context_hash,
                    ),
                    "revision": current.revision + 1,
                    "use_status": "confirmed_after_warning",
                    "summary": (
                        f"内容一致性状态仍为{current.content_status}；医学经理已在逐项确认提示后决定沿用。"
                    ),
                    "actor": request.actor.strip() or "medical_manager",
                    "confirmation_reason": reason,
                    "acknowledged_check_codes": sorted(acknowledged),
                    "created_at": _utc_now(),
                }
            )
            self._insert_record(connection, "confirmation", confirmed)
            self._advance_state(connection, confirmed, current.revision)
            connection.execute(
                "INSERT INTO source_content_validation_idempotency VALUES (?, 'confirmation', ?, ?, ?, ?)",
                (
                    project_id,
                    request.idempotency_key,
                    request_hash,
                    confirmed.validation_id,
                    confirmed.created_at.isoformat(),
                ),
            )
            connection.commit()
            return confirmed

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS source_content_validation_records (
                    validation_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    source_entry_id TEXT NOT NULL,
                    module TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    operation TEXT NOT NULL,
                    file_sha256 TEXT NOT NULL,
                    expected_context_hash TEXT NOT NULL,
                    validator_version TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(project_id, source_entry_id, revision)
                );
                CREATE TABLE IF NOT EXISTS source_content_validation_state (
                    project_id TEXT NOT NULL,
                    source_entry_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    validation_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, source_entry_id),
                    FOREIGN KEY(validation_id) REFERENCES source_content_validation_records(validation_id)
                );
                CREATE TABLE IF NOT EXISTS source_content_validation_idempotency (
                    project_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    validation_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, operation, idempotency_key),
                    FOREIGN KEY(validation_id) REFERENCES source_content_validation_records(validation_id)
                );
                CREATE TRIGGER IF NOT EXISTS source_validation_records_no_update
                BEFORE UPDATE ON source_content_validation_records
                BEGIN SELECT RAISE(ABORT, 'source validation records are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS source_validation_records_no_delete
                BEFORE DELETE ON source_content_validation_records
                BEGIN SELECT RAISE(ABORT, 'source validation records are immutable'); END;
                """
            )

    @staticmethod
    def _current_with(
        connection: sqlite3.Connection,
        project_id: str,
        source_entry_id: str,
    ) -> SourceContentValidationRecord | None:
        row = connection.execute(
            """
            SELECT record.payload_json
            FROM source_content_validation_state AS state
            JOIN source_content_validation_records AS record
              ON record.validation_id=state.validation_id
            WHERE state.project_id=? AND state.source_entry_id=?
            """,
            (project_id, source_entry_id),
        ).fetchone()
        return (
            SourceContentValidationRecord.model_validate_json(row["payload_json"])
            if row is not None
            else None
        )

    @staticmethod
    def _insert_record(
        connection: sqlite3.Connection,
        operation: str,
        record: SourceContentValidationRecord,
    ) -> None:
        connection.execute(
            "INSERT INTO source_content_validation_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.validation_id,
                record.project_id,
                record.source_entry_id,
                record.module,
                record.revision,
                operation,
                record.file_sha256,
                record.expected_context_hash,
                record.validator_version,
                record.model_dump_json(),
                record.created_at.isoformat(),
            ),
        )

    @staticmethod
    def _advance_state(
        connection: sqlite3.Connection,
        record: SourceContentValidationRecord,
        expected_revision: int,
    ) -> None:
        if expected_revision == 0:
            connection.execute(
                "INSERT INTO source_content_validation_state VALUES (?, ?, ?, ?, ?)",
                (
                    record.project_id,
                    record.source_entry_id,
                    record.revision,
                    record.validation_id,
                    record.created_at.isoformat(),
                ),
            )
            return
        cursor = connection.execute(
            """
            UPDATE source_content_validation_state
            SET revision=?, validation_id=?, updated_at=?
            WHERE project_id=? AND source_entry_id=? AND revision=?
            """,
            (
                record.revision,
                record.validation_id,
                record.created_at.isoformat(),
                record.project_id,
                record.source_entry_id,
                expected_revision,
            ),
        )
        if cursor.rowcount != 1:
            raise SourceContentValidationConflict("source validation state changed concurrently")


class SourceContentValidationService:
    def __init__(self, store: SourceContentValidationStore):
        self.store = store

    def assess_listing(
        self,
        *,
        project_id: str,
        source_entry_id: str,
        module: str,
        filename: str,
        file_sha256: str,
        sheets: Sequence[ListingSheetPayload],
        expected: SourceExpectedContext,
        actor: str,
    ) -> SourceContentValidationRecord:
        try:
            current = self.store.current(project_id, source_entry_id)
            next_revision = current.revision + 1
        except KeyError:
            next_revision = 1

        rows = [row for sheet in sheets for row in sheet.rows]
        headers = {_normalized_header(key) for row in rows for key in row}
        if not sheets or not rows or not headers:
            record = self._record(
                project_id=project_id,
                source_entry_id=source_entry_id,
                module=module,
                revision=next_revision,
                file_sha256=file_sha256,
                expected=expected,
                technical_status="failed",
                checks=[
                    SourceContentValidationCheck(
                        check_code="technical_readability",
                        label="文件技术可读性",
                        observed_value="未解析到可用数据表或数据行",
                        outcome="mismatch",
                        overridable=False,
                    )
                ],
                actor=actor,
            )
            return self.store.save_assessment(record)

        role_check = self._listing_role_check(headers, expected.expected_file_role)
        safety_event_check = None
        safety_scope_check = None
        if expected.expected_file_role == "safety_medical_review_listing":
            safety_event_check = self._listing_safety_event_structure_check(sheets)
            safety_scope_check = self._listing_safety_review_scope_check(sheets)
            role_check = self._listing_safety_file_role_check(
                safety_event_check,
                safety_scope_check,
            )
        checks = [
            SourceContentValidationCheck(
                check_code="technical_readability",
                label="文件技术可读性",
                observed_value=f"{len(sheets)}个数据表，{len(rows)}行",
                outcome="match",
                overridable=False,
                evidence_locators=[f"listing:{Path(filename).name}"],
            ),
            role_check,
            self._listing_project_check(rows, expected.project_identifiers),
        ]
        if safety_event_check is not None and safety_scope_check is not None:
            checks.extend([safety_event_check, safety_scope_check])
        record = self._record(
            project_id=project_id,
            source_entry_id=source_entry_id,
            module=module,
            revision=next_revision,
            file_sha256=file_sha256,
            expected=expected,
            technical_status="ready",
            checks=checks,
            actor=actor,
        )
        return self.store.save_assessment(record)

    def assess_protocol(
        self,
        *,
        project_id: str,
        source_entry_id: str,
        module: str,
        filename: str,
        file_sha256: str,
        document: ProtocolTextDocument,
        expected: SourceExpectedContext,
        actor: str,
    ) -> SourceContentValidationRecord:
        try:
            current = self.store.current(project_id, source_entry_id)
            next_revision = current.revision + 1
        except KeyError:
            next_revision = 1
        text = "\n".join(span.text for span in document.spans if span.text.strip())
        if not text.strip():
            record = self._record(
                project_id=project_id,
                source_entry_id=source_entry_id,
                module=module,
                revision=next_revision,
                file_sha256=file_sha256,
                expected=expected,
                technical_status="failed",
                checks=[
                    SourceContentValidationCheck(
                        check_code="technical_readability",
                        label="文件技术可读性",
                        observed_value="DOCX未解析到正文",
                        outcome="mismatch",
                        overridable=False,
                    )
                ],
                actor=actor,
            )
            return self.store.save_assessment(record)

        full_text = f"{Path(filename).name}\n{document.title}\n{text}"
        checks = [
            SourceContentValidationCheck(
                check_code="technical_readability",
                label="文件技术可读性",
                observed_value=(
                    f"{len(document.paragraphs)}个段落，{len(document.tables)}张表，"
                    f"{len(document.spans)}个内容片段"
                ),
                outcome="match",
                overridable=False,
                evidence_locators=["docx:document"],
            ),
            self._protocol_role_check(full_text, expected.expected_file_role),
            self._text_project_check(full_text, expected.project_identifiers),
        ]
        if expected.indication_terms:
            checks.append(self._text_term_check(
                "indication",
                "适应症",
                full_text,
                expected.indication_terms,
            ))
        if expected.expected_protocol_version:
            checks.append(self._text_term_check(
                "protocol_version",
                "方案版本",
                full_text,
                (expected.expected_protocol_version,),
            ))
        record = self._record(
            project_id=project_id,
            source_entry_id=source_entry_id,
            module=module,
            revision=next_revision,
            file_sha256=file_sha256,
            expected=expected,
            technical_status="ready",
            checks=checks,
            actor=actor,
        )
        return self.store.save_assessment(record)

    def assess_inventory(
        self,
        *,
        project_id: str,
        source_entry_id: str,
        module: str,
        inventory: RawSubjectBundleInventory,
        file_sha256: str,
        expected: SourceExpectedContext,
        actor: str,
    ) -> SourceContentValidationRecord:
        try:
            current = self.store.current(project_id, source_entry_id)
            next_revision = current.revision + 1
        except KeyError:
            next_revision = 1
        usable_files = [file for file in inventory.files if file.size_bytes > 0]
        if not usable_files:
            record = self._record(
                project_id=project_id,
                source_entry_id=source_entry_id,
                module=module,
                revision=next_revision,
                file_sha256=file_sha256,
                expected=expected,
                technical_status="failed",
                checks=[
                    SourceContentValidationCheck(
                        check_code="technical_readability",
                        label="文件技术可读性",
                        observed_value="资料包为空或全部文件大小为0",
                        outcome="mismatch",
                        overridable=False,
                    )
                ],
                actor=actor,
            )
            return self.store.save_assessment(record)

        suffixes = sorted({file.suffix for file in usable_files})
        path_text = "\n".join(
            [Path(inventory.root_path).name]
            + [file.relative_path for file in usable_files]
        )
        checks = [
            SourceContentValidationCheck(
                check_code="technical_readability",
                label="文件技术可读性",
                observed_value=f"{len(usable_files)}个非空文件；类型 {' / '.join(suffixes) or '无扩展名'}",
                outcome="match",
                overridable=False,
                evidence_locators=["bundle:inventory"],
            ),
            self._inventory_role_check(suffixes, expected.expected_file_role),
            self._inventory_project_check(path_text, expected.project_identifiers),
        ]
        record = self._record(
            project_id=project_id,
            source_entry_id=source_entry_id,
            module=module,
            revision=next_revision,
            file_sha256=file_sha256,
            expected=expected,
            technical_status="ready",
            checks=checks,
            actor=actor,
        )
        return self.store.save_assessment(record)

    def confirm_after_warning(
        self,
        project_id: str,
        source_entry_id: str,
        request: SourceContentValidationConfirmationRequest,
    ) -> SourceContentValidationRecord:
        return self.store.confirm_after_warning(project_id, source_entry_id, request)

    @staticmethod
    def _listing_role_check(
        headers: set[str],
        expected_role: str,
    ) -> SourceContentValidationCheck:
        has_subject = bool(headers & SUBJECT_ID_FIELDS)
        has_clinical_data = bool(headers & CLINICAL_DATA_FIELDS)
        if expected_role in {"", "clinical_data_file"}:
            outcome = "match" if has_subject else "warning"
        elif expected_role == "edc_data_listing":
            outcome = "match" if has_subject and has_clinical_data else "mismatch"
        elif expected_role == "sdtm_or_adam_dataset":
            outcome = "match" if "STUDYID" in headers and "USUBJID" in headers else "mismatch"
        elif expected_role == "subject_report":
            outcome = "match" if has_subject else "mismatch"
        else:
            outcome = "not_assessed"
        return SourceContentValidationCheck(
            check_code="file_role",
            label="文件角色",
            expected_value=expected_role,
            observed_value=", ".join(sorted(headers)[:20]),
            outcome=outcome,
            evidence_locators=["listing:headers"],
        )

    @staticmethod
    def _listing_safety_event_structure_check(
        sheets: Sequence[ListingSheetPayload],
    ) -> SourceContentValidationCheck:
        partial_sheets: list[str] = []
        complete_sheets: list[str] = []
        for sheet in sheets:
            headers = _semantic_headers(sheet)
            has_subject = bool(headers & SUBJECT_ID_FIELDS)
            has_term = bool(headers & {"AETERM", "AEDECOD"})
            if not (has_subject and has_term):
                continue
            partial_sheets.append(sheet.sheet_name)
            has_timing = bool(headers & {"AESTDAT", "AESTDTC", "AESTDY", "AEENDAT", "AEENDTC", "AEENDY", "ASTDY"})
            has_review_detail = any(
                header in {"AESEV", "AESER"}
                or header.startswith(("AETOXGR", "AEREL", "AEACN", "AEOUT"))
                for header in headers
            )
            if has_timing and has_review_detail:
                complete_sheets.append(sheet.sheet_name)

        if complete_sheets:
            outcome = "match"
            observed = f"完整个体AE结构：{', '.join(complete_sheets[:4])}"
            locators = [f"listing:sheet:{name}" for name in complete_sheets[:4]]
        elif partial_sheets:
            outcome = "warning"
            observed = f"存在受试者与AE术语，但缺少时间或复核字段：{', '.join(partial_sheets[:4])}"
            locators = [f"listing:sheet:{name}" for name in partial_sheets[:4]]
        else:
            outcome = "mismatch"
            observed = "未发现同一数据表内同时包含受试者标识与AE术语字段"
            locators = ["listing:sheet_and_header_structure"]
        return SourceContentValidationCheck(
            check_code="safety_review_event_structure",
            label="个体AE复核结构",
            expected_value="同一数据表包含受试者、AE术语、时间及至少一类医学复核字段",
            observed_value=observed,
            outcome=outcome,
            evidence_locators=locators,
        )

    @staticmethod
    def _listing_safety_review_scope_check(
        sheets: Sequence[ListingSheetPayload],
    ) -> SourceContentValidationCheck:
        observed_groups: list[str] = []
        evidence_locators: list[str] = []
        for group in SAFETY_CONTEXT_GROUPS.values():
            matched_sheets: list[str] = []
            for sheet in sheets:
                headers = _semantic_headers(sheet)
                has_subject = bool(headers & SUBJECT_ID_FIELDS)
                has_payload = any(
                    header.startswith(tuple(group["header_prefixes"]))
                    and any(token in header for token in group["payload_tokens"])
                    for header in headers
                )
                if has_subject and has_payload:
                    matched_sheets.append(sheet.sheet_name)
            if matched_sheets:
                observed_groups.append(str(group["label"]))
                evidence_locators.extend(
                    f"listing:sheet:{sheet_name}" for sheet_name in matched_sheets[:3]
                )

        if len(observed_groups) >= 3:
            outcome = "match"
        elif observed_groups:
            outcome = "warning"
        else:
            outcome = "mismatch"
        return SourceContentValidationCheck(
            check_code="safety_review_data_scope",
            label="安全性医学复核数据结构",
            expected_value=(
                "AE核心字段，并覆盖至少3类复核上下文：病史、非试验用药（CM）、"
                "试验用药/剂量调整、实验室/生命体征/心电图"
            ),
            observed_value=(
                "已识别：" + "、".join(observed_groups)
                if observed_groups
                else "未识别到安全性复核上下文数据"
            ),
            outcome=outcome,
            evidence_locators=evidence_locators or ["listing:sheet_and_header_structure"],
        )

    @staticmethod
    def _listing_safety_file_role_check(
        event_check: SourceContentValidationCheck,
        scope_check: SourceContentValidationCheck,
    ) -> SourceContentValidationCheck:
        outcomes = {event_check.outcome, scope_check.outcome}
        if "mismatch" in outcomes:
            outcome = "mismatch"
        elif "warning" in outcomes:
            outcome = "warning"
        else:
            outcome = "match"
        return SourceContentValidationCheck(
            check_code="file_role",
            label="文件角色",
            expected_value="safety_medical_review_listing",
            observed_value=(
                f"个体AE复核结构：{source_check_outcome_label(event_check.outcome)}；"
                f"安全性上下文覆盖：{source_check_outcome_label(scope_check.outcome)}"
            ),
            outcome=outcome,
            evidence_locators=list(dict.fromkeys(
                event_check.evidence_locators + scope_check.evidence_locators
            )),
        )

    @staticmethod
    def _listing_project_check(
        rows: Sequence[dict[str, object]],
        expected_identifiers: Sequence[str],
    ) -> SourceContentValidationCheck:
        observed = sorted(
            {
                str(value).strip()
                for row in rows
                for key, value in row.items()
                if _normalized_header(key) in STUDY_ID_FIELDS and str(value).strip()
            }
        )
        expected_normalized = {_normalize_identifier(value) for value in expected_identifiers if value.strip()}
        observed_normalized = {_normalize_identifier(value) for value in observed}
        if not expected_normalized:
            outcome = "not_assessed"
        elif not observed_normalized:
            outcome = "warning"
        elif any(
            _identifiers_compatible(expected, observed)
            for expected in expected_normalized
            for observed in observed_normalized
        ):
            outcome = "match"
        else:
            outcome = "mismatch"
        return SourceContentValidationCheck(
            check_code="project_identity",
            label="项目/研究标识",
            expected_value=" / ".join(expected_identifiers),
            observed_value=" / ".join(observed) if observed else "未发现STUDYID或等效字段值",
            outcome=outcome,
            evidence_locators=["listing:study_identifier_fields"],
        )

    @staticmethod
    def _protocol_role_check(full_text: str, expected_role: str) -> SourceContentValidationCheck:
        lowered = full_text.lower()
        protocol_markers = sum(
            marker in lowered
            for marker in (
                "研究方案",
                "clinical study protocol",
                "入选标准",
                "排除标准",
                "inclusion criteria",
                "exclusion criteria",
                "研究设计",
            )
        )
        publication_markers = sum(
            marker in lowered
            for marker in ("abstract", "results", "discussion", "doi:", "参考文献")
        )
        if expected_role in {"protocol_docx", "protocol"}:
            if protocol_markers >= 2:
                outcome = "match"
            elif publication_markers >= 3:
                outcome = "mismatch"
            else:
                outcome = "warning"
        elif expected_role == "dsur_source_document":
            dsur_markers = sum(
                marker in lowered
                for marker in (
                    "development safety update report",
                    "研发期间安全性更新报告",
                    "dsur",
                    "安全性资料收集",
                )
            )
            outcome = "match" if dsur_markers else "warning"
        elif expected_role == "clinical_safety_summary_document":
            safety_summary_markers = sum(
                marker in lowered
                for marker in ("2.7.4", "临床安全性总结", "summary of clinical safety")
            )
            outcome = "match" if safety_summary_markers else "warning"
        else:
            outcome = "not_assessed"
        observed = (
            f"方案结构标志{protocol_markers}项；publication结构标志{publication_markers}项"
        )
        return SourceContentValidationCheck(
            check_code="file_role",
            label="文件角色",
            expected_value=expected_role,
            observed_value=observed,
            outcome=outcome,
            evidence_locators=["docx:document_structure"],
        )

    @staticmethod
    def _text_project_check(
        full_text: str,
        expected_identifiers: Sequence[str],
    ) -> SourceContentValidationCheck:
        expected_normalized = {
            _normalize_identifier(value) for value in expected_identifiers if value.strip()
        }
        normalized_text = _normalize_identifier(full_text)
        observed = sorted(
            candidate
            for candidate in set(
                re.findall(
                    r"\b[A-Z]{2,12}[-_][A-Z0-9]+(?:[-_][A-Z0-9]+){0,3}\b",
                    full_text.upper(),
                )
            )
            if any(character.isdigit() for character in candidate)
        )
        if not expected_normalized:
            outcome = "not_assessed"
        elif any(identifier in normalized_text for identifier in expected_normalized):
            outcome = "match"
        elif observed:
            outcome = "mismatch"
        else:
            outcome = "warning"
        return SourceContentValidationCheck(
            check_code="project_identity",
            label="项目/研究标识",
            expected_value=" / ".join(expected_identifiers),
            observed_value=" / ".join(observed) if observed else "未识别到明确研究标识",
            outcome=outcome,
            evidence_locators=["docx:document_text"],
        )

    @staticmethod
    def _text_term_check(
        check_code: str,
        label: str,
        full_text: str,
        expected_terms: Sequence[str],
    ) -> SourceContentValidationCheck:
        normalized_text = _normalize_search_text(full_text)
        matched = [
            term for term in expected_terms if _normalize_search_text(term) in normalized_text
        ]
        return SourceContentValidationCheck(
            check_code=check_code,
            label=label,
            expected_value=" / ".join(expected_terms),
            observed_value=" / ".join(matched) if matched else "未在文件名、标题或正文中识别到预期内容",
            outcome="match" if matched else "warning",
            evidence_locators=["docx:document_text"],
        )

    @staticmethod
    def _inventory_role_check(
        suffixes: Sequence[str],
        expected_role: str,
    ) -> SourceContentValidationCheck:
        suffix_set = {suffix.lower() for suffix in suffixes}
        role_suffixes = {
            "raw_subject_bundle_inventory": {".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx"},
            "tfl_dataset_package_inventory": {".xpt", ".sas7bdat", ".xml"},
            "tfl_output_package_inventory": {".rtf", ".pdf", ".xlsx", ".xls", ".docx"},
            "safety_signal_package_inventory": {".xlsx", ".xls", ".xlsm", ".csv", ".docx", ".pdf"},
            "pv_safety_package_inventory": {".doc", ".docx", ".pdf", ".xlsx", ".xls"},
            "clinical_safety_summary_inventory": {".doc", ".docx", ".pdf", ".rtf"},
            "file_bundle_inventory": set(),
        }
        expected_suffixes = role_suffixes.get(expected_role)
        if expected_suffixes is None or not expected_suffixes:
            outcome = "not_assessed"
        elif suffix_set & expected_suffixes:
            outcome = "match"
        else:
            outcome = "mismatch"
        return SourceContentValidationCheck(
            check_code="file_role",
            label="资料包角色",
            expected_value=expected_role,
            observed_value=" / ".join(suffixes) or "未识别到文件扩展名",
            outcome=outcome,
            evidence_locators=["bundle:file_types"],
        )

    @staticmethod
    def _inventory_project_check(
        path_text: str,
        expected_identifiers: Sequence[str],
    ) -> SourceContentValidationCheck:
        expected_normalized = {
            _normalize_identifier(value) for value in expected_identifiers if value.strip()
        }
        normalized_text = _normalize_identifier(path_text)
        if not expected_normalized:
            outcome = "not_assessed"
        else:
            outcome = "warning"
        return SourceContentValidationCheck(
            check_code="project_identity",
            label="项目/研究标识",
            expected_value=" / ".join(expected_identifiers),
            observed_value=(
                "目录/文件名存在预期项目线索，但尚未完成文件内容级核对"
                if expected_normalized
                and any(identifier in normalized_text for identifier in expected_normalized)
                else "资料包清单尚未完成文件内容级研究标识核对"
            ),
            outcome=outcome,
            evidence_locators=["bundle:path_and_filename_clues"],
        )

    @staticmethod
    def _record(
        *,
        project_id: str,
        source_entry_id: str,
        module: str,
        revision: int,
        file_sha256: str,
        expected: SourceExpectedContext,
        technical_status: str,
        checks: Sequence[SourceContentValidationCheck],
        actor: str,
    ) -> SourceContentValidationRecord:
        if technical_status == "failed":
            content_status = "not_assessed"
            use_status = "blocked_technical_failure"
            summary = "文件技术读取失败，未执行内容一致性核验。"
        else:
            outcomes = {check.outcome for check in checks}
            if "mismatch" in outcomes:
                content_status = "mismatch"
            elif "warning" in outcomes:
                content_status = "warning"
            elif outcomes <= {"match", "not_assessed"} and "match" in outcomes:
                content_status = "matched"
            else:
                content_status = "not_assessed"
            use_status = "allowed" if content_status == "matched" else "requires_confirmation"
            summary = {
                "matched": "文件基本信息与当前项目使用场景一致。",
                "warning": "部分内容无法自动确认，继续使用前需医学经理逐项确认。",
                "mismatch": "文件内容与当前项目或文件角色不一致，继续使用前需医学经理逐项确认并说明理由。",
                "not_assessed": "缺少足够信息完成内容一致性核验，继续使用前需医学经理确认。",
            }[content_status]
        return SourceContentValidationRecord(
            validation_id=_validation_id(
                project_id,
                source_entry_id,
                revision,
                file_sha256,
                expected.context_hash,
            ),
            project_id=project_id,
            source_entry_id=source_entry_id,
            module=module,
            revision=revision,
            technical_status=technical_status,
            content_status=content_status,
            use_status=use_status,
            file_sha256=file_sha256,
            expected_context_hash=expected.context_hash,
            validator_version=VALIDATOR_VERSION,
            checks=list(checks),
            summary=summary,
            actor=actor,
            created_at=_utc_now(),
        )


def _same_assessment(
    current: SourceContentValidationRecord,
    incoming: SourceContentValidationRecord,
) -> bool:
    return (
        current.file_sha256 == incoming.file_sha256
        and current.expected_context_hash == incoming.expected_context_hash
        and current.validator_version == incoming.validator_version
        and current.technical_status == incoming.technical_status
        and current.content_status == incoming.content_status
        and current.checks == incoming.checks
    )


def _validation_id(
    project_id: str,
    source_entry_id: str,
    revision: int,
    file_sha256: str,
    context_hash: str,
) -> str:
    digest = hashlib.sha256(
        f"{project_id}|{source_entry_id}|{revision}|{file_sha256}|{context_hash}|{VALIDATOR_VERSION}".encode(
            "utf-8"
        )
    ).hexdigest()[:24]
    return f"srcval_{digest}"


def _normalized_header(value: object) -> str:
    return str(value).strip().upper().replace(" ", "_")


def _semantic_headers(sheet: ListingSheetPayload) -> set[str]:
    return {
        re.sub(r"__\d+$", "", unicodedata.normalize("NFKC", _normalized_header(key)))
        for row in sheet.rows
        for key in row
    }


def _identifiers_compatible(expected: str, observed: str) -> bool:
    return expected == observed or expected.startswith(observed) or observed.startswith(expected)


def source_check_outcome_label(outcome: str) -> str:
    return {
        "match": "匹配",
        "warning": "需确认",
        "mismatch": "不一致",
        "not_assessed": "未评估",
    }.get(outcome, outcome)


def _normalize_identifier(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _normalize_search_text(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def _sha256_json(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
