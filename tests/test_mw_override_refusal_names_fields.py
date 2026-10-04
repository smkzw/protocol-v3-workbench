"""R27 第1轮 L2/L4 收尾：例外放行拒绝文案在无PICOS草稿时也必须具名。

活体复现（实现师 20261004，proj_user_335ebdcef0b7，5301）：
- framing 已完成、PICOS 从未保存草稿时例外放行被拒，文案为
  「…当前仍缺必填项：第二步PICOS必填项。…」——字段名位置仍是泛称，
  与账本 L4（必填缺项只报数量/泛称不报字段名，用户得自己翻页签找）同族。

修复契约：picos_draft 为空时，用 PICOS 模型自身的 missing_required_fields()
（全默认值即"全缺"清单）具名列出；有草稿时维持现状（草稿缺口清单）。
"""

from __future__ import annotations

import unittest

from packages.contracts.workbench_contracts import (
    MedicalWritingAuthoringJourneyCreateRequest,
    MedicalWritingCorpusGateOverrideRequest,
    MedicalWritingPicosDefinition,
)
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyService,
)

from tests.test_medical_writing_authoring_journey import (
    _complete_framing,
    _complete_picos,
)


class OverrideRefusalNamesFieldsTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        from pathlib import Path

        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.service = MedicalWritingAuthoringJourneyService(
            root / "journeys.sqlite3"
        )
        self.project_id = "proj_override_refusal_names_fields"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _create_with_complete_framing(self) -> None:
        self.service.create(
            self.project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=_complete_framing(),
                actor="medical_manager_test",
                idempotency_key="create-override-names-fields",
            ),
        )

    def test_refusal_without_picos_draft_names_canonical_required_fields(self):
        self._create_with_complete_framing()
        state = self.service.get(self.project_id)
        missing = list(state.corpus_gate.missing_requirements)

        with self.assertRaises(ValueError) as refused:
            self.service.override_corpus_gate(
                self.project_id,
                MedicalWritingCorpusGateOverrideRequest(
                    expected_revision=state.revision,
                    reason="验证无草稿时拒绝文案具名。",
                    acknowledged_missing_requirements=missing,
                    actor="medical_manager_test",
                    idempotency_key="override-names-fields-no-draft",
                ),
            )
        message = str(refused.exception)
        canonical = MedicalWritingPicosDefinition().missing_required_fields()
        named = [field for field in canonical if field in message]
        self.assertTrue(
            named,
            "picos_draft 为空时拒绝文案必须具名列出PICOS必填字段"
            f"（至少含 {canonical[:3]}…），实际文案：{message}",
        )
        self.assertNotIn("第二步PICOS必填项：第二步PICOS必填项", message)

    def test_refusal_with_picos_draft_keeps_draft_gap_list(self):
        self._create_with_complete_framing()
        from packages.contracts.workbench_contracts import (
            MedicalWritingAuthoringJourneyDraftSaveRequest,
        )

        self.service.save_stage_draft(
            self.project_id,
            MedicalWritingAuthoringJourneyDraftSaveRequest(
                expected_revision=1,
                stage="picos",
                picos=_complete_picos(design_archetype=""),
                actor="medical_manager_test",
                idempotency_key="draft-override-names-fields",
            ),
        )
        state = self.service.get(self.project_id)
        missing = list(state.corpus_gate.missing_requirements)

        with self.assertRaises(ValueError) as refused:
            self.service.override_corpus_gate(
                self.project_id,
                MedicalWritingCorpusGateOverrideRequest(
                    expected_revision=state.revision,
                    reason="验证有草稿时维持草稿缺口清单。",
                    acknowledged_missing_requirements=missing,
                    actor="medical_manager_test",
                    idempotency_key="override-names-fields-with-draft",
                ),
            )
        message = str(refused.exception)
        self.assertIn("design_archetype", message)


if __name__ == "__main__":
    unittest.main()
