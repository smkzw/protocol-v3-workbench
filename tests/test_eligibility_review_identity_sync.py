from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.api.app import eligibility
from services.api.app.eligibility_protocol_rules import (
    EligibilityProtocolProjectConfig,
    EligibilityProtocolRuleService,
)
from services.api.app.sqlite_runtime_store import SqliteRuntimeStore


REAL_CASES = (
    ("proj_d001", "SA07005", 36),
    ("proj_my009_uc", "S01009", 34),
)


class EligibilityReviewIdentitySyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_workflow = eligibility.review_workflow
        self._previous_protocol_rule_service = eligibility.protocol_rule_service
        configs_by_project = {
            config.project_id: config
            for config in eligibility.RAW_INTAKE_PROJECTS.values()
        }
        eligibility.protocol_rule_service = EligibilityProtocolRuleService(
            [
                EligibilityProtocolProjectConfig(
                    project_id=config.project_id,
                    aliases=tuple(
                        alias
                        for alias, candidate in eligibility.RAW_INTAKE_PROJECTS.items()
                        if candidate.project_id == config.project_id
                    ),
                    protocol_path=config.protocol_path,
                    source_entry=f"{config.project_id}_protocol",
                    source_version="test_source_manifest",
                )
                for config in configs_by_project.values()
            ]
        )

    def tearDown(self) -> None:
        eligibility.protocol_rule_service = self._previous_protocol_rule_service
        eligibility.review_workflow = self.previous_workflow

    def test_two_real_projects_sync_current_rule_and_source_identities(self):
        for project_id, subject_id, expected_criteria in REAL_CASES:
            config = eligibility.RAW_INTAKE_PROJECTS[project_id]
            if not Path(config.protocol_path).exists() or not Path(
                config.raw_subject_root
            ).exists():
                self.skipTest(f"real eligibility inputs unavailable: {project_id}")
            with self.subTest(project_id=project_id), tempfile.TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "runtime.sqlite3"
                store = SqliteRuntimeStore(db_path)
                eligibility.configure_eligibility_review_workflow(store)

                workflow, rule_set, subject = eligibility._sync_review_identity(
                    project_id, subject_id
                )

                self.assertIs(workflow.store, store)
                self.assertEqual(project_id, rule_set.project_id)
                self.assertEqual(project_id, subject.project_id)
                self.assertEqual(expected_criteria, len(store.eligibility_rule_revision_rows(project_id)))
                self.assertEqual(
                    {"inclusion", "exclusion"},
                    {
                        row["criterion_kind"]
                        for row in store.eligibility_rule_revision_rows(project_id)
                    },
                )

                with sqlite3.connect(db_path) as connection:
                    source_rows = connection.execute(
                        """
                        SELECT source_id, source_revision, subject_source_revision,
                               content_hash, is_current
                        FROM eligibility_source_revisions
                        WHERE project_id = ? AND subject_id = ?
                        ORDER BY source_id
                        """,
                        (project_id, subject_id),
                    ).fetchall()
                self.assertEqual(subject.file_count, len(source_rows))
                self.assertTrue(all(row[4] == 1 for row in source_rows))
                self.assertEqual(
                    {subject.subject_source_revision},
                    {row[2] for row in source_rows},
                )
                self.assertTrue(all(row[0].startswith("eligsrc_") for row in source_rows))
                self.assertTrue(all(row[1].startswith("eligsrcv_") for row in source_rows))
                self.assertTrue(all(len(row[3]) == 64 for row in source_rows))

    def test_route_aliases_persist_only_canonical_project_identity(self):
        config = eligibility.RAW_INTAKE_PROJECTS["d001_raw_intake"]
        if not Path(config.protocol_path).exists() or not Path(config.raw_subject_root).exists():
            self.skipTest("D001 real eligibility inputs unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.sqlite3"
            store = SqliteRuntimeStore(db_path)
            eligibility.configure_eligibility_review_workflow(store)
            eligibility._sync_review_identity("d001_raw_intake", "SA07005")

            with sqlite3.connect(db_path) as connection:
                projects = {
                    row[0]
                    for row in connection.execute(
                        "SELECT DISTINCT project_id FROM eligibility_rule_revisions"
                    )
                }
            self.assertEqual({"proj_d001"}, projects)


if __name__ == "__main__":
    unittest.main()
