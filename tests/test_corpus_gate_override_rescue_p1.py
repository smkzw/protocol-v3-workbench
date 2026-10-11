"""新纪元第5轮末修订（P0-1/NEW-35）：例外放行门覆盖失效根治。

定案（P0-1③，本会话代码实证）：勾选框渲染源就是
journey.corpus_gate.missing_requirements（journey setup:2893 missing →
:4770 missing.map）——忠实度锚点进入 live 缺失集后**只要新载荷到达就有
勾选框**；缺陷在 422 路径不重拉载荷（快照 5 项 vs live 13 项 → ack(5)≠
live(N) → 422 恒拒，用户永远看不到新增项）。

修后契约（反例先红）：
T1 提交前 fresh-fetch——overrideCorpusGate 先 GET 最新 journey 并
   applyJourneyResponse（AGG-P0-03 保留存活勾选），ack 按 live 缺失集过滤；
T2 422 处置——错误消息命中 'must acknowledge every current missing
   requirement' 时自动重拉 journey + toast '准入条件已更新…请补勾后重试'
   （一轮内恢复可勾可过）；
T3 单一源渲染维持：勾选框遍历 missing_requirements（既有行为钉住防回退）。
"""
from __future__ import annotations

import unittest
from pathlib import Path

SETUP = (
    Path(__file__).resolve().parents[1]
    / "frontend/src/features/medical-writing"
    / "MedicalWritingAuthoringJourneySetup.jsx"
).read_text(encoding="utf-8")


class CorpusGateOverrideRescueTests(unittest.TestCase):
    def test_fresh_fetch_before_ack_built(self) -> None:
        """T1：构建 ack 前先 GET 最新 journey（快照集≠live集根治）。"""
        fn_start = SETUP.index("const overrideCorpusGate = async")
        fn_body = SETUP[fn_start:fn_start + 4200]
        self.assertIn(
            'fetch(`/api/projects/${requestProjectId}/medical-writing/authoring-journey`)',
            fn_body,
            "例外放行未先拉取最新 journey；ack 仍按陈旧快照构建。",
        )
        self.assertIn("applyJourneyResponse(latest", fn_body)

    def test_422_triggers_repull_and_update_toast(self) -> None:
        """T2：422 命中即自动重拉+点名新增项请补勾。"""
        self.assertIn("must acknowledge every current missing requirement", SETUP)
        self.assertIn("准入条件已更新", SETUP)
        self.assertIn("请补勾后重试", SETUP)

    def test_single_source_render_pinned(self) -> None:
        """T3：勾选框单一源渲染钉住（missing_requirements 直接遍历）。"""
        self.assertIn("const missing = journey?.corpus_gate?.missing_requirements || [];", SETUP)
        self.assertIn("missing.map((label) =>", SETUP)


if __name__ == "__main__":
    unittest.main()
