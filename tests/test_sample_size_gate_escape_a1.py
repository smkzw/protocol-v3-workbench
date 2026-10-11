"""新纪元第3轮末修订（A1①/NEW-24①）：样本量门拒绝一等公民出路。

现场（NEW-24，r3-11/12 死锁终态）：完成第二步提交被样本量门 422 恒拒
（BP601 声明280/组 vs 复算183/组），前端只复用表单中部横幅——无 toast、
无 scrollIntoView、无'去修正声明'跳转，连点×6 每次失败无增量变化，被
感知为'静默吞掉'。5301 日志一查定案（A1③，本会话实测）：60 条
POST /stages/picos/commit，尾部连续 422——每次点击都到达并被拒，测试者
编辑字段（picos.sample_size_strategy）与门读字段（authoring_journey.py
:1343）一致。

修后契约（反例先红）：
T1 后端：声明不一致时 commit_stage 抛 SampleSizeDeclarationBlockedError
   （带 field_anchor='picos.sample_size_strategy'/required/declared），
   路由 422 detail 为结构化 {code, message, field_anchor, ...}；
T2 前端：saveStage 捕获该 code → 自动切到 picos·执行与统计 组 +
scrollIntoView 样本量声明字段（data-testid=sample-size-warning）+
toast 人话（复算/声明例数）+ 横幅'去修正声明'按钮（jumpToSampleSizeDeclaration）；
T3 前端 rejection 不再只复用中部横幅（rejection 增量变化可感知）。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from packages.contracts.workbench_contracts import (
    MedicalWritingAuthoringJourneyCommitRequest,
    MedicalWritingAuthoringJourneyCreateRequest,
)
from tests.test_medical_writing_authoring_journey import (
    _complete_framing,
    _complete_picos,
)

GER601_TEXT = "两组各45例共90例；按GERD-HRQL组间差6分、SD 12、α=0.05双侧、80%把握度探索性设定。"


class SampleSizeGateEscapeBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        from services.api.app.medical_writing_authoring_journey import (
            MedicalWritingAuthoringJourneyService,
        )

        self.db_path = Path(self.tmp.name) / "journeys.sqlite3"
        self.service = MedicalWritingAuthoringJourneyService(self.db_path)
        self.project_id = "proj_ss_gate_escape_a1"
        framed = self.service.create(
            self.project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=_complete_framing(),
                actor="medical_manager_test",
                idempotency_key="create-ss-escape-a1",
            ),
        )
        self.base_revision = framed.revision

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_inconsistent_commit_raises_typed_error_with_field_anchor(self) -> None:
        """T1：拒绝是一等公民错误——带字段锚与复算/声明例数。"""
        from services.api.app.medical_writing_authoring_journey import (
            SampleSizeDeclarationBlockedError,
        )

        picos = _complete_picos()
        picos.sample_size_strategy = GER601_TEXT
        with self.assertRaises(SampleSizeDeclarationBlockedError) as refused:
            self.service.commit_stage(
                self.project_id,
                MedicalWritingAuthoringJourneyCommitRequest(
                    expected_revision=self.base_revision,
                    stage="picos",
                    picos=picos,
                    actor="medical_manager_test",
                    idempotency_key="commit-ss-escape-a1",
                ),
            )
        error = refused.exception
        self.assertEqual("picos.sample_size_strategy", error.field_anchor)
        self.assertEqual(63, error.required_per_group)
        self.assertEqual(45, error.declared_per_group)
        self.assertIn("63", str(error))

    def test_route_maps_typed_error_to_structured_422(self) -> None:
        """T1b：路由 422 detail 为结构化载荷（code/field_anchor/例数）。"""
        from services.api.app.main import _mw_journey_error_detail
        from services.api.app.medical_writing_authoring_journey import (
            SampleSizeDeclarationBlockedError,
        )

        error = SampleSizeDeclarationBlockedError(
            "样本量声明与假设不一致：复算需63例/组，当前声明45例/组：请修正声明或调整假设。",
            field_anchor="picos.sample_size_strategy",
            required_per_group=63,
            declared_per_group=45,
        )
        detail = _mw_journey_error_detail(error)
        self.assertIsInstance(detail, dict)
        self.assertEqual("sample_size_declaration_mismatch", detail["code"])
        self.assertEqual("picos.sample_size_strategy", detail["field_anchor"])
        self.assertEqual(63, detail["required_per_group"])
        self.assertIn("修正声明", detail["message"])


class SampleSizeGateEscapeFrontendContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = (
            Path(__file__).resolve().parents[1]
            / "frontend/src/features/medical-writing"
            / "MedicalWritingAuthoringJourneySetup.jsx"
        ).read_text(encoding="utf-8")

    def test_commit_catch_routes_to_execution_group_with_scroll_and_button(self) -> None:
        """T2/T3：捕获即跳转执行与统计+scrollIntoView+去修正声明按钮。"""
        self.assertIn('error?.code === "sample_size_declaration_mismatch"', self.source)
        self.assertIn("jumpToSampleSizeDeclaration", self.source)
        self.assertIn('data-testid="sample-size-warning"', self.source)
        self.assertIn("scrollIntoView", self.source)
        self.assertIn("去修正声明", self.source)


if __name__ == "__main__":
    unittest.main()


class CancelledPipelineCardTests(unittest.TestCase):
    """A1②（NEW-24③）：无快照且管线终态不再永驻进度卡。"""

    def setUp(self) -> None:
        self.source = (
            Path(__file__).resolve().parents[1]
            / "frontend/src/features/medical-writing"
            / "MedicalWritingAuthoringJourneySetup.jsx"
        ).read_text(encoding="utf-8")

    def test_cancelled_terminal_state_hides_progress_card_and_shows_cancelled_line(self) -> None:
        self.assertIn("const compactResearchTerminalCancelled = (\n    compactResearchPipeline.stage === \"cancelled\"\n  );", self.source)
        self.assertIn(
            "const showCompactResearchProgress = !compactResearchTerminalCancelled",
            self.source,
        )
        self.assertIn('data-testid="authoring-automatic-research-cancelled"', self.source)
        self.assertIn("可重新检索；本行不阻断写作步骤。", self.source)
