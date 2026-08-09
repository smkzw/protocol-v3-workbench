from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import zipfile

from openpyxl import Workbook

from services.api.app.monitoring_batch_repository import (
    MonitoringBatchRepository,
    MonitoringBatchRepositoryError,
)
from services.api.app.monitoring_batch_service import (
    MonitoringBatchIntakeBlocked,
    MonitoringBatchService,
)


@dataclass
class _Check:
    label: str
    outcome: str


class _Validation:
    def __init__(self, use_status: str = "allowed"):
        self.validation_id = "validation-1"
        self.revision = 1
        self.validator_version = "source_content_consistency_v2"
        self.use_status = use_status
        self.confirmation_reason = ""
        self.checks = [_Check("文件技术可读性", "match")]

    def model_dump(self, mode: str = "json"):
        return {
            "validation_id": self.validation_id,
            "revision": self.revision,
            "validator_version": self.validator_version,
            "use_status": self.use_status,
        }


class _SourceRegistry:
    def __init__(self, use_status: str = "allowed"):
        self.validation = _Validation(use_status)
        self.calls = 0

    def register_listing_file(
        self,
        project_id,
        filename,
        content,
        module,
        expected_file_role,
        parsed_sheets=None,
    ):
        self.calls += 1
        return SimpleNamespace(
            entry=SimpleNamespace(
                entry_id="source-entry-1",
                content_hash=sha256(content).hexdigest(),
            )
        )

    def current_content_validation(self, project_id, source_entry_id):
        return self.validation


class MonitoringBatchServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        root = Path(self.temporary.name)
        self.repository = MonitoringBatchRepository(
            root / "monitoring.sqlite3",
            root / "objects",
        )

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def _clean_csv():
        return (
            "__STUDYOID,__STUDYEVENTOID,__STUDYEVENTREPEATKEY,DOMAIN,"
            "USUBJID,PAGE,FORM,LINE,AETERM\n"
            "STUDY-1,V1,1,AE,S01001,AE,AE,1,头痛\n"
        ).encode("utf-8")

    @staticmethod
    def _dimension_defect_xlsx():
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "AE"
        sheet.append(["STUDYID", "SITEID", "SUBJID", "VISTOID", "FORMOID", "RECREP", "AETERM"])
        sheet.append(["RUX-03-002", "01", "S01001", "V1", "AE", "1", "头痛"])
        original = io.BytesIO()
        workbook.save(original)
        workbook.close()

        rewritten = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(original.getvalue()), "r") as source:
            with zipfile.ZipFile(rewritten, "w") as target:
                for entry in source.infolist():
                    payload = source.read(entry.filename)
                    if entry.filename == "xl/worksheets/sheet1.xml":
                        payload = payload.replace(
                            b'<dimension ref="A1:G2"/>',
                            b'<dimension ref="A1:A1"/>',
                        )
                    target.writestr(entry, payload)
        return rewritten.getvalue()

    def test_clean_listing_creates_traceable_draft_without_running_risk_engine(self):
        service = MonitoringBatchService(_SourceRegistry(), self.repository)

        result = service.intake_listing(
            project_id="project-1",
            filename="EDC_export.csv",
            content=self._clean_csv(),
            idempotency_key="intake-1",
        )

        self.assertEqual("draft", result.batch.batch.state)
        self.assertEqual(3, result.batch.batch.version)
        self.assertEqual(1, result.row_count)
        self.assertEqual(("AE",), result.observed_domains)
        self.assertEqual("EDC_export.csv", result.source.file_name)
        self.assertEqual("source-entry-1", result.source.source_entry_id)
        row = self.repository.list_rows(result.batch.batch.batch_id)[0]
        self.assertEqual(2, row.source_locator["row_number"])

    def test_same_intake_idempotency_replays_same_source_and_batch(self):
        registry = _SourceRegistry()
        service = MonitoringBatchService(registry, self.repository)
        first = service.intake_listing(
            project_id="project-1",
            filename="EDC_export.csv",
            content=self._clean_csv(),
            idempotency_key="intake-same",
        )
        second = service.intake_listing(
            project_id="project-1",
            filename="EDC_export.csv",
            content=self._clean_csv(),
            idempotency_key="intake-same",
        )

        self.assertEqual(first.source.source_id, second.source.source_id)
        self.assertEqual(first.batch.batch.batch_id, second.batch.batch.batch_id)
        self.assertTrue(second.batch.replayed)

    def test_changed_medical_explanation_creates_new_source_revision(self):
        registry = _SourceRegistry()
        service = MonitoringBatchService(registry, self.repository)
        content = self._clean_csv()
        first = service.intake_listing(
            project_id="project-1",
            filename="historical_处理后.csv",
            content=content,
            idempotency_key="intake-revision-1",
            classification_override_reason=(
                "医学经理确认这是 B 级处理后历史全量快照。"
            ),
        )
        second = service.intake_listing(
            project_id="project-1",
            filename="historical_处理后.csv",
            content=content,
            idempotency_key="intake-revision-2",
            classification_override_reason=(
                "医学经理复核报告后补充确认数据截止日期；来源等级仍为 B。"
            ),
        )

        self.assertEqual("processed_full_snapshot", first.source.source_class)
        self.assertEqual("processed_full_snapshot", second.source.source_class)
        self.assertEqual(2, second.source.binding_revision)
        self.assertEqual(first.source.source_id, second.source.supersedes_source_id)
        self.assertEqual(
            "monitoring_source_classifier.v2",
            second.source.classification_version,
        )

    def test_verify_derived_snapshot_reparses_original_object_and_returns_medical_summary(self):
        service = MonitoringBatchService(_SourceRegistry(), self.repository)
        intake = service.intake_listing(
            project_id="project-1",
            filename="RUX-03-002_EDC_export.xlsx",
            content=self._dimension_defect_xlsx(),
            idempotency_key="derived-intake",
            classification_override_reason="确认原始文件仅 worksheet dimension 元数据异常。",
        )
        parsed = self.repository.transition_batch(
            batch_id=intake.batch.batch.batch_id,
            target_state="parsed",
            expected_version=intake.batch.batch.version,
            idempotency_key="derived-intake:parsed",
        )

        result = service.verify_derived_snapshot(
            batch_id=parsed.batch.batch_id,
            source_id=intake.source.source_id,
            source_content_sha256=intake.source.content_sha256,
            original_source_class="raw_snapshot_with_format_defect",
            parser_version=intake.source.parser_version,
            transformation_type="parser_dimension_recovery",
            execution_tool="listing_file_parser",
            execution_tool_version=intake.source.parser_version,
            original_parse_sheets=(
                {"sheet_name": "AE", "parsed_row_count": 1},
            ),
            normalized_row_count=1,
            expected_domains=("AE",),
            verified_by="medical_manager",
            reason="原始工作簿仅工作区范围元数据错误，恢复后解析结果与持久化事实一致。",
            expected_version=parsed.batch.version,
            idempotency_key="derived-intake:verify",
        )

        self.assertEqual("verified_derived_full_snapshot", result.source_summary["verified_source_class"])
        self.assertEqual(1, result.fact_summary["normalized_row_count"])
        self.assertEqual(["AE"], result.fact_summary["expected_domains"])
        self.assertNotIn(str(self.temporary.name), str(result.to_dict()))

    def test_shared_source_confirmation_blocks_before_batch_creation(self):
        service = MonitoringBatchService(
            _SourceRegistry("requires_confirmation"),
            self.repository,
        )

        with self.assertRaises(MonitoringBatchIntakeBlocked) as raised:
            service.intake_listing(
                project_id="project-1",
                filename="EDC_export.csv",
                content=self._clean_csv(),
                idempotency_key="intake-blocked",
            )

        self.assertEqual(
            "source_content_confirmation_required",
            raised.exception.code,
        )

    def test_comparison_workbook_requires_acknowledgement_but_keeps_classification(self):
        service = MonitoringBatchService(_SourceRegistry(), self.repository)
        content = (
            "状态,__STUDYOID,__STUDYEVENTOID,__STUDYEVENTREPEATKEY,DOMAIN,"
            "USUBJID,PAGE,FORM,LINE,AETERM\n"
            "Changed,STUDY-1,V1,1,AE,S01001,AE,AE,1,头痛\n"
        ).encode("utf-8")

        with self.assertRaises(MonitoringBatchIntakeBlocked):
            service.intake_listing(
                project_id="project-1",
                filename="Comparison.csv",
                content=content,
                idempotency_key="comparison-blocked",
            )
        accepted = service.intake_listing(
            project_id="project-1",
            filename="Comparison.csv",
            content=content,
            idempotency_key="comparison-accepted",
            classification_override_reason="确认该文件仅用于重算差异，不作为原始全量基线。",
        )

        self.assertEqual("comparison_workbook", accepted.source.source_class)

    def test_detailed_diff_uses_persisted_header_schema_and_returns_auditable_identity(self):
        previous = SimpleNamespace(
            project_id="project-1",
            rows=(),
            mapping_revision="mapping-v1",
            expected_domains=("LB",),
            schema_fields=(("LB", "LBTEST", "LB"),),
        )
        current = SimpleNamespace(
            project_id="project-1",
            rows=(),
            mapping_revision="mapping-v1",
            expected_domains=("LB",),
            schema_fields=(
                ("LB", "LBTEST", "LB"),
                ("LB", "LBORRESU", "LB"),
            ),
        )
        repository = Mock()
        repository.load_diff_ready_batch.side_effect = [previous, current]
        service = MonitoringBatchService(_SourceRegistry(), repository)

        result = service.detailed_diff("batch-previous", "batch-current")

        self.assertEqual(
            [{"domain": "LB", "added_fields": ["LBORRESU"], "removed_fields": []}],
            result["schema_diffs"],
        )
        self.assertEqual("monitoring_batch_diff.v3", result["algorithm_version"])
        self.assertEqual(64, len(result["output_sha256"]))

    def test_detailed_diff_does_not_assume_full_snapshot_proof(self):
        previous = SimpleNamespace(
            project_id="project-1",
            rows=(
                SimpleNamespace(
                    to_dict=lambda: {
                        "domain": "AE",
                        "business_key": "AE:removed",
                        "data": {"AETERM": "Nausea"},
                        "source_locator": {"locator": "listing:AE:3"},
                    },
                ),
            ),
            mapping_revision="mapping-v1",
            expected_domains=("AE",),
            schema_fields=(("AE", "AETERM", "AE"),),
            full_snapshot_proven=False,
        )
        current = SimpleNamespace(
            project_id="project-1",
            rows=(),
            mapping_revision="mapping-v1",
            expected_domains=("AE",),
            schema_fields=(("AE", "AETERM", "AE"),),
            full_snapshot_proven=False,
        )
        repository = Mock()
        repository.load_diff_ready_batch.side_effect = [previous, current]
        service = MonitoringBatchService(_SourceRegistry(), repository)

        result = service.detailed_diff("batch-previous", "batch-current")

        self.assertFalse(result["full_snapshot_proven"])
        self.assertEqual([], result["removal_eligible_keys"])
        self.assertEqual(["AE:removed"], result["removal_blocked_keys"])

    def test_detailed_diff_rejects_cross_project_batches(self):
        previous = SimpleNamespace(
            project_id="project-1",
            rows=(),
            mapping_revision="mapping-v1",
            expected_domains=("AE",),
            schema_fields=(),
            full_snapshot_proven=False,
        )
        current = SimpleNamespace(
            project_id="project-2",
            rows=(),
            mapping_revision="mapping-v1",
            expected_domains=("AE",),
            schema_fields=(),
            full_snapshot_proven=False,
        )
        repository = Mock()
        repository.load_diff_ready_batch.side_effect = [previous, current]
        service = MonitoringBatchService(_SourceRegistry(), repository)

        with self.assertRaisesRegex(
            MonitoringBatchRepositoryError,
            "different projects",
        ):
            service.detailed_diff("batch-previous", "batch-current")
