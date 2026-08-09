from __future__ import annotations

import tempfile
import unittest
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from packages.contracts.workbench_contracts import TflReviewAction, TflReviewRecord
from services.api.app.evidence_design_manifest import EvidenceDesignManifestService
from services.api.app.main import app
from services.api.app.medical_writing_manifest import MedicalWritingManifestService
from services.api.app.project_source_manifest import ProjectSourceManifestService
from services.api.app.safety_pv_manifest import SafetyPvManifestService
from services.api.app.tfl_manifest import TflManifestService
from services.api.app.tfl_review_workbench import TflReviewStore


class CanonicalProjectContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        cls.catalog = ProjectSourceManifestService()

    def test_catalog_lists_each_canonical_project_once(self) -> None:
        project_ids = self.catalog.canonical_project_ids()

        self.assertEqual(len(project_ids), len(set(project_ids)))
        self.assertEqual(
            {
                "proj_mgk10_sar_demo",
                "proj_mgk10_sar_real",
                "proj_mgk10_crswnp",
                "proj_rux_03_002",
                "proj_d001",
                "proj_my009_uc",
                "proj_my008_pnh_3_01",
                "proj_my008_pnh_3_02",
                "proj_ra_greenfield_sandbox",
            },
            set(project_ids),
        )

    def test_legacy_route_ids_resolve_to_canonical_project(self) -> None:
        aliases = {
            "d001_raw_intake": "proj_d001",
            "proj_d001_raw_intake": "proj_d001",
            "my009_uc": "proj_my009_uc",
            "my009_uc_raw_intake": "proj_my009_uc",
            "my009_uc_monitoring_raw": "proj_my009_uc",
            "rux_03_002_monitoring_raw": "proj_rux_03_002",
            "my008_pnh_3_01": "proj_my008_pnh_3_01",
            "my008_pnh_3_02": "proj_my008_pnh_3_02",
        }

        for alias, expected in aliases.items():
            with self.subTest(alias=alias):
                self.assertEqual(expected, self.catalog.canonical_project_id(alias))
                self.assertEqual(expected, self.catalog.build_manifest(alias).project_id)

    def test_projects_api_returns_canonical_contexts_without_alias_duplicates(self) -> None:
        response = self.client.get("/api/projects")

        self.assertEqual(200, response.status_code, response.text)
        projects = response.json()
        project_ids = [project["project_id"] for project in projects]
        canonical_ids = list(self.catalog.canonical_project_ids())
        self.assertEqual(canonical_ids, project_ids[: len(canonical_ids)])
        self.assertEqual(len(project_ids), len(set(project_ids)))
        self.assertNotIn("d001_raw_intake", project_ids)
        self.assertNotIn("my009_uc_monitoring_raw", project_ids)
        for project_id in project_ids[len(canonical_ids) :]:
            self.assertNotIn(project_id, canonical_ids)
        for project in projects:
            self.assertIn("modules", project)
            self.assertIn("source_mode", project)
            self.assertNotIn("/Users/", str(project))

    def test_module_manifests_are_project_scoped(self) -> None:
        rux_tfl = TflManifestService().build_manifest("proj_rux_03_002")
        my008_tfl = TflManifestService().build_manifest("proj_my008_pnh_3_01")
        rux_writing = MedicalWritingManifestService().build_manifest("proj_rux_03_002")
        d001_writing = MedicalWritingManifestService().build_manifest("proj_d001")
        rux_safety = SafetyPvManifestService().build_manifest("proj_rux_03_002")
        my009_safety = SafetyPvManifestService().build_manifest("proj_my009_uc")
        crswnp_evidence = EvidenceDesignManifestService().build_manifest("proj_mgk10_crswnp")

        self.assertEqual({"rux_03_002"}, {package.package_id for package in rux_tfl.packages})
        self.assertEqual({"my008_pnh_3_01"}, {package.package_id for package in my008_tfl.packages})
        self.assertEqual({"rux_03_002_protocol_writing"}, {package.package_id for package in rux_writing.packages})
        self.assertEqual({"cms_d001_protocol_writing"}, {package.package_id for package in d001_writing.packages})
        self.assertEqual({"rux_03_002_pv"}, {package.package_id for package in rux_safety.packages})
        self.assertEqual({"my009_uc_s1"}, {package.package_id for package in my009_safety.packages})
        self.assertEqual({"crswnp_competitive_evidence"}, {package.package_id for package in crswnp_evidence.packages})

    def test_unconfigured_module_fails_closed_instead_of_returning_another_project(self) -> None:
        response = self.client.get("/api/projects/proj_d001/tfl/manifest")

        self.assertEqual(404, response.status_code, response.text)
        self.assertIn("not configured", response.json()["detail"])

    def test_my008_pnh_3_02_does_not_fall_through_to_medical_writing_or_tfl(self) -> None:
        for route in (
            "/api/projects/proj_my008_pnh_3_02/medical-writing/manifest",
            "/api/projects/proj_my008_pnh_3_02/tfl/manifest",
        ):
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(404, response.status_code, response.text)
                self.assertIn("not configured", response.json()["detail"])

    def test_source_candidate_cannot_be_registered_to_another_project(self) -> None:
        response = self.client.post(
            "/api/projects/proj_my008_pnh_3_01/sources/local-candidate",
            params={"candidate_id": "tfl-rux-final-tfl", "module": "data_analysis_tfl"},
        )

        self.assertEqual(503, response.status_code, response.text)
        self.assertEqual(
            "monitoring_principal_unavailable",
            response.json()["detail"]["code"],
        )

    def test_public_module_manifests_exclude_internal_source_fields(self) -> None:
        routes = (
            "/api/projects/proj_rux_03_002/medical-writing/manifest",
            "/api/projects/proj_rux_03_002/tfl/manifest",
            "/api/projects/proj_my009_uc/safety-pv/manifest",
            "/api/projects/proj_mgk10_crswnp/evidence-design/manifest",
        )
        forbidden_fields = ("content_hash", "server_path", "storage_key", "source_record_id", "text_preview")

        for route in routes:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(200, response.status_code, response.text)
                serialized = json.dumps(response.json(), ensure_ascii=False)
                for forbidden_field in forbidden_fields:
                    self.assertNotIn(forbidden_field, serialized)

    def test_real_project_empty_monitoring_intake_never_uses_demo_payload(self) -> None:
        response = self.client.post(
            "/api/projects/proj_rux_03_002/monitoring/intake",
            json={
                "batch_label": "empty-real-project-canary",
                "extract_date": "2026-07-10",
                "uploaded_by": "medical_manager",
                "sheets": [],
            },
        )

        self.assertIn(response.status_code, (400, 404, 409, 422, 503), response.text)
        serialized = json.dumps(response.json(), ensure_ascii=False)
        for demo_subject in ("10008", "06021", "10021", "10045"):
            self.assertNotIn(demo_subject, serialized)

    def test_same_item_id_is_isolated_by_project_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = TflReviewStore(Path(temporary_directory) / "tfl_actions.jsonl")
            created_at = datetime.now(timezone.utc)
            for project_id, status in (("proj_rux_03_002", "医学已审阅"), ("proj_my008_pnh_3_01", "需统计复核")):
                store.append(
                    TflReviewRecord(
                        record_id=f"record_{project_id}",
                        project_id=project_id,
                        package_id="shared_package_id",
                        output_id="shared_output_id",
                        output_display_id="t-14-3-1",
                        action=TflReviewAction.MARK_REVIEWED,
                        actor="medical_manager",
                        previous_status="待医学审阅",
                        new_status=status,
                        comment="cross-project isolation canary",
                        created_at=created_at,
                    )
                )

            rux_records = store.records("proj_rux_03_002", "shared_package_id", "shared_output_id")
            my008_records = store.records("proj_my008_pnh_3_01", "shared_package_id", "shared_output_id")
            self.assertEqual(["医学已审阅"], [record.new_status for record in rux_records])
            self.assertEqual(["需统计复核"], [record.new_status for record in my008_records])


if __name__ == "__main__":
    unittest.main()
