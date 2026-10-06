"""R27 第5轮末修订 片A③（NEW-P0-21）：分诊锁定→确认篮子0交接修。

现场（R5-D）：人工改判1项直接竞品+3项间接参照→『确认并锁定全部14项』
成功（状态条『已锁定14项候选研究』），点『确认分诊后继续』却报
『当前确认的分诊篮子为0项』——两套真相源在确认动作处失联：
- 前端 continueResearchPipelineAfterTriage 只发 {actor}（无
  retained_candidate_ids）；
- 后端 _confirm_triage_basket 走AI run自己的recommended_retain∩公开文档
  重算篮子，用户写入 journey.corpus_triage.retained_candidate_ids 的14项
  被完全忽略；交集为空时篮子=0→409空篮拦截。

修复契约（红先修后）：
- ①前端确认body携带 journey.corpus_triage.retained_candidate_ids；
- ②后端 _confirm_triage_basket 优先级反转：journey.corpus_triage 已
  finalized且快照一致时以用户锁定的retained为主源，AI run仅兜底——
  防其他调用方再丢参。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from services.api.app.medical_writing_research_pipeline import (
    MedicalWritingResearchPipelineService,
)
from types import SimpleNamespace


class FrontendHandoffContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (
            ROOT
            / "frontend/src/features/medical-writing/MedicalWritingAuthoringJourneySetup.jsx"
        ).read_text(encoding="utf-8")

    def test_continue_after_triage_body_carries_user_retained_ids(self):
        handler = re.search(
            r"const continueResearchPipelineAfterTriage = async \(\) => \{[\s\S]*?\n  \};",
            self.source,
        )
        self.assertIsNotNone(handler)
        self.assertIn(
            "retained_candidate_ids",
            handler.group(0),
            "确认分诊后继续的请求体必须携带 journey.corpus_triage."
            "retained_candidate_ids——现场：只发{actor}，后端用AI run重算"
            "篮子=0（用户锁定的14项被丢弃）。",
        )


class BackendFinalizedPriorityTests(unittest.TestCase):
    def test_confirm_basket_prefers_finalized_user_retained(self):
        def _snapshot(project_id, snapshot_id):
            return SimpleNamespace(
                candidates=[
                    SimpleNamespace(nct_id="NCT00000001", public_documents=[]),
                    SimpleNamespace(nct_id="NCT00000002", public_documents=[]),
                ]
            )

        journey = SimpleNamespace(
            search_plan=SimpleNamespace(latest_snapshot_id="wref_handoff"),
            corpus_gate=SimpleNamespace(
                access_permitted=False,
                override=SimpleNamespace(active=False),
            ),
            # 用户已在分诊UI锁定14项的现场等价：finalized + retained集合
            corpus_triage=SimpleNamespace(
                status="finalized",
                snapshot_id="wref_handoff",
                retained_candidate_ids=["NCT00000001"],
            ),
        )
        journey.get = lambda project_id: journey
        journey.save_research_pipeline = lambda project_id, payload: None
        service = MedicalWritingResearchPipelineService(
            journey_service=journey,
            discovery_service=SimpleNamespace(),
            triage_service=SimpleNamespace(
                repository=SimpleNamespace(
                    search_snapshot=_snapshot,
                    relevance_decisions_for_snapshot=lambda *a, **k: [],
                )
            ),
            preparation_batch_service=SimpleNamespace(),
            translation_batch_service=SimpleNamespace(),
            corpus_readiness_service=SimpleNamespace(),
            china_client_factory=lambda: None,
            corpus_analysis_ai_service=SimpleNamespace(),
        )
        state = SimpleNamespace(
            pipeline_id="mwpipe_handoff",
            project_id="proj_handoff",
            stage="awaiting_triage_confirm",
            snapshot_id="wref_handoff",
            triage_run_id="",
        )
        retained = service._confirm_triage_basket(
            "proj_handoff", "medical_manager", state, None
        )
        self.assertEqual(
            ["NCT00000001"],
            retained,
            "journey.corpus_triage已finalized且快照一致时必须以用户锁定的"
            "retained为主源（现场：AI run∩公开文档=空→篮子0→409）。",
        )


if __name__ == "__main__":
    unittest.main()
