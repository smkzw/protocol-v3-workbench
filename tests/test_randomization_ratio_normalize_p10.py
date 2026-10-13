"""NEW-37层位定案（新纪元第10轮）：随机化比回显层修复——PICOS 提交处
比例规范化。

定案（本会话 live 库只读查询）：'3:3:3' 唯一来源是用户 authored 文本——
proj_user_f601cf2900ea 等多个项目的 picos.sample_size_anchor /
sample_size_strategy 存值含 '（3:3:3随机…）'（生成指令 :1769 管不到
用户输入）。修法=镜像 fact_intake 枚举规范化模式：PICOS 提交处把等比
臂 'N:N:N'/'N:N' 规范化为 '1:1:1'/'1:1'（非等比保原样），导出兜底另批。

红测（先红后修）：
T1 等比臂规范化：'3:3:3随机' → '1:1:1随机'；'4:4:4' → '1:1:1'；
T2 非等比/日常数字比保原样：'2:1'、'1:1:2'、日期时间不受影响；
T3 commit_stage 层：sample_size_anchor 含 '3:3:3' 提交后持久化为 '1:1:1'。
"""
from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from packages.contracts.workbench_contracts import (
    MedicalWritingAuthoringJourneyCommitRequest,
    MedicalWritingAuthoringJourneyCreateRequest,
)
from tests.test_medical_writing_authoring_journey import (
    _complete_framing,
    _complete_picos,
)


def _normalize(text: str) -> str:
    from services.api.app.medical_writing_full_draft import (
        normalize_randomization_ratio_labels,
    )

    return normalize_randomization_ratio_labels(text)


class RatioNormalizationTests(unittest.TestCase):
    def test_equal_arms_normalized(self) -> None:
        self.assertIn("1:1:1随机", _normalize("按3:3:3随机分组"))
        self.assertIn("1:1:1", _normalize("（4:4:4）"))
        self.assertIn("1:1", _normalize("随机化比例为2:2"))

    def test_unequal_and_plain_text_untouched(self) -> None:
        self.assertEqual("按2:1随机分组", _normalize("按2:1随机分组"))
        self.assertEqual("按1:1:2随机分组", _normalize("按1:1:2随机分组"))
        self.assertEqual("无比例文本", _normalize("无比例文本"))

    def test_times_and_ids_not_touched(self) -> None:
        self.assertEqual("访视第12:30", _normalize("访视第12:30"))
        self.assertEqual("样本量每组40例", _normalize("样本量每组40例"))


class CommitStageNormalizationTests(unittest.TestCase):
    def test_commit_normalizes_anchor_and_strategy(self) -> None:
        """T3：提交后持久化值已是规范形态（3:3:3 → 1:1:1）。"""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        from services.api.app.medical_writing_authoring_journey import (
            MedicalWritingAuthoringJourneyService,
        )

        service = MedicalWritingAuthoringJourneyService(
            Path(tmp.name) / "journeys.sqlite3"
        )
        project_id = "proj_ratio_normalize_p10"
        framed = service.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=_complete_framing(),
                actor="medical_manager_test",
                idempotency_key="create-ratio-p10",
            ),
        )
        picos = _complete_picos()
        picos.sample_size_anchor = (
            "IIa探索性样本量：每组约40例、三组共120例（3:3:3随机至"
            "160mg BID/80mg BID/安慰剂）。"
        )
        picos.sample_size_strategy = "三组共120例（3:3:3随机），每组40例。"
        committed = service.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=framed.revision,
                stage="picos",
                picos=picos,
                actor="medical_manager_test",
                idempotency_key="commit-ratio-p10",
            ),
        )
        self.assertNotIn("3:3:3", committed.picos.sample_size_anchor)
        self.assertIn("1:1:1", committed.picos.sample_size_anchor)
        self.assertNotIn("3:3:3", committed.picos.sample_size_strategy)
        self.assertIn("1:1:1", committed.picos.sample_size_strategy)


if __name__ == "__main__":
    unittest.main()
