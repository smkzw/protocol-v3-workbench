"""R9（第8轮末修订动作2）：P0-18 样本量输入层门——终局根因为PICOS层
结构化输入无算术校验（八轮八件同病），从『双锁』简化为『一锁』。

红用例四组（ask原文指定）：
- GER601（proj_user_1dc601868b26 实查文本）：两组各45例共90例；按
  GERD-HRQL组间差6分、SD 12、α=0.05双侧、80%把握度 → 复算需63例/组
  （d=0.5，双侧80%）——不一致，完成第二步必须被阻断；
- f96adb842507：每组45例…差4.5%/SD 6.5% → 复算需33例/组——不一致；
- dad07744e604（RT2旧案）：40例/组…差25米/SD 45米 → 复算需51例/组
  ——不一致；
- 基准轮正向工艺（51/102/192，外部锚点比例+单侧α0.025）——比例型
  设计无SD/δ连续量，不得误拦（须通过）。

三层契约（红先修后）：
T1 输入校验器 sample_size_declaration_check：四组文本判定正确
   （不一致×3 + 正向通过）；自洽正例（63例/组与假设一致）放行；
T2 commit_stage（picos）不一致时拒绝并给出人话复算明细；
   允许保存草稿不受影响（校验只在完成第二步）；
T3 生成层护栏：不自洽节的声明数字不得照抄——改写为复算值并附
   复算注记；要素缺失时输出悬置块（含锁定条件）；
T4 导出门：统计章 sample_size 状态≠自洽计入缺口计数→草案-N。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from packages.contracts.workbench_contracts import (
    MedicalWritingAuthoringJourneyCommitRequest,
    MedicalWritingAuthoringJourneyCreateRequest,
)
from tests.test_medical_writing_authoring_journey import (
    _complete_framing,
    _complete_picos,
)

GER601_TEXT = "两组各45例共90例；按GERD-HRQL组间差6分、SD 12、α=0.05双侧、80%把握度探索性设定。"
F96ADB_TEXT = "每组45例；按组间差4.5%、SD 6.5%、双侧α=0.05、把握度80%设定。"
DAD0_TEXT = "40例/组；按组间差25米、SD 45米、双侧α=0.05、把握度80%估算。"
POSITIVE_TEXT = (
    "本研究按两比例之差的检验计算样本量：基于外部锚点预期应答率47.4%与"
    "对照22.5%，单侧α=0.025、把握度80%，需51例/组（两个队列共102例，"
    "考虑脱落扩展至192例）。"
)
CONSISTENT_TEXT = "按组间差6分、SD 12、双侧α=0.05、把握度80%，需63例/组。"


class DeclarationCheckTests(unittest.TestCase):
    def _check(self, text):
        from services.api.app.medical_writing_full_draft import (
            sample_size_declaration_check,
        )

        return sample_size_declaration_check(text)

    def test_ger601_declared_45_requires_63(self) -> None:
        check = self._check(GER601_TEXT)
        self.assertIsNotNone(check)
        self.assertEqual("不一致", check["status"])
        self.assertEqual(45, check["declared_per_group"])
        self.assertEqual(63, check["required_per_group"])
        self.assertIn("63", check["detail"])
        self.assertIn("45", check["detail"])

    def test_f96adb_declared_45_requires_33(self) -> None:
        check = self._check(F96ADB_TEXT)
        self.assertEqual("不一致", check["status"])
        self.assertEqual(45, check["declared_per_group"])
        self.assertEqual(33, check["required_per_group"])

    def test_dad0_declared_40_requires_51(self) -> None:
        check = self._check(DAD0_TEXT)
        self.assertEqual("不一致", check["status"])
        self.assertEqual(40, check["declared_per_group"])
        self.assertEqual(51, check["required_per_group"])

    def test_positive_proportion_craft_passes_without_false_block(self) -> None:
        check = self._check(POSITIVE_TEXT)
        self.assertNotEqual(
            "不一致", (check or {}).get("status"),
            "比例型设计（无连续SD/δ）不得被连续量公式误拦。",
        )

    def test_consistent_declaration_passes(self) -> None:
        check = self._check(CONSISTENT_TEXT)
        self.assertEqual("自洽", check["status"])
        self.assertEqual(63, check["required_per_group"])

    def test_plain_text_without_declaration_returns_none(self) -> None:
        self.assertIsNone(self._check("本研究为随机双盲安慰剂对照研究。"))


class CommitStageInputGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        from services.api.app.medical_writing_authoring_journey import (
            MedicalWritingAuthoringJourneyService,
        )

        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmp.name) / "journeys.sqlite3"
        )
        self.project_id = "proj_sample_size_gate_r9"
        framed = self.service.create(
            self.project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=_complete_framing(),
                actor="medical_manager_test",
                idempotency_key="create-ss-gate-r9",
            ),
        )
        self.base_revision = framed.revision

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _commit_picos(self, strategy: str, key: str):
        picos = _complete_picos()
        picos.sample_size_strategy = strategy
        return self.service.commit_stage(
            self.project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=self.base_revision,
                stage="picos",
                picos=picos,
                actor="medical_manager_test",
                idempotency_key=key,
            ),
        )

    def test_inconsistent_declaration_blocks_picos_commit(self) -> None:
        with self.assertRaises(ValueError) as refused:
            self._commit_picos(GER601_TEXT, "commit-ss-gate-bad-r9")
        message = str(refused.exception)
        self.assertIn("63例/组", message)
        self.assertIn("45例/组", message)
        self.assertIn("修正声明或调整假设", message)

    def test_consistent_declaration_commits(self) -> None:
        committed = self._commit_picos(CONSISTENT_TEXT, "commit-ss-gate-ok-r9")
        self.assertTrue(committed.picos_complete)

    def test_proportion_craft_commits(self) -> None:
        committed = self._commit_picos(POSITIVE_TEXT, "commit-ss-gate-prop-r9")
        self.assertTrue(committed.picos_complete)


class GenerationGuardTests(unittest.TestCase):
    def test_inconsistent_numbers_are_rewritten_with_footnote(self) -> None:
        from services.api.app.medical_writing_full_draft import (
            apply_sample_size_guard_to_section,
        )

        section = {
            "section_id": "sec_stat",
            "section_number": "9.1",
            "heading": "样本量",
            "proposal_text": (
                "9.1 样本量。" + GER601_TEXT + "考虑到脱落率15%，最终入组104例。"
            ),
        }
        apply_sample_size_guard_to_section(section)
        text = section["proposal_text"]
        self.assertNotIn("两组各45例", text, "不一致声明数字不得照抄进正文。")
        self.assertIn("两组各63例", text)
        self.assertIn("复算", text, "改写必须附复算注记（审计透明）。")
        self.assertEqual("不一致", section["sample_size_check"]["status"])

    def test_missing_elements_get_suspended_block(self) -> None:
        from services.api.app.medical_writing_full_draft import (
            apply_sample_size_guard_to_section,
        )

        section = {
            "section_id": "sec_stat",
            "section_number": "9.1",
            "heading": "样本量",
            "proposal_text": "9.1 样本量。计划每组30例，具体假设待统计确认。",
        }
        apply_sample_size_guard_to_section(section)
        text = section["proposal_text"]
        self.assertIn("样本量待确认", text, "要素缺失输出悬置块。")
        self.assertIn("锁定条件", text)

    def test_consistent_section_untouched(self) -> None:
        from services.api.app.medical_writing_full_draft import (
            apply_sample_size_guard_to_section,
        )

        original = "9.1 样本量。" + CONSISTENT_TEXT
        section = {
            "section_id": "sec_stat",
            "section_number": "9.1",
            "heading": "样本量",
            "proposal_text": original,
        }
        apply_sample_size_guard_to_section(section)
        self.assertEqual(original, section["proposal_text"])
        self.assertEqual("自洽", section["sample_size_check"]["status"])


class ExportGapGateTests(unittest.TestCase):
    def test_inconsistent_stat_section_counts_into_gap_and_draft_label(self) -> None:
        from services.api.app.main import _export_placeholder_report, _export_version_label
        from packages.contracts.workbench_contracts import (
            ProtocolDocument,
            ProtocolSection,
        )

        document = ProtocolDocument(
            document_id="doc_ss_gate",
            project_id="proj_ss_gate",
            protocol_id="CMS-SS-T",
            version="1.0",
            sections=[
                ProtocolSection(
                    section_id="sec_9",
                    document_id="doc_ss_gate",
                    heading="统计学",
                    section_number="9",
                    content_blocks=[
                        {
                            "block_id": "b9",
                            "block_type": "paragraph",
                            "text": GER601_TEXT,
                        }
                    ],
                )
            ],
        )
        report = _export_placeholder_report(document)
        self.assertGreaterEqual(int(report.get("gap_count") or 0), 1)
        self.assertTrue(
            any("样本量" in (item.get("reason") or "") + (item.get("section_heading") or "")
                for item in report.get("gap_sections") or []),
            "缺口清单必须点名样本量不自洽章节。",
        )
        label = _export_version_label(
            document,
            total_markers=int(report.get("total_count") or 0),
            mode="approved_final",
            gap_count=int(report.get("gap_count") or 0),
        )
        self.assertTrue(label.startswith("草案-"), f"得到 {label!r}")


if __name__ == "__main__":
    unittest.main()
