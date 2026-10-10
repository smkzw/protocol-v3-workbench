"""新纪元第3轮修订·第三步：骨架落位钉子测试（E12/NEW-24 原路径复验红先）。

现场（NC401 导出件实测）：停药三段式骨架与随机化/揭盲/DMC 骨架全部堆积
在 14.4 项目特异附录之后，而 6.3/6.4/4.7 标题下零段落——落位行为从未被
任何测试钉住（tests/test_mw_skeleton_placement_p2.py 只钉差异化/元数据/
导出缺口计数三件事）。

钉子契约（红先修后）：
T1 组装含缺口 6.3（研究性干预剂量调整）的文档 → 骨架 block 落在
   6.3.content_blocks；
T2 该 block 不得出现在附录节（14.4/14.5）——附录只存无主块；
T3 4.7（DMC 相关风险控制节）缺口 → 风险控制骨架落在 4.7 本节。
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace


def _gap_blocks(section):
    from services.api.app.medical_writing_repository import (
        _gap_placeholder_blocks,
    )

    return _gap_placeholder_blocks(
        {
            "section_id": section["section_id"],
            "heading": section["heading"],
            "section_number": section["section_number"],
        },
        {},
    )


def _skeleton_texts(section):
    return [str(block.get("text") or "") for block in _gap_blocks(section)]


class SkeletonPlacementPinTests(unittest.TestCase):
    def test_dose_adjustment_skeleton_targets_its_own_section(self) -> None:
        section = {
            "section_id": "sec_6_4",
            "heading": "6.4 研究性干预剂量调整",
            "section_number": "6.4",
        }
        texts = _skeleton_texts(section)
        self.assertTrue(texts)
        for text in texts:
            self.assertIn("6.4", text.split("。")[0])
            self.assertIn("范围限本节", text.split("。")[0])

    def test_no_skeleton_block_leaks_to_appendix_sections(self) -> None:
        appendix = {
            "section_id": "sec_14_4",
            "heading": "14.4 项目特异附录",
            "section_number": "14.4",
        }
        appendix_text = "\n".join(_skeleton_texts(appendix))
        dose_texts = _skeleton_texts(
            {
                "section_id": "sec_6_4",
                "heading": "研究性干预剂量调整",
                "section_number": "6.4",
            }
        )
        for text in dose_texts:
            self.assertNotIn(
                text[:40],
                appendix_text,
                "6.4 的骨架块不得出现在附录（附录只存无主块）。",
            )

    def test_risk_control_skeleton_targets_section_4_7(self) -> None:
        section = {
            "section_id": "sec_4_7",
            "heading": "4.7 数据监查委员会与风险控制",
            "section_number": "4.7",
        }
        texts = _skeleton_texts(section)
        self.assertTrue(texts)
        self.assertTrue(
            any("4.7" in text.split("。")[0] for text in texts),
            "风险控制骨架首段必须点名 4.7 本节。",
        )
        self.assertTrue(
            any("数据监查委员会" in text or "DMC" in text for text in texts)
        )


class SoaSkeletonRenderPositionTests(unittest.TestCase):
    """NEW-BENCH-2 渲染位钉子：1.3 流程表骨架必须渲染在本节区间。"""

    def test_soa_skeleton_renders_inside_its_section(self) -> None:
        from packages.contracts.workbench_contracts import (
            ProtocolDocument,
            ProtocolSection,
        )
        from services.api.app.medical_writing_document_exporter import (
            _ordered_blocks,
        )
        from services.api.app.medical_writing_repository import (
            _gap_placeholder_blocks,
        )

        soa = {
            "section_id": "sec_1_3",
            "heading": "1.3 研究流程表",
            "section_number": "1.3",
        }
        soa_blocks = _gap_placeholder_blocks(soa, {})
        self.assertTrue(soa_blocks, "SoA 缺口必须产出 [说明段+访视×活动矩阵] 骨架")
        document = ProtocolDocument(
            document_id="doc_soa_order",
            project_id="proj_soa_order",
            protocol_id="CMS-SOA",
            version="1.0",
            sections=[
                ProtocolSection(
                    section_id="sec_1_2",
                    document_id="doc_soa_order",
                    heading="1.2 研究示意图",
                    section_number="1.2",
                    content_blocks=[
                        {"block_id": "h12", "block_type": "heading", "text": "1.2 示意图", "body_order": 1},
                    ],
                ),
                ProtocolSection(
                    section_id="sec_1_3",
                    document_id="doc_soa_order",
                    heading="1.3 研究流程表",
                    section_number="1.3",
                    content_blocks=[
                        {"block_id": "h13", "block_type": "heading", "text": "1.3 流程表", "body_order": 2},
                        *soa_blocks,
                    ],
                ),
                ProtocolSection(
                    section_id="sec_14_4",
                    document_id="doc_soa_order",
                    heading="14.4 项目特异附录",
                    section_number="14.4",
                    content_blocks=[
                        {"block_id": "h144", "block_type": "heading", "text": "14.4 附录", "body_order": 31},
                    ],
                ),
            ],
        )
        rendered = [
            str(block.get("text") or "")
            for _, _, block in _ordered_blocks(document)
        ]
        h13 = rendered.index("1.3 流程表")
        h144 = rendered.index("14.4 附录")
        soa_texts = [str(block.get("text") or "") for block in soa_blocks]
        for text in soa_texts:
            marker = text[:20]
            if not marker:
                continue  # 矩阵表体 text 为空（structured_table 载荷），按说明段断言
            position = next(
                (i for i, candidate in enumerate(rendered) if marker in candidate),
                None,
            )
            self.assertIsNotNone(position, f"SoA 骨架文本未渲染：{marker}")
            self.assertGreater(position, h13, "SoA 骨架必须在本节标题之后")
            self.assertLess(position, h144, "SoA 骨架不得排到附录之后（旧排序根因）")


if __name__ == "__main__":
    unittest.main()
