"""R27 第4轮末修订 片2（NEW-P0-19 / L2重开）：triage互锁根修。

现场（R4-A形态一 + R4-D形态二，两测试者独立复现）：
- awaiting_triage_confirm 不在 USER_ACTION_WAITING_STAGES 也不在
  AUTHORING_WRITE_ALLOWED_WAITING_STAGES → authoring_writes_blocked_by_
  pipeline=True → framing/picos commit 一律 409；
- 解锁该状态的『确认分诊』又要求 picos_complete（journey finalize_
  corpus_triage 前置）→ 数学死锁：完成第一步↔确认分诊互为前置；
- 报错文案承诺『或取消本次流水线后立即提交』但 awaiting_triage_confirm
  等待卡片无取消按钮（承诺的逃生门缺失）。

修复契约（红先修后）：
- ① awaiting_triage_confirm 加入放行集（分诊确认动作本身不写
  framing/picos，作者提交不会污染其冻结输入——分诊快照已由
  immutable snapshot 机制单独守护）；
- ② finalize_corpus_triage 的前置改为只要求 search_plan 存在+快照匹配
  （PICOS完成度由独立 corpus gate 把关，双前置是死锁源头）；
- ③ 等待卡片提供流水线取消按钮（前端契约，源断言）。
"""

from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyService,
)
from services.api.app.medical_writing_research_pipeline import (
    authoring_writes_blocked_by_pipeline,
)


class TriageConfirmUnblockTests(unittest.TestCase):
    def test_awaiting_triage_confirm_allows_authoring_writes(self):
        self.assertFalse(
            authoring_writes_blocked_by_pipeline("awaiting_triage_confirm"),
            "分诊确认等待期必须放行作者提交——现场两形态死锁：完成第一步被"
            "409挡住，而解除该状态的确认分诊又要求先完成PICOS。",
        )

    def test_frozen_progress_stages_still_block(self):
        for stage in ("triaging", "preparing", "translating", "searching"):
            self.assertTrue(
                authoring_writes_blocked_by_pipeline(stage),
                f"{stage} 是运行中的冻结输入所有者，仍须阻断作者提交。",
            )


class FinalizeWithoutPicosTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmp.name) / "journeys.sqlite3"
        )
        self.project_id = "proj_finalize_no_picos"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _journey_with_snapshot(self) -> None:
        from tests.test_medical_writing_authoring_journey import _complete_framing
        from packages.contracts.workbench_contracts import (
            MedicalWritingAuthoringJourneyCreateRequest,
        )

        created = self.service.create(
            self.project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=_complete_framing(),
                actor="medical_manager_test",
                idempotency_key="create-finalize-no-picos",
            ),
        )
        # 绑定快照：直接把 search_plan.latest_snapshot_id 写为测试值。
        journey = self.service.get(self.project_id)
        import json

        with self.service._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM medical_writing_authoring_journeys "
                "WHERE project_id=?",
                (self.project_id,),
            ).fetchone()
            payload = json.loads(row["payload_json"])
            payload["search_plan"]["latest_snapshot_id"] = "wref_snap_finalize"
            payload["picos_complete"] = False
            connection.execute(
                "UPDATE medical_writing_authoring_journeys SET payload_json=? "
                "WHERE project_id=?",
                (json.dumps(payload, ensure_ascii=False), self.project_id),
            )
            connection.commit()
        self.assertFalse(self.service.get(self.project_id).picos_complete)

    def test_finalize_triage_no_longer_requires_picos_complete(self):
        from packages.contracts.workbench_contracts import (
            MedicalWritingCorpusTriageFinalizeRequest,
        )

        self._journey_with_snapshot()
        state = self.service.get(self.project_id)
        finalized = self.service.finalize_corpus_triage(
            self.project_id,
            MedicalWritingCorpusTriageFinalizeRequest(
                expected_revision=state.revision,
                snapshot_id="wref_snap_finalize",
                retained_candidate_ids=["NCT00000001"],
                reason="分诊确认不应以PICOS完成为前置（现场死锁）。",
                actor="medical_manager_test",
                idempotency_key="finalize-no-picos-1",
            ),
        )
        self.assertEqual("finalized", finalized.corpus_triage.status)


class CancelButtonContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (
            ROOT
            / "frontend/src/features/medical-writing/MedicalWritingAuthoringJourneySetup.jsx"
        ).read_text(encoding="utf-8")

    def test_awaiting_triage_confirm_waiting_card_offers_cancel(self):
        self.assertIn("cancelResearchPipeline", cls_src := self.source)
        # 等待/进行卡片的按钮组必须把 awaiting_triage_confirm 纳入可取消范围。
        self.assertRegex(
            self.source,
            r"awaiting_triage_confirm[\s\S]{0,600}cancelResearchPipeline|"
            r"cancelResearchPipeline[\s\S]{0,600}awaiting_triage_confirm",
            "awaiting_triage_confirm 等待卡片必须提供『取消本次流水线』按钮"
            "（文案承诺的逃生门，现场全界面不存在）。",
        )


if __name__ == "__main__":
    unittest.main()
