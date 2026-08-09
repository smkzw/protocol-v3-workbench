from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app.evidence_design_manifest import CRSWNP_MASTER_ROOT, EvidenceDesignManifestService  # noqa: E402
from services.api.app.main import app  # noqa: E402


@unittest.skipUnless(CRSWNP_MASTER_ROOT.exists(), "CRSwNP evidence fixture path is unavailable")
class EvidenceDesignManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = EvidenceDesignManifestService().build_manifest("proj_mgk10_crswnp")

    def package(self):
        return self.manifest.packages[0]

    def test_crswnp_manifest_reads_real_master_database_counts(self):
        package = self.package()

        self.assertEqual("CRSwNP竞品证据与方案设计资料包", package.package_label)
        self.assertEqual(17, len(package.products))
        self.assertEqual(24, len(package.trial_designs))
        self.assertEqual(75, len(package.documents))
        self.assertEqual(28, len(package.efficacy_results))
        self.assertEqual(11, len(package.safety_results))
        self.assertEqual(5, len(package.picos_questions))
        self.assertGreaterEqual(package.document_count_by_type.get("Protocol", 0), 10)
        self.assertGreaterEqual(package.document_count_by_type.get("Publication", 0), 40)

    def test_quality_gates_preserve_source_boundary_and_field_alignment_warning(self):
        gates = {gate.gate_label: gate for gate in self.package().quality_gates}

        self.assertEqual("ok", gates["来源边界已锁定"].status)
        self.assertIn("既有深度报告/HTML只允许作QA参考", gates["来源边界已锁定"].detail)
        self.assertEqual("warning", gates["疗效结果字段语义需复核"].status)
        self.assertIn("暂不支持自动数值图、跨试验排名或优选判断", gates["疗效结果字段语义需复核"].detail)
        self.assertEqual("blocked", gates["PICOS输出需医学批准"].status)

    def test_picos_questions_are_design_prompts_not_approved_protocol_output(self):
        domains = {question.picos_domain for question in self.package().picos_questions}

        self.assertEqual({"P - 研究人群", "I - 干预措施", "C - 对照", "O - 终点", "S - 研究设计"}, domains)
        for question in self.package().picos_questions:
            self.assertIn("医学", question.required_user_decision)
            self.assertTrue(question.source_refs)
            self.assertNotIn("最终", question.question)
            self.assertNotIn("已批准", question.question)

    def test_endpoint_is_desensitized_and_does_not_expose_lifecycle_or_overclaim_terms(self):
        response = TestClient(app).get("/api/projects/proj_mgk10_crswnp/evidence-design/manifest")
        self.assertEqual(200, response.status_code)
        payload = response.json()
        serialized = json.dumps(payload, ensure_ascii=False)

        self.assertEqual("证据调研与方案设计", payload["module_label"])
        self.assertEqual(1, payload["package_count"])
        self.assertGreaterEqual(payload["total_products"], 15)
        self.assertGreaterEqual(payload["total_trials"], 20)
        self.assertGreaterEqual(payload["total_documents"], 70)
        for forbidden in [
            "/Users/",
            "第2环节",
            "第二环节",
            "阶段2",
            "Stage 2",
            "最终医学结论",
            "正式医学结论",
            "已批准方案",
            "方案定稿",
            "可直接提交监管",
            "可直接写入方案",
            "AI已确认",
            "竞品证明",
            "疗效最优",
            "首选方案",
            "监管认可",
        ]:
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
