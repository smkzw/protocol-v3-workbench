"""R27 第5轮末修订 片A①（NEW-P0-23/P0-16复发加重）：建项ref守卫泄漏。

现场（R5-E 20分钟零反馈 + R3-D 84秒冻结 + R5-D 首击无响应，三案同根）：
App.jsx createNewProject 中 newProjectSubmitRef.current=true 在参数校验
之前置位，而校验失败的早退 return 不经过任何 finally——ref 永久卡 true，
此后一切有效提交在守卫行静默返回：无请求、无busy态、无报错、按钮文字
不变。触发链：空提交/Enter等价提交落在未填齐时刻→ref中毒→填齐后点击
静默（R3-D先空提交shots_w3/28→84秒；R5-E含一次Enter→20分钟）。
刷新重挂载=新ref=false才能建成（R5-D实测）。

修复契约（红先修后）：守卫置位必须在校验通过之后（早退路径不再碰
  ref），或函数体整体 try/finally 统一复位。源契约断言置位顺序。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "frontend/src/App.jsx").read_text(encoding="utf-8")


class RefGuardLeakTests(unittest.TestCase):
    def test_submit_ref_set_after_validation_early_returns(self):
        handler = re.search(
            r"const createNewProject = async \(event\) => \{[\s\S]*?\n  \};",
            SOURCE,
        )
        self.assertIsNotNone(handler, "createNewProject handler not found")
        body = handler.group(0)
        set_pos = body.find("newProjectSubmitRef.current = true")
        validation_return = body.find("请先补全标记为必填的项目信息")
        self.assertGreater(
            set_pos,
            validation_return,
            "守卫置位必须在校验早退之后——现场：空提交置位ref后早退不复位，"
            "此后一切有效提交静默返回（R5-E 20分钟零反馈的根因）。",
        )

    def test_every_early_return_path_is_before_ref_set_or_in_try(self):
        handler = re.search(
            r"const createNewProject = async \(event\) => \{[\s\S]*?\n  \};",
            SOURCE,
        )
        body = handler.group(0)
        set_pos = body.find("newProjectSubmitRef.current = true")
        # set 之后的裸 return（不在 try 内）= 泄漏路径
        after = body[set_pos:]
        try_pos = after.find("try {")
        bare_returns = [
            m.start()
            for m in re.finditer(r"\n      return;", after)
        ]
        for pos in bare_returns:
            self.assertLess(
                try_pos if try_pos >= 0 else len(after),
                pos,
                "set 之后的裸 return 必须位于 try 块内（finally 复位覆盖）。",
            )


if __name__ == "__main__":
    unittest.main()
