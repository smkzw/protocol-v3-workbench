"""新纪元第4轮修订·第一刀：_ordered_blocks 渲染序根因（反例先红）。

五轮不解的真根因（深度分析·第3轮，已实验证明）：骨架/SoA块创建时无
body_order（repository.py:276-281/407-412），而 document_exporter 的
_ordered_blocks 排序键把无 body_order 的块全局排尾
（key 第一分量 = _body_order(block) is None）——注入到中段节 6.3 的骨架
渲染序排在 14.4 附录之后。此前差异化/元数据/逐节 append 三轮修复全部被
渲染排序无声作废。

B案契约（红先修后，断言对象=渲染后位置）：
T1 中段缺口节（6.3）注入无 body_order 骨架后，_ordered_blocks 渲染序
   必须落在本节区间内（本节有序块之后、下一节首块之前）；
T2 14.4 附录不得含他节骨架文本（渲染序层面）；
T3 全序块（带 body_order）的既有全局顺序不回退——有序块仍按 body_order
   序渲染（既有导出契约不破）。
"""
from __future__ import annotations

import unittest

from packages.contracts.workbench_contracts import (
    ProtocolDocument,
    ProtocolSection,
)
from services.api.app.medical_writing_document_exporter import _ordered_blocks

_GAP_SKELETON = (
    "本『6.3 研究性干预管理』章节正文为参数化标准文本骨架，范围限本节"
    "（研究性干预管理）；待医学经理审核确认。"
)


def _document():
    return ProtocolDocument(
        document_id="doc_order",
        project_id="proj_order",
        protocol_id="CMS-ORDER",
        version="1.0",
        sections=[
            ProtocolSection(
                section_id="sec_6_2",
                document_id="doc_order",
                heading="6.2 研究性干预剂量和方案的依据",
                section_number="6.2",
                content_blocks=[
                    {"block_id": "h62", "block_type": "heading", "text": "6.2 依据", "body_order": 1},
                    {"block_id": "b62", "block_type": "paragraph", "text": "6.2正文", "body_order": 2},
                ],
            ),
            ProtocolSection(
                section_id="sec_6_3",
                document_id="doc_order",
                heading="6.3 研究性干预管理",
                section_number="6.3",
                content_blocks=[
                    {"block_id": "h63", "block_type": "heading", "text": "6.3 管理", "body_order": 11},
                    # 缺口注入的骨架块：无 body_order（现场形态）
                    {"block_id": "gap_63", "block_type": "paragraph", "text": _GAP_SKELETON},
                ],
            ),
            ProtocolSection(
                section_id="sec_6_4",
                document_id="doc_order",
                heading="6.4 研究性干预剂量调整",
                section_number="6.4",
                content_blocks=[
                    {"block_id": "h64", "block_type": "heading", "text": "6.4 剂量调整", "body_order": 21},
                    {"block_id": "b64", "block_type": "paragraph", "text": "6.4正文", "body_order": 22},
                ],
            ),
            ProtocolSection(
                section_id="sec_14_4",
                document_id="doc_order",
                heading="14.4 项目特异附录",
                section_number="14.4",
                content_blocks=[
                    {"block_id": "h144", "block_type": "heading", "text": "14.4 附录", "body_order": 31},
                    {"block_id": "b144", "block_type": "paragraph", "text": "附录正文", "body_order": 32},
                ],
            ),
        ],
    )


class OrderedBlocksRenderPositionTests(unittest.TestCase):
    def _rendered_texts(self, document):
        return [str(block.get("text") or "") for _, _, block in _ordered_blocks(document)]

    def test_skeleton_renders_inside_its_own_section_range(self) -> None:
        rendered = self._rendered_texts(_document())
        h62 = rendered.index("6.2 依据")
        h63 = rendered.index("6.3 管理")
        h64 = rendered.index("6.4 剂量调整")
        gap = next(i for i, text in enumerate(rendered) if "参数化标准文本骨架" in text)
        self.assertGreater(gap, h63, "骨架必须渲染在 6.3 标题之后")
        self.assertLess(gap, h64, "骨架必须渲染在 6.4 之前（当前缺陷：全局排尾）")

    def test_appendix_does_not_render_other_sections_skeleton(self) -> None:
        rendered = self._rendered_texts(_document())
        h144 = rendered.index("14.4 附录")
        tail = rendered[h144:]
        self.assertTrue(
            all("参数化标准文本骨架" not in text for text in tail),
            "14.4 附录之后不得渲染他节骨架（现场：全部骨架堆积附录之下）。",
        )

    def test_body_ordered_blocks_keep_global_sequence(self) -> None:
        rendered = self._rendered_texts(_document())
        b62 = rendered.index("6.2正文")
        b64 = rendered.index("6.4正文")
        b144 = rendered.index("附录正文")
        self.assertLess(b62, b64)
        self.assertLess(b64, b144)


if __name__ == "__main__":
    unittest.main()
