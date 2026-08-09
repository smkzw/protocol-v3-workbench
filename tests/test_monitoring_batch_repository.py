from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from services.api.app.monitoring_batch_repository import (
    CompletenessGateError,
    ContentValidationError,
    DuplicateBusinessKeyError,
    FrozenBatchError,
    IdempotencyConflictError,
    InvalidStateTransitionError,
    MonitoringBatchRepository,
    OptimisticVersionConflictError,
    RepositoryIntegrityError,
    TechnicalValidationError,
)


PROJECT_ID = "proj_rux_03_002"


def _row(
    business_key: str,
    domain: str,
    value: object,
    *,
    row_number: int,
) -> dict:
    return {
        "business_key": business_key,
        "domain": domain,
        "data": {
            "USUBJID": "RUX-001",
            "VISIT": "W4",
            "TEST": business_key,
            "VALUE": value,
        },
        "source_locator": {
            "sheet": domain,
            "row": row_number,
        },
    }


class MonitoringBatchRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = MonitoringBatchRepository(
            self.root / "monitoring.sqlite3",
            self.root / "object-store",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _file(self, name: str, payload: bytes) -> Path:
        path = self.root / name
        path.write_bytes(payload)
        return path

    def _register(
        self,
        *,
        name: str = "RUX-03-002_listing.xlsx",
        payload: bytes = b"PK\x03\x04clinical-listing",
        technical_status: str = "passed",
        content_warnings=(),
        override_reason=None,
        source_class: str = "raw_full_snapshot_candidate",
        validation_use_status: str = "allowed",
        classification_version: str = "monitoring_source_classifier.v2",
    ):
        return self.repository.register_source(
            project_id=PROJECT_ID,
            source_entry_id=f"source-entry-{name}",
            validation_id=f"validation-{name}",
            validation_revision=1,
            validator_version="source-content-v2",
            validation_use_status=validation_use_status,
            role="primary_listing",
            source_class=source_class,
            file_path=self._file(name, payload),
            parser_version="listing-parser/1.0.0",
            classification_version=classification_version,
            technical_status=technical_status,
            content_warnings=content_warnings,
            medical_override_reason=override_reason,
        )

    def _draft_with_rows(
        self,
        *,
        source=None,
        rows=None,
        expected_domains=("AE", "LB"),
        key_prefix="batch",
    ):
        source = source or self._register()
        rows = rows or (
            _row("AE:RUX-001:1", "AE", "Headache", row_number=4),
            _row("LB:RUX-001:ALT:W4", "LB", 82, row_number=9),
        )
        created = self.repository.create_batch(
            project_id=PROJECT_ID,
            idempotency_key=f"{key_prefix}:create",
            expected_domains=expected_domains,
        )
        attached = self.repository.attach_source(
            batch_id=created.batch.batch_id,
            source_id=source.source_id,
            expected_version=created.batch.version,
            idempotency_key=f"{key_prefix}:attach",
        )
        materialized = self.repository.replace_rows(
            batch_id=created.batch.batch_id,
            rows=rows,
            expected_version=attached.batch.version,
            idempotency_key=f"{key_prefix}:rows",
        )
        return source, materialized

    def _parsed_with_validation(
        self,
        *,
        source=None,
        rows=None,
        expected_domains=("AE", "LB"),
        proof=None,
        key_prefix="batch",
    ):
        source, draft = self._draft_with_rows(
            source=source,
            rows=rows,
            expected_domains=expected_domains,
            key_prefix=key_prefix,
        )
        parsed = self.repository.transition_batch(
            batch_id=draft.batch.batch_id,
            target_state="parsed",
            expected_version=draft.batch.version,
            idempotency_key=f"{key_prefix}:parsed",
        )
        evidence = self.repository.record_validation_evidence(
            batch_id=parsed.batch.batch_id,
            mapping_revision="mapping-v1",
            mapping={
                "AE": {"business_key": ["USUBJID", "AESEQ"]},
                "LB": {"business_key": ["USUBJID", "LBTESTCD", "VISIT"]},
            },
            expected_domains=expected_domains,
            full_snapshot_proof=proof
            or {
                "confirmed": True,
                "basis": "EDC full export with all expected sheets",
                "confirmed_by": "medical_manager",
            },
            expected_version=parsed.batch.version,
            idempotency_key=f"{key_prefix}:validation-evidence",
        )
        return source, evidence

    def _parsed_format_defect_batch(self, *, key_prefix="derived-proof"):
        source = self._register(
            name=f"{key_prefix}.xlsx",
            payload=b"PK\x03\x04original-workbook-with-dimension-defect",
            source_class="raw_snapshot_with_format_defect",
            content_warnings=("worksheet dimension metadata recovered",),
            override_reason="确认原始父文件仅存在 worksheet dimension 元数据缺陷。",
        )
        source, draft = self._draft_with_rows(
            source=source,
            rows=(
                _row("AE:RUX-001:1", "AE", "Headache", row_number=4),
                _row("LB:RUX-001:ALT:W4", "LB", 82, row_number=9),
            ),
            expected_domains=("AE", "LB"),
            key_prefix=key_prefix,
        )
        parsed = self.repository.transition_batch(
            batch_id=draft.batch.batch_id,
            target_state="parsed",
            expected_version=draft.batch.version,
            idempotency_key=f"{key_prefix}:parsed",
        )
        return source, parsed

    @staticmethod
    def _derived_snapshot_proof_kwargs(source, parsed, *, key="verify-derived"):
        sheets = (
            {"sheet_name": "AE", "parsed_row_count": 1},
            {"sheet_name": "LB", "parsed_row_count": 1},
        )
        return {
            "batch_id": parsed.batch.batch_id,
            "source_id": source.source_id,
            "source_content_sha256": source.content_sha256,
            "original_source_class": "raw_snapshot_with_format_defect",
            "parser_version": source.parser_version,
            "transformation_type": "parser_dimension_recovery",
            "execution_tool": "listing_file_parser",
            "execution_tool_version": source.parser_version,
            "original_parse_sheets": sheets,
            "observed_original_parse_sheets": sheets,
            "observed_original_source_class": "raw_snapshot_with_format_defect",
            "normalized_row_count": 2,
            "expected_domains": ("AE", "LB"),
            "verified_by": "medical_manager",
            "reason": "原始 Excel 仅 worksheet dimension 元数据错误，恢复解析后行数与域守恒。",
            "expected_version": parsed.batch.version,
            "idempotency_key": key,
        }

    def _freeze_batch(
        self,
        *,
        source=None,
        key_prefix="batch",
        rows=None,
        expected_domains=("AE", "LB"),
    ):
        source, evidence = self._parsed_with_validation(
            source=source,
            key_prefix=key_prefix,
            rows=rows,
            expected_domains=expected_domains,
        )
        validated = self.repository.transition_batch(
            batch_id=evidence.batch.batch_id,
            target_state="validated",
            expected_version=evidence.batch.version,
            idempotency_key=f"{key_prefix}:validated",
        )
        confirmed = self.repository.transition_batch(
            batch_id=validated.batch.batch_id,
            target_state="confirmed",
            expected_version=validated.batch.version,
            idempotency_key=f"{key_prefix}:confirmed",
        )
        frozen = self.repository.transition_batch(
            batch_id=confirmed.batch.batch_id,
            target_state="frozen",
            expected_version=confirmed.batch.version,
            idempotency_key=f"{key_prefix}:frozen",
        )
        return source, frozen

    def test_verify_derived_snapshot_persists_immutable_proof_and_advances_source_and_batch(self):
        source, parsed = self._parsed_format_defect_batch(key_prefix="derived-success")
        original_object = self.repository.read_source_bytes(source.source_id)

        result = self.repository.verify_derived_snapshot(
            **self._derived_snapshot_proof_kwargs(source, parsed)
        )

        self.assertFalse(result.replayed)
        self.assertEqual(parsed.batch.version + 1, result.batch.version)
        self.assertEqual(
            "verified_derived_full_snapshot",
            result.source_summary["verified_source_class"],
        )
        self.assertEqual(
            "raw_snapshot_with_format_defect",
            result.proof["original_source_class"],
        )
        self.assertEqual(64, len(result.proof["proof_sha256"]))
        self.assertNotIn("path", str(result.to_dict()).lower())
        self.assertEqual(
            "已核实为可审计派生全量来源",
            result.medical_summary["status"],
        )
        self.assertEqual(original_object, self.repository.read_source_bytes(source.source_id))
        self.assertEqual(
            source.content_sha256,
            self.repository.get_source(source.source_id).content_sha256,
        )
        self.assertEqual(
            "raw_snapshot_with_format_defect",
            self.repository.get_source(source.source_id).source_class,
        )
        verified_source = self.repository.get_source(
            result.source_summary["source_id"]
        )
        self.assertEqual(
            "verified_derived_full_snapshot",
            verified_source.source_class,
        )
        self.assertEqual(source.source_id, verified_source.supersedes_source_id)
        self.assertEqual(2, verified_source.binding_revision)
        with sqlite3.connect(self.repository.db_path) as connection:
            self.assertEqual(
                result.source_summary["source_id"],
                connection.execute(
                    """
                    SELECT source_id FROM monitoring_batch_sources
                    WHERE batch_id = ?
                    """,
                    (parsed.batch.batch_id,),
                ).fetchone()[0],
            )
            proof_row = connection.execute(
                """
                SELECT original_source_class, verified_source_class, proof_sha256
                FROM monitoring_derived_snapshot_proofs
                WHERE batch_id = ?
                """,
                (parsed.batch.batch_id,),
            ).fetchone()
            self.assertEqual(
                (
                    "raw_snapshot_with_format_defect",
                    "verified_derived_full_snapshot",
                    result.proof["proof_sha256"],
                ),
                proof_row,
            )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    UPDATE monitoring_derived_snapshot_proofs
                    SET reason = 'changed'
                    WHERE batch_id = ?
                    """,
                    (parsed.batch.batch_id,),
                )

    def test_verify_derived_snapshot_rejects_hash_count_domain_and_parse_mismatches(self):
        cases = (
            ("source_content_sha256", "0" * 64, "hash"),
            ("normalized_row_count", 3, "row count"),
            ("expected_domains", ("AE",), "domains"),
            (
                "original_parse_sheets",
                ({"sheet_name": "AE", "parsed_row_count": 2},),
                "parse",
            ),
        )
        for index, (field, value, expected_message) in enumerate(cases):
            with self.subTest(field=field):
                source, parsed = self._parsed_format_defect_batch(
                    key_prefix=f"derived-mismatch-{index}"
                )
                payload = self._derived_snapshot_proof_kwargs(
                    source,
                    parsed,
                    key=f"verify-derived-mismatch-{index}",
                )
                payload[field] = value
                with self.assertRaises(Exception) as raised:
                    self.repository.verify_derived_snapshot(**payload)
                self.assertIn(expected_message, str(raised.exception).lower())
                self.assertEqual(
                    "raw_snapshot_with_format_defect",
                    self.repository.get_source(source.source_id).source_class,
                )
                self.assertEqual(
                    parsed.batch.version,
                    self.repository.get_batch(parsed.batch.batch_id).version,
                )

    def test_verify_derived_snapshot_rejects_noncanonical_source_content_hash(self):
        cases = (
            ("padded", lambda digest: f" {digest}"),
            ("uppercase", lambda digest: digest.upper()),
            ("nonhex", lambda digest: "g" * 64),
            ("short", lambda digest: digest[:-1]),
            ("nonstring", lambda digest: [digest]),
        )
        for index, (label, transform) in enumerate(cases):
            with self.subTest(label=label):
                source, parsed = self._parsed_format_defect_batch(
                    key_prefix=f"derived-noncanonical-{index}"
                )
                payload = self._derived_snapshot_proof_kwargs(
                    source,
                    parsed,
                    key=f"verify-derived-noncanonical-{index}",
                )
                payload["source_content_sha256"] = transform(
                    source.content_sha256
                )
                with self.assertRaisesRegex(
                    RepositoryIntegrityError,
                    "hash",
                ):
                    self.repository.verify_derived_snapshot(**payload)
                self.assertEqual(
                    "raw_snapshot_with_format_defect",
                    self.repository.get_source(source.source_id).source_class,
                )
                self.assertEqual(
                    parsed.batch.version,
                    self.repository.get_batch(parsed.batch.batch_id).version,
                )

    def test_verify_derived_snapshot_rejects_illegal_source_classes(self):
        for index, source_class in enumerate(
            (
                "comparison_workbook",
                "mixed_monitoring_workbook",
                "unknown_blocked",
                "processed_full_snapshot",
                "restored_transitional",
            )
        ):
            with self.subTest(source_class=source_class):
                source = self._register(
                    name=f"illegal-{index}.xlsx",
                    source_class=source_class,
                    override_reason="仅用于验证非法来源类别不会被升级。",
                )
                _, draft = self._draft_with_rows(
                    source=source,
                    expected_domains=("AE", "LB"),
                    key_prefix=f"illegal-{index}",
                )
                parsed = self.repository.transition_batch(
                    batch_id=draft.batch.batch_id,
                    target_state="parsed",
                    expected_version=draft.batch.version,
                    idempotency_key=f"illegal-{index}:parsed",
                )
                payload = self._derived_snapshot_proof_kwargs(
                    source,
                    parsed,
                    key=f"illegal-{index}:verify",
                )
                payload["original_source_class"] = source_class
                payload["observed_original_source_class"] = source_class
                with self.assertRaises(Exception) as raised:
                    self.repository.verify_derived_snapshot(**payload)
                self.assertIn("source class", str(raised.exception).lower())

    def test_verify_derived_snapshot_requires_parsed_single_source_and_current_version(self):
        source, draft = self._draft_with_rows(
            source=self._register(
                source_class="raw_snapshot_with_format_defect",
                content_warnings=("dimension defect",),
                override_reason="确认仅存在格式元数据缺陷。",
            ),
            key_prefix="derived-state",
        )
        payload = self._derived_snapshot_proof_kwargs(source, draft, key="state:verify")
        with self.assertRaises(InvalidStateTransitionError):
            self.repository.verify_derived_snapshot(**payload)

        parsed = self.repository.transition_batch(
            batch_id=draft.batch.batch_id,
            target_state="parsed",
            expected_version=draft.batch.version,
            idempotency_key="derived-state:parsed",
        )
        second_source = self._register(
            name="second-source.xlsx",
            payload=b"PK\x03\x04second",
            source_class="raw_snapshot_with_format_defect",
            content_warnings=("dimension defect",),
            override_reason="确认仅存在格式元数据缺陷。",
        )
        with self.repository._transaction() as connection:
            connection.execute(
                """
                INSERT INTO monitoring_batch_sources(batch_id, source_id, attached_at)
                VALUES (?, ?, ?)
                """,
                (parsed.batch.batch_id, second_source.source_id, "2026-07-29T00:00:00Z"),
            )
        payload = self._derived_snapshot_proof_kwargs(
            source, parsed, key="multi-source:verify"
        )
        with self.assertRaises(Exception) as raised:
            self.repository.verify_derived_snapshot(**payload)
        self.assertIn("single source", str(raised.exception).lower())

        source2, parsed2 = self._parsed_format_defect_batch(key_prefix="derived-cas")
        stale = self._derived_snapshot_proof_kwargs(source2, parsed2, key="cas:verify")
        stale["expected_version"] -= 1
        with self.assertRaises(OptimisticVersionConflictError):
            self.repository.verify_derived_snapshot(**stale)

    def test_verify_derived_snapshot_replays_identical_request_and_conflicts_on_change(self):
        source, parsed = self._parsed_format_defect_batch(key_prefix="derived-idem")
        payload = self._derived_snapshot_proof_kwargs(
            source, parsed, key="derived-idem:verify"
        )
        first = self.repository.verify_derived_snapshot(**payload)
        second = self.repository.verify_derived_snapshot(**payload)
        self.assertFalse(first.replayed)
        self.assertTrue(second.replayed)
        self.assertEqual(first.proof["proof_sha256"], second.proof["proof_sha256"])
        self.assertEqual(first.batch.version, second.batch.version)

        changed = dict(payload)
        changed["reason"] = "同一幂等键改用不同证明理由，必须产生冲突而不是覆盖原证明。"
        with self.assertRaises(IdempotencyConflictError):
            self.repository.verify_derived_snapshot(**changed)

    def test_verified_derived_source_still_requires_existing_mapping_and_full_snapshot_gates(self):
        source, parsed = self._parsed_format_defect_batch(key_prefix="derived-gates")
        verified = self.repository.verify_derived_snapshot(
            **self._derived_snapshot_proof_kwargs(
                source,
                parsed,
                key="derived-gates:verify",
            )
        )
        with self.assertRaises(CompletenessGateError):
            self.repository.transition_batch(
                batch_id=verified.batch.batch_id,
                target_state="validated",
                expected_version=verified.batch.version,
                idempotency_key="derived-gates:validated-too-early",
            )

        evidence = self.repository.record_validation_evidence(
            batch_id=verified.batch.batch_id,
            mapping_revision="mapping-v1",
            mapping={
                "AE": {"business_key": ["USUBJID", "AESEQ"]},
                "LB": {"business_key": ["USUBJID", "LBTESTCD", "VISIT"]},
            },
            expected_domains=("AE", "LB"),
            full_snapshot_proof={
                "confirmed": True,
                "basis": "医学经理核对本次为可审计派生全量快照。",
                "confirmed_by": "medical_manager",
            },
            expected_version=verified.batch.version,
            idempotency_key="derived-gates:evidence",
        )
        validated = self.repository.transition_batch(
            batch_id=evidence.batch.batch_id,
            target_state="validated",
            expected_version=evidence.batch.version,
            idempotency_key="derived-gates:validated",
        )
        confirmed = self.repository.transition_batch(
            batch_id=validated.batch.batch_id,
            target_state="confirmed",
            expected_version=validated.batch.version,
            idempotency_key="derived-gates:confirmed",
        )
        frozen = self.repository.transition_batch(
            batch_id=confirmed.batch.batch_id,
            target_state="frozen",
            expected_version=confirmed.batch.version,
            idempotency_key="derived-gates:frozen",
        )
        self.assertEqual("frozen", frozen.batch.state)

    def test_content_addressed_copy_is_byte_identical_read_only_and_deduplicated(self):
        payload = b"\x00\x01RUX listing bytes\xff"
        original_a = self._file("listing_a.xlsx", payload)
        original_b = self._file("listing_b.xlsx", payload)
        original_digest = sha256(payload).hexdigest()

        first = self.repository.register_source(
            project_id=PROJECT_ID,
            source_entry_id="entry-listing-a",
            validation_id="validation-listing-a",
            validation_revision=1,
            validator_version="source-content-v2",
            validation_use_status="allowed",
            role="primary_listing",
            source_class="raw_full_snapshot_candidate",
            file_path=original_a,
            parser_version="parser-v1",
        )
        second = self.repository.register_source(
            project_id=PROJECT_ID,
            source_entry_id="entry-listing-b",
            validation_id="validation-listing-b",
            validation_revision=1,
            validator_version="source-content-v2",
            validation_use_status="allowed",
            role="primary_listing",
            source_class="raw_full_snapshot_candidate",
            file_path=original_b,
            parser_version="parser-v1",
        )

        self.assertNotEqual(first.source_id, second.source_id)
        self.assertEqual(original_digest, first.content_sha256)
        self.assertEqual(first.content_sha256, second.content_sha256)
        self.assertEqual(first.blob_relative_path, second.blob_relative_path)
        object_path = self.repository.object_path(first.source_id)
        self.assertEqual(payload, object_path.read_bytes())
        self.assertEqual(payload, original_a.read_bytes())
        self.assertEqual(0, object_path.stat().st_mode & 0o222)
        with sqlite3.connect(self.repository.db_path) as connection:
            self.assertEqual(
                1,
                connection.execute(
                    "SELECT COUNT(*) FROM monitoring_content_objects"
                ).fetchone()[0],
            )
            self.assertEqual(
                2,
                connection.execute(
                    "SELECT COUNT(*) FROM monitoring_sources"
                ).fetchone()[0],
            )

    def test_source_registration_preserves_validation_metadata(self):
        source = self._register(
            content_warnings=("indication differs from project metadata",),
            override_reason="医学经理确认该文件为同项目扩展队列。",
        )

        loaded = self.repository.get_source(source.source_id)

        self.assertEqual("primary_listing", loaded.role)
        self.assertEqual("raw_full_snapshot_candidate", loaded.source_class)
        self.assertTrue(loaded.source_entry_id)
        self.assertTrue(loaded.validation_id)
        self.assertEqual(1, loaded.validation_revision)
        self.assertEqual("source-content-v2", loaded.validator_version)
        self.assertEqual("allowed", loaded.validation_use_status)
        self.assertEqual(1, loaded.binding_revision)
        self.assertEqual(
            "monitoring_source_classifier.v2",
            loaded.classification_version,
        )
        self.assertEqual(64, len(loaded.binding_sha256))
        self.assertIsNone(loaded.supersedes_source_id)
        self.assertEqual("listing-parser/1.0.0", loaded.parser_version)
        self.assertEqual("passed", loaded.technical_status)
        self.assertEqual(
            ("indication differs from project metadata",),
            loaded.content_warnings,
        )
        self.assertIn("医学经理确认", loaded.medical_override_reason)

    def test_persisted_source_binding_metadata_tamper_fails_closed_on_read(self):
        source = self._register(name="source-binding-integrity.xlsx")

        with sqlite3.connect(self.repository.db_path) as connection:
            connection.execute("DROP TRIGGER trg_monitoring_sources_no_update")
            connection.execute(
                "UPDATE monitoring_sources SET role = ? WHERE source_id = ?",
                ("secondary_listing", source.source_id),
            )

        with self.assertRaisesRegex(
            RepositoryIntegrityError,
            "source binding metadata hash mismatch",
        ):
            self.repository.get_source(source.source_id)

    def test_persisted_source_binding_hash_must_remain_lowercase(self):
        source = self._register(name="source-binding-canonical.xlsx")

        with sqlite3.connect(self.repository.db_path) as connection:
            connection.execute("DROP TRIGGER trg_monitoring_sources_no_update")
            connection.execute(
                "UPDATE monitoring_sources SET binding_sha256 = ? "
                "WHERE source_id = ?",
                (source.binding_sha256.upper(), source.source_id),
            )

        with self.assertRaisesRegex(
            RepositoryIntegrityError,
            "persisted source binding_sha256 is not canonical",
        ):
            self.repository.get_source(source.source_id)

    def test_register_source_rejects_noncanonical_prior_lineage_hashes(self):
        for index, field in enumerate(("binding_sha256", "content_sha256"), start=1):
            with self.subTest(field=field):
                name = f"source-lineage-hash-{index}.xlsx"
                source = self._register(name=name)
                malformed = "A" * 64
                with sqlite3.connect(self.repository.db_path) as connection:
                    connection.execute("PRAGMA foreign_keys = OFF")
                    connection.execute(
                        "DROP TRIGGER IF EXISTS trg_monitoring_sources_no_update"
                    )
                    if field == "binding_sha256":
                        connection.execute(
                            "UPDATE monitoring_sources SET binding_sha256 = ? "
                            "WHERE source_id = ?",
                            (malformed, source.source_id),
                        )
                    else:
                        connection.execute(
                            "INSERT INTO monitoring_content_objects("
                            "content_sha256, size_bytes, blob_relative_path, created_at"
                            ") VALUES (?, ?, ?, ?)",
                            (
                                malformed,
                                source.size_bytes,
                                f"tampered/{index}",
                                "2026-08-05T00:00:00+00:00",
                            ),
                        )
                        connection.execute(
                            "UPDATE monitoring_sources SET content_sha256 = ? "
                            "WHERE source_id = ?",
                            (malformed, source.source_id),
                        )

                with self.assertRaisesRegex(
                    RepositoryIntegrityError,
                    "persisted source (binding|content) hash must be a canonical SHA-256 value",
                ):
                    self._register(name=name)

    def test_legacy_source_table_is_migrated_without_recreating_database(self):
        legacy_root = self.root / "legacy"
        legacy_root.mkdir()
        db_path = legacy_root / "monitoring.sqlite3"
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                """
                CREATE TABLE monitoring_sources (
                    source_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    source_class TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    parser_version TEXT NOT NULL,
                    technical_status TEXT NOT NULL,
                    content_warnings_json TEXT NOT NULL,
                    medical_override_reason TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )

        migrated = MonitoringBatchRepository(
            db_path,
            legacy_root / "objects",
        )
        with sqlite3.connect(db_path) as connection:
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(monitoring_sources)"
                ).fetchall()
            }
        self.assertTrue(
            {
                "source_entry_id",
                "validation_id",
                "validation_revision",
                "validator_version",
                "validation_use_status",
            }.issubset(columns)
        )

        source_path = legacy_root / "listing.csv"
        source_path.write_bytes(b"STUDYID,SUBJID\nRUX-03-002,S001\n")
        registered = migrated.register_source(
            project_id=PROJECT_ID,
            source_entry_id="legacy-migration-entry",
            validation_id="legacy-migration-validation",
            validation_revision=1,
            validator_version="source-content-v2",
            validation_use_status="allowed",
            role="primary_listing",
            source_class="raw_full_snapshot_candidate",
            file_path=source_path,
            parser_version="listing-parser/1.0.0",
        )
        self.assertEqual("legacy-migration-entry", registered.source_entry_id)

    def test_legacy_source_migration_rejects_noncanonical_content_hashes(self):
        for index, malformed in enumerate(
            ("A" * 64, " " + "a" * 64, "g" * 64, "a" * 63, 123),
            start=1,
        ):
            with self.subTest(malformed=repr(malformed)):
                legacy_root = self.root / f"legacy-invalid-{index}"
                legacy_root.mkdir()
                db_path = legacy_root / "monitoring.sqlite3"
                with sqlite3.connect(db_path) as connection:
                    connection.execute(
                        """
                        CREATE TABLE monitoring_content_objects (
                            content_sha256 TEXT PRIMARY KEY,
                            size_bytes INTEGER NOT NULL,
                            blob_relative_path TEXT NOT NULL UNIQUE,
                            created_at TEXT NOT NULL
                        )
                        """
                    )
                    connection.execute(
                        """
                        CREATE TABLE monitoring_sources (
                            source_id TEXT PRIMARY KEY,
                            project_id TEXT NOT NULL,
                            role TEXT NOT NULL,
                            source_class TEXT NOT NULL,
                            file_name TEXT NOT NULL,
                            content_sha256 TEXT NOT NULL,
                            size_bytes INTEGER NOT NULL,
                            parser_version TEXT NOT NULL,
                            technical_status TEXT NOT NULL,
                            content_warnings_json TEXT NOT NULL,
                            medical_override_reason TEXT,
                            created_at TEXT NOT NULL
                        )
                        """
                    )
                    connection.execute(
                        "INSERT INTO monitoring_content_objects VALUES (?, ?, ?, ?)",
                        (malformed, 1, f"objects/{index}", "2026-08-05T00:00:00+00:00"),
                    )
                    connection.execute(
                        "INSERT INTO monitoring_sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            f"legacy-invalid-source-{index}",
                            PROJECT_ID,
                            "primary_listing",
                            "raw_full_snapshot_candidate",
                            f"legacy-{index}.csv",
                            malformed,
                            1,
                            "listing-parser/1.0.0",
                            "passed",
                            "[]",
                            None,
                            "2026-08-05T00:00:00+00:00",
                        ),
                    )

                with self.assertRaisesRegex(
                    RepositoryIntegrityError,
                    "legacy source content hash must be a canonical SHA-256 value",
                ):
                    MonitoringBatchRepository(db_path, legacy_root / "objects")

    def test_intermediate_unique_binding_hash_schema_is_migrated_to_revision_history(self):
        source = self._register(name="intermediate-schema.xlsx")
        with sqlite3.connect(self.repository.db_path) as connection:
            connection.execute(
                "DROP INDEX idx_monitoring_source_binding_sha256"
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX idx_monitoring_source_binding_sha256
                ON monitoring_sources(binding_sha256)
                """
            )

        migrated = MonitoringBatchRepository(
            self.repository.db_path,
            self.repository.object_root,
        )

        self.assertEqual(source.source_id, migrated.get_source(source.source_id).source_id)
        with sqlite3.connect(self.repository.db_path) as connection:
            index_row = next(
                row
                for row in connection.execute(
                    "PRAGMA index_list(monitoring_sources)"
                )
                if row[1] == "idx_monitoring_source_binding_sha256"
            )
            self.assertEqual(0, index_row[2])
            self.assertEqual([], list(connection.execute("PRAGMA foreign_key_check")))

    def test_same_source_validation_binding_is_idempotent(self):
        first = self._register(name="same-binding.xlsx")
        second = self._register(name="same-binding.xlsx")

        self.assertEqual(first.source_id, second.source_id)
        self.assertEqual(first.binding_sha256, second.binding_sha256)
        self.assertEqual(1, second.binding_revision)

    def test_changed_medical_reason_creates_immutable_source_revision(self):
        first = self._register(
            name="reason-revision.xlsx",
            override_reason="医学经理确认该文件为处理后历史全量快照。",
            source_class="processed_full_snapshot",
        )
        second = self._register(
            name="reason-revision.xlsx",
            override_reason="医学经理复核报告后补充确认截止日期及覆盖中心。",
            source_class="processed_full_snapshot",
        )

        self.assertNotEqual(first.source_id, second.source_id)
        self.assertEqual(first.content_sha256, second.content_sha256)
        self.assertEqual(first.validation_id, second.validation_id)
        self.assertEqual(1, first.binding_revision)
        self.assertEqual(2, second.binding_revision)
        self.assertEqual(first.source_id, second.supersedes_source_id)
        self.assertEqual(
            "医学经理确认该文件为处理后历史全量快照。",
            self.repository.get_source(first.source_id).medical_override_reason,
        )
        with sqlite3.connect(self.repository.db_path) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    UPDATE monitoring_sources
                    SET medical_override_reason = 'forbidden'
                    WHERE source_id = ?
                    """,
                    (first.source_id,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM monitoring_sources WHERE source_id = ?",
                    (first.source_id,),
                )

    def test_changed_classifier_version_creates_revision_and_exact_replay_is_stable(self):
        first = self._register(
            name="classifier-revision.xlsx",
            classification_version="monitoring_source_classifier.v1",
        )
        second = self._register(
            name="classifier-revision.xlsx",
            classification_version="monitoring_source_classifier.v2",
        )
        replay = self._register(
            name="classifier-revision.xlsx",
            classification_version="monitoring_source_classifier.v2",
        )

        self.assertEqual(2, second.binding_revision)
        self.assertEqual(first.source_id, second.supersedes_source_id)
        self.assertEqual(second.source_id, replay.source_id)

    def test_reverting_to_older_metadata_creates_explicit_new_revision(self):
        first = self._register(
            name="reason-revert.xlsx",
            override_reason="医学说明 A：初次确认。",
        )
        second = self._register(
            name="reason-revert.xlsx",
            override_reason="医学说明 B：补充项目报告信息。",
        )
        reverted = self._register(
            name="reason-revert.xlsx",
            override_reason="医学说明 A：初次确认。",
        )

        self.assertEqual(3, reverted.binding_revision)
        self.assertEqual(second.source_id, reverted.supersedes_source_id)
        self.assertEqual(first.binding_sha256, reverted.binding_sha256)
        self.assertNotEqual(first.source_id, reverted.source_id)

    def test_source_revision_rejects_changed_bytes_for_same_registry_binding(self):
        self._register(name="same-registry-binding.xlsx", payload=b"first")

        with self.assertRaisesRegex(
            RepositoryIntegrityError, "cannot replace content bytes"
        ):
            self._register(
                name="same-registry-binding.xlsx",
                payload=b"second",
                override_reason="医学经理补充说明，但字节已经变化。",
            )

    def test_processed_snapshot_revision_cannot_be_promoted_to_raw_source_class(self):
        first = self._register(
            name="processed-history.xlsx",
            source_class="processed_full_snapshot",
            override_reason="医学经理确认该文件为 B 级处理后历史全量快照。",
        )
        revised = self._register(
            name="processed-history.xlsx",
            source_class="processed_full_snapshot",
            override_reason="医学经理补充确认报告日期；来源等级仍为 B。",
        )
        self.assertEqual("processed_full_snapshot", revised.source_class)
        self.assertEqual(first.source_id, revised.supersedes_source_id)

        with self.assertRaisesRegex(
            RepositoryIntegrityError, "cannot be promoted"
        ):
            self._register(
                name="processed-history.xlsx",
                source_class="raw_full_snapshot",
                override_reason="不得将处理后来源改称原始来源。",
            )

    def test_same_idempotent_request_replays_and_changed_request_conflicts(self):
        first = self.repository.create_batch(
            project_id=PROJECT_ID,
            idempotency_key="create-same",
            expected_domains=("AE", "LB"),
        )
        replay = self.repository.create_batch(
            project_id=PROJECT_ID,
            idempotency_key="create-same",
            expected_domains=("LB", "AE"),
        )

        self.assertFalse(first.replayed)
        self.assertTrue(replay.replayed)
        self.assertEqual(first.batch, replay.batch)
        with self.assertRaises(IdempotencyConflictError):
            self.repository.create_batch(
                project_id=PROJECT_ID,
                idempotency_key="create-same",
                expected_domains=("AE",),
            )
        with sqlite3.connect(self.repository.db_path) as connection:
            self.assertEqual(
                1,
                connection.execute(
                    "SELECT COUNT(*) FROM monitoring_batches"
                ).fetchone()[0],
            )

    def test_idempotent_replay_rejects_noncanonical_persisted_request_hash(self):
        for index, malformed in enumerate(
            ("A" * 64, " " + "a" * 64, "g" * 64, 123),
            start=1,
        ):
            with self.subTest(malformed=repr(malformed)):
                key = f"create-noncanonical-request-{index}"
                self.repository.create_batch(
                    project_id=PROJECT_ID,
                    idempotency_key=key,
                    expected_domains=("AE",),
                )
                with sqlite3.connect(self.repository.db_path) as connection:
                    connection.execute(
                        "UPDATE monitoring_idempotency SET request_sha256 = ? "
                        "WHERE project_id = ? AND idempotency_key = ?",
                        (malformed, PROJECT_ID, key),
                    )

                with self.assertRaisesRegex(
                    RepositoryIntegrityError,
                    "persisted idempotency request hash must be a canonical SHA-256 value",
                ):
                    self.repository.create_batch(
                        project_id=PROJECT_ID,
                        idempotency_key=key,
                        expected_domains=("AE",),
                    )

    def test_idempotent_replay_rejects_operation_drift(self):
        first = self.repository.create_batch(
            project_id=PROJECT_ID,
            idempotency_key="create-operation-drift",
            expected_domains=("AE",),
        )
        with sqlite3.connect(self.repository.db_path) as connection:
            connection.execute(
                "UPDATE monitoring_idempotency SET operation = ? "
                "WHERE project_id = ? AND idempotency_key = ?",
                ("replace_rows", PROJECT_ID, "create-operation-drift"),
            )

        with self.assertRaisesRegex(
            IdempotencyConflictError,
            "different operation",
        ):
            self.repository.create_batch(
                project_id=PROJECT_ID,
                idempotency_key="create-operation-drift",
                expected_domains=("AE",),
            )
        self.assertEqual("draft", first.batch.state)

    def test_idempotent_replay_rejects_malformed_or_cross_project_response(self):
        first = self.repository.create_batch(
            project_id=PROJECT_ID,
            idempotency_key="create-response-drift",
            expected_domains=("AE",),
        )
        with sqlite3.connect(self.repository.db_path) as connection:
            connection.execute(
                "UPDATE monitoring_idempotency SET response_json = ? "
                "WHERE project_id = ? AND idempotency_key = ?",
                ("[]", PROJECT_ID, "create-response-drift"),
            )

        with self.assertRaisesRegex(
            RepositoryIntegrityError,
            "response must be an object",
        ):
            self.repository.create_batch(
                project_id=PROJECT_ID,
                idempotency_key="create-response-drift",
                expected_domains=("AE",),
            )

        with sqlite3.connect(self.repository.db_path) as connection:
            connection.execute(
                "UPDATE monitoring_idempotency SET response_json = ? "
                "WHERE project_id = ? AND idempotency_key = ?",
                (
                    json.dumps({"batch": {"project_id": "project-other"}}),
                    PROJECT_ID,
                    "create-response-drift",
                ),
            )
        with self.assertRaisesRegex(
            RepositoryIntegrityError,
            "project binding mismatch",
        ):
            self.repository.create_batch(
                project_id=PROJECT_ID,
                idempotency_key="create-response-drift",
                expected_domains=("AE",),
            )
        self.assertFalse(first.replayed)

    def test_mutation_idempotency_replays_before_current_version_check(self):
        source = self._register()
        created = self.repository.create_batch(
            project_id=PROJECT_ID,
            idempotency_key="idem-mutation-create",
        )
        first = self.repository.attach_source(
            batch_id=created.batch.batch_id,
            source_id=source.source_id,
            expected_version=1,
            idempotency_key="idem-mutation-attach",
        )
        replay = self.repository.attach_source(
            batch_id=created.batch.batch_id,
            source_id=source.source_id,
            expected_version=1,
            idempotency_key="idem-mutation-attach",
        )

        self.assertEqual(2, first.batch.version)
        self.assertTrue(replay.replayed)
        self.assertEqual(first.batch, replay.batch)
        with self.assertRaises(IdempotencyConflictError):
            self.repository.replace_rows(
                batch_id=created.batch.batch_id,
                rows=[_row("AE:1", "AE", "headache", row_number=1)],
                expected_version=2,
                idempotency_key="idem-mutation-attach",
            )

    def test_technical_failure_is_recorded_but_cannot_be_overridden_or_parsed(self):
        with self.assertRaises(TechnicalValidationError):
            self._register(
                name="corrupt.xlsx",
                payload=b"corrupt",
                technical_status="failed",
                override_reason="医学确认仍需使用",
            )

    def test_unconfirmed_shared_source_validation_blocks_parsed_state(self):
        source = self._register(validation_use_status="requires_confirmation")
        _, draft = self._draft_with_rows(
            source=source,
            key_prefix="source-admission-pending",
        )

        with self.assertRaises(TechnicalValidationError):
            self.repository.transition_batch(
                batch_id=draft.batch.batch_id,
                target_state="parsed",
                expected_version=draft.batch.version,
                idempotency_key="source-admission-pending:parsed",
            )

        failed = self._register(
            name="corrupt-recorded.xlsx",
            payload=b"corrupt-recorded",
            technical_status="failed",
        )
        self.assertEqual("failed", failed.technical_status)
        _, draft = self._draft_with_rows(
            source=failed,
            expected_domains=("AE", "LB"),
            key_prefix="technical-failed",
        )
        with self.assertRaises(TechnicalValidationError):
            self.repository.transition_batch(
                batch_id=draft.batch.batch_id,
                target_state="parsed",
                expected_version=draft.batch.version,
                idempotency_key="technical-failed:parsed",
            )
        current = self.repository.get_batch(draft.batch.batch_id)
        self.assertEqual("draft", current.state)
        self.assertEqual(draft.batch.version, current.version)

    def test_content_warning_blocks_validation_without_override(self):
        warned = self._register(
            name="warning.xlsx",
            payload=b"warning-listing",
            content_warnings=("document type may be publication",),
        )
        _, evidence = self._parsed_with_validation(
            source=warned,
            key_prefix="warning-block",
        )

        with self.assertRaises(ContentValidationError):
            self.repository.transition_batch(
                batch_id=evidence.batch.batch_id,
                target_state="validated",
                expected_version=evidence.batch.version,
                idempotency_key="warning-block:validated",
            )
        current = self.repository.get_batch(evidence.batch.batch_id)
        self.assertEqual("parsed", current.state)

    def test_medical_override_allows_content_warning_to_pass(self):
        overridden = self._register(
            name="warning-overridden.xlsx",
            payload=b"warning-overridden-listing",
            content_warnings=("indication metadata differs",),
            override_reason="医学经理确认是同一主方案下的目标队列。",
        )
        _, evidence = self._parsed_with_validation(
            source=overridden,
            key_prefix="warning-override",
        )

        validated = self.repository.transition_batch(
            batch_id=evidence.batch.batch_id,
            target_state="validated",
            expected_version=evidence.batch.version,
            idempotency_key="warning-override:validated",
        )

        self.assertEqual("validated", validated.batch.state)

    def test_duplicate_business_key_is_rejected_without_partial_rows(self):
        source = self._register()
        created = self.repository.create_batch(
            project_id=PROJECT_ID,
            idempotency_key="duplicates:create",
        )
        attached = self.repository.attach_source(
            batch_id=created.batch.batch_id,
            source_id=source.source_id,
            expected_version=created.batch.version,
            idempotency_key="duplicates:attach",
        )
        with self.assertRaises(DuplicateBusinessKeyError):
            self.repository.replace_rows(
                batch_id=created.batch.batch_id,
                rows=[
                    _row("AE:duplicate", "AE", "a", row_number=1),
                    _row("AE:duplicate", "AE", "b", row_number=2),
                ],
                expected_version=attached.batch.version,
                idempotency_key="duplicates:rows",
            )

        self.assertEqual((), self.repository.list_rows(created.batch.batch_id))
        self.assertEqual(
            attached.batch.version,
            self.repository.get_batch(created.batch.batch_id).version,
        )

    def test_missing_expected_domain_blocks_validated_state(self):
        _, evidence = self._parsed_with_validation(
            rows=(_row("AE:only", "AE", "Headache", row_number=4),),
            expected_domains=("AE", "LB"),
            key_prefix="missing-domain",
        )

        with self.assertRaises(CompletenessGateError) as raised:
            self.repository.transition_batch(
                batch_id=evidence.batch.batch_id,
                target_state="validated",
                expected_version=evidence.batch.version,
                idempotency_key="missing-domain:validated",
            )

        self.assertIn("LB", str(raised.exception))
        current = self.repository.get_batch(evidence.batch.batch_id)
        self.assertEqual("parsed", current.state)

    def test_full_snapshot_proof_must_be_explicitly_confirmed(self):
        _, evidence = self._parsed_with_validation(
            proof={
                "confirmed": False,
                "basis": "unconfirmed export assumption",
                "confirmed_by": "medical_manager",
            },
            key_prefix="proof-unconfirmed",
        )
        validated = self.repository.transition_batch(
            batch_id=evidence.batch.batch_id,
            target_state="validated",
            expected_version=evidence.batch.version,
            idempotency_key="proof-unconfirmed:validated",
        )

        with self.assertRaises(CompletenessGateError):
            self.repository.transition_batch(
                batch_id=validated.batch.batch_id,
                target_state="confirmed",
                expected_version=validated.batch.version,
                idempotency_key="proof-unconfirmed:confirmed",
            )

    def test_comparison_source_cannot_be_promoted_to_full_snapshot_by_override(self):
        source = self._register(
            name="comparison.xlsx",
            content_warnings=("人工比较状态",),
            override_reason="医学经理确认仅用于重算，不采用来源比较结论。",
            source_class="comparison_workbook",
        )
        _, evidence = self._parsed_with_validation(
            source=source,
            key_prefix="comparison-baseline",
        )
        validated = self.repository.transition_batch(
            batch_id=evidence.batch.batch_id,
            target_state="validated",
            expected_version=evidence.batch.version,
            idempotency_key="comparison-baseline:validated",
        )

        with self.assertRaises(CompletenessGateError):
            self.repository.transition_batch(
                batch_id=validated.batch.batch_id,
                target_state="confirmed",
                expected_version=validated.batch.version,
                idempotency_key="comparison-baseline:confirmed",
            )

        current = self.repository.get_batch(validated.batch.batch_id)
        self.assertEqual("validated", current.state)
        self.assertEqual(validated.batch.version, current.version)

    def test_processed_full_snapshot_can_be_confirmed_only_with_b_grade_ack_and_override(self):
        source = self._register(
            name="processed-full-snapshot.xlsx",
            source_class="processed_full_snapshot",
            override_reason="医学经理已核对该处理型文件的来源、范围及全量属性。",
        )
        _, evidence = self._parsed_with_validation(
            source=source,
            proof={
                "confirmed": True,
                "basis": "经来源追溯确认其为 B 级处理型全量快照。",
                "confirmed_by": "medical_manager",
                "source_authority_grade": "B",
                "processed_source_acknowledged": True,
            },
            key_prefix="processed-b-grade",
        )
        validated = self.repository.transition_batch(
            batch_id=evidence.batch.batch_id,
            target_state="validated",
            expected_version=evidence.batch.version,
            idempotency_key="processed-b-grade:validated",
        )

        confirmed = self.repository.transition_batch(
            batch_id=validated.batch.batch_id,
            target_state="confirmed",
            expected_version=validated.batch.version,
            idempotency_key="processed-b-grade:confirmed",
        )

        self.assertEqual("confirmed", confirmed.batch.state)

    def test_processed_full_snapshot_rejects_incomplete_control_evidence(self):
        cases = (
            (
                "missing-grade",
                {
                    "confirmed": True,
                    "basis": "处理型全量快照。",
                    "confirmed_by": "medical_manager",
                    "processed_source_acknowledged": True,
                },
                "医学经理已核对处理来源。",
            ),
            (
                "wrong-grade",
                {
                    "confirmed": True,
                    "basis": "处理型全量快照。",
                    "confirmed_by": "medical_manager",
                    "source_authority_grade": "A",
                    "processed_source_acknowledged": True,
                },
                "医学经理已核对处理来源。",
            ),
            (
                "missing-ack",
                {
                    "confirmed": True,
                    "basis": "处理型全量快照。",
                    "confirmed_by": "medical_manager",
                    "source_authority_grade": "B",
                },
                "医学经理已核对处理来源。",
            ),
            (
                "negative-ack",
                {
                    "confirmed": True,
                    "basis": "处理型全量快照。",
                    "confirmed_by": "medical_manager",
                    "source_authority_grade": "B",
                    "processed_source_acknowledged": False,
                },
                "医学经理已核对处理来源。",
            ),
            (
                "missing-override",
                {
                    "confirmed": True,
                    "basis": "处理型全量快照。",
                    "confirmed_by": "medical_manager",
                    "source_authority_grade": "B",
                    "processed_source_acknowledged": True,
                },
                None,
            ),
        )
        for index, (case_name, proof, override_reason) in enumerate(cases):
            with self.subTest(case=case_name):
                source = self._register(
                    name=f"processed-{case_name}.xlsx",
                    source_class="processed_full_snapshot",
                    override_reason=override_reason,
                )
                _, evidence = self._parsed_with_validation(
                    source=source,
                    proof=proof,
                    key_prefix=f"processed-reject-{index}",
                )
                validated = self.repository.transition_batch(
                    batch_id=evidence.batch.batch_id,
                    target_state="validated",
                    expected_version=evidence.batch.version,
                    idempotency_key=f"processed-reject-{index}:validated",
                )

                with self.assertRaises(CompletenessGateError):
                    self.repository.transition_batch(
                        batch_id=validated.batch.batch_id,
                        target_state="confirmed",
                        expected_version=validated.batch.version,
                        idempotency_key=f"processed-reject-{index}:confirmed",
                    )

                current = self.repository.get_batch(validated.batch.batch_id)
                self.assertEqual("validated", current.state)
                self.assertEqual(validated.batch.version, current.version)

    def test_non_processed_disallowed_sources_remain_blocked_with_processed_proof(self):
        for index, source_class in enumerate(
            (
                "comparison_workbook",
                "mixed_monitoring_workbook",
                "restored_transitional",
                "unknown_blocked",
            )
        ):
            with self.subTest(source_class=source_class):
                source = self._register(
                    name=f"blocked-{source_class}.xlsx",
                    source_class=source_class,
                    override_reason="医学经理已核对来源，但该类别不得作为全量基线。",
                )
                _, evidence = self._parsed_with_validation(
                    source=source,
                    proof={
                        "confirmed": True,
                        "basis": "不得放宽的来源类别。",
                        "confirmed_by": "medical_manager",
                        "source_authority_grade": "B",
                        "processed_source_acknowledged": True,
                    },
                    key_prefix=f"blocked-source-{index}",
                )
                validated = self.repository.transition_batch(
                    batch_id=evidence.batch.batch_id,
                    target_state="validated",
                    expected_version=evidence.batch.version,
                    idempotency_key=f"blocked-source-{index}:validated",
                )

                with self.assertRaises(CompletenessGateError):
                    self.repository.transition_batch(
                        batch_id=validated.batch.batch_id,
                        target_state="confirmed",
                        expected_version=validated.batch.version,
                        idempotency_key=f"blocked-source-{index}:confirmed",
                    )

    def test_mapping_revision_and_proof_are_required_before_confirmation(self):
        _, draft = self._draft_with_rows(key_prefix="missing-mapping")
        parsed = self.repository.transition_batch(
            batch_id=draft.batch.batch_id,
            target_state="parsed",
            expected_version=draft.batch.version,
            idempotency_key="missing-mapping:parsed",
        )

        with self.assertRaises(CompletenessGateError):
            self.repository.transition_batch(
                batch_id=parsed.batch.batch_id,
                target_state="validated",
                expected_version=parsed.batch.version,
                idempotency_key="missing-mapping:validated",
            )

    def test_optimistic_version_and_state_machine_reject_stale_or_skipped_writes(self):
        source = self._register()
        created = self.repository.create_batch(
            project_id=PROJECT_ID,
            idempotency_key="state:create",
        )
        with self.assertRaises(InvalidStateTransitionError):
            self.repository.transition_batch(
                batch_id=created.batch.batch_id,
                target_state="validated",
                expected_version=created.batch.version,
                idempotency_key="state:skip",
            )

        attached = self.repository.attach_source(
            batch_id=created.batch.batch_id,
            source_id=source.source_id,
            expected_version=created.batch.version,
            idempotency_key="state:attach",
        )
        with self.assertRaises(OptimisticVersionConflictError):
            self.repository.replace_rows(
                batch_id=created.batch.batch_id,
                rows=[_row("AE:stale", "AE", "Headache", row_number=1)],
                expected_version=created.batch.version,
                idempotency_key="state:stale-rows",
            )

        self.assertEqual(
            attached.batch.version,
            self.repository.get_batch(created.batch.batch_id).version,
        )
        self.assertEqual((), self.repository.list_rows(created.batch.batch_id))

    def test_happy_state_sequence_is_append_only_in_event_history(self):
        _, frozen = self._freeze_batch(key_prefix="state-history")

        self.assertEqual("frozen", frozen.batch.state)
        self.assertIsNotNone(frozen.batch.frozen_at)
        with sqlite3.connect(self.repository.db_path) as connection:
            events = connection.execute(
                """
                SELECT batch_version, state, event_type
                FROM monitoring_batch_events
                WHERE batch_id = ?
                ORDER BY batch_version
                """,
                (frozen.batch.batch_id,),
            ).fetchall()
        self.assertEqual(
            list(range(1, frozen.batch.version + 1)),
            [event[0] for event in events],
        )
        self.assertEqual("batch_created", events[0][2])
        self.assertEqual("transition_to_frozen", events[-1][2])
        self.assertEqual("frozen", events[-1][1])

    def test_frozen_batch_rejects_rows_sources_validation_and_transitions(self):
        _, frozen = self._freeze_batch(key_prefix="frozen")
        another_source = self._register(
            name="another.xlsx",
            payload=b"another-listing",
        )

        operations = (
            lambda: self.repository.attach_source(
                batch_id=frozen.batch.batch_id,
                source_id=another_source.source_id,
                expected_version=frozen.batch.version,
                idempotency_key="frozen:attach-after",
            ),
            lambda: self.repository.replace_rows(
                batch_id=frozen.batch.batch_id,
                rows=[_row("AE:new", "AE", "new", row_number=1)],
                expected_version=frozen.batch.version,
                idempotency_key="frozen:rows-after",
            ),
            lambda: self.repository.record_validation_evidence(
                batch_id=frozen.batch.batch_id,
                mapping_revision="mapping-v2",
                mapping={"AE": {"business_key": ["USUBJID"]}},
                expected_domains=("AE",),
                full_snapshot_proof={
                    "confirmed": True,
                    "basis": "new proof",
                    "confirmed_by": "medical_manager",
                },
                expected_version=frozen.batch.version,
                idempotency_key="frozen:evidence-after",
            ),
            lambda: self.repository.transition_batch(
                batch_id=frozen.batch.batch_id,
                target_state="frozen",
                expected_version=frozen.batch.version,
                idempotency_key="frozen:transition-after",
            ),
        )
        for operation in operations:
            with self.subTest(operation=operation):
                with self.assertRaises(FrozenBatchError):
                    operation()

        current = self.repository.get_batch(frozen.batch.batch_id)
        self.assertEqual(frozen.batch, current)

    def test_diff_ready_snapshots_use_business_keys_and_row_fingerprints(self):
        previous_rows = (
            _row("AE:stable", "AE", "Headache", row_number=1),
            _row("LB:changed", "LB", 82, row_number=2),
            _row("AE:removed", "AE", "Nausea", row_number=3),
        )
        current_rows = (
            _row("AE:stable", "AE", "Headache", row_number=1),
            _row("LB:changed", "LB", 105, row_number=2),
            _row("AE:added", "AE", "Rash", row_number=4),
        )
        _, previous = self._freeze_batch(
            key_prefix="diff-previous",
            rows=previous_rows,
        )
        _, current = self._freeze_batch(
            key_prefix="diff-current",
            rows=current_rows,
        )

        snapshot = self.repository.load_diff_ready_batch(current.batch.batch_id)
        diff = self.repository.diff_batches(
            previous.batch.batch_id,
            current.batch.batch_id,
        )

        self.assertEqual("frozen", snapshot.state)
        self.assertEqual("mapping-v1", snapshot.mapping_revision)
        self.assertTrue(snapshot.full_snapshot_proven)
        self.assertTrue(snapshot.source_hashes)
        self.assertTrue(
            all(row.row_fingerprint for row in snapshot.rows)
        )
        self.assertEqual(("AE:added",), diff.added_business_keys)
        self.assertEqual(("AE:removed",), diff.removed_business_keys)
        self.assertEqual(("AE:removed",), diff.removal_eligible_business_keys)
        self.assertEqual((), diff.removal_blocked_business_keys)
        self.assertTrue(diff.full_snapshot_proven)
        self.assertEqual(("LB:changed",), diff.changed_business_keys)
        self.assertEqual(("AE:stable",), diff.unchanged_business_keys)

    def test_persisted_normalized_row_tamper_fails_closed_on_restart_read(self):
        _, draft = self._draft_with_rows(key_prefix="row-integrity")
        batch_id = draft.batch.batch_id

        with sqlite3.connect(self.repository.db_path) as connection:
            connection.execute(
                "UPDATE monitoring_normalized_rows SET data_json = ? "
                "WHERE batch_id = ? AND business_key = ?",
                (
                    '{"TEST":"tampered","USUBJID":"RUX-001","VALUE":"Headache","VISIT":"W4"}',
                    batch_id,
                    "AE:RUX-001:1",
                ),
            )
        with self.assertRaisesRegex(
            RepositoryIntegrityError,
            "normalized row fingerprint does not match its payload",
        ):
            self.repository.list_rows(batch_id)

        with sqlite3.connect(self.repository.db_path) as connection:
            connection.execute(
                "UPDATE monitoring_normalized_rows SET data_json = ?, "
                "source_locator_json = ? WHERE batch_id = ? AND business_key = ?",
                (
                    '{"TEST":"AE:RUX-001:1","USUBJID":"RUX-001","VALUE":"Headache","VISIT":"W4"}',
                    '{"row":999,"sheet":"AE"}',
                    batch_id,
                    "AE:RUX-001:1",
                ),
            )
        with self.assertRaisesRegex(
            RepositoryIntegrityError,
            "normalized rows no longer match replace_rows evidence",
        ):
            self.repository.list_rows(batch_id)

    def test_persisted_normalized_row_fingerprint_must_remain_canonical(self):
        _, draft = self._draft_with_rows(key_prefix="row-fingerprint-canonical")
        with sqlite3.connect(self.repository.db_path) as connection:
            fingerprint = connection.execute(
                "SELECT row_fingerprint FROM monitoring_normalized_rows "
                "WHERE batch_id = ? LIMIT 1",
                (draft.batch.batch_id,),
            ).fetchone()[0]
            connection.execute(
                "UPDATE monitoring_normalized_rows SET row_fingerprint = ? "
                "WHERE batch_id = ?",
                (fingerprint.upper(), draft.batch.batch_id),
            )

        with self.assertRaisesRegex(
            RepositoryIntegrityError,
            "row fingerprint is not canonical",
        ):
            self.repository.list_rows(draft.batch.batch_id)

    def test_supplied_row_fingerprint_must_be_canonical_before_comparison(self):
        row = _row("AE:provided-fingerprint", "AE", "Headache", row_number=4)
        calculated = sha256(
            json.dumps(
                {"domain": "AE", "data": row["data"]},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        valid_row = dict(row)
        valid_row["row_fingerprint"] = calculated
        _, valid_batch = self._draft_with_rows(
            rows=(valid_row,),
            expected_domains=("AE",),
            key_prefix="row-fingerprint-supplied-valid",
        )
        self.assertEqual(
            (calculated,),
            tuple(
                item.row_fingerprint
                for item in self.repository.list_rows(valid_batch.batch.batch_id)
            ),
        )

        malformed_values = (
            calculated.upper(),
            " " + calculated,
            "g" + calculated[1:],
            calculated[:-1],
            123,
        )
        for index, malformed in enumerate(malformed_values, start=1):
            with self.subTest(malformed=repr(malformed)):
                malformed_row = dict(row)
                malformed_row["row_fingerprint"] = malformed
                with self.assertRaisesRegex(
                    RepositoryIntegrityError,
                    "row_fingerprint must be a canonical SHA-256 value",
                ):
                    self._draft_with_rows(
                        rows=(malformed_row,),
                        expected_domains=("AE",),
                        key_prefix=f"row-fingerprint-supplied-{index}",
                    )

    def test_field_profile_cache_identity_hash_must_remain_canonical(self):
        _, draft = self._draft_with_rows(key_prefix="cache-identity-canonical")
        parsed = self.repository.transition_batch(
            batch_id=draft.batch.batch_id,
            target_state="parsed",
            expected_version=draft.batch.version,
            idempotency_key="cache-identity-canonical:parsed",
        )
        batch_id = parsed.batch.batch_id
        with sqlite3.connect(self.repository.db_path) as connection:
            row = connection.execute(
                "SELECT payload_json FROM monitoring_batch_events "
                "WHERE batch_id = ? AND event_type = 'replace_rows'",
                (batch_id,),
            ).fetchone()
            payload = json.loads(row[0])
            payload["row_set_sha256"] = payload["row_set_sha256"].upper()
            connection.execute(
                "UPDATE monitoring_batch_events SET payload_json = ? "
                "WHERE batch_id = ? AND event_type = 'replace_rows'",
                (json.dumps(payload, sort_keys=True), batch_id),
            )

        with self.assertRaisesRegex(
            RepositoryIntegrityError,
            "row_set_sha256 is not canonical",
        ):
            self.repository.load_field_profile_cache_identity(batch_id)

    def test_frozen_batch_mapping_contract_preserves_confirmed_identity_and_fields(
        self,
    ):
        _, draft = self._draft_with_rows(
            rows=(
                {
                    "business_key": "EX:RUX-001:1",
                    "domain": "EX",
                    "data": {
                        "中心编码": "001",
                        "患者键": "RUX-001",
                        "给药业务日期": "2026-01-10",
                        "PAGELMDT": "2026-07-29T16:04:03",
                    },
                    "source_locator": {"sheet": "EX", "row": 4},
                },
            ),
            expected_domains=("EX",),
            key_prefix="frozen-mapping-contract",
        )
        parsed = self.repository.transition_batch(
            batch_id=draft.batch.batch_id,
            target_state="parsed",
            expected_version=draft.batch.version,
            idempotency_key="frozen-mapping-contract:parsed",
        )
        mapping_revision = "monmaprev_" + "a" * 28
        mapping_content_sha256 = "b" * 64
        mapping = {
            "schema_version": "monitoring_project_mapping_v1",
            "mapping_revision": mapping_revision,
            "mapping_content_sha256": mapping_content_sha256,
            "source_batch_id": "mapping-source-batch",
            "source_profile_sha256": "c" * 64,
            "fields": [
                {
                    "domain": "EX",
                    "source_field": "中心编码",
                    "recommended_role": "site_identifier",
                    "field_kind": "source_metadata",
                },
                {
                    "domain": "EX",
                    "source_field": "患者键",
                    "recommended_role": "subject_identifier",
                    "field_kind": "source_metadata",
                },
                {
                    "domain": "EX",
                    "source_field": "给药业务日期",
                    "recommended_role": "actual_dose_date",
                    "field_kind": "source_collected",
                },
                {
                    "domain": "EX",
                    "source_field": "PAGELMDT",
                    "recommended_role": "page_last_modified_datetime",
                    "field_kind": "source_metadata",
                },
            ],
        }
        evidence = self.repository.record_validation_evidence(
            batch_id=parsed.batch.batch_id,
            mapping_revision=mapping_revision,
            mapping=mapping,
            expected_domains=("EX",),
            full_snapshot_proof={
                "confirmed": True,
                "basis": "医学经理确认完整 EX listing。",
                "confirmed_by": "medical_manager",
            },
            expected_version=parsed.batch.version,
            idempotency_key="frozen-mapping-contract:evidence",
        )
        validated = self.repository.transition_batch(
            batch_id=evidence.batch.batch_id,
            target_state="validated",
            expected_version=evidence.batch.version,
            idempotency_key="frozen-mapping-contract:validated",
        )
        confirmed = self.repository.transition_batch(
            batch_id=validated.batch.batch_id,
            target_state="confirmed",
            expected_version=validated.batch.version,
            idempotency_key="frozen-mapping-contract:confirmed",
        )
        frozen = self.repository.transition_batch(
            batch_id=confirmed.batch.batch_id,
            target_state="frozen",
            expected_version=confirmed.batch.version,
            idempotency_key="frozen-mapping-contract:frozen",
        )

        contract = self.repository.load_frozen_mapping_contract(
            frozen.batch.batch_id
        )

        self.assertEqual(mapping_revision, contract.mapping_revision)
        self.assertEqual(mapping_content_sha256, contract.mapping_content_sha256)
        self.assertEqual(frozen.batch.version, contract.batch_version)
        self.assertEqual(64, len(contract.mapping_sha256))
        self.assertEqual(
            ["中心编码", "患者键", "给药业务日期", "PAGELMDT"],
            [field["source_field"] for field in contract.fields],
        )
        identity = contract.identity_dict()
        self.assertEqual(
            "monitoring_record_field_mapping_identity.v1",
            identity["schema_version"],
        )
        self.assertEqual(contract.mapping_sha256, identity["mapping_sha256"])

        with sqlite3.connect(self.repository.db_path) as connection:
            connection.execute(
                "UPDATE monitoring_mapping_revisions "
                "SET mapping_sha256 = ? WHERE batch_id = ?",
                (contract.mapping_sha256.upper(), frozen.batch.batch_id),
            )

        with self.assertRaisesRegex(
            RepositoryIntegrityError,
            "repository hash is not canonical",
        ):
            self.repository.load_frozen_mapping_contract(frozen.batch.batch_id)

    def test_persisted_mapping_revision_hash_must_remain_canonical_before_reuse(
        self,
    ):
        mapping = {
            "AE": {"business_key": ["USUBJID", "AESEQ"]},
            "LB": {"business_key": ["USUBJID", "LBTESTCD", "VISIT"]},
        }
        valid_mapping_sha256 = sha256(
            json.dumps(
                mapping,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        malformed_values = (
            valid_mapping_sha256.upper(),
            " " + valid_mapping_sha256,
            "g" + valid_mapping_sha256[1:],
            valid_mapping_sha256[:-1],
            123,
        )
        for index, malformed in enumerate(malformed_values, start=1):
            with self.subTest(malformed=repr(malformed)):
                _, evidence = self._parsed_with_validation(
                    key_prefix=f"mapping-revision-hash-{index}",
                )
                with sqlite3.connect(self.repository.db_path) as connection:
                    connection.execute(
                        "UPDATE monitoring_mapping_revisions "
                        "SET mapping_sha256 = ? "
                        "WHERE batch_id = ? AND mapping_revision = ?",
                        (malformed, evidence.batch.batch_id, "mapping-v1"),
                    )

                with self.assertRaisesRegex(
                    RepositoryIntegrityError,
                    "persisted mapping revision hash must be a canonical "
                    "SHA-256 value",
                ):
                    self.repository.record_validation_evidence(
                        batch_id=evidence.batch.batch_id,
                        mapping_revision="mapping-v1",
                        mapping=mapping,
                        expected_domains=("AE", "LB"),
                        full_snapshot_proof={
                            "confirmed": True,
                            "basis": "EDC full export with all expected sheets",
                            "confirmed_by": "medical_manager",
                        },
                        expected_version=evidence.batch.version,
                        idempotency_key=(
                            f"mapping-revision-hash-{index}:replay"
                        ),
                    )

    def test_profile_ready_batch_source_binding_hash_must_remain_canonical(self):
        for index, malformed in enumerate(
            ("A" * 64, " " + "a" * 64, "g" * 64, "a" * 63),
            start=1,
        ):
            with self.subTest(malformed=repr(malformed)):
                source = self._register(
                    name=f"profile-source-hash-{index}.xlsx",
                )
                source, frozen = self._freeze_batch(
                    source=source,
                    key_prefix=f"profile-source-hash-{index}",
                )
                with sqlite3.connect(self.repository.db_path) as connection:
                    connection.execute("PRAGMA foreign_keys = OFF")
                    connection.execute(
                        "DROP TRIGGER IF EXISTS trg_monitoring_sources_no_update"
                    )
                    connection.execute(
                        "UPDATE monitoring_sources SET content_sha256 = ? "
                        "WHERE source_id = ?",
                        (malformed, source.source_id),
                    )

                with self.assertRaisesRegex(
                    RepositoryIntegrityError,
                    "source content hash must be a canonical SHA-256 value",
                ):
                    self.repository.load_profile_ready_batch(
                        frozen.batch.batch_id,
                    )

    def test_diff_ignores_source_row_reordering_but_preserves_locator(self):
        previous_rows = (
            _row("AE:stable", "AE", "Headache", row_number=4),
        )
        current_rows = (
            _row("AE:stable", "AE", "Headache", row_number=19),
        )
        _, previous = self._freeze_batch(
            key_prefix="reorder-previous",
            rows=previous_rows,
            expected_domains=("AE",),
        )
        _, current = self._freeze_batch(
            key_prefix="reorder-current",
            rows=current_rows,
            expected_domains=("AE",),
        )

        diff = self.repository.diff_batches(
            previous.batch.batch_id,
            current.batch.batch_id,
        )
        current_row = self.repository.list_rows(current.batch.batch_id)[0]

        self.assertEqual(("AE:stable",), diff.unchanged_business_keys)
        self.assertEqual(19, current_row.source_locator["row"])

    def test_diff_treats_incomplete_persisted_full_snapshot_proof_as_unproven(self):
        previous_rows = (
            _row("AE:removed", "AE", "Nausea", row_number=3),
        )
        _, previous = self._freeze_batch(
            key_prefix="proof-tamper-previous",
            rows=previous_rows,
            expected_domains=("AE",),
        )
        _, current = self._freeze_batch(
            key_prefix="proof-tamper-current",
            rows=(),
            expected_domains=("AE",),
        )
        with sqlite3.connect(self.repository.db_path) as connection:
            connection.execute(
                "UPDATE monitoring_batches SET full_snapshot_proof_json = ? "
                "WHERE batch_id = ?",
                (
                    json.dumps(
                        {
                            "confirmed": True,
                            "basis": "tampered proof",
                            "confirmed_by": "medical_manager",
                        }
                    ),
                    current.batch.batch_id,
                ),
            )

        loaded = self.repository.load_diff_ready_batch(current.batch.batch_id)
        diff = self.repository.diff_batches(
            previous.batch.batch_id,
            current.batch.batch_id,
        )
        self.assertFalse(loaded.full_snapshot_proven)
        self.assertFalse(diff.full_snapshot_proven)
        self.assertEqual(("AE:removed",), diff.removed_business_keys)
        self.assertEqual((), diff.removal_eligible_business_keys)
        self.assertEqual(("AE:removed",), diff.removal_blocked_business_keys)

    def test_repository_diff_reconciles_versioned_identity_aliases(self):
        alias = "edc-display-v1|SUBJ|SUBJ||01|S01021|||受试者页|0|0"
        previous_row = _row(
            "edc|SUBJ|legacy|instance:abc:1",
            "SUBJ",
            "完成试验",
            row_number=23,
        )
        previous_row["source_locator"]["identity_aliases"] = [alias]
        current_row = _row(
            "edc|SUBJ|current",
            "SUBJ",
            "完成试验",
            row_number=22,
        )
        previous_row["data"]["TEST"] = "SUBJSTA"
        current_row["data"]["TEST"] = "SUBJSTA"
        current_row["source_locator"]["identity_aliases"] = [alias]
        _, previous = self._freeze_batch(
            key_prefix="alias-previous",
            rows=(previous_row,),
            expected_domains=("SUBJ",),
        )
        _, current = self._freeze_batch(
            key_prefix="alias-current",
            rows=(current_row,),
            expected_domains=("SUBJ",),
        )

        diff = self.repository.diff_batches(
            previous.batch.batch_id,
            current.batch.batch_id,
        )

        self.assertEqual((), diff.added_business_keys)
        self.assertEqual((), diff.removed_business_keys)
        self.assertEqual((), diff.changed_business_keys)
        self.assertEqual(
            ("edc|SUBJ|current",),
            diff.unchanged_business_keys,
        )

    def test_diff_rejects_batch_before_freeze(self):
        source = self.repository.register_source(
            project_id="project-1",
            source_entry_id="not-frozen-entry",
            validation_id="not-frozen-validation",
            validation_revision=1,
            validator_version="source-content-v2",
            validation_use_status="allowed",
            role="edc_data_listing",
            source_class="raw_full_snapshot",
            file_path=self._file("not-frozen.xlsx", b"PK\x03\x04not-frozen"),
            parser_version="listing-parser-v1",
        )
        batch = self.repository.create_batch(
            project_id="project-1",
            idempotency_key="not-frozen-create",
        ).batch
        batch = self.repository.attach_source(
            batch_id=batch.batch_id,
            source_id=source.source_id,
            expected_version=batch.version,
            idempotency_key="not-frozen-source",
        ).batch
        batch = self.repository.replace_rows(
            batch_id=batch.batch_id,
            rows=(_row("AE:1", "AE", "Headache", row_number=1),),
            expected_version=batch.version,
            idempotency_key="not-frozen-rows",
        ).batch

        with self.assertRaises(CompletenessGateError):
            self.repository.load_diff_ready_batch(batch.batch_id)

    def test_batch_root_read_rejects_noncanonical_expected_domains(self):
        created = self.repository.create_batch(
            project_id=PROJECT_ID,
            idempotency_key="root-shape-domains:create",
            expected_domains=("AE", "LB"),
        ).batch
        with sqlite3.connect(self.repository.db_path) as connection:
            connection.execute(
                """
                UPDATE monitoring_batches
                SET expected_domains_json = ?
                WHERE batch_id = ?
                """,
                ('["lb", "AE"]', created.batch_id),
            )

        with self.assertRaises(RepositoryIntegrityError) as raised:
            self.repository.get_batch(created.batch_id)
        self.assertIn("expected domains", str(raised.exception))

    def test_batch_root_read_rejects_non_object_full_snapshot_proof(self):
        created = self.repository.create_batch(
            project_id=PROJECT_ID,
            idempotency_key="root-shape-proof:create",
        ).batch
        with sqlite3.connect(self.repository.db_path) as connection:
            connection.execute(
                """
                UPDATE monitoring_batches
                SET full_snapshot_proof_json = '[]'
                WHERE batch_id = ?
                """,
                (created.batch_id,),
            )

        with self.assertRaises(RepositoryIntegrityError) as raised:
            self.repository.get_batch(created.batch_id)
        self.assertIn("full snapshot proof", str(raised.exception))

    def test_batch_root_read_rejects_non_integral_version(self):
        created = self.repository.create_batch(
            project_id=PROJECT_ID,
            idempotency_key="root-shape-version:create",
        ).batch
        with sqlite3.connect(self.repository.db_path) as connection:
            connection.execute(
                """
                UPDATE monitoring_batches
                SET version = 1.5
                WHERE batch_id = ?
                """,
                (created.batch_id,),
            )

        with self.assertRaises(RepositoryIntegrityError) as raised:
            self.repository.get_batch(created.batch_id)
        self.assertIn("version", str(raised.exception))

    def test_batch_root_read_rejects_text_version_without_coercion(self):
        created = self.repository.create_batch(
            project_id=PROJECT_ID,
            idempotency_key="root-shape-text-version:create",
        ).batch
        with sqlite3.connect(self.repository.db_path) as connection:
            connection.execute(
                "UPDATE monitoring_batches SET version = ? WHERE batch_id = ?",
                ("not-an-int", created.batch_id),
            )

        with self.assertRaises(RepositoryIntegrityError) as raised:
            self.repository.get_batch(created.batch_id)
        self.assertIn("version", str(raised.exception))

    def test_batch_root_read_rejects_frozen_at_on_non_frozen_batch(self):
        created = self.repository.create_batch(
            project_id=PROJECT_ID,
            idempotency_key="root-shape-frozen-at:create",
        ).batch
        with sqlite3.connect(self.repository.db_path) as connection:
            connection.execute(
                """
                UPDATE monitoring_batches
                SET frozen_at = ?
                WHERE batch_id = ?
                """,
                ("2026-08-05T00:00:00+00:00", created.batch_id),
            )

        with self.assertRaises(RepositoryIntegrityError) as raised:
            self.repository.get_batch(created.batch_id)
        self.assertIn("frozen_at", str(raised.exception))

    def test_batch_root_read_rejects_missing_frozen_at_for_frozen_batch(self):
        _, frozen = self._freeze_batch(key_prefix="root-shape-frozen-missing")
        with sqlite3.connect(self.repository.db_path) as connection:
            connection.execute(
                """
                UPDATE monitoring_batches
                SET frozen_at = NULL
                WHERE batch_id = ?
                """,
                (frozen.batch.batch_id,),
            )

        with self.assertRaises(RepositoryIntegrityError) as raised:
            self.repository.get_batch(frozen.batch.batch_id)
        self.assertIn("frozen_at", str(raised.exception))

    def test_sqlite_enforces_wal_foreign_keys_indexes_and_integrity(self):
        self.assertEqual("ok", self.repository.integrity_check())
        with self.repository._connect() as connection:
            self.assertEqual(
                "wal",
                str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower(),
            )
            self.assertEqual(
                1,
                int(connection.execute("PRAGMA foreign_keys").fetchone()[0]),
            )
            indexes = {
                row[1]
                for row in connection.execute(
                    "PRAGMA index_list(monitoring_normalized_rows)"
                ).fetchall()
            }
            self.assertIn("idx_monitoring_rows_domain", indexes)


if __name__ == "__main__":
    unittest.main()
