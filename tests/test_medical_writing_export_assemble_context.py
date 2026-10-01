# -*- coding: utf-8 -*-
"""SMOKE-r1-3 ⑧（R27 收敛修订）反例：DOCX 导出在「组装章节」阶段必抛
NameError: name '_context' is not defined。

现场（r2/r3 两轮导出 job 错误原文逐字一致）：NEW-17 引入的导出占位符门在
_assemble_medical_writing_document_export 里引用了未定义的 _context——该
函数签名只有 verified，回调 lambda 又把自己的 context 参数弃用了。修后
契约：装配函数接收导出任务上下文，占位符门的 acknowledge_placeholders
从 context.payload 读取，整段装配不再抛 NameError。
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services.api.app import main as app_main


class _StubDocument(dict):
    pass


class ExportAssembleContextTests(unittest.TestCase):
    def _run(self, payload: dict) -> dict:
        verified = {"project_id": "proj_export_ctx", "mode": "draft_preview"}
        context = SimpleNamespace(payload=payload)
        document = _StubDocument(sections=[])
        gate_calls: list[dict] = []
        with patch.object(
            app_main.medical_writing_document_service, "source_mode",
            return_value="guided_greenfield",
        ), patch.object(
            app_main.medical_writing_runtime_repository,
            "assemble_document_for_export", return_value=document,
        ), patch.object(
            app_main, "_apply_export_text_quality_lint", return_value=[],
        ), patch.object(
            app_main, "_export_placeholder_report",
            return_value={"placeholders": []},
        ), patch.object(
            app_main, "_enforce_export_placeholder_gate",
            side_effect=lambda report, mode, acknowledge: gate_calls.append(
                {"mode": mode, "acknowledge": acknowledge}
            ),
        ):
            result = app_main._assemble_medical_writing_document_export(
                context, verified
            )
        self.assertEqual(1, len(gate_calls))
        self.assertEqual("draft_preview", gate_calls[0]["mode"])
        self.assertEqual(bool(payload.get("acknowledge_placeholders")),
                         gate_calls[0]["acknowledge"])
        return result

    def test_assemble_passes_context_payload_to_placeholder_gate(self):
        result = self._run({"acknowledge_placeholders": True})
        self.assertIn("document", result)
        self.assertIn("placeholder_report", result)

    def test_assemble_without_acknowledge_defaults_to_false(self):
        self._run({})
        # gate acknowledge=False（未确认占位符时不放行）——由 _run 内断言覆盖


if __name__ == "__main__":
    unittest.main()
