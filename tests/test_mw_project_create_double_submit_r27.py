"""R27 第1轮末修订 NEW-P0-04：连点『创建并进入写作』生成两个复制项目。

现场（R1-D，MW-III-CE989C87 与 MW-III-5D6E4B88，user_projects 两行
created_at 仅差0.26秒）：
- 前端防护是异步 state（setNewProjectBusy(true) 重渲染前不生效），同帧
  双击两次进入 handler；
- 幂等键每次随机生成（create-project-${Date.now()}-${random}），双击=
  两个不同 key，后端 idempotency_key 去重永不命中；绿田项目编号自动
  随机，project_code 查重也绕过。

修复契约（红先修后）：
- ① 前端：弹窗打开时生成一次会话稳定幂等键（成功后才重置）；
- ② 前端：handler 入口同步 ref 守卫挡同帧双提交；
- ③ 后端 user_project_store.create：同一 actor 5秒内同名同适应症软查重
  ——命中即返回既有项目（幂等回放语义），不产生第二行。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from packages.contracts.workbench_contracts import UserProjectCreateRequest
from services.api.app.user_project_store import UserProjectStore

ROOT = Path(__file__).resolve().parents[1]


def _request(idempotency_key: str, **overrides) -> UserProjectCreateRequest:
    payload = {
        "project_code": "",
        "project_name": "双击验证-慢性咳嗽",
        "indication": "难治性慢性咳嗽",
        "product_name": "IMPL-DBL-01",
        "study_phase": "II期",
        "entry_mode": "from_zero",
        "actor": "medical_manager_test",
        "idempotency_key": idempotency_key,
    }
    payload.update(overrides)
    return UserProjectCreateRequest(**payload)


class DoubleSubmitSoftDedupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = UserProjectStore(Path(self.tmp.name) / "user_projects.sqlite3")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_same_actor_same_name_within_5s_creates_one_project(self):
        first = self.store.create(_request("dbl-key-1"))
        # 双击的第二发：不同幂等键（前端随机键生成竞态）+ 同名同适应症同 actor。
        second = self.store.create(_request("dbl-key-2"))

        self.assertEqual(first.project_id, second.project_id, (
            "同一操作者5秒内同名同适应症的第二次创建必须软查重命中既有"
            "项目（幂等回放），不得产生第二行（现场0.26秒双行实据）。"
        ))
        rows = list(self.store.records())
        same_name = [
            row for row in rows if row.project_name == "双击验证-慢性咳嗽"
        ]
        self.assertEqual(1, len(same_name))

    def test_different_projects_still_created_after_window_or_distinct_input(self):
        first = self.store.create(_request("dbl-key-3"))
        # 不同适应症 = 不同项目意图，必须正常创建。
        second = self.store.create(
            _request("dbl-key-4", indication="良性前列腺增生")
        )
        self.assertNotEqual(first.project_id, second.project_id)

    def test_idempotency_key_replay_still_works(self):
        first = self.store.create(_request("dbl-key-5"))
        replay = self.store.create(_request("dbl-key-5"))
        self.assertEqual(first.project_id, replay.project_id)


class FrontendStableKeyContractTests(unittest.TestCase):
    """前端两层防护的源契约（组件级 App 挂载成本过高，按源契约断言）。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (ROOT / "frontend/src/App.jsx").read_text(encoding="utf-8")

    def test_dialog_open_generates_session_stable_idempotency_key(self):
        self.assertIn("setNewProjectIdempotencyKey", self.source)
        self.assertIn(
            "create-project-session-",
            self.source,
            "幂等键必须来自弹窗会话state（打开时生成一次），不得每次提交用"
            "Date.now/random 现拼（双击=两键，后端去重永不命中）。",
        )
        self.assertNotIn(
            "idempotency_key: `create-project-${Date.now()}",
            self.source,
        )

    def test_submit_handler_has_synchronous_ref_guard(self):
        self.assertIn("newProjectSubmitRef", self.source)
        self.assertIn("if (newProjectSubmitRef.current) return;", self.source)

    def test_topbar_new_project_path_also_generates_session_key(self):
        """NEW-P0-25（R2回归，批三A）：顶栏『新建项目』按钮此前不生成会话
        幂等键（只有空看板入口生成），有activeProject时只能走顶栏路径→
        键恒空→后端 min_length=8 拒收422（现场6次复现）。契约：顶栏按钮
        onClick 也必须生成键。"""
        import re

        # 匹配含 setNewProjectOpen(true) 的 onClick 块（模板字面量内含
        # ${} 大括号，需按语句边界而非 [^}] 截断）。
        blocks = re.findall(
            r"onClick=\{\(\) => \{(.*?)\}\}",
            self.source,
            re.S,
        )
        openers = [b for b in blocks if "setNewProjectOpen(true)" in b]
        self.assertTrue(openers, "未找到任何打开新建项目对话框的onClick")
        self.assertTrue(
            all("setNewProjectIdempotencyKey" in body for body in openers),
            "所有 setNewProjectOpen(true) 打开路径都必须同时生成会话幂等键",
        )

    def test_submit_has_nonempty_idempotency_key_fallback(self):
        """NEW-P0-25 兜底：提交体不得原样发送空键——必须有非空兜底。"""
        self.assertRegex(
            self.source,
            r"idempotency_key: newProjectIdempotencyKey\s*\|\|",
            "提交处需 newProjectIdempotencyKey || 兜底生成，杜绝空键422",
        )


class EntryPathKeyAuditTests(unittest.TestCase):
    """批A①（R27第2轮末修订 NEW-P0-09）：全入口幂等键审计+提交期兜底。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (ROOT / "frontend/src/App.jsx").read_text(encoding="utf-8")

    def test_every_dialog_open_path_generates_session_key(self):
        opens = [
            m.start()
            for m in __import__("re").finditer(r"setNewProjectOpen\(true\)", cls_src)
        ] if (cls_src := None) else []
        import re

        opens = [m.start() for m in re.finditer(r"setNewProjectOpen\(true\)", self.source)]
        self.assertTrue(opens, "应存在新建项目弹窗入口")
        for pos in opens:
            window = self.source[max(0, pos - 700) : pos]
            self.assertIn(
                "setNewProjectIdempotencyKey(",
                window,
                "每个打开新建项目弹窗的入口都必须先生成会话幂等键"
                "（NEW-P0-09：单一入口生成→其他路径空键→422裸JSON）。",
            )

    def test_submit_time_last_resort_key_never_empty(self):
        import re

        self.assertRegex(
            self.source,
            r"idempotency_key:\s*newProjectIdempotencyKey\s*\|\|",
            "提交体必须带兜底键生成——任何未来新增入口漏生成时，提交期"
            "兜底保证键非空（现场：idempotency_key string_too_short 422）。",
        )
