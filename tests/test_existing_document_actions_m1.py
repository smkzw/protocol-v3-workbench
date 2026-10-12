"""新纪元第6轮末修订（M1-1/NEW-40）：写作平台入口与例外块蒸发——渲染死角
修复（existingDocument 分支从纯声明面板改为有动作面板）。

现场（r6-07/08）：例外已记录（头部'例外允许写作'）+ existingDocument 真
（冻结 v11 的失败尝试已建文档会话）→ 三元链 existingDocument 分支渲染纯
声明面板（'返回编辑器完成重绑定'，无任何按钮）——'进入写作平台'按钮与
例外块同时蒸发，用户被闲在声明面板。

修后契约（反例先红）：
T1 existingDocument 分支必含可点动作'打开写作平台'（GET greenfield-document
   → onCreated 进入，与 createDocument 的幂等 GET 路径同构）；
T2 该分支显示动作结果反馈通道（失败人话，如'未找到已建立的写作文档'）；
T3 冻结原因可见：流水线非终态时分支内显示管线阶段提示（'投影待重算'
   一等公民化的可见面部分）。
"""
from __future__ import annotations

import unittest
from pathlib import Path

SETUP = (
    Path(__file__).resolve().parents[1]
    / "frontend/src/features/medical-writing"
    / "MedicalWritingAuthoringJourneySetup.jsx"
).read_text(encoding="utf-8")


class ExistingDocumentBranchActionTests(unittest.TestCase):
    def _branch(self) -> str:
        marker = ": existingDocument ? <div className=\"authoring-writing-entry\">"
        start = SETUP.index(marker)
        return SETUP[start:start + 3500]

    def test_existing_document_branch_has_open_platform_action(self) -> None:
        """T1：分支内必有'打开写作平台'可点动作（GET→onCreated 同构）。"""
        branch = self._branch()
        self.assertIn("打开写作平台", branch, "existingDocument 分支仍是纯声明面板")
        self.assertIn("openExistingDocumentSession", branch)

    def test_open_handler_uses_idempotent_get_and_oncreated(self) -> None:
        """T1b：处理器走幂等 GET greenfield-document→onCreated（不重复建稿）。"""
        self.assertIn("const openExistingDocumentSession = async", SETUP)
        handler_start = SETUP.index("const openExistingDocumentSession = async")
        handler = SETUP[handler_start:handler_start + 1600]
        self.assertIn("greenfield-document", handler)
        self.assertIn("onCreated(", handler)
        self.assertIn("未找到已建立的写作文档", handler)

    def test_frozen_pipeline_reason_visible_in_branch(self) -> None:
        """T3：流水线非终态时分支显示投影待重算提示（冻结原因可见）。"""
        branch = self._branch()
        self.assertIn("投影待重算", branch)


if __name__ == "__main__":
    unittest.main()
