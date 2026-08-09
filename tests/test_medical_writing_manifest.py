from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app.main import app  # noqa: E402
from services.api.app.medical_writing_manifest import (  # noqa: E402
    D001_PROTOCOL_DOCX,
    MY008_PNH_3_01_PROTOCOL_DOCX,
    RUX_PROTOCOL_DOCX,
    MedicalWritingManifestService,
)


@unittest.skipUnless(
    RUX_PROTOCOL_DOCX.exists() and D001_PROTOCOL_DOCX.exists() and MY008_PNH_3_01_PROTOCOL_DOCX.exists(),
    "real protocol DOCX fixtures are unavailable",
)
class MedicalWritingManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        service = MedicalWritingManifestService()
        cls.manifests = [
            service.build_manifest("proj_rux_03_002"),
            service.build_manifest("proj_d001"),
            service.build_manifest("proj_my008_pnh_3_01"),
        ]
        cls.packages = [manifest.packages[0] for manifest in cls.manifests]

    def test_manifest_parses_real_protocol_docx_files(self):
        self.assertTrue(all(manifest.module_label == "医学写作" for manifest in self.manifests))
        self.assertTrue(all(manifest.package_count == 1 for manifest in self.manifests))
        self.assertGreaterEqual(sum(manifest.total_source_spans for manifest in self.manifests), 4500)
        self.assertGreaterEqual(sum(manifest.total_tables for manifest in self.manifests), 40)

        docs = [package.documents[0] for package in self.packages]
        by_protocol_id = {doc.protocol_identifier: doc for doc in docs}
        self.assertIn("RUX-03-002", by_protocol_id)
        self.assertIn("D001-02-002", by_protocol_id)
        self.assertIn("MY008211A-PNH-3-01", by_protocol_id)
        self.assertGreaterEqual(by_protocol_id["RUX-03-002"].paragraph_count, 1900)
        self.assertGreaterEqual(by_protocol_id["D001-02-002"].paragraph_count, 2700)
        self.assertGreaterEqual(by_protocol_id["MY008211A-PNH-3-01"].paragraph_count, 1700)
        self.assertEqual("正文已解析", by_protocol_id["RUX-03-002"].parser_status)
        self.assertEqual("正文已解析", by_protocol_id["D001-02-002"].parser_status)
        self.assertEqual("正文已解析", by_protocol_id["MY008211A-PNH-3-01"].parser_status)
        self.assertEqual("V1.1", by_protocol_id["MY008211A-PNH-3-01"].protocol_version)
        self.assertEqual("2025-01-07", by_protocol_id["MY008211A-PNH-3-01"].protocol_date)

    def test_manifest_exposes_conservative_sections_tables_and_quality_gates(self):
        for package in self.packages:
            self.assertTrue(package.sections)
            self.assertTrue(package.tables)
            self.assertTrue(any(section.requires_human_mapping for section in package.sections))
            self.assertTrue(any(table.role_hint == "研究流程/SoA候选" for table in package.tables))
            self.assertTrue(any(table.quality_notes for table in package.tables))
            gate_by_label = {gate.gate_label: gate for gate in package.quality_gates}
            self.assertEqual("ok", gate_by_label["来源绑定完整性"].status)
            self.assertIn(gate_by_label["AI修订线程已关闭"].status, {"blocked", "warning"})
            self.assertEqual("blocked", gate_by_label["导出元数据齐备"].status)
            self.assertEqual("ok", gate_by_label["禁用表述扫描通过"].status)

    def test_manifest_payload_has_no_local_path_lifecycle_or_overclaim(self):
        payload = {"manifests": [manifest.model_dump(mode="json") for manifest in self.manifests]}
        serialized = json.dumps(payload, ensure_ascii=False)
        forbidden = [
            "/Users/",
            "第8环节",
            "阶段8",
            "Stage 8",
            "AI 已完成正式方案",
            "自动定稿",
            "可直接提交监管",
            "正式方案已生成",
            "最终医学结论",
            "监管认可",
            "疗效最优",
            "首选方案",
            "竞品证明",
            "待医学批准",
            "经批准证据",
        ]
        for fragment in forbidden:
            self.assertNotIn(fragment, serialized)
        self.assertIn("候选/待作者确认", serialized)
        self.assertIn("不可生成正式导出包", serialized)
        self.assertIn("独立AI服务未配置", serialized)
        self.assertNotIn("codex_runtime_dependency=false", serialized)

    def test_manifest_endpoint_returns_same_scope(self):
        response = self.client.get("/api/projects/proj_rux_03_002/medical-writing/manifest")
        self.assertEqual(200, response.status_code, response.text)
        payload = response.json()
        self.assertEqual("医学写作", payload["module_label"])
        self.assertEqual(1, payload["package_count"])
        self.assertGreaterEqual(payload["total_source_spans"], 1800)
        self.assertFalse("/Users/" in json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
