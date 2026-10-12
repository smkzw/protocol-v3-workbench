"""NEW-32/N8（新纪元第8轮·终轮）：docx 元数据时间真实持有者修正——
front_matter.protocol_date（exporter:138 字段定义、:2460 版本记录表同源），
第7轮误接 document.protocol_date（不存在）→ 回退固定时间戳，修复失效。

夹具规范（终轮系统性规则）：派生/守卫类测试禁用 SimpleNamespace 人造
属性，必须构造真实合同对象（本文件用导出器自有 _FrontMatterContext）——
夹具绿、真实对象红的教训（背景外查枚举夹具/本件）两案同源。

修后契约（反例先红）：
T1 真实 _FrontMatterContext(protocol_date='2026-10-08') → 派生 2026-10-08 UTC；
T2 protocol_date 空 → 回落固定 2000-01-01（确定性保底）；
T3 导出装配路径接线：_configure_core_properties 接收 front_matter 并用其
   protocol_date 派生（源级契约）。
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path


def _timestamp(front_matter):
    from services.api.app.medical_writing_document_exporter import (
        _document_core_timestamp,
    )

    return _document_core_timestamp(front_matter)


def _front_matter(protocol_date: str):
    from services.api.app.medical_writing_document_exporter import (
        _FrontMatterContext,
    )

    return _FrontMatterContext(
        block_ids=frozenset(),
        document_title="研究方案",
        study_phase="II期",
        investigational_product="试验药物",
        protocol_date=protocol_date,
        sponsor="申办方",
    )


class DocumentCoreTimestampTests(unittest.TestCase):
    def test_real_front_matter_date_derived(self) -> None:
        """T1：真实合同对象 protocol_date → 派生 core 时间。"""
        self.assertEqual(
            datetime(2026, 10, 8, tzinfo=timezone.utc),
            _timestamp(_front_matter("2026-10-08")),
        )
        self.assertEqual(
            datetime(2026, 10, 8, tzinfo=timezone.utc),
            _timestamp(_front_matter("2026年10月8日")),
        )

    def test_missing_date_falls_back_to_fixed(self) -> None:
        """T2：无方案日期 → 固定 2000-01-01 保底（字节确定）。"""
        from services.api.app.medical_writing_table_exporter import (
            _FIXED_CORE_TIMESTAMP as FIXED,
        )

        self.assertEqual(FIXED, _timestamp(_front_matter("")))

    def test_export_assembly_wires_front_matter_into_core_properties(self) -> None:
        """T3：装配路径把 front_matter 传入 core 属性配置（源级契约）。"""
        source = (
            Path(__file__).resolve().parents[1]
            / "services/api/app/medical_writing_document_exporter.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "_configure_core_properties(output, document, export_mode, approval_ref, front_matter=front_matter)",
            source,
        )
        self.assertIn("front_matter.protocol_date", source)


if __name__ == "__main__":
    unittest.main()
