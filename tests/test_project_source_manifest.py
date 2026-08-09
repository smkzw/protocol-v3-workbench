from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from packages.contracts.workbench_contracts import UserProjectCreateRequest
from services.api.app.project_source_manifest import (
    MEDICAL_MODULE_LABELS,
    ProjectSourceManifestService,
)
from services.api.app.user_project_store import UserProjectStore
from services.api.app.monitoring_identity_authorization import MonitoringRole
from services.api.app.monitoring_runtime_principal import MonitoringAuthenticatedPrincipal

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - minimal runtimes can skip route checks.
    TestClient = None


FORBIDDEN_PUBLIC_TOKENS = (
    "/Users/",
    "source_path",
    "server_path",
    "content_hash",
    "preview_hash",
    "storage_key",
    "internal_path",
)


class ProjectSourceManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ProjectSourceManifestService()

    def assert_public_payload_is_sanitized(self, payload: dict) -> None:
        serialized = json.dumps(payload, ensure_ascii=False)
        for token in FORBIDDEN_PUBLIC_TOKENS:
            self.assertNotIn(token, serialized)

    def test_manifest_covers_demo_and_three_real_project_families(self) -> None:
        manifests = {
            project_id: self.service.public_manifest(project_id)
            for project_id in (
                "proj_mgk10_sar_demo",
                "proj_rux_03_002",
                "d001_raw_intake",
                "my009_uc_monitoring_raw",
            )
        }

        self.assertEqual("MG-K10-SAR-DEMO", manifests["proj_mgk10_sar_demo"]["header_project"]["project_code"])
        self.assertEqual("RUX-03-002", manifests["proj_rux_03_002"]["header_project"]["project_code"])
        self.assertEqual("CMS-D001", manifests["d001_raw_intake"]["header_project"]["project_code"])
        self.assertEqual("MY009-UC", manifests["my009_uc_monitoring_raw"]["header_project"]["project_code"])

        for manifest in manifests.values():
            self.assert_public_payload_is_sanitized(manifest)
            labels = [module["label"] for module in manifest["modules"]]
            self.assertTrue(labels)
            for label in labels:
                self.assertNotIn("环节", label)
                self.assertNotIn("阶段", label)
                self.assertNotRegex(label, r"第[一二三四五六七八九十0-9]+")
            self.assertTrue(set(module["module"] for module in manifest["modules"]).issubset(MEDICAL_MODULE_LABELS))

    def test_rux_manifest_separates_cm_from_investigational_product_changes(self) -> None:
        manifest = self.service.public_manifest("proj_rux_03_002")

        roles = {source["source_role"]: source for source in manifest["sources"]}
        self.assertIn("monitoring_listing", roles)
        self.assertIn("monitoring_subject_report", roles)
        self.assertIn("protocol_docx", roles)
        self.assertIn("concomitant_medication_domain", roles)
        self.assertIn("study_drug_change_domain", roles)
        self.assertEqual("非试验用合并用药", roles["concomitant_medication_domain"]["boundary_label"])
        self.assertEqual("试验药物变更/剂量调整", roles["study_drug_change_domain"]["boundary_label"])
        self.assertNotEqual(
            roles["concomitant_medication_domain"]["source_id"],
            roles["study_drug_change_domain"]["source_id"],
        )

        monitoring = self.service.module_binding("proj_rux_03_002", "medical_monitoring")
        self.assertEqual("proj_rux_03_002", monitoring.route_project_id)
        self.assertIn("rux_listing_20250612", monitoring.primary_source_ids)
        self.assertEqual("RUX listing 2025-06-12", monitoring.public_dict()["display_batch"]["batch_label"])
        self.assertEqual("2025-06-12", monitoring.public_dict()["display_batch"]["extract_date"])

    def test_my008_pnh_3_02_is_source_only_and_does_not_activate_writing_routes(self) -> None:
        manifest = self.service.public_manifest("my008_pnh_3_02")

        self.assertEqual("proj_my008_pnh_3_02", manifest["project_id"])
        self.assertEqual("MY008211A-PNH-3-02", manifest["header_project"]["project_code"])
        self.assertEqual("V2.1", manifest["header_project"]["protocol_version"])
        self.assertEqual(
            {"dashboard", "medical_monitoring"},
            {module["module"] for module in manifest["modules"]},
        )
        monitoring = manifest["route_bindings"]["medical_monitoring"]
        self.assertEqual("source_manifest_only", monitoring["implementation_status"])
        self.assertEqual(
            ["my008_pnh_3_02_locked_dataset", "my008_pnh_3_02_protocol_v2_1"],
            monitoring["primary_source_ids"],
        )
        self.assertEqual(
            ["my008_pnh_3_02_tfl_delivery", "my008_pnh_3_02_csr"],
            monitoring["supplemental_source_ids"],
        )
        sources = {source["source_id"]: source for source in manifest["sources"]}
        self.assertEqual(
            {
                "my008_pnh_3_02_locked_dataset",
                "my008_pnh_3_02_protocol_v2_1",
                "my008_pnh_3_02_tfl_delivery",
                "my008_pnh_3_02_csr",
            },
            set(sources),
        )
        self.assertTrue(all(source["availability"] == "available" for source in sources.values()))
        self.assertEqual(
            "锁库后总量基线",
            sources["my008_pnh_3_02_locked_dataset"]["boundary_label"],
        )
        with self.assertRaises(KeyError):
            self.service.module_binding("proj_my008_pnh_3_02", "medical_writing")
        self.assert_public_payload_is_sanitized(manifest)

    def test_my008_pnh_3_01_registers_monitoring_sources_without_activation(self) -> None:
        manifest = self.service.public_manifest("my008_pnh_3_01")

        self.assertEqual("proj_my008_pnh_3_01", manifest["project_id"])
        monitoring = manifest["route_bindings"]["medical_monitoring"]
        self.assertEqual("source_manifest_only", monitoring["implementation_status"])
        self.assertEqual(
            ["my008_pnh_3_01_locked_dataset", "my008_pnh_protocol_v1_1"],
            monitoring["primary_source_ids"],
        )
        self.assertEqual(
            ["my008_pnh_tfl_delivery", "my008_pnh_csr"],
            monitoring["supplemental_source_ids"],
        )
        sources = {source["source_id"]: source for source in manifest["sources"]}
        self.assertEqual("锁库后总量基线", sources["my008_pnh_3_01_locked_dataset"]["boundary_label"])
        self.assertEqual("available", sources["my008_pnh_3_01_locked_dataset"]["availability"])
        self.assertEqual("available", sources["my008_pnh_protocol_v1_1"]["availability"])
        self.assert_public_payload_is_sanitized(manifest)

    def test_d001_manifest_uses_raw_intake_as_input_and_legacy_only_as_comparison(self) -> None:
        manifest = self.service.public_manifest("d001_raw_intake")
        roles = {source["source_role"]: source for source in manifest["sources"]}

        self.assertIn("eligibility_protocol_docx", roles)
        self.assertIn("eligibility_raw_subject_bundle", roles)
        self.assertIn("legacy_eligibility_adapter", roles)
        self.assertEqual("legacy_comparison", roles["legacy_eligibility_adapter"]["source_scope"])
        self.assertNotIn("legacy_eligibility_adapter", manifest["route_bindings"]["eligibility_review"]["primary_source_ids"])
        self.assertEqual("d001_raw_intake", manifest["route_bindings"]["eligibility_review"]["route_project_id"])
        self.assertEqual(
            "D001 全量入组资料",
            manifest["route_bindings"]["eligibility_review"]["display_batch"]["batch_label"],
        )

    def test_my009_aliases_route_to_same_canonical_project_without_d001_or_rux_leakage(self) -> None:
        by_monitoring_id = self.service.public_manifest("my009_uc_monitoring_raw")
        by_eligibility_id = self.service.public_manifest("my009_uc_raw_intake")

        self.assertEqual(by_monitoring_id["project_id"], by_eligibility_id["project_id"])
        self.assertEqual("proj_my009_uc", by_monitoring_id["project_id"])
        self.assertEqual("my009_uc_raw_intake", by_monitoring_id["route_bindings"]["eligibility_review"]["route_project_id"])
        self.assertEqual("my009_uc_monitoring_raw", by_monitoring_id["route_bindings"]["medical_monitoring"]["route_project_id"])
        self.assertEqual(
            "MY009 MM Listing 2026-04-08",
            by_monitoring_id["route_bindings"]["medical_monitoring"]["display_batch"]["batch_label"],
        )

        serialized = json.dumps(by_monitoring_id, ensure_ascii=False)
        self.assertNotIn("D001", serialized)
        self.assertNotIn("RUX-03-002 原始数据 listing 2025-06-12", serialized)
        self.assert_public_payload_is_sanitized(by_monitoring_id)

    def test_ra_greenfield_sandbox_has_no_prebuilt_protocol_or_cross_project_alias(self) -> None:
        manifest = self.service.public_manifest("proj_ra_greenfield_sandbox")

        self.assertEqual("greenfield_sandbox", manifest["source_mode"])
        self.assertEqual(["proj_ra_greenfield_sandbox"], manifest["aliases"])
        self.assertEqual([], manifest["sources"])
        self.assertEqual("类风湿关节炎", manifest["header_project"]["indication"])
        self.assertEqual("-", manifest["header_project"]["protocol_version"])
        self.assertEqual(
            "proj_ra_greenfield_sandbox",
            manifest["route_bindings"]["medical_writing"]["route_project_id"],
        )
        self.assertEqual(
            "greenfield_ready",
            manifest["route_bindings"]["medical_writing"]["implementation_status"],
        )
        self.assert_public_payload_is_sanitized(manifest)

    def test_reference_projects_are_listed_by_default(self) -> None:
        listed_ids = {
            project["project_id"] for project in self.service.list_public_projects()
        }

        self.assertEqual(set(self.service.canonical_project_ids()), listed_ids)

    def test_reference_projects_can_be_excluded_from_an_empty_user_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            user_store = UserProjectStore(Path(tmpdir) / "user_projects.sqlite3")
            service = ProjectSourceManifestService(
                user_project_store=user_store,
                include_reference_projects=False,
            )

            self.assertEqual([], service.list_public_projects())

    def test_user_projects_remain_listed_when_reference_projects_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            user_store = UserProjectStore(Path(tmpdir) / "user_projects.sqlite3")
            record = user_store.create(
                UserProjectCreateRequest(
                    project_code="CLEAN-E2E-001",
                    project_name="Clean E2E user project",
                    indication="类风湿关节炎",
                    product_name="TEST-001",
                    study_phase="II期",
                    protocol_id="CLEAN-E2E-001",
                    protocol_version="V0.1",
                    protocol_date="2026-07-27",
                    entry_mode="from_zero",
                    actor="clean_e2e_test",
                    idempotency_key="clean-e2e-user-project",
                )
            )
            service = ProjectSourceManifestService(
                user_project_store=user_store,
                include_reference_projects=False,
            )

            projects = service.list_public_projects()

            self.assertEqual(
                [record.project_id],
                [project["project_id"] for project in projects],
            )

    @unittest.skipUnless(TestClient is not None, "FastAPI test client is unavailable")
    def test_user_created_manifest_does_not_require_legacy_monitoring_principal(self) -> None:
        from services.api.app.main import app

        with tempfile.TemporaryDirectory() as tmpdir:
            user_store = UserProjectStore(Path(tmpdir) / "user_projects.sqlite3")
            record = user_store.create(
                UserProjectCreateRequest(
                    project_code="MANIFEST-E2E-001",
                    project_name="Manifest E2E user project",
                    indication="特应性皮炎",
                    product_name="TEST-MANIFEST-001",
                    study_phase="II期",
                    protocol_id="MANIFEST-E2E-001",
                    protocol_version="V0.1",
                    protocol_date="2026-08-04",
                    entry_mode="from_zero",
                    actor="manifest_e2e_test",
                    idempotency_key="manifest-e2e-user-project",
                )
            )
            isolated_service = ProjectSourceManifestService(
                user_project_store=user_store,
                include_reference_projects=False,
            )
            with patch(
                "services.api.app.main.project_source_manifest_service",
                isolated_service,
            ):
                response = TestClient(app).get(
                    f"/api/projects/{record.project_id}/source-manifest"
                )

            self.assertEqual(200, response.status_code, response.text)
            payload = response.json()
            self.assertEqual(record.project_id, payload["project_id"])
            self.assertIn("medical_writing", payload["route_bindings"])
            self.assertNotIn("medical_monitoring", payload["route_bindings"])

    def test_canonical_manifest_build_remains_available_when_references_are_excluded(self) -> None:
        service = ProjectSourceManifestService(include_reference_projects=False)

        manifest = service.build_manifest("proj_rux_03_002")

        self.assertEqual("proj_rux_03_002", manifest.project_id)
        self.assertEqual("RUX-03-002", manifest.header_project.project_code)

    def test_reference_project_environment_value_is_strict(self) -> None:
        parser = ProjectSourceManifestService.parse_include_reference_projects

        self.assertTrue(parser(None))
        self.assertTrue(parser(" TRUE "))
        self.assertFalse(parser("false"))
        with self.assertRaisesRegex(ValueError, "must be 'true' or 'false'"):
            parser("0")

    @unittest.skipUnless(TestClient is not None, "FastAPI test client is unavailable")
    def test_source_manifest_api_exposes_sanitized_payload_for_raw_project_aliases(self) -> None:
        from services.api.app.main import app

        principal = MonitoringAuthenticatedPrincipal(
            principal_id="source-manifest-test",
            tenant_id="tenant-kangzhe",
            roles=(MonitoringRole.MEDICAL_MANAGER,),
            project_scope=("proj_d001",),
            issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
            authenticated=True,
            authn_method="test-server-session",
            session_id="source-manifest-test-session",
            directory_revision="source-manifest-test-v1",
            verification_ref_sha256="6" * 64,
        )

        class _PrincipalMiddleware:
            def __init__(self, application, verified_principal):
                self.application = application
                self.verified_principal = verified_principal

            async def __call__(self, scope, receive, send):
                if scope["type"] == "http":
                    scope.setdefault("state", {})["monitoring_principal"] = self.verified_principal
                await self.application(scope, receive, send)

        client = TestClient(_PrincipalMiddleware(app, principal))
        response = client.get("/api/projects/d001_raw_intake/source-manifest")

        self.assertEqual(200, response.status_code, response.text)
        payload = response.json()
        self.assertEqual("CMS-D001", payload["header_project"]["project_code"])
        self.assertEqual("d001_raw_intake", payload["route_bindings"]["eligibility_review"]["route_project_id"])
        self.assert_public_payload_is_sanitized(payload)


if __name__ == "__main__":
    unittest.main()
