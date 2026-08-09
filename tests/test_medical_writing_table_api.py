from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from services.api.app import main as app_main
from services.api.app.medical_writing_document import MedicalWritingDocumentService
from services.api.app.medical_writing_repository import MedicalWritingRuntimeRepository
from services.api.app.sqlite_runtime_store import SqliteRuntimeStore


class MedicalWritingTableApiTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.documents = MedicalWritingDocumentService()
        self.store = SqliteRuntimeStore(Path(self.tmpdir.name) / "runtime.sqlite3")
        self.repository = MedicalWritingRuntimeRepository(self.documents, self.store)
        self.repo_patch = patch(
            "services.api.app.main.medical_writing_runtime_repository",
            self.repository,
        )
        self.repo_patch.start()
        self.client = TestClient(app_main.app)

    def tearDown(self):
        self.repo_patch.stop()
        self.tmpdir.cleanup()

    def _real_table_target(self):
        project_id = "proj_rux_03_002"
        document = self.documents.document_session(project_id)
        for section in document.sections:
            loaded = self.documents.section(project_id, section.section_id)
            table = next(
                (
                    block
                    for block in loaded.content_blocks
                    if block.get("block_type") == "table"
                ),
                None,
            )
            if table is not None:
                return project_id, section, table
        self.fail("RUX source protocol has no table block")

    def test_real_table_get_batch_update_replay_stale_conflict_and_restart(self):
        project_id, section, table_block = self._real_table_target()
        route = (
            f"/api/projects/{project_id}/medical-writing/working-copies/"
            f"{section.section_id}/tables/{table_block['block_id']}"
        )
        initial = self.client.get(route)
        self.assertEqual(200, initial.status_code, initial.text)
        self.assertEqual(0, initial.json()["version"])
        visible_cell = next(
            cell
            for row in initial.json()["rows"]
            for cell in row["cells"]
            if not cell.get("semantic_value", {})
            .get("_medical_writing_table", {})
            .get("hidden")
        )
        payload = {
            "expected_working_copy_revision": 0,
            "expected_table_version": 0,
            "operations": [
                {
                    "op": "edit_cell",
                    "cell_id": visible_cell["cell_id"],
                    "text": "真实表格API修订内容",
                }
            ],
            "actor": "medical_manager_test",
            "idempotency_key": "table-api-rux-edit-001",
        }
        updated = self.client.post(f"{route}/batch-update", json=payload)
        self.assertEqual(200, updated.status_code, updated.text)
        self.assertEqual(1, updated.json()["working_copy"]["revision"])
        self.assertEqual(1, updated.json()["table"]["version"])

        replay = self.client.post(f"{route}/batch-update", json=payload)
        self.assertEqual(200, replay.status_code, replay.text)
        self.assertEqual(1, replay.json()["working_copy"]["revision"])

        stale = dict(payload)
        stale["idempotency_key"] = "table-api-rux-edit-002"
        stale_response = self.client.post(f"{route}/batch-update", json=stale)
        self.assertEqual(409, stale_response.status_code, stale_response.text)

        restarted = MedicalWritingRuntimeRepository(
            MedicalWritingDocumentService(),
            SqliteRuntimeStore(Path(self.tmpdir.name) / "runtime.sqlite3"),
        )
        recovered = restarted.working_copy(project_id, section.section_id)
        self.assertEqual(1, recovered.revision)
        recovered_table = next(
            block
            for block in recovered.content_blocks
            if block.get("block_id") == table_block["block_id"]
        )
        recovered_text = [
            cell.get("text")
            for row in recovered_table["rows"]
            for cell in row
            if cell.get("cell_id") == visible_cell["cell_id"]
        ]
        self.assertEqual(["真实表格API修订内容"], recovered_text)

    def test_template_duplicate_requires_explicit_confirmation_and_records_lineage(self):
        project_id = "proj_rux_03_002"
        document = self.documents.document_session(project_id)
        section = next(
            item
            for item in document.sections
            if not any(
                block.get("template_id") == "analysis_sets"
                for block in self.documents.section(project_id, item.section_id).content_blocks
            )
        )
        working_copy_route = (
            f"/api/projects/{project_id}/medical-writing/working-copies/"
            f"{section.section_id}"
        )
        initial = self.client.get(working_copy_route)
        self.assertEqual(200, initial.status_code, initial.text)
        saved = self.client.post(
            working_copy_route,
            json={
                "document_id": document.document_id,
                "expected_revision": 0,
                "content_blocks": initial.json()["content_blocks"],
                "actor": "medical_manager_test",
                "idempotency_key": "table-duplicate-precondition-save",
            },
        )
        self.assertEqual(200, saved.status_code, saved.text)
        instantiate_route = (
            f"{working_copy_route}/table-templates/analysis_sets/instantiate"
        )
        first = self.client.post(
            instantiate_route,
            params={
                "actor": "medical_manager_test",
                "idempotency_key": "table-analysis-sets-first-intent",
            },
        )
        self.assertEqual(200, first.status_code, first.text)

        silent_duplicate = self.client.post(
            instantiate_route,
            params={
                "actor": "medical_manager_test",
                "idempotency_key": "table-analysis-sets-second-intent",
            },
        )
        self.assertEqual(409, silent_duplicate.status_code, silent_duplicate.text)
        self.assertIn("same table template already exists", silent_duplicate.text)

        confirmed_duplicate = self.client.post(
            instantiate_route,
            params={
                "actor": "medical_manager_test",
                "idempotency_key": "table-analysis-sets-confirmed-second-intent",
                "allow_duplicate": True,
                "duplicate_reason": "同一章节需要分别呈现主要分析与补充分析定义",
            },
        )
        self.assertEqual(200, confirmed_duplicate.status_code, confirmed_duplicate.text)
        first_block = first.json()["table_block"]
        duplicate_block = confirmed_duplicate.json()["table_block"]
        self.assertNotEqual(first_block["block_id"], duplicate_block["block_id"])
        self.assertEqual(
            first_block["block_id"], duplicate_block["duplicate_of_block_id"]
        )
        self.assertEqual(
            "同一章节需要分别呈现主要分析与补充分析定义",
            duplicate_block["duplicate_reason"],
        )
        matching_blocks = [
            block
            for block in confirmed_duplicate.json()["working_copy"]["content_blocks"]
            if block.get("template_id") == "analysis_sets"
        ]
        self.assertEqual(2, len(matching_blocks))


if __name__ == "__main__":
    unittest.main()
