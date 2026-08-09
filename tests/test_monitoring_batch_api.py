from __future__ import annotations

from datetime import datetime, timezone
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

from fastapi.testclient import TestClient
from openpyxl import Workbook

from services.api.app.main import app
from services.api.app.monitoring_batch_repository import MonitoringBatchRepository
from services.api.app.monitoring_batch_service import MonitoringBatchService
from services.api.app.monitoring_identity_authorization import MonitoringRole
from services.api.app.monitoring_runtime_principal import MonitoringAuthenticatedPrincipal
from services.api.app.source_content_validation import (
    SourceContentValidationService,
    SourceContentValidationStore,
    SourceExpectedContext,
)
from services.api.app.source_intake import SourceRegistryService, SourceRegistryStore


class MonitoringBatchApiTests(unittest.TestCase):
    class _PrincipalMiddleware:
        def __init__(self, application, principal):
            self.application = application
            self.principal = principal

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                scope.setdefault("state", {})["monitoring_principal"] = self.principal
            await self.application(scope, receive, send)

    def setUp(self):
        self.temporary = TemporaryDirectory()
        root = Path(self.temporary.name)
        validation_service = SourceContentValidationService(
            SourceContentValidationStore(root / "validations.sqlite3")
        )
        self.source_registry = SourceRegistryService(
            SourceRegistryStore(root / "sources.jsonl"),
            artifact_root=root / "source-artifacts",
            content_validation_service=validation_service,
            expected_context_resolver=lambda project_id, module, source_kind: SourceExpectedContext(
                project_identifiers=("RUX-03-002",),
                expected_file_role="edc_data_listing",
            ),
        )
        self.repository = MonitoringBatchRepository(
            root / "monitoring.sqlite3",
            root / "objects",
        )
        self.service = MonitoringBatchService(
            self.source_registry,
            self.repository,
        )
        principal = MonitoringAuthenticatedPrincipal(
            principal_id="batch-api-test",
            tenant_id="tenant-kangzhe",
            roles=(
                MonitoringRole.MEDICAL_MANAGER,
                MonitoringRole.DATA_MANAGEMENT,
                MonitoringRole.STATISTICS_PROGRAMMING,
            ),
            project_scope=("proj_rux_03_002",),
            issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
            authenticated=True,
            authn_method="test-server-session",
            session_id="batch-api-test-session",
            directory_revision="batch-api-test-v1",
            verification_ref_sha256="e" * 64,
        )
        self.client = TestClient(self._PrincipalMiddleware(app, principal))
        self.service_patch = patch(
            "services.api.app.main.monitoring_batch_service",
            self.service,
        )
        self.repository_patch = patch(
            "services.api.app.main.monitoring_batch_repository",
            self.repository,
        )
        self.service_patch.start()
        self.repository_patch.start()

    def tearDown(self):
        self.repository_patch.stop()
        self.service_patch.stop()
        self.temporary.cleanup()

    @staticmethod
    def _listing(value: str = "头痛") -> bytes:
        return (
            "STUDYID,SITEID,SUBJID,VISTOID,VISTREP,FORMOID,FORMREP,RECREP,AETERM\n"
            f"RUX-03-002,01,S01001,V1,0,AE,0,1,{value}\n"
        ).encode("utf-8")

    @staticmethod
    def _dimension_defect_xlsx() -> bytes:
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

    def test_api_intake_state_chain_and_batch_list(self):
        intake = self.client.post(
            "/api/projects/proj_rux_03_002/monitoring/batches/intake-file",
            params={
                "filename": "RUX-03-002_EDC_export.csv",
                "idempotency_key": "api-batch-1",
            },
            content=self._listing(),
        )

        self.assertEqual(200, intake.status_code, intake.text)
        payload = intake.json()
        batch = payload["batch"]["batch"]
        self.assertEqual("draft", batch["state"])
        self.assertEqual(1, payload["row_count"])
        self.assertEqual(["AE"], payload["observed_domains"])
        batch_id = batch["batch_id"]
        source_id = payload["source"]["source_id"]

        parsed = self.client.post(
            f"/api/projects/proj_rux_03_002/monitoring/batches/{batch_id}/transition",
            json={
                "target_state": "parsed",
                "expected_version": batch["version"],
                "idempotency_key": "api-batch-1:parsed",
            },
        )
        self.assertEqual(403, parsed.status_code, parsed.text)
        self.assertEqual(
            "monitoring_write_action_unconfigured",
            parsed.json()["detail"]["code"],
        )
        # The HTTP lifecycle write is intentionally blocked until a named
        # action exists. Keep the repository/service state-machine contract
        # covered directly so this API test never treats the policy gap as
        # authorized.
        parsed_batch = self.service.transition(
            batch_id=batch_id,
            target_state="parsed",
            expected_version=batch["version"],
            idempotency_key="api-batch-1:parsed:service",
        ).batch.to_dict()

        evidence = self.client.post(
            f"/api/projects/proj_rux_03_002/monitoring/batches/{batch_id}/validation-evidence",
            json={
                "mapping_revision": "mapping-rux-v1",
                "mapping": {
                    "AE": {
                        "business_key": [
                            "STUDYID",
                            "SITEID",
                            "SUBJID",
                            "VISTOID",
                            "FORMOID",
                            "RECREP",
                        ]
                    }
                },
                "expected_domains": ["AE"],
                "full_snapshot_proof": {
                    "confirmed": True,
                    "basis": "医学经理确认本次为当前数据库全量 EDC 导出。",
                    "confirmed_by": "medical_manager",
                    "snapshot_source_ids": [source_id],
                    "observed_row_count": 1,
                    "expected_domains": ["AE"],
                },
                "expected_version": parsed_batch["version"],
                "idempotency_key": "api-batch-1:evidence",
            },
        )
        self.assertEqual(200, evidence.status_code, evidence.text)
        current = evidence.json()["batch"]
        for target in ("validated", "confirmed", "frozen"):
            response = self.client.post(
                f"/api/projects/proj_rux_03_002/monitoring/batches/{batch_id}/transition",
                json={
                    "target_state": target,
                    "expected_version": current["version"],
                    "idempotency_key": f"api-batch-1:{target}",
                },
            )
            self.assertEqual(403, response.status_code, response.text)
            self.assertEqual(
                "monitoring_write_action_unconfigured",
                response.json()["detail"]["code"],
            )
            current = self.service.transition(
                batch_id=batch_id,
                target_state=target,
                expected_version=current["version"],
                idempotency_key=f"api-batch-1:{target}:service",
            ).batch.to_dict()

        self.assertEqual("frozen", current["state"])
        summary = self.client.get(
            f"/api/projects/proj_rux_03_002/monitoring/batches/{batch_id}"
        )
        self.assertEqual(200, summary.status_code, summary.text)
        self.assertEqual(1, summary.json()["row_count"])
        self.assertEqual({"AE": 1}, summary.json()["domain_counts"])
        self.assertEqual(source_id, summary.json()["sources"][0]["source_id"])
        listed = self.client.get(
            "/api/projects/proj_rux_03_002/monitoring/batches"
        )
        self.assertEqual(200, listed.status_code, listed.text)
        self.assertEqual(batch_id, listed.json()["batches"][0]["batch_id"])

    def test_comparison_upload_returns_actionable_confirmation_without_batch(self):
        response = self.client.post(
            "/api/projects/proj_rux_03_002/monitoring/batches/intake-file",
            params={
                "filename": "RUX-03-002_Comparison.csv",
                "idempotency_key": "api-comparison",
            },
            content=(
                "状态,STUDYID,SITEID,SUBJID,VISTOID,VISTREP,FORMOID,FORMREP,RECREP,AETERM\n"
                "Changed,RUX-03-002,01,S01001,V1,0,AE,0,1,头痛\n"
            ).encode("utf-8"),
        )

        self.assertEqual(409, response.status_code, response.text)
        detail = response.json()["detail"]
        self.assertEqual(
            "listing_classification_confirmation_required",
            detail["code"],
        )
        self.assertEqual(
            "comparison_workbook",
            detail["classification"]["source_class"],
        )

    def test_verify_derived_snapshot_api_is_auditable_and_path_free(self):
        intake = self.client.post(
            "/api/projects/proj_rux_03_002/monitoring/batches/intake-file",
            params={
                "filename": "RUX-03-002_EDC_export.xlsx",
                "idempotency_key": "api-derived",
                "classification_override_reason": "确认仅 worksheet dimension 元数据异常。",
            },
            content=self._dimension_defect_xlsx(),
        )
        self.assertEqual(200, intake.status_code, intake.text)
        intake_payload = intake.json()
        batch = intake_payload["batch"]["batch"]
        source = intake_payload["source"]
        parsed = self.client.post(
            f"/api/projects/proj_rux_03_002/monitoring/batches/{batch['batch_id']}/transition",
            json={
                "target_state": "parsed",
                "expected_version": batch["version"],
                "idempotency_key": "api-derived:parsed",
            },
        )
        self.assertEqual(403, parsed.status_code, parsed.text)
        self.assertEqual(
            "monitoring_write_action_unconfigured",
            parsed.json()["detail"]["code"],
        )
        parsed_batch = self.service.transition(
            batch_id=batch["batch_id"],
            target_state="parsed",
            expected_version=batch["version"],
            idempotency_key="api-derived:parsed:service",
        ).batch.to_dict()
        request = {
            "expected_version": parsed_batch["version"],
            "source_id": source["source_id"],
            "source_content_sha256": source["content_sha256"],
            "original_source_class": "raw_snapshot_with_format_defect",
            "parser_version": source["parser_version"],
            "transformation_type": "parser_dimension_recovery",
            "execution_tool": "listing_file_parser",
            "execution_tool_version": source["parser_version"],
            "original_parse_sheets": [
                {"sheet_name": "AE", "parsed_row_count": 1},
            ],
            "normalized_row_count": 1,
            "expected_domains": ["AE"],
            "verified_by": "medical_manager",
            "reason": "原始 Excel 仅工作区范围元数据错误，恢复解析后的事实与批次持久化事实一致。",
            "idempotency_key": "api-derived:verify",
        }
        verified = self.client.post(
            f"/api/projects/proj_rux_03_002/monitoring/batches/{batch['batch_id']}/verify-derived-snapshot",
            json=request,
        )
        self.assertEqual(200, verified.status_code, verified.text)
        payload = verified.json()
        self.assertEqual("verified_derived_full_snapshot", payload["source"]["verified_source_class"])
        self.assertTrue(
            payload["medical_summary"]["review"].startswith("batch-api-test：")
        )
        self.assertEqual(1, payload["facts"]["normalized_row_count"])
        self.assertEqual(
            "已核实为可审计派生全量来源",
            payload["medical_summary"]["status"],
        )
        self.assertNotIn(str(self.temporary.name), str(payload))

        replay = self.client.post(
            f"/api/projects/proj_rux_03_002/monitoring/batches/{batch['batch_id']}/verify-derived-snapshot",
            json=request,
        )
        self.assertEqual(200, replay.status_code, replay.text)
        self.assertTrue(replay.json()["replayed"])

        changed = dict(request)
        changed["reason"] = "同一个幂等键不允许替换为不同的证明理由。"
        conflict = self.client.post(
            f"/api/projects/proj_rux_03_002/monitoring/batches/{batch['batch_id']}/verify-derived-snapshot",
            json=changed,
        )
        self.assertEqual(409, conflict.status_code, conflict.text)
