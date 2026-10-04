"""R26 自检第4次（本轮）P1-4：修订输出校验过严——人群词一刀切拒稿。

现场（proj_user_97c9c19afb20 ⑦）：medical_writing_revision 3次尝试约
90分钟全部失败，error_summary 均为
"revision.proposal_text introduces population terms not present in
current-project sources: ['患者']"——被修订章节的既有文本与项目事实源
都没有任何人群称谓词（试验参与者/受试者/患者/健康志愿者），模型在正常
临床表述中写出『患者』即被拒，且重试无法自愈（语料准入链路被③阻断，
任何人群词都无法"补"进源文本）。

该检查的本意是术语一致性（源已选定称谓时不得擅自换用），不是禁止正常
医学措辞。修复契约（红先修后）：
- 源侧（被修订章节/事实源）存在既定人群称谓时，维持现状：proposal 换用
  或新增不同称谓仍然报错（术语漂移保护不变）；
- 源侧完全没有既定称谓时，不再因 proposal 使用人群称谓词而拒稿（无约定
  可漂移；其余守卫——受控标签/罗马数字层级/占位符——照常生效）。
"""

from __future__ import annotations

import unittest

from services.api.app.ai_task_runner import (
    validate_medical_writing_revision_semantics,
)

from tests.test_ai_task_runner import AiTaskRunnerTests


class PopulationTermGateTests(AiTaskRunnerTests):
    def _source(self, text_preview: str):
        return self.source.model_copy(
            update={
                "source_type": "protocol_docx_paragraph_selection",
                "text_preview": text_preview,
            }
        )

    def test_population_word_allowed_when_source_has_no_established_term(self):
        # 现场⑦反例：被修订章节没有任何人群称谓，修订稿写出『患者』。
        source = self._source(
            "研究药物为口服小分子制剂，每日一次给药，与食物同服。"
        )
        output = {
            "revision": {
                "proposal_text": "研究药物为口服小分子制剂，患者每日一次"
                "给药，与食物同服。",
                "alternatives": [],
            }
        }

        errors = validate_medical_writing_revision_semantics(output, [source])

        self.assertEqual(
            [],
            [error for error in errors if "population terms" in error],
            "源文本没有既定人群称谓时，使用『患者』等普通人群称谓不属于"
            "术语漂移，不得据此拒稿（现场3次重试全部失败的根因）。",
        )
        self.assertEqual([], errors)

    def test_term_switch_still_rejected_when_source_has_established_term(self):
        # 守卫：源已用『试验参与者』，修订改用『患者』仍必须报错。
        source = self._source(
            "纳入中重度活动性类风湿关节炎成人试验参与者，接受研究药物"
            "皮下注射。"
        )
        output = {
            "revision": {
                "proposal_text": "纳入中重度活动性类风湿关节炎成人患者，"
                "接受研究药物皮下注射。",
                "alternatives": [],
            }
        }

        errors = validate_medical_writing_revision_semantics(output, [source])

        self.assertTrue(
            any("introduces population terms" in error for error in errors)
        )
        self.assertTrue(
            any("omits controlled population terms" in error for error in errors)
        )

    def test_greenfield_blank_target_without_any_term_source_allows_wording(self):
        blank_target = self.source.model_copy(
            update={
                "source_type": "greenfield_working_copy_selection",
                "text_preview": "",
            }
        )
        fact_source = self.source.model_copy(
            update={
                "source_id": "framing_facts_001",
                "source_type": "study_framing_facts",
                "text_preview": "研究药物为口服制剂，适应症为慢性心力衰竭。",
            }
        )
        output = {
            "revision": {
                "proposal_text": "本研究针对慢性心力衰竭患者开展。",
                "alternatives": [],
            }
        }

        errors = validate_medical_writing_revision_semantics(
            output,
            [blank_target, fact_source],
        )

        self.assertEqual(
            [],
            [error for error in errors if "population terms" in error],
        )


if __name__ == "__main__":
    unittest.main()
