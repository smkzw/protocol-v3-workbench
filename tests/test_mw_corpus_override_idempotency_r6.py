"""R6 第6轮末修订 片A′（P2-43 + P0-24 服务侧契约）：例外放行幂等。

现场（R6-A proj_user_ee74b6fda2c2 及另有3个项目各有2次
authoring_journey_corpus_gate_overridden 事件）：『确认例外并放行』
没有已放行幂等——只要确认集仍等于当前缺失集，重复放行会再次
+1 修订号并新增事件（版本 14→16 静默膨胀），审计链里出现多条
 medically 等价的放行记录；w6-13 场景里测试者在放行+重算（rev17→18）
 之间反复点击进入写作平台，版本churn叠加前端陈旧态后按钮零响应。

契约（红先修后）：
- 门上已有 active override 且本次确认集覆盖当前缺失集时，
  重复 override_corpus_gate 必须是 no-op：返回当前状态，
  修订号不变、不新增 override 事件（首次放行记录是唯一权威审计）；
- 缺失集在重算后变化（apply_corpus_projection 会保留放行）时，
  再次提交对新缺失集的放行同样不得新建版本——access_permitted
  已为 true，放行决定并未失效（service 2898 注释的既定语义）；
- 首次放行行为不变：仍 +1 修订、单条事件、access_permitted=true。
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from packages.contracts.workbench_contracts import (
    MedicalWritingAuthoringJourneyCommitRequest,
    MedicalWritingAuthoringJourneyCreateRequest,
    MedicalWritingCorpusGateOverrideRequest,
    MedicalWritingCorpusRequirementStatus,
)
from tests.test_medical_writing_authoring_journey import (
    _complete_framing,
    _complete_picos,
)
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyService,
)

PROJECT_ID = "proj_override_idempotency_r6"

_CODES = [
    ("candidate_triage", "竞品候选研究已完成人工相关性分诊"),
    ("protocol_structure", "至少一份相关Protocol已完成内容校验与结构化解析"),
    ("regulatory_zh_translation", "英文竞品方案关键章节已形成监管中文参考译文"),
    ("medical_admission", "项目适用中文语料已完成医学准入"),
    ("picos_alignment", "PICOS关键设计事实与语料冲突已处置"),
]


def _requirements(satisfied_flags: list[bool]) -> list[MedicalWritingCorpusRequirementStatus]:
    return [
        MedicalWritingCorpusRequirementStatus(
            code=code, label=label, satisfied=flag, evidence_ids=[], detail=""
        )
        for (code, label), flag in zip(_CODES, satisfied_flags, strict=True)
    ]


class CorpusOverrideIdempotencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "journeys.sqlite3"
        self.service = MedicalWritingAuthoringJourneyService(self.db_path)
        framed = self.service.create(
            PROJECT_ID,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=_complete_framing(),
                actor="medical_manager_test",
                idempotency_key="create-override-idem-r6",
            ),
        )
        designed = self.service.commit_stage(
            PROJECT_ID,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=framed.revision,
                stage="picos",
                picos=_complete_picos(),
                actor="medical_manager_test",
                idempotency_key="commit-override-idem-r6-picos",
            ),
        )
        self.missing = list(designed.corpus_gate.missing_requirements)
        self.assertEqual(5, len(self.missing))
        self.base_revision = designed.revision

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _override(self, *, key: str, acknowledged: list[str], reason: str = "先行建稿") -> object:
        return self.service.override_corpus_gate(
            PROJECT_ID,
            MedicalWritingCorpusGateOverrideRequest(
                expected_revision=self.base_revision,
                reason=reason,
                acknowledged_missing_requirements=acknowledged,
                actor="medical_manager_test",
                idempotency_key=key,
            ),
        )

    def _override_event_count(self) -> int:
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT count(*) FROM medical_writing_authoring_journey_events "
                "WHERE project_id = ? AND event_type = 'authoring_journey_corpus_gate_overridden'",
                (PROJECT_ID,),
            ).fetchone()
        return int(row[0])

    def test_first_override_still_creates_single_event_and_bumps_once(self) -> None:
        allowed = self._override(
            key="override-idem-r6-first", acknowledged=self.missing
        )
        self.assertTrue(allowed.corpus_gate.access_permitted)
        self.assertTrue(allowed.corpus_gate.override.active)
        self.assertEqual(self.base_revision + 1, allowed.revision)
        self.assertEqual(1, self._override_event_count())

    def test_repeated_override_with_same_set_is_idempotent_noop(self) -> None:
        first = self._override(
            key="override-idem-r6-first", acknowledged=self.missing
        )
        # 新幂等键（前端旧实现按 sourceRevision 派生键，修订号已变即新键）。
        second = self._override(
            key="override-idem-r6-second", acknowledged=self.missing
        )
        self.assertEqual(
            first.revision,
            second.revision,
            "已放行且确认集覆盖当前缺失集时，重复放行不得再膨胀修订号。",
        )
        self.assertTrue(second.corpus_gate.access_permitted)
        self.assertEqual(
            1,
            self._override_event_count(),
            "重复放行不得追加 override 事件（首次记录是唯一权威审计）。",
        )
        # 首次放行的审计字段保持原样。
        self.assertEqual(
            sorted(self.missing),
            sorted(
                second.corpus_gate.override.acknowledged_missing_requirements
            ),
        )

    def test_override_after_recalc_with_changed_missing_set_is_noop(self) -> None:
        self._override(key="override-idem-r6-first", acknowledged=self.missing)
        # 进入写作端点会触发 corpus readiness 重算；此处模拟缺失集变化
        # （准入推进：前3项满足）——apply_corpus_projection 按契约保留放行。
        recalculated = self.service.apply_corpus_projection(
            PROJECT_ID,
            bound_snapshot_id="",
            source_state_hash="hash_override_idem_r6",
            requirements=_requirements([True, True, True, False, False]),
        )
        self.assertTrue(recalculated.corpus_gate.access_permitted)
        new_missing = list(recalculated.corpus_gate.missing_requirements)
        self.assertEqual(2, len(new_missing))
        # 测试者此时若再次『确认例外并放行』（确认新缺失集）：
        # 门已 permitted、放行未失效——必须 no-op，不得新建版本。
        again = self._override(
            key="override-idem-r6-after-recalc", acknowledged=new_missing
        )
        self.assertEqual(
            recalculated.revision,
            again.revision,
            "重算后重复放行同样不得新建修订（放行决定未失效）。",
        )
        self.assertEqual(1, self._override_event_count())
        self.assertTrue(again.corpus_gate.access_permitted)


if __name__ == "__main__":
    unittest.main()
