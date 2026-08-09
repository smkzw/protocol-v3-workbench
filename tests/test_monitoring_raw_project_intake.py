from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch
from datetime import datetime, timezone

from services.api.app.monitoring_raw_intake import (
    MonitoringRawProjectConfig,
    MonitoringRawProjectIntakeService,
)
from services.api.app.monitoring_identity_authorization import MonitoringRole
from services.api.app.monitoring_runtime_principal import MonitoringAuthenticatedPrincipal

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - minimal runtimes can skip route checks.
    TestClient = None


RUX_LISTING = Path(
    "/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/CFDI Inspection/准备阶段/"
    "RUX-03-002_列表_数据集_Excel_20250612_处理后.xlsx"
)
RUX_PROTOCOL = Path(
    "/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/CFDI Inspection/RUX-03-002-自查文件包-20260107/"
    "10-临床试验重要文件/1-临床试验方案/V1.3版-2024.8.14/"
    "磷酸芦可替尼乳膏-AD3期临床研究方案V1.3-clean-20240814.docx"
)
MY009_LISTING = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY009治疗UC/S1安全性评价-202604/"
    "MY009-UC-2-01-MM Listing_20260408(已自动还原).xlsx"
)
MY009_PROTOCOL = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY009治疗UC/方案及配套资料/3.0/"
    "MY009-UC-Ⅱa期-临床研究方案-V3.0 20250926-clean (1).docx"
)


