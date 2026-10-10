"""新纪元第4轮修订·第五刀：溯源串引用格式化层（NEW-29 根因修，红先）。

现场（HA501 75/274行）：剂量出处行直出'剂量依据内部IB v3.1（§5.2 剂量
方案）'——内部锚点（§x.y）不可回验，医学总监判科学诚信红旗。根因=守卫
把录入原样上纸（full_draft.py f'（剂量出处：{source_text}）'），未经引用
格式化（20261001b 文献管理裁定未建）。

契约（红先修后）：
T1 format_provenance_reference：内部锚点串（含'§'或'内部IB'）→
   '数据来源：申办方内部资料（IB v3.1，<研究代号>）'式可回验引用——
   IB 版本号从原文提取；上纸文本不含裸'§'；
T2 完整原始锚点保留在结构化字段（dose_source/sample_size_provenance
   审阅面元数据），不丢失定位信息；
T3 已是规范引用（无内部锚点记号）的原样通过，不改写；
T4 样本量锚点同样过格式化层。
"""
from __future__ import annotations

import unittest


class ProvenanceFormatTests(unittest.TestCase):
    def test_internal_anchor_is_reformatted_to_verifiable_citation(self) -> None:
        from services.api.app.medical_writing_full_draft import (
            format_provenance_reference,
        )

        formatted = format_provenance_reference(
            "内部IB v3.1（§5.2 剂量方案）", study_code="KZ-HA501-201"
        )
        self.assertIn("数据来源：申办方内部资料", formatted)
        self.assertIn("IB v3.1", formatted)
        self.assertIn("KZ-HA501-201", formatted)
        self.assertNotIn("§", formatted)

    def test_section_anchor_without_ib_version_still_sanitized(self) -> None:
        from services.api.app.medical_writing_full_draft import (
            format_provenance_reference,
        )

        formatted = format_provenance_reference("IB§5.1", study_code="KZ-NC401-101")
        self.assertNotIn("§", formatted)
        self.assertIn("申办方内部资料", formatted)

    def test_clean_citation_passes_through(self) -> None:
        from services.api.app.medical_writing_full_draft import (
            format_provenance_reference,
        )

        clean = "IB v2.0（2026-03）给药章节"
        self.assertEqual(clean, format_provenance_reference(clean, study_code="KZ-X"))

    def test_dose_guard_writes_formatted_and_keeps_full_anchor(self) -> None:
        from services.api.app.medical_writing_full_draft import (
            apply_dose_presence_guard_to_section,
        )

        section = {
            "section_number": "6.2",
            "heading": "研究治疗与给药",
            "proposal_text": "KZ-HA501片50mg每日一次口服，连续给药12周。",
        }
        apply_dose_presence_guard_to_section(
            section, source="内部IB v3.1（§5.2 剂量方案）"
        )
        text = section["proposal_text"]
        self.assertIn("数据来源：申办方内部资料", text)
        self.assertNotIn("§", text)
        self.assertEqual(
            "内部IB v3.1（§5.2 剂量方案）", section.get("dose_source"),
            "完整原始锚点必须保留在审阅面元数据。",
        )

    def test_sample_size_anchor_also_formatted(self) -> None:
        from services.api.app.medical_writing_full_draft import (
            apply_sample_size_guard_to_section,
        )

        section = {
            "section_number": "9.1",
            "heading": "样本量",
            "proposal_text": "样本量按组间差6分、SD 12、双侧α=0.05、把握度80%计算，需每组63例。",
        }
        apply_sample_size_guard_to_section(
            section, anchor="内部IB v3.1（§5.1 样本量）"
        )
        text = section["proposal_text"]
        self.assertIn("数据来源：申办方内部资料", text)
        self.assertNotIn("§", text)


if __name__ == "__main__":
    unittest.main()
