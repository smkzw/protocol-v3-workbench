from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_eligibility_six_subject_matrix import FIXED_COHORT, build_matrix
from services.api.app.eligibility import (
    RAW_INTAKE_PROJECTS,
    _review_source_rows,
    raw_intake_service,
)
from services.api.app.sqlite_runtime_store import SqliteRuntimeStore


class EligibilitySixSubjectMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        for project_id in FIXED_COHORT:
            config = RAW_INTAKE_PROJECTS[project_id]
            if not Path(config.protocol_path).exists() or not Path(
                config.raw_subject_root
            ).exists():
                self.skipTest(f"real eligibility inputs unavailable: {project_id}")

    def test_matrix_reconciles_file_page_and_logical_source_units(self) -> None:
        payload = build_matrix()
        rows = payload["subjects"]
        expected = {
            (project_id, subject_id)
            for project_id, subject_ids in FIXED_COHORT.items()
            for subject_id in subject_ids
        }
        self.assertEqual(
            expected,
            {(row["project_id"], row["subject_id"]) for row in rows},
        )
        self.assertEqual(6, payload["totals"]["subject_count"])
        self.assertTrue(
            all(
                row["physical_file_count"] == row["logical_source_count"]
                and row["pdf_page_count"] > 0
                and row["expected_processing_unit_count"]
                >= row["page_or_image_work_units"]
                and row["resolved_processing_unit_count"] == 0
                and row["ai_review_gate"].startswith("blocked_")
                for row in rows
            )
        )
        self.assertEqual(297, payload["totals"]["expected_processing_unit_count"])
        self.assertEqual(0, payload["totals"]["resolved_processing_unit_count"])
        self.assertEqual(
            "blocked_pending_safe_unpack",
            next(row for row in rows if row["subject_id"] == "SA07005")[
                "archive_gate"
            ],
        )
        serialized = json.dumps(payload, ensure_ascii=False)
        for forbidden in ("/Users/", "relative_path", "filename", "legacy_review_report"):
            self.assertNotIn(forbidden, serialized)

    def test_product_source_mapping_persists_all_units_and_ai_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SqliteRuntimeStore(Path(tmp) / "isolated-runtime.sqlite3")
            persisted_units = 0
            for project_id, subject_ids in FIXED_COHORT.items():
                config = RAW_INTAKE_PROJECTS[project_id]
                for subject_id in subject_ids:
                    manifest = raw_intake_service.subject_manifest(config, subject_id)
                    rows = _review_source_rows(manifest)
                    store.replace_eligibility_subject_sources(
                        project_id,
                        subject_id,
                        manifest.subject_source_revision,
                        rows,
                    )
                    persisted_units += sum(
                        int(row["expected_unit_count"]) for row in rows
                    )
                    self.assertEqual(
                        "not_started",
                        store.eligibility_ai_source_unit_contract_state(
                            project_id=project_id,
                            subject_id=subject_id,
                            subject_source_revision=manifest.subject_source_revision,
                        ),
                    )
            with store._connect() as connection:
                stored_units = connection.execute(
                    """
                    SELECT SUM(expected_unit_count)
                    FROM eligibility_source_revisions
                    WHERE tenant_id = 'kangzhe_local' AND is_current = 1
                    """
                ).fetchone()[0]
            self.assertEqual(297, persisted_units)
            self.assertEqual(297, stored_units)


if __name__ == "__main__":
    unittest.main()
