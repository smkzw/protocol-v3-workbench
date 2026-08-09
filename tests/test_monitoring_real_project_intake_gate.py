from __future__ import annotations

import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import openpyxl
from fastapi.testclient import TestClient

from services.api.app.main import app
from services.api.app.monitoring_identity_authorization import MonitoringRole
from services.api.app.monitoring_runtime_principal import MonitoringAuthenticatedPrincipal
from services.api.app.source_content_validation import (
    SourceContentValidationService,
    SourceContentValidationStore,
    SourceExpectedContext,
)
from services.api.app.source_intake import SourceRegistryService, SourceRegistryStore


class MonitoringRealProjectIntakeGateTests(unittest.TestCase):
    class _PrincipalMiddleware:
        def __init__(self, application, principal):
            self.application = application
            self.principal = principal

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                scope.setdefault("state", {})["monitoring_principal"] = self.principal
            await self.application(scope, receive, send)

    @staticmethod
    def _principal() -> MonitoringAuthenticatedPrincipal:
        return MonitoringAuthenticatedPrincipal(
            principal_id="intake-gate-test",
            tenant_id="tenant-kangzhe",
            roles=(MonitoringRole.MEDICAL_MANAGER,),
            project_scope=("proj_rux_03_002", "proj_my009_uc", "proj_mgk10_sar_demo"),
            issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
            authenticated=True,
            authn_method="test-server-session",
            session_id="intake-gate-test-session",
            directory_revision="intake-gate-test-v1",
            verification_ref_sha256="2" * 64,
        )

    def setUp(self) -> None:
        self.client = TestClient(self._PrincipalMiddleware(app, self._principal()))

    def test_json_intake_for_registered_real_projects_stops_before_generic_submit(self) -> None:
        request = {
            "batch_label": "incremental-listing",
            "extract_date": "2026-07-13",
            "uploaded_by": "medical_manager",
            "sheets": [],
        }

        for project_id, canonical_id in (
            ("proj_rux_03_002", "proj_rux_03_002"),
            ("rux_03_002_monitoring_raw", "proj_rux_03_002"),
            ("proj_my009_uc", "proj_my009_uc"),
            ("my009_uc_monitoring_raw", "proj_my009_uc"),
        ):
            with self.subTest(project_id=project_id):
                generic_intake = Mock()
                with patch("services.api.app.main.monitoring_intake", generic_intake):
                    response = self.client.post(
                        f"/api/projects/{project_id}/monitoring/intake",
                        json=request,
                    )

                self.assertEqual(409, response.status_code, response.text)
                self.assertEqual(
                    {
                        "code": "real_project_incremental_monitoring_not_enabled",
                        "message": "当前真实项目尚未启用增量医学监查执行；文件已完成登记与内容核验，未运行通用规则引擎。",
                        "project_id": canonical_id,
                    },
                    response.json()["detail"],
                )
                generic_intake.submit.assert_not_called()

    def test_admitted_real_project_file_returns_safe_registration_before_generic_submit(self) -> None:
        for project_id, study_id in (
            ("proj_rux_03_002", "RUX-03-002"),
            ("proj_my009_uc", "MY009-UC-2-01"),
        ):
            with self.subTest(project_id=project_id), tempfile.TemporaryDirectory() as tmp:
                registry = _temporary_registry(Path(tmp), study_id)
                generic_intake = Mock()
                with (
                    patch("services.api.app.main.source_registry", registry),
                    patch("services.api.app.main.monitoring_intake", generic_intake),
                ):
                    response = self.client.post(
                        f"/api/projects/{project_id}/monitoring/intake/file",
                        params={
                            "filename": "incremental_listing.xlsx",
                            "extract_date": "2026-07-13",
                        },
                        content=_listing_bytes(study_id=study_id),
                    )

                self.assertEqual(409, response.status_code, response.text)
                detail = response.json()["detail"]
                self.assertEqual(
                    "real_project_incremental_monitoring_not_enabled",
                    detail["code"],
                )
                self.assertEqual(project_id, detail["project_id"])
                self.assertEqual("allowed", detail["content_validation"]["use_status"])
                self.assertEqual(project_id, detail["source_entry"]["project_id"])
                self.assertEqual("incremental_listing.xlsx", detail["source_entry"]["public_title"])
                generic_intake.submit.assert_not_called()

                serialized = json.dumps(detail, ensure_ascii=False).lower()
                for forbidden in (
                    "content_hash",
                    "file_sha256",
                    "expected_context_hash",
                    "server_path",
                    "storage_key",
                    str(Path(tmp)).lower(),
                    "security scan",
                    "security-scan",
                ):
                    self.assertNotIn(forbidden, serialized)

    def test_unconfirmed_real_project_file_keeps_confirmation_required_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = _temporary_registry(Path(tmp), "RUX-03-002")
            generic_intake = Mock()
            with (
                patch("services.api.app.main.source_registry", registry),
                patch("services.api.app.main.monitoring_intake", generic_intake),
            ):
                response = self.client.post(
                    "/api/projects/proj_rux_03_002/monitoring/intake/file",
                    params={
                        "filename": "listing_without_study_id.xlsx",
                        "extract_date": "2026-07-13",
                    },
                    content=_listing_bytes(),
                )

        self.assertEqual(409, response.status_code, response.text)
        detail = response.json()["detail"]
        self.assertEqual("source_content_confirmation_required", detail["code"])
        self.assertEqual("requires_confirmation", detail["validation"]["use_status"])
        generic_intake.submit.assert_not_called()

    def test_demo_json_intake_still_executes_generic_service(self) -> None:
        result = Mock()
        result.model_dump.return_value = {
            "session_id": "intake_demo",
            "project_id": "proj_mgk10_sar_demo",
        }
        generic_intake = Mock()
        generic_intake.submit.return_value = result

        with patch("services.api.app.main.monitoring_intake", generic_intake):
            response = self.client.post(
                "/api/projects/proj_mgk10_sar_demo/monitoring/intake",
                json={
                    "batch_label": "demo-listing",
                    "extract_date": "2026-07-13",
                    "uploaded_by": "medical_manager",
                    "sheets": [],
                },
            )

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("intake_demo", response.json()["session_id"])
        generic_intake.submit.assert_called_once()
        self.assertEqual(
            "intake-gate-test",
            generic_intake.submit.call_args.args[1].uploaded_by,
        )

    def test_demo_file_intake_still_registers_validates_and_executes_generic_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = _temporary_registry(Path(tmp), "MG-K10-SAR-III")
            result = Mock()
            result.model_dump.return_value = {
                "session_id": "intake_demo_file",
                "project_id": "proj_mgk10_sar_demo",
            }
            generic_intake = Mock()
            generic_intake.submit.return_value = result

            with (
                patch("services.api.app.main.source_registry", registry),
                patch("services.api.app.main.monitoring_intake", generic_intake),
            ):
                response = self.client.post(
                    "/api/projects/proj_mgk10_sar_demo/monitoring/intake/file",
                    params={
                        "filename": "demo_incremental_listing.xlsx",
                        "extract_date": "2026-07-13",
                    },
                    content=_listing_bytes(study_id="MG-K10-SAR-III"),
                )

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("intake_demo_file", response.json()["session_id"])
        self.assertEqual("allowed", response.json()["content_validation"]["use_status"])
        self.assertTrue(response.json()["source_entry_id"])
        generic_intake.submit.assert_called_once()


def _temporary_registry(root: Path, expected_study_id: str) -> SourceRegistryService:
    validation_service = SourceContentValidationService(
        SourceContentValidationStore(root / "source_validations.sqlite3")
    )
    return SourceRegistryService(
        SourceRegistryStore(root / "sources.jsonl"),
        content_validation_service=validation_service,
        expected_context_resolver=lambda project_id, module, source_kind: SourceExpectedContext(
            project_identifiers=(expected_study_id,),
            expected_file_role="edc_data_listing",
        ),
    )


def _listing_bytes(study_id: str = "") -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "AE"
    headers = ["SUBJID", "AETERM"]
    row = ["S01001", "headache"]
    if study_id:
        headers.insert(0, "STUDYID")
        row.insert(0, study_id)
    sheet.append(headers)
    sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
