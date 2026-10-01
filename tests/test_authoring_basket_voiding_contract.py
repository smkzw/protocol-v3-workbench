# -*- coding: utf-8 -*-
"""SMOKE-r1-2 ③（R27 收敛修订）反例：第一步必填项补齐静默作废已确认竞品篮子。

现场（proj_user_9bed9903e9e5）：用户 15:02 确认锁定 823 项
（ct_conf_3930d4e834f1ea809bb6，事件 authoring_journey_discovery_basket_
projected@rev4）；16:05-16:10 按界面要求补齐第一步必填（总体设计模式/
目标人群/内在研究目的——全部是 triage_criteria 的输入字段）并完成第一步，
commit_stage 的 search_contract_changed 判定命中（criteria 变化即清空），
discovery_basket_projection 被重置为全空（rev16 实证 confirmation_id=""）。
翻译重试逐项走 _validate_frozen_lineage → _snapshot_scope 两条权威路径都
不满足 → "batch translation requires either finalized corpus triage or a
confirmed discovery basket projection" 死路。

修后契约：
- 仅 criteria 变化（registry filter 不变、同一锁定快照）：人工保留/排除
  决策继续有效（confirm_basket：确认即医学决策，候选宇宙未变），
  projection 保留；_rebuild_search_plan 已把计划状态降级提示确认早于当前
  标准。
- registry filter 变化（候选宇宙变）或检索就绪度丢失：仍全部重置（原安全
  语义保留）。
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from packages.contracts.workbench_contracts import (
    MedicalWritingAuthoringJourneyCommitRequest,
    MedicalWritingAuthoringJourneyCreateRequest,
    MedicalWritingCompetitorSearchExecuteRequest,
    MedicalWritingJourneyImpactPreviewRequest,
    WritingReferenceSearchRequest,
    WritingReferenceSearchSnapshot,
    WritingReferenceTrialCandidate,
)
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyService,
)
from tests.test_medical_writing_authoring_journey import (
    _complete_framing,
)

PROJECT_ID = "proj_basket_voiding_contract"


def _snapshot(project_id: str, snapshot_id: str) -> WritingReferenceSearchSnapshot:
    request = WritingReferenceSearchRequest(
        indication="Rheumatoid Arthritis",
        phases=["PHASE2"],
    )
    candidates = [
        WritingReferenceTrialCandidate(
            nct_id="NCT00000001",
            brief_title="competitor study",
            study_record_url="https://clinicaltrials.gov/study/NCT00000001",
            conditions=["Rheumatoid Arthritis"],
            phases=["PHASE2"],
        )
    ]
    return WritingReferenceSearchSnapshot(
        snapshot_id=snapshot_id,
        project_id=project_id,
        request=request,
        query_url="https://example.org/search",
        api_version="2.0",
        data_timestamp="2026-09-30",
        total_count=len(candidates),
        returned_count=len(candidates),
        page_count=1,
        candidates=candidates,
        created_by="test",
        created_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
    )


class BasketVoidingContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "authoring_journey.sqlite3"
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _journey_with_confirmed_basket(self):
        created = self.service.create(
            PROJECT_ID,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=_complete_framing(),
                actor="medical_manager_test",
                idempotency_key="basket-voiding-create",
            ),
        )
        self.assertIsNotNone(created.search_plan)
        attached = self.service.attach_search_snapshot(
            PROJECT_ID,
            _snapshot(PROJECT_ID, "wref_search_basket_voiding"),
            MedicalWritingCompetitorSearchExecuteRequest(
                search_plan_id=created.search_plan.plan_id,
                actor="medical_manager_test",
                idempotency_key="basket-voiding-attach-snapshot",
            ),
        )
        self.assertEqual(
            "wref_search_basket_voiding",
            attached.search_plan.latest_snapshot_id,
        )
        projected = self.service.project_human_reconfirmed_basket(
            PROJECT_ID,
            _snapshot(PROJECT_ID, "wref_search_basket_voiding"),
            confirmation_id="ct_conf_basket_voiding",
            confirmation_hash="hash_basket_voiding",
            source_confirmation_id="ct_conf_basket_voiding_source",
            run_id="ct_run_basket_voiding",
            retained_nct_ids=["NCT00000001"],
            excluded_nct_ids=[],
            expected_revision=attached.revision,
            actor="medical_manager_test",
            reason="确认保留全部候选",
            idempotency_key="basket-voiding-project",
        )
        self.assertEqual(
            "ct_conf_basket_voiding",
            projected.discovery_basket_projection.confirmation_id,
        )
        return projected

    def _commit_framing(self, journey, framing):
        preview = self.service.impact_preview(
            PROJECT_ID,
            MedicalWritingJourneyImpactPreviewRequest(
                expected_revision=journey.revision,
                stage="framing",
                framing=framing,
            ),
        )
        return self.service.commit_stage(
            PROJECT_ID,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=journey.revision,
                stage="framing",
                framing=framing,
                impact_preview_id=(
                    preview.preview_id if preview.requires_confirmation else ""
                ),
                actor="medical_manager_test",
                idempotency_key=f"basket-voiding-commit-{journey.revision}",
            ),
        )

    def test_criteria_only_completion_keeps_confirmed_basket(self):
        """修前红：补齐 criteria 输入字段（目标人群/设计模式）即触发
        search_contract_changed → projection 清空。修后：候选宇宙未变，
        人工确认保留。"""
        journey = self._journey_with_confirmed_basket()
        framing = _complete_framing()
        # SMOKE-r1-2 现场：用户按界面要求补齐/充实 criteria 输入字段
        framing.population_intent = (
            "既往csDMARD治疗反应不充分的中重度活动性成人患者（补齐必填后）"
        )
        framing.design_pattern = (
            "随机、双盲、安慰剂对照、平行组、多中心研究（修订描述）"
        )
        committed = self._commit_framing(journey, framing)
        self.assertEqual(
            "ct_conf_basket_voiding",
            committed.discovery_basket_projection.confirmation_id,
            "仅 criteria 变化（registry filter 不变）不得作废已确认篮子",
        )
        self.assertEqual(
            "wref_search_basket_voiding",
            committed.discovery_basket_projection.snapshot_id,
        )
        # 快照身份同样保留：翻译 lineage 校验依赖 plan.latest_snapshot_id
        self.assertEqual(
            "wref_search_basket_voiding",
            committed.search_plan.latest_snapshot_id,
        )

    def test_registry_filter_change_still_resets_basket(self):
        """候选宇宙变化（适应症变化 → condition term 变）仍全部重置：
        原「候选宇宙变 → 重新检索+重新确认」的安全语义保留。"""
        journey = self._journey_with_confirmed_basket()
        framing = _complete_framing(
            indication="银屑病",
            clinicaltrials_condition_term="Psoriasis",
        )
        committed = self._commit_framing(journey, framing)
        self.assertEqual(
            "",
            committed.discovery_basket_projection.confirmation_id,
            "registry filter 变化必须作废已确认篮子并要求重新检索",
        )
        self.assertEqual("", committed.search_plan.latest_snapshot_id)


if __name__ == "__main__":
    unittest.main()
