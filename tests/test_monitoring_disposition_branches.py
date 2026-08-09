from __future__ import annotations

import unittest

from packages.contracts.workbench_contracts import (
    MonitoringRiskDispositionKind,
    RuxRiskDispositionAction,
    RuxRiskDispositionActionRequest,
)
from services.api.app.workbench_inbox import _validate_rux_disposition_transition


class MonitoringDispositionBranchTests(unittest.TestCase):
    def test_non_query_branches_reach_auditable_terminal_states(self) -> None:
        non_query_kinds = [
            MonitoringRiskDispositionKind.EXPLAINED_NO_EXTERNAL_ACTION,
            MonitoringRiskDispositionKind.DATA_CORRECTION,
            MonitoringRiskDispositionKind.FOLLOW_UP,
            MonitoringRiskDispositionKind.PD_UPDATE,
            MonitoringRiskDispositionKind.SAFETY_PV_COLLABORATION,
            MonitoringRiskDispositionKind.CONTINUE_OBSERVATION,
            MonitoringRiskDispositionKind.DUPLICATE_NOT_APPLICABLE,
        ]

        for kind in non_query_kinds:
            with self.subTest(kind=kind.value):
                request = RuxRiskDispositionActionRequest(
                    action=RuxRiskDispositionAction.REVIEWED,
                    disposition_kind=kind,
                    medical_judgments={"review_completed": True},
                    comment=f"已完成{kind.value}分支医学处置并保留来源审计。",
                    expected_source_version="source-v1",
                )
                self.assertEqual(kind.value, _validate_rux_disposition_transition("pending_review", request))

    def test_only_center_query_branch_can_create_query_draft(self) -> None:
        request = RuxRiskDispositionActionRequest(
            action=RuxRiskDispositionAction.QUERY_DRAFT,
            disposition_kind=MonitoringRiskDispositionKind.SAFETY_PV_COLLABORATION,
            comment="转Safety/PV协作，不应生成中心Query。",
            query_draft_text="不应保存的Query文本",
            expected_source_version="source-v1",
        )

        with self.assertRaisesRegex(ValueError, "center_query"):
            _validate_rux_disposition_transition("reviewed", request)


if __name__ == "__main__":
    unittest.main()