class MonitoringRawProjectIntakeTests(unittest.TestCase):
    @staticmethod
    def _principal() -> MonitoringAuthenticatedPrincipal:
        return MonitoringAuthenticatedPrincipal(
            principal_id="raw-intake-monitoring-test",
            tenant_id="tenant-kangzhe",
            roles=(MonitoringRole.MEDICAL_MANAGER,),
            project_scope=("proj_rux_03_002",),
            issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
            authenticated=True,
            authn_method="test-server-session",
            session_id="raw-intake-monitoring-test-session",
            directory_revision="raw-intake-monitoring-test-v1",
            verification_ref_sha256="d" * 64,
        )

    def test_ai_provider_configured_override_requires_boolean(self) -> None:
        with self.assertRaisesRegex(ValueError, "ai_provider_configured"):
            MonitoringRawProjectIntakeService(ai_provider_configured="false")  # type: ignore[arg-type]

    def test_ai_task_plan_requires_semantic_runtime_readiness(self) -> None:
        service = MonitoringRawProjectIntakeService()
        not_ready = {
            "configured": True,
            "semantic_ai_tasks_enabled": False,
            "codex_runtime_dependency": False,
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "transport": "openai_compatible",
            "deployment_profile": "disabled",
            "deployment_profile_approved": False,
            "route_validation_errors": [],
            "missing_env": ["WORKBENCH_AI_DEPLOYMENT_PROFILE"],
        }
        ready = {**not_ready, "semantic_ai_tasks_enabled": True}

        blocked_plan = service._ai_task_plan(not_ready)
        ready_plan = service._ai_task_plan(ready)

        self.assertTrue(all(item.status == "blocked_external_ai_not_ready" for item in blocked_plan))
        self.assertTrue(all(item.status == "ready_external_ai_configured" for item in ready_plan))

    def test_unknown_sheet_names_use_header_shape_and_ambiguous_shapes_stay_unclassified(self) -> None:
        service = MonitoringRawProjectIntakeService(ai_provider_configured=False)
        groups, unclassified = service._domain_groups(
            [
                SimpleNamespace(
                    sheet_name="TABLE_ALPHA",
                    rows=[
                        {"SUBJID": "S001", "AETERM": "headache", "AESTDTC": "2026-01-01"}
                    ],
                ),
                SimpleNamespace(
                    sheet_name="TABLE_BETA",
                    rows=[
                        {"SUBJID": "S001", "CMTRT": "paracetamol", "CMSTDTC": "2026-01-01"}
                    ],
                ),
                SimpleNamespace(
                    sheet_name="TABLE_GAMMA",
                    rows=[
                        {"SUBJID": "S001", "EXTRT": "study drug", "EXDOSE": "10 mg"}
                    ],
                ),
                SimpleNamespace(
                    sheet_name="TABLE_AMBIGUOUS",
                    rows=[
                        {
                            "SUBJID": "S001",
                            "AETERM": "headache",
                            "AESTDTC": "2026-01-01",
                            "MHTERM": "migraine",
                            "MHSTDTC": "2025-01-01",
                        }
                    ],
                ),
                SimpleNamespace(
                    sheet_name="TABLE_UNKNOWN",
                    rows=[{"SUBJID": "S001", "FIELD_A": "value"}],
                ),
            ]
        )

        assert set(groups) == {"adverse_event", "concomitant_medication", "study_drug_change"}
        assert groups["adverse_event"].sheet_names == ["TABLE_ALPHA"]
        assert groups["concomitant_medication"].sheet_names == ["TABLE_BETA"]
        assert groups["study_drug_change"].sheet_names == ["TABLE_GAMMA"]
        assert unclassified == ["TABLE_AMBIGUOUS", "TABLE_UNKNOWN"]

    def test_raw_intake_cache_rotates_when_semantic_readiness_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            listing = root / "listing.xlsx"
            protocol = root / "protocol.docx"
            listing.write_bytes(b"synthetic listing")
            protocol.write_bytes(b"synthetic protocol")
            fake_sheets = [
                SimpleNamespace(
                    sheet_name="AE",
                    rows=[{"SUBJID": "S001", "SITEID": "01", "DOMAIN": "AE"}],
                )
            ]
            fake_document = SimpleNamespace(
                filename="protocol.docx",
                title="Synthetic Protocol",
                paragraphs=[object()],
                tables=[],
                spans=[object()],
            )
            config = MonitoringRawProjectConfig(
                project_id="synthetic_monitoring_raw",
                project_label="Synthetic",
                listing_path=listing,
                protocol_path=protocol,
                allowed_roots=[root],
            )
            base_status = {
                "configured": True,
                "semantic_ai_tasks_enabled": False,
                "codex_runtime_dependency": False,
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
                "transport": "openai_compatible",
                "deployment_profile": "disabled",
                "deployment_profile_approved": False,
                "route_validation_errors": [],
                "missing_env": ["WORKBENCH_AI_DEPLOYMENT_PROFILE"],
            }
            ready_status = {**base_status, "semantic_ai_tasks_enabled": True}
            service = MonitoringRawProjectIntakeService()
            with patch(
                "services.api.app.monitoring_raw_intake.parse_listing_file",
                return_value=fake_sheets,
            ) as parse_listing, patch(
                "services.api.app.monitoring_raw_intake.parse_protocol_docx",
                return_value=fake_document,
            ) as parse_protocol, patch(
                "services.api.app.monitoring_raw_intake.ai_gateway_status_from_env",
                side_effect=[base_status, ready_status],
            ):
                blocked = service.discover_project(config)
                ready = service.discover_project(config)

            self.assertIsNot(blocked, ready)
            self.assertTrue(
                all(item.status == "blocked_external_ai_not_ready" for item in blocked.ai_task_plan)
            )
            self.assertTrue(
                all(item.status == "ready_external_ai_configured" for item in ready.ai_task_plan)
            )
            self.assertEqual(2, parse_listing.call_count)
            self.assertEqual(2, parse_protocol.call_count)

    @unittest.skipUnless(RUX_LISTING.exists() and RUX_PROTOCOL.exists(), "RUX raw monitoring sources unavailable")
    def test_rux_monitoring_raw_intake_discovers_listing_protocol_and_task_plan(self) -> None:
        service = MonitoringRawProjectIntakeService(ai_provider_configured=False)

        snapshot = service.discover_project(
            MonitoringRawProjectConfig(
                project_id="rux_03_002_monitoring_raw",
                project_label="RUX-03-002 AD",
                listing_path=RUX_LISTING,
                protocol_path=RUX_PROTOCOL,
            )
        )

        self.assertEqual("source_registry/raw_monitoring_source", snapshot.source_system)
        self.assertEqual(54, snapshot.listing.sheet_count)
        self.assertGreaterEqual(snapshot.listing.row_count, 180000)
        self.assertEqual(241, snapshot.listing.subject_count)
        self.assertGreaterEqual(snapshot.protocol.paragraph_count, 1000)
        self.assertIn("SUBJID", snapshot.listing.subject_id_fields)

        domains = snapshot.domain_groups
        self.assertIn("adverse_event", domains)
        self.assertIn("medical_history", domains)
        self.assertIn("lab", domains)
        self.assertIn("concomitant_medication", domains)
        self.assertIn("study_drug_change", domains)
        self.assertIn("CM--既往及合并用药治疗", domains["concomitant_medication"].sheet_names)
        self.assertTrue(
            {"ECB--研究药物给药-医嘱用药", "ECA--研究药物给药-实际用药"}.intersection(
                set(domains["study_drug_change"].sheet_names)
            )
        )
        self.assertFalse(set(domains["concomitant_medication"].sheet_names).intersection(domains["study_drug_change"].sheet_names))

        task_types = {task.task_type for task in snapshot.ai_task_plan}
        self.assertIn("listing_semantic_mapping", task_types)
        self.assertIn("protocol_rule_extraction", task_types)
        self.assertIn("monitoring_risk_interpretation", task_types)
        self.assertIn("subject_timeline_derivation", task_types)
        self.assertIn("patient_profile_derivation", task_types)
        self.assertTrue(all(task.status == "blocked_external_ai_not_ready" for task in snapshot.ai_task_plan))

        public_payload = json.dumps(snapshot.public_dict(), ensure_ascii=False)
        for forbidden in ("/Users/", "content_hash", "preview_hash", "storage_key", "server_path", "source_path"):
            self.assertNotIn(forbidden, public_payload)

    @unittest.skipUnless(MY009_LISTING.exists() and MY009_PROTOCOL.exists(), "MY009 raw monitoring sources unavailable")
    def test_my009_monitoring_raw_intake_generalizes_beyond_rux_sheet_names(self) -> None:
        service = MonitoringRawProjectIntakeService(ai_provider_configured=False)

        snapshot = service.discover_project(
            MonitoringRawProjectConfig(
                project_id="my009_uc_monitoring_raw",
                project_label="MY009 UC",
                listing_path=MY009_LISTING,
                protocol_path=MY009_PROTOCOL,
            )
        )

        self.assertEqual("source_registry/raw_monitoring_source", snapshot.source_system)
        self.assertEqual(62, snapshot.listing.sheet_count)
        self.assertGreaterEqual(snapshot.listing.row_count, 4000)
        self.assertGreaterEqual(snapshot.listing.subject_count, 20)
        self.assertIn("USUBJID", snapshot.listing.subject_id_fields)
        self.assertGreaterEqual(snapshot.protocol.paragraph_count, 1000)

        domains = snapshot.domain_groups
        self.assertIn("adverse_event", domains)
        self.assertIn("concomitant_medication", domains)
        self.assertIn("study_drug_change", domains)
        self.assertIn("efficacy", domains)
        self.assertIn("AE", domains["adverse_event"].sheet_names)
        self.assertIn("CM", domains["concomitant_medication"].sheet_names)
        self.assertTrue({"QS", "QS1", "QS2", "QS3"}.issubset(set(domains["efficacy"].sheet_names)))
        self.assertTrue({"DA", "EX"}.intersection(set(domains["study_drug_change"].sheet_names)))
        self.assertFalse(set(domains["concomitant_medication"].sheet_names).intersection(domains["study_drug_change"].sheet_names))

        public_payload = json.dumps(snapshot.public_dict(), ensure_ascii=False)
        self.assertNotIn("/Users/", public_payload)
        self.assertNotIn("RUX-LAB-ALT-AST-GT3ULN-INTERRUPT", public_payload)

    @unittest.skipUnless(
        TestClient is not None and RUX_LISTING.exists() and RUX_PROTOCOL.exists(),
        "FastAPI or RUX raw monitoring sources unavailable",
    )
    def test_monitoring_raw_intake_api_exposes_rux_snapshot_without_path_leak(self) -> None:
        from services.api.app.main import app

        client = TestClient(app)
        with patch(
            "services.api.app.main.resolve_monitoring_principal_from_request",
            return_value=self._principal(),
        ):
            response = client.get("/api/projects/proj_rux_03_002/monitoring/raw-intake")

        self.assertEqual(200, response.status_code, response.text)
        payload = response.json()
        self.assertEqual("source_registry/raw_monitoring_source", payload["source_system"])
        self.assertEqual(54, payload["listing"]["sheet_count"])
        self.assertEqual(241, payload["listing"]["subject_count"])
        self.assertIn("study_drug_change", payload["domain_groups"])
        self.assertIn("concomitant_medication", payload["domain_groups"])
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn("content_hash", serialized)

    def test_raw_intake_reuses_snapshot_when_source_files_are_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            listing = Path(tmp) / "listing.xlsx"
            protocol = Path(tmp) / "protocol.docx"
            listing.write_bytes(b"synthetic listing")
            protocol.write_bytes(b"synthetic protocol")
            fake_sheets = [
                SimpleNamespace(
                    sheet_name="AE",
                    rows=[
                        {"SUBJID": "S001", "SITEID": "01", "DOMAIN": "AE"},
                        {"SUBJID": "S002", "SITEID": "01", "DOMAIN": "AE"},
                    ],
                )
            ]
            fake_document = SimpleNamespace(
                filename="protocol.docx",
                title="Synthetic Protocol",
                paragraphs=[object(), object()],
                tables=[],
                spans=[object(), object()],
            )
            service = MonitoringRawProjectIntakeService(ai_provider_configured=False)
            config = MonitoringRawProjectConfig(
                project_id="synthetic_monitoring_raw",
                project_label="Synthetic",
                listing_path=listing,
                protocol_path=protocol,
                allowed_roots=[tmp],
            )

            with patch("services.api.app.monitoring_raw_intake.parse_listing_file", return_value=fake_sheets) as parse_listing, patch(
                "services.api.app.monitoring_raw_intake.parse_protocol_docx", return_value=fake_document
            ) as parse_protocol:
                first = service.discover_project(config)
                second = service.discover_project(config)

            self.assertEqual(first.public_dict(), second.public_dict())
            self.assertEqual(1, parse_listing.call_count)
            self.assertEqual(1, parse_protocol.call_count)

    def test_raw_intake_single_flies_concurrent_requests_for_same_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            listing = Path(tmp) / "listing.xlsx"
            protocol = Path(tmp) / "protocol.docx"
            listing.write_bytes(b"synthetic listing")
            protocol.write_bytes(b"synthetic protocol")
            fake_sheets = [
                SimpleNamespace(
                    sheet_name="AE",
                    rows=[{"SUBJID": "S001", "SITEID": "01", "DOMAIN": "AE"}],
                )
            ]
            fake_document = SimpleNamespace(
                filename="protocol.docx",
                title="Synthetic Protocol",
                paragraphs=[object()],
                tables=[],
                spans=[object()],
            )
            service = MonitoringRawProjectIntakeService(
                ai_provider_configured=False
            )
            config = MonitoringRawProjectConfig(
                project_id="synthetic_monitoring_raw",
                listing_path=listing,
                protocol_path=protocol,
                allowed_roots=[tmp],
            )
            parse_entered = Event()
            release_parse = Event()
            second_started = Event()

            def delayed_listing_parse(*_args):
                parse_entered.set()
                self.assertTrue(release_parse.wait(timeout=5))
                return fake_sheets

            def second_request():
                second_started.set()
                return service.discover_project(config)

            with patch(
                "services.api.app.monitoring_raw_intake.parse_listing_file",
                side_effect=delayed_listing_parse,
            ) as parse_listing, patch(
                "services.api.app.monitoring_raw_intake.parse_protocol_docx",
                return_value=fake_document,
            ) as parse_protocol, ThreadPoolExecutor(max_workers=2) as executor:
                first_future = executor.submit(service.discover_project, config)
                self.assertTrue(parse_entered.wait(timeout=5))
                second_future = executor.submit(second_request)
                self.assertTrue(second_started.wait(timeout=5))
                release_parse.set()
                first = first_future.result(timeout=5)
                second = second_future.result(timeout=5)

            self.assertIs(first, second)
            self.assertEqual(1, parse_listing.call_count)
            self.assertEqual(1, parse_protocol.call_count)


if __name__ == "__main__":
    unittest.main()
