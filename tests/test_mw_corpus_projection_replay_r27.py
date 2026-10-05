"""R27 自检（20261005r3）节点⑤ P0-1：写作入口幂等键UNIQUE死锁。

现场（SMOKE-r3-1S proj_user_bfcd0eec6505）：例外放行后点『进入写作平台』
→『建立工作稿失败：HTTP 500 重试』持续，本项目写作入口死锁。后端实测
Traceback：main.py create_medical_writing_greenfield_document →
authoring_journey.apply_corpus_projection:2958 → _persist_update:6269 →
_insert_event:6309 → sqlite3.IntegrityError: UNIQUE constraint failed:
medical_writing_authoring_journey_events.project_id, idempotency_key。

机制根因：每次进入写作端点都会触发 corpus readiness recalculate →
apply_corpus_projection。事件幂等键=『corpus-projection-{source_state_hash}』
只由源态哈希决定，而 request_sha256 还包含 requirements——requirements
变化（如准入推进/例外后重算）而源态哈希不变时，早退no-op检查不命中
（requirements不同）→落库写事件→与同哈希的既往事件撞UNIQUE→500。
"""

from __future__ import annotations

import unittest
from pathlib import Path
import tempfile

from packages.contracts.workbench_contracts import (
    MedicalWritingAuthoringJourneyCreateRequest,
    MedicalWritingCorpusRequirementStatus,
)
from tests.test_medical_writing_authoring_journey import _complete_framing
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyService,
)

PROJECT_ID = "proj_corpus_projection_replay"

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


class CorpusProjectionReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmp.name) / "journeys.sqlite3"
        )
        # create(带framing)自动生成search_plan（latest_snapshot_id=""），
        # apply_corpus_projection 以空快照ID即可绑定。
        self.service.create(
            PROJECT_ID,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=_complete_framing(),
                actor="medical_manager_test",
                idempotency_key="create-projection-replay",
            ),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_same_source_hash_different_requirements_does_not_hit_unique(self):
        source_hash = "hash_fixed_source_state"
        # 第一次投影：全不满足。
        first = self.service.apply_corpus_projection(
            PROJECT_ID,
            bound_snapshot_id="",
            source_state_hash=source_hash,
            requirements=_requirements([False] * 5),
        )
        self.assertFalse(first.corpus_gate.access_permitted)
        # 第二次投影：源态哈希不变、requirements 变化（准入推进）——
        # 现场死锁路径：事件键只含源态哈希 → UNIQUE 冲突 500。
        second = self.service.apply_corpus_projection(
            PROJECT_ID,
            bound_snapshot_id="",
            source_state_hash=source_hash,
            requirements=_requirements([True, True, True, False, False]),
        )
        self.assertEqual(
            ["竞品候选研究已完成人工相关性分诊", "至少一份相关Protocol已完成内容校验与结构化解析", "英文竞品方案关键章节已形成监管中文参考译文"],
            second.corpus_gate.covered_requirements,
            "requirements 部分满足时门状态应如实重算（3项覆盖，不再是全缺）"
            "——且不再撞UNIQUE 500。",
        )

    def test_identical_replay_is_noop(self):
        reqs = _requirements([False] * 5)
        first = self.service.apply_corpus_projection(
            PROJECT_ID,
            bound_snapshot_id="",
            source_state_hash="hash_fixed_source_state",
            requirements=reqs,
        )
        replay = self.service.apply_corpus_projection(
            PROJECT_ID,
            bound_snapshot_id="",
            source_state_hash="hash_fixed_source_state",
            requirements=reqs,
        )
        self.assertEqual(
            first.revision,
            replay.revision,
            "同哈希同requirements的重复投影必须是no-op（不加修订号）。",
        )


if __name__ == "__main__":
    unittest.main()
