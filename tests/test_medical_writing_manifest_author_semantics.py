from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.contracts.workbench_contracts import ProtocolDocument, ProtocolSection  # noqa: E402
from services.api.app.medical_writing_manifest import MedicalWritingManifestService  # noqa: E402


class MedicalWritingManifestAuthorSemanticsTests(unittest.TestCase):
    def test_full_greenfield_manifest_serialization_has_no_retired_approval_language(self):
        document = ProtocolDocument(
            document_id="doc_author_semantics",
            project_id="proj_author_semantics",
            protocol_id="AUTHOR-001",
            version="V0.1",
            sections=[
                ProtocolSection(
                    section_id="section_design",
                    document_id="doc_author_semantics",
                    heading="研究设计",
                    ich_m11_anchor="study_design",
                    risk_count=1,
                    content_blocks=[
                        {
                            "block_id": "heading_design",
                            "block_type": "heading",
                            "text": "研究设计",
                            "source_locator": "greenfield:section_design:heading",
                        },
                        {
                            "block_id": "paragraph_design",
                            "block_type": "paragraph",
                            "text": "AI生成的研究设计候选正文。",
                            "source_locator": "greenfield:section_design:paragraph:1",
                        },
                        {
                            "block_id": "table_soa",
                            "block_type": "table",
                            "table_id": "table_soa",
                            "title": "研究流程表",
                            "source_locator": "greenfield:section_design:table:1",
                            "column_count": 2,
                            "rows": [[{"text": "访视"}, {"text": "操作"}]],
                        },
                    ],
                )
            ],
            quality_gates=[
                {
                    "gate_id": "source_gap",
                    "label": "来源补齐",
                    "status": "blocked",
                    "detail": "证据不足，生成受阻；需作者确认后再冻结当前版本。",
                }
            ],
        )
        manifest = MedicalWritingManifestService(packages=[]).build_greenfield_manifest(
            "proj_author_semantics",
            document,
            {"approval_blocker_count": 1},
            project_code="AUTHOR-001",
            indication="测试适应症",
        )
        serialized = json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False)

        for fragment in ("待医学批准", "经批准证据", "医学批准"):
            self.assertNotIn(fragment, serialized)
        self.assertIn("候选/待作者确认", serialized)
        self.assertIn("作者确认", serialized)
        self.assertIn("冻结当前版本", serialized)
        self.assertIn("证据不足", serialized)
        self.assertIn("生成受阻", serialized)


if __name__ == "__main__":
    unittest.main()
