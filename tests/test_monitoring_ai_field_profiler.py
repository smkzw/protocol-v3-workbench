from __future__ import annotations

import json
import math
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from services.api.app.monitoring_ai_field_profile_cache import (
    MonitoringFieldProfileCache,
)
from services.api.app.monitoring_ai_field_profiler import (
    MonitoringAIFieldProfiler,
    MonitoringFieldProfileSnapshot,
    profile_monitoring_batch_fields,
)
from services.api.app.monitoring_batch_repository import (
    CompletenessGateError,
    MonitoringBatchRepository,
    RepositoryIntegrityError,
)


PROJECT_ID = "project-neutral-monitoring"


def _row(
    business_key: str,
    domain: str,
    data: dict,
    *,
    row_number: int,
    source_path: str = "",
) -> dict:
    locator = {"sheet": domain, "row": row_number}
    if source_path:
        locator["source_path"] = source_path
    return {
        "business_key": business_key,
        "domain": domain,
        "data": data,
        "source_locator": locator,
    }


class MonitoringAIFieldProfilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = MonitoringBatchRepository(
            self.root / "monitoring.sqlite3",
            self.root / "objects",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _freeze(
        self,
        rows: list[dict],
        *,
        key: str = "profile",
        schema_fields: list[dict] | None = None,
    ):
        schema_fields = schema_fields or []
        domains = tuple(sorted(
            {str(row["domain"]).upper() for row in rows}
            | {str(item["domain"]).upper() for item in schema_fields}
        ))
        source_file = self.root / f"{key}.xlsx"
        source_file.write_bytes(b"PK\x03\x04complete-listing")
        source = self.repository.register_source(
            project_id=PROJECT_ID,
            source_entry_id=f"{key}-source-entry",
            validation_id=f"{key}-validation",
            validation_revision=1,
            validator_version="source-content-v2",
            validation_use_status="allowed",
            role="primary_listing",
            source_class="raw_full_snapshot",
            file_path=source_file,
            parser_version="listing-parser/1.0.0",
        )
        batch = self.repository.create_batch(
            project_id=PROJECT_ID,
            idempotency_key=f"{key}:create",
            expected_domains=domains,
        ).batch
        batch = self.repository.attach_source(
            batch_id=batch.batch_id,
            source_id=source.source_id,
            expected_version=batch.version,
            idempotency_key=f"{key}:attach",
        ).batch
        batch = self.repository.replace_rows(
            batch_id=batch.batch_id,
            rows=rows,
            schema_fields=schema_fields,
            expected_version=batch.version,
            idempotency_key=f"{key}:rows",
        ).batch
        batch = self.repository.transition_batch(
            batch_id=batch.batch_id,
            target_state="parsed",
            expected_version=batch.version,
            idempotency_key=f"{key}:parsed",
        ).batch
        batch = self.repository.record_validation_evidence(
            batch_id=batch.batch_id,
            mapping_revision=f"{key}-mapping-v1",
            mapping={"status": "confirmed-input-mapping"},
            expected_domains=domains,
            full_snapshot_proof={
                "confirmed": True,
                "basis": "complete listing fixture",
                "confirmed_by": "test",
            },
            expected_version=batch.version,
            idempotency_key=f"{key}:evidence",
        ).batch
        for state in ("validated", "confirmed", "frozen"):
            batch = self.repository.transition_batch(
                batch_id=batch.batch_id,
                target_state=state,
                expected_version=batch.version,
                idempotency_key=f"{key}:{state}",
            ).batch
        return batch

    @staticmethod
    def _profiles(snapshot):
        return {(profile.domain, profile.field): profile for profile in snapshot.fields}

    def test_cached_snapshot_rejects_boolean_numeric_metadata(self):
        batch = self._freeze(
            [
                _row(
                    "LB:001",
                    "LB",
                    {"VALUE": "18"},
                    row_number=1,
                )
            ],
            key="strict-cache-counts",
        )
        snapshot = profile_monitoring_batch_fields(
            self.repository,
            batch.batch_id,
        )

        row_count_payload = snapshot.to_dict()
        row_count_payload["row_count"] = True
        with self.assertRaisesRegex(ValueError, "row_count"):
            MonitoringFieldProfileSnapshot.from_dict(row_count_payload)

        field_count_payload = snapshot.to_dict()
        field_count_payload["fields"][0]["total_rows"] = True
        with self.assertRaisesRegex(ValueError, "fields.total_rows"):
            MonitoringFieldProfileSnapshot.from_dict(field_count_payload)

        null_rate_payload = snapshot.to_dict()
        null_rate_payload["fields"][0]["null_rate"] = True
        with self.assertRaisesRegex(ValueError, "fields.null_rate"):
            MonitoringFieldProfileSnapshot.from_dict(null_rate_payload)

    def test_cached_snapshot_rejects_noncanonical_digest_shapes(self):
        batch = self._freeze(
            [
                _row(
                    "LB:001",
                    "LB",
                    {"VALUE": "18"},
                    row_number=1,
                )
            ],
            key="strict-cache-digests",
        )
        snapshot = profile_monitoring_batch_fields(
            self.repository,
            batch.batch_id,
        )
        for field_name, invalid_value in (
            ("input_sha256", "A" * 64),
            ("profile_sha256", " " + snapshot.profile_sha256),
            ("source_sha256s", [123]),
            ("source_bindings", [{
                "source_entry_id": "profile-source-entry",
                "source_content_sha256": "g" * 64,
            }]),
        ):
            payload = snapshot.to_dict()
            payload[field_name] = invalid_value
            with self.assertRaisesRegex(ValueError, "cached field profile"):
                MonitoringFieldProfileSnapshot.from_dict(payload)

        cache = MonitoringFieldProfileCache(self.root / "strict-cache")
        payload = snapshot.to_dict()
        payload["profile_sha256"] = "A" * 64
        with self.assertRaisesRegex(ValueError, "profile_sha256"):
            cache.store(
                batch_identity={},
                profiler_contract={},
                snapshot_payload=payload,
            )

    def test_profiles_complete_rows_types_frequencies_and_anomalies(self):
        absolute_locator = str(self.root / "private" / "listing.xlsx")
        rows = [
            _row(
                "AE:001",
                "AE",
                {
                    "ALL_NULL": None,
                    "BOOL": True,
                    "DATE": "2026-07-01",
                    "DATETIME": "2026-07-01T08:30:00+08:00",
                    "MIXED": 1,
                    "NUMBER": 1,
                    "SHARED": "headache",
                    "TEXT": "common",
                    "SUBJID": "SENSITIVE-001",
                },
                row_number=1,
                source_path=absolute_locator,
            ),
            _row(
                "AE:002",
                "AE",
                {
                    "ALL_NULL": " ",
                    "BOOL": "false",
                    "DATE": "2026-07-02",
                    "DATETIME": "2026-07-02 09:45:00",
                    "MIXED": 2,
                    "NUMBER": "2.5",
                    "SHARED": "headache",
                    "TEXT": "common",
                    "SUBJID": "SENSITIVE-002",
                },
                row_number=2,
                source_path=absolute_locator,
            ),
            _row(
                "AE:003",
                "AE",
                {
                    "BOOL": "Y",
                    "MIXED": "unexpected",
                    "NUMBER": 3,
                    "SHARED": "rash",
                    "TEXT": "rare",
                    "TOO_LONG": "x" * 300,
                    "SUBJID": "SENSITIVE-003",
                },
                row_number=3,
                source_path=absolute_locator,
            ),
            _row(
                "LB:001",
                "LB",
                {
                    "NON_FINITE": math.nan,
                    "SHARED": 7,
                },
                row_number=1,
                source_path=absolute_locator,
            ),
            _row(
                "LB:002",
                "LB",
                {
                    "NON_FINITE": 4.5,
                    "SHARED": 8,
                },
                row_number=2,
                source_path=absolute_locator,
            ),
        ]
        batch = self._freeze(rows)

        snapshot = profile_monitoring_batch_fields(
            self.repository,
            batch.batch_id,
            top_value_limit=3,
            representative_value_limit=4,
            anomaly_limit=5,
            max_text_length=64,
        )
        profiles = self._profiles(snapshot)

        self.assertEqual(5, snapshot.row_count)
        self.assertEqual(batch.version, snapshot.batch_revision)
        self.assertEqual(f"{'profile'}-mapping-v1", snapshot.mapping_revision)
        self.assertEqual(
            (("profile-source-entry", snapshot.source_sha256s[0]),),
            snapshot.source_bindings,
        )
        self.assertEqual(1, len(snapshot.source_sha256s))
        self.assertEqual("boolean", profiles[("AE", "BOOL")].inferred_type)
        self.assertEqual("date", profiles[("AE", "DATE")].inferred_type)
        self.assertEqual("datetime", profiles[("AE", "DATETIME")].inferred_type)
        self.assertEqual("decimal", profiles[("AE", "NUMBER")].inferred_type)
        self.assertEqual("mixed", profiles[("AE", "MIXED")].inferred_type)
        self.assertEqual("string", profiles[("AE", "ALL_NULL")].inferred_type)

        all_null = profiles[("AE", "ALL_NULL")]
        self.assertEqual(3, all_null.total_rows)
        self.assertEqual(0, all_null.non_empty_count)
        self.assertEqual(1.0, all_null.null_rate)
        self.assertEqual(0, all_null.unique_value_count)

        text = profiles[("AE", "TEXT")]
        self.assertEqual(3, text.total_rows)
        self.assertEqual(3, text.non_empty_count)

        self.assertEqual(2, text.unique_value_count)
        self.assertEqual("common", text.top_values[0].value)
        self.assertEqual(2, text.top_values[0].count)
        self.assertEqual(("common", "rare"), text.representative_values)

        mixed_anomalies = profiles[("AE", "MIXED")].anomaly_examples
        self.assertEqual(
            ["type_conflict"],
            [item.code for item in mixed_anomalies],
        )
        self.assertEqual("AE:003", mixed_anomalies[0].business_key)
        self.assertEqual("integer", mixed_anomalies[0].expected_type)

        long_anomalies = profiles[("AE", "TOO_LONG")].anomaly_examples
        self.assertEqual("text_too_long", long_anomalies[0].code)
        self.assertEqual(300, long_anomalies[0].length)
        self.assertEqual(
            "non_finite_number",
            profiles[("LB", "NON_FINITE")].anomaly_examples[0].code,
        )
        self.assertEqual("string", profiles[("AE", "SHARED")].inferred_type)
        self.assertEqual("integer", profiles[("LB", "SHARED")].inferred_type)

        serialized = json.dumps(
            snapshot.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        self.assertNotIn(absolute_locator, serialized)
        self.assertNotIn("source_locator", serialized)
        ai_payload = snapshot.to_ai_payload()
        ai_serialized = json.dumps(
            ai_payload,
            ensure_ascii=False,
            sort_keys=True,
        )
        self.assertNotIn("SENSITIVE-001", ai_serialized)
        self.assertNotIn("SENSITIVE-002", ai_serialized)
        self.assertNotIn("SENSITIVE-003", ai_serialized)
        self.assertNotIn("business_key", ai_serialized)
        self.assertTrue(
            self._profiles(snapshot)[("AE", "SUBJID")].to_ai_dict()["values_redacted"]
        )

    def test_text_boolean_inference_requires_whole_column_context(self):
        rows = [
            _row(
                "CM:001",
                "CM",
                {
                    "ATC1CODE": "A",
                    "YN_FLAG": "Y",
                    "WORD_FLAG": "yes",
                    "MIXED_TEXT": "N",
                },
                row_number=1,
            ),
            _row(
                "CM:002",
                "CM",
                {
                    "ATC1CODE": "B",
                    "YN_FLAG": "N",
                    "WORD_FLAG": "no",
                    "MIXED_TEXT": "clinical text",
                },
                row_number=2,
            ),
            _row(
                "CM:003",
                "CM",
                {
                    "ATC1CODE": "C",
                    "YN_FLAG": "Y",
                    "WORD_FLAG": "true",
                    "MIXED_TEXT": "Y",
                },
                row_number=3,
            ),
            _row(
                "CM:004",
                "CM",
                {
                    "ATC1CODE": "N",
                    "YN_FLAG": "N",
                    "WORD_FLAG": "false",
                    "MIXED_TEXT": "other text",
                },
                row_number=4,
            ),
        ]
        batch = self._freeze(rows, key="contextual-boolean")

        snapshot = profile_monitoring_batch_fields(
            self.repository,
            batch.batch_id,
        )
        profiles = self._profiles(snapshot)

        self.assertEqual("string", profiles[("CM", "ATC1CODE")].inferred_type)
        self.assertEqual("boolean", profiles[("CM", "YN_FLAG")].inferred_type)
        self.assertEqual("boolean", profiles[("CM", "WORD_FLAG")].inferred_type)
        self.assertEqual("string", profiles[("CM", "MIXED_TEXT")].inferred_type)
        self.assertFalse(profiles[("CM", "ATC1CODE")].anomaly_examples)
        self.assertFalse(profiles[("CM", "MIXED_TEXT")].anomaly_examples)
        atc_top_types = {
            item.observed_type
            for item in profiles[("CM", "ATC1CODE")].top_values
        }
        self.assertEqual({"string"}, atc_top_types)

    def test_native_boolean_and_boolean_text_remain_boolean_together(self):
        rows = [
            _row("AE:001", "AE", {"FLAG": True}, row_number=1),
            _row("AE:002", "AE", {"FLAG": "false"}, row_number=2),
            _row("AE:003", "AE", {"FLAG": "Y"}, row_number=3),
        ]
        batch = self._freeze(rows, key="native-and-text-boolean")

        snapshot = profile_monitoring_batch_fields(
            self.repository,
            batch.batch_id,
        )

        self.assertEqual(
            "boolean",
            self._profiles(snapshot)[("AE", "FLAG")].inferred_type,
        )

    def test_header_only_domain_is_profiled_without_false_row_evidence(self):
        batch = self._freeze(
            [_row("DM:001", "DM", {"SUBJID": "S001"}, row_number=2)],
            key="header-only",
            schema_fields=[
                {"domain": "DM", "field": "SUBJID", "source_sheet": "DM"},
                {"domain": "AE", "field": "SUBJID", "source_sheet": "AE"},
                {"domain": "AE", "field": "AETERM", "source_sheet": "AE"},
            ],
        )

        snapshot = profile_monitoring_batch_fields(
            self.repository,
            batch.batch_id,
        )
        profiles = self._profiles(snapshot)

        self.assertEqual(0, profiles[("AE", "AETERM")].total_rows)
        self.assertEqual(0, profiles[("AE", "AETERM")].non_empty_count)
        self.assertEqual("unknown", profiles[("AE", "AETERM")].inferred_type)
        self.assertIn(
            ("AE", "AETERM", "AE"),
            self.repository.load_diff_ready_batch(batch.batch_id).schema_fields,
        )

    def test_uses_late_rows_and_large_complete_batch_without_sampling(self):
        row_count = 1500
        rows = []
        for index in range(row_count):
            data = {
                "FREQUENCY": "common" if index < 1490 else "late",
                "MIXED_LATE": index if index < row_count - 1 else "conflict",
            }
            if index == row_count - 1:
                data["LATE_FIELD"] = "present"
            rows.append(
                _row(
                    f"AE:{index:05d}",
                    "AE",
                    data,
                    row_number=index + 1,
                )
            )
        batch = self._freeze(rows, key="large")
        profiler = MonitoringAIFieldProfiler(
            self.repository,
            top_value_limit=2,
            representative_value_limit=3,
        )

        first = profiler.profile_frozen_batch(batch.batch_id)
        second = profiler.profile_frozen_batch(batch.batch_id)
        profiles = self._profiles(first)

        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.input_sha256, second.input_sha256)
        self.assertEqual(first.profile_sha256, second.profile_sha256)
        self.assertEqual(row_count, profiles[("AE", "LATE_FIELD")].total_rows)
        self.assertEqual(1, profiles[("AE", "LATE_FIELD")].non_empty_count)
        self.assertEqual(
            round((row_count - 1) / row_count, 12),
            profiles[("AE", "LATE_FIELD")].null_rate,
        )
        self.assertEqual(
            1490,
            profiles[("AE", "FREQUENCY")].top_values[0].count,
        )
        self.assertEqual("mixed", profiles[("AE", "MIXED_LATE")].inferred_type)
        self.assertEqual(
            "AE:01499",
            profiles[("AE", "MIXED_LATE")].anomaly_examples[0].business_key,
        )
        ordered_keys = [(profile.domain, profile.field) for profile in first.fields]
        self.assertEqual(sorted(ordered_keys), ordered_keys)

    def test_profiles_same_row_term_code_relationships_without_row_values(self):
        rows = [
            _row(
                "AE:001",
                "AE",
                {
                    "不良事件名称 PT": "头痛",
                    "不良事件名称 PT CODE": "10019211",
                },
                row_number=1,
            ),
            _row(
                "AE:002",
                "AE",
                {
                    "不良事件名称 PT": "头痛",
                    "不良事件名称 PT CODE": "10019211",
                },
                row_number=2,
            ),
            _row(
                "AE:003",
                "AE",
                {
                    "不良事件名称 PT": "头痛",
                    "不良事件名称 PT CODE": "99999999",
                },
                row_number=3,
            ),
            _row(
                "AE:004",
                "AE",
                {"不良事件名称 PT": "皮疹"},
                row_number=4,
            ),
            _row(
                "AE:005",
                "AE",
                {"不良事件名称 PT CODE": "10037844"},
                row_number=5,
            ),
        ]
        batch = self._freeze(rows, key="term-code")

        snapshot = profile_monitoring_batch_fields(
            self.repository,
            batch.batch_id,
        )

        self.assertEqual(1, len(snapshot.relationships))
        relationship = snapshot.relationships[0]
        self.assertEqual("term_code_pair", relationship.relationship_type)
        self.assertEqual(3, relationship.jointly_non_empty_count)
        self.assertEqual(1, relationship.left_only_count)
        self.assertEqual(1, relationship.right_only_count)
        self.assertEqual(2, relationship.unique_pair_count)
        self.assertEqual(1, relationship.left_values_with_multiple_right)
        self.assertEqual(0, relationship.right_values_with_multiple_left)
        relationship_payload = snapshot.to_ai_payload()["relationships"][0]
        self.assertNotIn("pair_values", relationship_payload)
        self.assertNotIn("business_key", relationship_payload)

    def test_profiles_common_code_text_and_drug_dictionary_pairs(self):
        rows = [
            _row(
                "CM:001",
                "CM",
                {
                    "ATC1CODE": "D",
                    "ATC1TEXT": "皮肤病用药",
                    "DRUGCODE": "90021901001",
                    "DRUGNAME": "其他皮肤科制剂",
                    "DRUGPTCD": "90021901001",
                    "DRUGPTNM": "其他皮肤科制剂",
                    "DRUGVER": "20250301",
                    "PTCODE": "10019211",
                    "PTTERM": "头痛",
                },
                row_number=1,
            ),
            _row(
                "CM:002",
                "CM",
                {
                    "ATC1CODE": "R",
                    "ATC1TEXT": "呼吸系统用药",
                    "DRUGCODE": "00908302001",
                    "DRUGNAME": "糠酸莫米松",
                    "DRUGPTCD": "00908302001",
                    "DRUGPTNM": "糠酸莫米松",
                    "DRUGVER": "20250301",
                    "PTCODE": "10037844",
                    "PTTERM": "皮疹",
                },
                row_number=2,
            ),
        ]
        batch = self._freeze(rows, key="common-coded-pairs")

        snapshot = profile_monitoring_batch_fields(
            self.repository,
            batch.batch_id,
        )

        pairs = {
            (item.left_field, item.right_field)
            for item in snapshot.relationships
        }
        self.assertIn(("ATC1TEXT", "ATC1CODE"), pairs)
        self.assertIn(("DRUGNAME", "DRUGCODE"), pairs)
        self.assertIn(("DRUGPTNM", "DRUGPTCD"), pairs)
        self.assertIn(("PTTERM", "PTCODE"), pairs)

    def test_profiles_repeated_header_relationships_by_exact_suffix_group(self):
        secret_values = {
            "known_2_term": "SECRET-KNOWN-2-TERM",
            "known_2_code": "SECRET-KNOWN-2-CODE",
            "known_3_term": "SECRET-KNOWN-3-TERM",
            "known_3_code": "SECRET-KNOWN-3-CODE",
            "code_text_term": "SECRET-CODE-TEXT-TERM",
            "code_text_code": "SECRET-CODE-TEXT-CODE",
            "code_term_term": "SECRET-CODE-TERM-TERM",
            "code_term_code": "SECRET-CODE-TERM-CODE",
            "cd_nm_term": "SECRET-CD-NM-TERM",
            "cd_nm_code": "SECRET-CD-NM-CODE",
            "drug_name": "SECRET-DRUG-NAME",
            "drug_code": "SECRET-DRUG-CODE",
            "drug_pt_name": "SECRET-DRUG-PT-NAME",
            "drug_pt_code": "SECRET-DRUG-PT-CODE",
        }
        rows = [
            _row(
                "AE:001",
                "AE",
                {
                    "AETERM": "baseline term",
                    "AEDECOD": "baseline code",
                    "AETERM__2": secret_values["known_2_term"],
                    "AEDECOD__2": secret_values["known_2_code"],
                    "AETERM__3": secret_values["known_3_term"],
                    "AEDECOD__3": secret_values["known_3_code"],
                    "ATC1TEXT__2": secret_values["code_text_term"],
                    "ATC1CODE__2": secret_values["code_text_code"],
                    "PTTERM__2": secret_values["code_term_term"],
                    "PTCODE__2": secret_values["code_term_code"],
                    "TESTNM__2": secret_values["cd_nm_term"],
                    "TESTCD__2": secret_values["cd_nm_code"],
                    "DRUGNAME__2": secret_values["drug_name"],
                    "DRUGCODE__2": secret_values["drug_code"],
                    "DRUGPTNM__2": secret_values["drug_pt_name"],
                    "DRUGPTCD__2": secret_values["drug_pt_code"],
                    "MIXTEXT__2": "must not cross suffix",
                    "MIXCODE__3": "must not cross suffix",
                    "OTHERDRUGNAME__2": "must not cross suffix",
                    "OTHERDRUGCODE__3": "must not cross suffix",
                },
                row_number=1,
            ),
            _row(
                "AE:002",
                "AE",
                {
                    "AETERM__2": "left only",
                },
                row_number=2,
            ),
            _row(
                "AE:003",
                "AE",
                {
                    "AEDECOD__2": "right only",
                },
                row_number=3,
            ),
        ]
        batch = self._freeze(rows, key="repeated-header-pairs")

        first = profile_monitoring_batch_fields(self.repository, batch.batch_id)
        second = profile_monitoring_batch_fields(self.repository, batch.batch_id)

        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.profile_sha256, second.profile_sha256)
        pairs = {
            (item.left_field, item.right_field)
            for item in first.relationships
        }
        for expected_pair in (
            ("AETERM", "AEDECOD"),
            ("AETERM__2", "AEDECOD__2"),
            ("AETERM__3", "AEDECOD__3"),
            ("ATC1TEXT__2", "ATC1CODE__2"),
            ("PTTERM__2", "PTCODE__2"),
            ("TESTNM__2", "TESTCD__2"),
            ("DRUGNAME__2", "DRUGCODE__2"),
            ("DRUGPTNM__2", "DRUGPTCD__2"),
        ):
            self.assertIn(expected_pair, pairs)
        self.assertNotIn(("MIXTEXT__2", "MIXCODE__3"), pairs)
        self.assertNotIn(("OTHERDRUGNAME__2", "OTHERDRUGCODE__3"), pairs)
        repeated_known_pair = next(
            item
            for item in first.relationships
            if (item.left_field, item.right_field)
            == ("AETERM__2", "AEDECOD__2")
        )
        self.assertEqual(3, repeated_known_pair.total_rows)
        self.assertEqual(1, repeated_known_pair.jointly_non_empty_count)
        self.assertEqual(1, repeated_known_pair.left_only_count)
        self.assertEqual(1, repeated_known_pair.right_only_count)
        self.assertEqual(1, repeated_known_pair.unique_pair_count)

        relationship_payload = first.to_ai_payload()["relationships"]
        relationship_serialized = json.dumps(
            relationship_payload,
            ensure_ascii=False,
            sort_keys=True,
        )
        for secret_value in secret_values.values():
            self.assertNotIn(secret_value, relationship_serialized)
        expected_payload_keys = {
            "domain",
            "left_field",
            "right_field",
            "relationship_type",
            "total_rows",
            "jointly_non_empty_count",
            "left_only_count",
            "right_only_count",
            "unique_pair_count",
            "left_values_with_multiple_right",
            "right_values_with_multiple_left",
        }
        self.assertTrue(relationship_payload)
        self.assertTrue(
            all(set(item) == expected_payload_keys for item in relationship_payload)
        )

    def test_profiles_explicit_non_coding_same_row_relationships(self):
        rows = [
            _row(
                "SV:001",
                "SV",
                {
                    "SITEID": "01",
                    "SITENM": "secret site name",
                    "SITE": "secret site label",
                    "VISIT": "筛选期",
                    "VISTOID": "SCR",
                    "VISITNUM": 10,
                    "RESULT": 12.5,
                    "RESULT_UNIT": "mg/L",
                    "RATE": "3.5",
                    "RATEUNIT": "mL/min",
                    "CMDOSE": 5,
                    "CMDOSU": "mg",
                    "LBPERF": "Y",
                    "LBREASND": "not applicable",
                },
                row_number=1,
            ),
            _row(
                "SV:002",
                "SV",
                {
                    "SITEID": "02",
                    "SITENM": "second secret site",
                    "SITE": "second secret label",
                    "VISIT": "基线期",
                    "VISTOID": "BASE",
                    "VISITNUM": 20,
                    "RESULT": 8,
                    "RESULT_UNIT": "mg/L",
                    "RATE": 4,
                    "RATEUNIT": "mL/min",
                    "CMDOSE": 10,
                    "CMDOSU": "mg",
                    "LBPERF": "N",
                    "LBREASND": "subject refused",
                },
                row_number=2,
            ),
        ]
        batch = self._freeze(rows, key="explicit-non-coding-pairs")

        first = profile_monitoring_batch_fields(self.repository, batch.batch_id)
        second = profile_monitoring_batch_fields(self.repository, batch.batch_id)

        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.profile_sha256, second.profile_sha256)
        relationships = {
            (item.left_field, item.right_field): item
            for item in first.relationships
        }
        expected_pairs = {
            ("SITEID", "SITENM"): "site_identity_pair",
            ("SITEID", "SITE"): "site_identity_pair",
            ("VISIT", "VISTOID"): "visit_identity_pair",
            ("VISIT", "VISITNUM"): "visit_identity_pair",
            ("RESULT", "RESULT_UNIT"): "value_unit_pair",
            ("RATE", "RATEUNIT"): "value_unit_pair",
            ("CMDOSE", "CMDOSU"): "value_unit_pair",
            ("LBPERF", "LBREASND"): "performed_reason_pair",
        }
        for pair, relationship_type in expected_pairs.items():
            self.assertIn(pair, relationships)
            self.assertEqual(
                relationship_type,
                relationships[pair].relationship_type,
            )
            self.assertEqual(2, relationships[pair].jointly_non_empty_count)

        relationship_serialized = json.dumps(
            first.to_ai_payload()["relationships"],
            ensure_ascii=False,
            sort_keys=True,
        )
        expected_payload_keys = {
            "domain",
            "left_field",
            "right_field",
            "relationship_type",
            "total_rows",
            "jointly_non_empty_count",
            "left_only_count",
            "right_only_count",
            "unique_pair_count",
            "left_values_with_multiple_right",
            "right_values_with_multiple_left",
        }
        self.assertTrue(
            all(
                set(item) == expected_payload_keys
                for item in first.to_ai_payload()["relationships"]
            )
        )
        for secret_value in (
            "secret site name",
            "secret site label",
            "second secret site",
            "second secret label",
            "subject refused",
        ):
            self.assertNotIn(secret_value, relationship_serialized)

    def test_non_coding_relationships_require_exact_repeat_group_and_pattern(self):
        rows = [
            _row(
                "SV:001",
                "SV",
                {
                    "SITEID__2": "01",
                    "SITENM__2": "site two",
                    "SITE__3": "site three",
                    "VISIT__2": "筛选期",
                    "VISTOID__2": "SCR",
                    "VISITNUM__3": 10,
                    "RESULT__2": 12.5,
                    "RESULT_UNIT__2": "mg/L",
                    "OTHER__2": 8,
                    "OTHERUNIT__3": "mmol/L",
                    "CMDOSE__2": 5,
                    "CMDOSU__2": "mg",
                    "LBPERF__2": "N",
                    "LBREASND__2": "not done",
                    "EGPERF__2": "Y",
                    "LBREASND__3": "different group",
                    "COMMENT__2": "not numeric",
                    "COMMENT_UNIT__2": "not a value-unit pair",
                    "SITELABEL__2": "not an allowed site pattern",
                    "VISITDAY__2": 1,
                    "MEASURE__2": 7,
                    "MEASUREU__2": "not an allowed unit suffix",
                    "DASHVALUE__2": 9,
                    "DASHVALUE-UNIT__2": "not an allowed unit separator",
                    "SPACEVALUE__2": 11,
                    "SPACEVALUE UNIT__2": "not an allowed unit separator",
                    "XPERF__2": "N",
                    "YREASND__2": "different prefix",
                    "CROSSPERF__2": "N",
                },
                row_number=1,
            ),
            _row(
                "DM:001",
                "DM",
                {
                    "CROSSREASND__2": "different domain",
                },
                row_number=1,
            ),
        ]
        batch = self._freeze(rows, key="non-coding-repeat-boundary")

        first = profile_monitoring_batch_fields(self.repository, batch.batch_id)
        second = profile_monitoring_batch_fields(self.repository, batch.batch_id)

        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.profile_sha256, second.profile_sha256)
        relationships = {
            (item.left_field, item.right_field): item.relationship_type
            for item in first.relationships
        }
        self.assertEqual(
            "site_identity_pair",
            relationships[("SITEID__2", "SITENM__2")],
        )
        self.assertEqual(
            "visit_identity_pair",
            relationships[("VISIT__2", "VISTOID__2")],
        )
        self.assertEqual(
            "value_unit_pair",
            relationships[("RESULT__2", "RESULT_UNIT__2")],
        )
        self.assertEqual(
            "value_unit_pair",
            relationships[("CMDOSE__2", "CMDOSU__2")],
        )
        self.assertEqual(
            "performed_reason_pair",
            relationships[("LBPERF__2", "LBREASND__2")],
        )
        for forbidden_pair in (
            ("SITEID__2", "SITE__3"),
            ("VISIT__2", "VISITNUM__3"),
            ("OTHER__2", "OTHERUNIT__3"),
            ("EGPERF__2", "LBREASND__3"),
            ("COMMENT__2", "COMMENT_UNIT__2"),
            ("SITEID__2", "SITELABEL__2"),
            ("VISIT__2", "VISITDAY__2"),
            ("MEASURE__2", "MEASUREU__2"),
            ("DASHVALUE__2", "DASHVALUE-UNIT__2"),
            ("SPACEVALUE__2", "SPACEVALUE UNIT__2"),
            ("XPERF__2", "YREASND__2"),
            ("CROSSPERF__2", "CROSSREASND__2"),
        ):
            self.assertNotIn(forbidden_pair, relationships)

    def test_rejects_non_frozen_batch_and_invalid_limits(self):
        batch = self.repository.create_batch(
            project_id=PROJECT_ID,
            idempotency_key="draft:create",
        ).batch

        with self.assertRaises(CompletenessGateError):
            MonitoringAIFieldProfiler(self.repository).profile_frozen_batch(
                batch.batch_id
            )
        with self.assertRaisesRegex(
            ValueError, "top_value_limit must be a positive integer"
        ):
            MonitoringAIFieldProfiler(
                self.repository,
                top_value_limit=0,
            )

    def test_verified_cache_hit_does_not_reload_normalized_rows(self):
        batch = self._freeze(
            [
                _row(
                    "AE:001",
                    "AE",
                    {"SUBJID": "001", "AETERM": "头痛"},
                    row_number=1,
                )
            ],
            key="cache-hit",
        )
        cache_root = self.root / "field-profile-cache"
        profiler = MonitoringAIFieldProfiler(
            self.repository,
            cache_root=cache_root,
        )

        first = profiler.profile_batch(batch.batch_id)
        identity = self.repository.load_field_profile_cache_identity(
            batch.batch_id
        )
        cache_key = MonitoringFieldProfileCache.cache_key(
            batch_identity=identity.to_dict(),
            profiler_contract=profiler.profiler_contract(),
        )
        manifest_path = (
            cache_root / cache_key[:2] / cache_key / "manifest.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(cache_key, manifest["cache_key"])
        self.assertEqual(
            identity.source_bindings[0].binding_revision,
            manifest["batch_identity"]["source_bindings"][0][
                "binding_revision"
            ],
        )

        with patch.object(
            self.repository,
            "load_profile_ready_batch",
            side_effect=AssertionError("cache hit reloaded full rows"),
        ):
            second = profiler.profile_batch(batch.batch_id)

        self.assertEqual(first.to_dict(), second.to_dict())

    def test_corrupt_cache_fails_closed_recomputes_and_repairs_entry(self):
        batch = self._freeze(
            [
                _row(
                    "LB:001",
                    "LB",
                    {"SUBJID": "001", "LBORRES": "18"},
                    row_number=1,
                )
            ],
            key="cache-corrupt",
        )
        cache_root = self.root / "field-profile-cache"
        profiler = MonitoringAIFieldProfiler(
            self.repository,
            cache_root=cache_root,
        )
        expected = profiler.profile_batch(batch.batch_id)
        identity = self.repository.load_field_profile_cache_identity(
            batch.batch_id
        )
        cache_key = MonitoringFieldProfileCache.cache_key(
            batch_identity=identity.to_dict(),
            profiler_contract=profiler.profiler_contract(),
        )
        snapshot_path = (
            cache_root / cache_key[:2] / cache_key / "snapshot.json"
        )
        snapshot_path.write_text('{"corrupt":true}', encoding="utf-8")

        original_loader = self.repository.load_profile_ready_batch
        with patch.object(
            self.repository,
            "load_profile_ready_batch",
            wraps=original_loader,
        ) as loader:
            repaired = profiler.profile_batch(batch.batch_id)
        self.assertEqual(1, loader.call_count)
        self.assertEqual(expected.to_dict(), repaired.to_dict())

        with patch.object(
            self.repository,
            "load_profile_ready_batch",
            side_effect=AssertionError("repaired cache was not reused"),
        ):
            verified = profiler.profile_batch(batch.batch_id)
        self.assertEqual(expected.to_dict(), verified.to_dict())

    def test_semantically_tampered_cache_recomputes_even_with_rehashed_manifest(
        self,
    ):
        batch = self._freeze(
            [
                _row(
                    "LB:001",
                    "LB",
                    {"SUBJID": "001", "LBORRES": "18"},
                    row_number=1,
                )
            ],
            key="cache-semantic-tamper",
        )
        cache_root = self.root / "field-profile-cache"
        profiler = MonitoringAIFieldProfiler(
            self.repository,
            cache_root=cache_root,
        )
        expected = profiler.profile_batch(batch.batch_id)
        identity = self.repository.load_field_profile_cache_identity(
            batch.batch_id
        )
        cache_key = MonitoringFieldProfileCache.cache_key(
            batch_identity=identity.to_dict(),
            profiler_contract=profiler.profiler_contract(),
        )
        entry_root = cache_root / cache_key[:2] / cache_key
        snapshot_path = entry_root / "snapshot.json"
        manifest_path = entry_root / "manifest.json"
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        snapshot["fields"][0]["inferred_type"] = "tampered"
        snapshot_bytes = json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        snapshot_path.write_bytes(snapshot_bytes)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["snapshot_sha256"] = sha256(snapshot_bytes).hexdigest()
        manifest["snapshot_size_bytes"] = len(snapshot_bytes)
        manifest.pop("manifest_sha256")
        manifest["manifest_sha256"] = sha256(
            json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        manifest_path.write_text(
            json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
            encoding="utf-8",
        )

        original_loader = self.repository.load_profile_ready_batch
        with patch.object(
            self.repository,
            "load_profile_ready_batch",
            wraps=original_loader,
        ) as loader:
            repaired = profiler.profile_batch(batch.batch_id)

        self.assertEqual(1, loader.call_count)
        self.assertEqual(expected.to_dict(), repaired.to_dict())

    def test_cache_key_invalidates_on_profiler_or_binding_contract_change(self):
        batch = self._freeze(
            [
                _row(
                    "CM:001",
                    "CM",
                    {"SUBJID": "001", "CMTRT": "对乙酰氨基酚"},
                    row_number=1,
                )
            ],
            key="cache-key",
        )
        identity = self.repository.load_field_profile_cache_identity(
            batch.batch_id
        )
        profiler = MonitoringAIFieldProfiler(
            self.repository,
            cache_root=self.root / "field-profile-cache",
        )
        base_key = MonitoringFieldProfileCache.cache_key(
            batch_identity=identity.to_dict(),
            profiler_contract=profiler.profiler_contract(),
        )
        changed_contract = dict(profiler.profiler_contract())
        changed_contract["max_text_length"] += 1
        self.assertNotEqual(
            base_key,
            MonitoringFieldProfileCache.cache_key(
                batch_identity=identity.to_dict(),
                profiler_contract=changed_contract,
            ),
        )
        changed_identity = identity.to_dict()
        changed_identity["source_bindings"] = [
            {
                **changed_identity["source_bindings"][0],
                "binding_revision": (
                    changed_identity["source_bindings"][0][
                        "binding_revision"
                    ]
                    + 1
                ),
            }
        ]
        self.assertNotEqual(
            base_key,
            MonitoringFieldProfileCache.cache_key(
                batch_identity=changed_identity,
                profiler_contract=profiler.profiler_contract(),
            ),
        )
        changed_content_identity = identity.to_dict()
        changed_content_identity["content_identity_sha256"] = "0" * 64
        changed_content_identity["identity_sha256"] = "1" * 64
        self.assertNotEqual(
            base_key,
            MonitoringFieldProfileCache.cache_key(
                batch_identity=changed_content_identity,
                profiler_contract=profiler.profiler_contract(),
            ),
        )

    def test_cache_identity_fails_closed_when_row_evidence_drifts(self):
        batch = self._freeze(
            [
                _row(
                    "AE:001",
                    "AE",
                    {"SUBJID": "001", "AETERM": "头痛"},
                    row_number=1,
                ),
                _row(
                    "AE:002",
                    "AE",
                    {"SUBJID": "002", "AETERM": "皮疹"},
                    row_number=2,
                ),
            ],
            key="cache-identity-drift",
        )
        with self.repository._connect() as connection:
            connection.execute(
                """
                DELETE FROM monitoring_normalized_rows
                WHERE batch_id = ? AND business_key = ?
                """,
                (batch.batch_id, "AE:002"),
            )

        with self.assertRaisesRegex(
            RepositoryIntegrityError,
            "row count no longer matches",
        ):
            self.repository.load_field_profile_cache_identity(batch.batch_id)

    def test_frozen_batch_rejects_one_registry_entry_bound_to_two_hashes(self):
        sources = []
        for revision, payload in ((1, b"first"), (2, b"second")):
            source_file = self.root / f"duplicate-{revision}.xlsx"
            source_file.write_bytes(payload)
            sources.append(
                self.repository.register_source(
                    project_id=PROJECT_ID,
                    source_entry_id="same-registry-entry",
                    validation_id=f"validation-{revision}",
                    validation_revision=revision,
                    validator_version="source-content-v2",
                    validation_use_status="allowed",
                    role="primary_listing",
                    source_class="raw_full_snapshot",
                    file_path=source_file,
                    parser_version="listing-parser/1.0.0",
                )
            )
        batch = self.repository.create_batch(
            project_id=PROJECT_ID,
            idempotency_key="duplicate:create",
            expected_domains=("AE",),
        ).batch
        for index, source in enumerate(sources, start=1):
            batch = self.repository.attach_source(
                batch_id=batch.batch_id,
                source_id=source.source_id,
                expected_version=batch.version,
                idempotency_key=f"duplicate:attach:{index}",
            ).batch
        batch = self.repository.replace_rows(
            batch_id=batch.batch_id,
            rows=[_row("AE:001", "AE", {"SUBJID": "001"}, row_number=1)],
            expected_version=batch.version,
            idempotency_key="duplicate:rows",
        ).batch
        batch = self.repository.transition_batch(
            batch_id=batch.batch_id,
            target_state="parsed",
            expected_version=batch.version,
            idempotency_key="duplicate:parsed",
        ).batch
        batch = self.repository.record_validation_evidence(
            batch_id=batch.batch_id,
            mapping_revision="duplicate-mapping",
            mapping={"status": "confirmed-input-mapping"},
            expected_domains=("AE",),
            full_snapshot_proof={
                "confirmed": True,
                "basis": "test fixture",
                "confirmed_by": "test",
            },
            expected_version=batch.version,
            idempotency_key="duplicate:evidence",
        ).batch
        for state in ("validated", "confirmed", "frozen"):
            batch = self.repository.transition_batch(
                batch_id=batch.batch_id,
                target_state=state,
                expected_version=batch.version,
                idempotency_key=f"duplicate:{state}",
            ).batch

        with self.assertRaisesRegex(
            CompletenessGateError,
            "one source entry ID to multiple content hashes",
        ):
            self.repository.load_diff_ready_batch(batch.batch_id)


if __name__ == "__main__":
    unittest.main()
