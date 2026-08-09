from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app.evidence_design_manifest import (  # noqa: E402
    CRSWNP_MASTER_ROOT,
    PNH_COMPETITOR_DB,
    EvidenceDesignManifestService,
    EvidenceDesignPackageConfig,
    EvidencePackageAdapterError,
    PnhSqliteEvidenceAdapter,
)
from services.api.app.main import app  # noqa: E402


@unittest.skipUnless(
    CRSWNP_MASTER_ROOT.exists() and PNH_COMPETITOR_DB.exists(),
    "real CRSwNP and PNH evidence sources are unavailable",
)
class EvidencePackageAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = EvidenceDesignManifestService()

    def test_project_package_catalogs_are_isolated_and_use_real_sources(self):
        crswnp = self.service.package_catalog("proj_mgk10_crswnp")
        pnh = self.service.package_catalog("proj_my008_pnh_3_01")

        self.assertEqual(["crswnp_competitive_evidence"], [item.package_id for item in crswnp.packages])
        self.assertEqual(["pnh_competitive_evidence"], [item.package_id for item in pnh.packages])
        self.assertEqual(26, pnh.packages[0].product_count)
        self.assertEqual(
            {"trial": 70, "publication": 41, "regulatory": 23},
            pnh.packages[0].candidate_count_by_type,
        )

        serialized = json.dumps(pnh.model_dump(mode="json"), ensure_ascii=False)
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn("CRSwNP", serialized)

    def test_pnh_candidates_are_paged_searchable_and_not_silently_truncated(self):
        first = self.service.candidate_page(
            "proj_my008_pnh_3_01",
            "pnh_competitive_evidence",
            candidate_type="all",
            page=1,
            page_size=20,
        )
        last = self.service.candidate_page(
            "proj_my008_pnh_3_01",
            "pnh_competitive_evidence",
            candidate_type="all",
            page=7,
            page_size=20,
        )

        self.assertEqual(134, first.total)
        self.assertEqual(20, len(first.items))
        self.assertTrue(first.has_next)
        self.assertEqual(14, len(last.items))
        self.assertFalse(last.has_next)
        self.assertEqual(134, len({item.evidence_id for page in range(1, 8) for item in self.service.candidate_page(
            "proj_my008_pnh_3_01",
            "pnh_competitive_evidence",
            candidate_type="all",
            page=page,
            page_size=20,
        ).items}))

        searched = self.service.candidate_page(
            "proj_my008_pnh_3_01",
            "pnh_competitive_evidence",
            candidate_type="all",
            search="ravulizumab",
            page=1,
            page_size=50,
        )
        self.assertGreater(searched.total, 0)
        self.assertTrue(all("ravulizumab" in item.search_text.lower() for item in searched.items))

    def test_candidate_ids_are_stable_across_service_rebuild_and_detail_is_source_bounded(self):
        first_service = EvidenceDesignManifestService()
        second_service = EvidenceDesignManifestService()
        first = first_service.candidate_page(
            "proj_my008_pnh_3_01",
            "pnh_competitive_evidence",
            candidate_type="trial",
            page=1,
            page_size=5,
        )
        second = second_service.candidate_page(
            "proj_my008_pnh_3_01",
            "pnh_competitive_evidence",
            candidate_type="trial",
            page=1,
            page_size=5,
        )

        self.assertEqual([item.evidence_id for item in first.items], [item.evidence_id for item in second.items])
        self.assertTrue(first.items[0].evidence_id.startswith("pnh_competitive_evidence:trial:"))

        detail = first_service.candidate_detail(
            "proj_my008_pnh_3_01",
            "pnh_competitive_evidence",
            first.items[0].evidence_id,
        )
        self.assertEqual(first.items[0].evidence_id, detail.evidence_id)
        self.assertEqual("proj_my008_pnh_3_01", detail.project_id)
        self.assertTrue(detail.source_refs)
        self.assertEqual("real_raw_source", detail.source_scope)
        self.assertNotIn("/Users/", json.dumps(detail.model_dump(mode="json"), ensure_ascii=False))

    def test_crswnp_candidate_pool_is_paged_from_real_master_tables(self):
        page = self.service.candidate_page(
            "proj_mgk10_crswnp",
            "crswnp_competitive_evidence",
            candidate_type="document",
            page=1,
            page_size=25,
        )

        self.assertEqual(75, page.total)
        self.assertEqual(25, len(page.items))
        self.assertTrue(page.has_next)
        self.assertTrue(all(item.evidence_type == "document" for item in page.items))

    def test_cross_project_package_access_fails_closed(self):
        with self.assertRaises(KeyError):
            self.service.candidate_page(
                "proj_mgk10_crswnp",
                "pnh_competitive_evidence",
                candidate_type="trial",
                page=1,
                page_size=20,
            )

        with self.assertRaises(KeyError):
            self.service.package_catalog("proj_unknown")

    def test_pnh_schema_drift_raises_public_diagnostic_without_partial_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "incomplete.sqlite3"
            with sqlite3.connect(db_path) as connection:
                connection.execute("CREATE TABLE trials (trial_uid TEXT, official_title TEXT)")
                connection.execute("CREATE TABLE publications (publication_id TEXT)")
                connection.execute("CREATE TABLE regulatory_status (regulatory_id TEXT)")

            config = EvidenceDesignPackageConfig(
                package_id="pnh_schema_drift",
                package_label="PNH schema drift test",
                indication="阵发性睡眠性血红蛋白尿",
                source_root=db_path.parent,
                master_root=db_path.parent,
                source_root_label="PNH schema drift fixture",
                package_role="adapter test",
                adapter_type="pnh_sqlite",
                sqlite_path=db_path,
            )
            adapter = PnhSqliteEvidenceAdapter(config)
            with self.assertRaises(EvidencePackageAdapterError) as raised:
                adapter.candidate_page(candidate_type="trial", page=1, page_size=20, search="")

            self.assertIn("PNH证据源结构不完整", str(raised.exception))
            self.assertNotIn(str(db_path), str(raised.exception))

    def test_api_exposes_pnh_package_page_and_detail_without_cross_project_fallback(self):
        client = TestClient(app)
        catalog = client.get("/api/projects/proj_my008_pnh_3_01/evidence-design/packages")
        self.assertEqual(200, catalog.status_code)
        self.assertEqual("pnh_competitive_evidence", catalog.json()["packages"][0]["package_id"])

        page = client.get(
            "/api/projects/proj_my008_pnh_3_01/evidence-design/packages/pnh_competitive_evidence/candidates",
            params={"candidate_type": "trial", "page": 1, "page_size": 5},
        )
        self.assertEqual(200, page.status_code)
        payload = page.json()
        self.assertEqual(70, payload["total"])
        evidence_id = payload["items"][0]["evidence_id"]

        detail = client.get(
            f"/api/projects/proj_my008_pnh_3_01/evidence-design/packages/pnh_competitive_evidence/candidates/{evidence_id}"
        )
        self.assertEqual(200, detail.status_code)
        self.assertEqual(evidence_id, detail.json()["evidence_id"])
        self.assertEqual("proj_my008_pnh_3_01", detail.json()["project_id"])

        mismatch = client.get(
            "/api/projects/proj_mgk10_crswnp/evidence-design/packages/pnh_competitive_evidence/candidates",
            params={"candidate_type": "trial"},
        )
        self.assertEqual(404, mismatch.status_code)


if __name__ == "__main__":
    unittest.main()
