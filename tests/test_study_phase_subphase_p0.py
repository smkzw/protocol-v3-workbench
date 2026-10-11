"""新纪元第2轮末修订（P0-1/NEW-18）：研究分期子阶段（Ib/IIa/IIb期）
后端枚举补齐——前端下拉（第1轮NEW-8修复）与后端校验单侧对齐的收口。

现场（r2-A 证据 i2-05 横幅原文）：步骤01'提交并拆解'实际发出了请求并被
后端拒绝——『initial fact value for framing.study_phase must be one of
('I期', 'I/II期', 'II期', 'II/III期', 'III期')』。前端下拉含 IIa期
（App.jsx:1622 等），后端 fact-intake 枚举（medical_writing_fact_intake.py
:143）与规范化映射（:198-207）均无子阶段 → 建项选 IIa 期后首条 turn 即
422，四种输入方式全败（共用同一 POST）。

修后契约（反例先红）：
T1 fact-intake 初始事实值：'IIa期'/'IIb期'/'Ib期' 原样受理；常见变体
   （iia/iib/ib、ii a/ii b、2a/2b、phase iia…）规范化到规范标签；
T2 建项（UserProjectCreateRequest）：'IIa期' 不得被折叠为 'II期'——
   子阶段标签原样持久化（此前 _PHASE_TOKEN_RE 无 a/b 后缀 token，
   'IIa期'被静默降级）；变体 '2a期'/'iia' 同样规范化到 'IIa期'；
T3 既有五值枚举与全部既有变体行为不变（II期→II期 等）。
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest


def _normalize(values: dict) -> dict:
    from services.api.app.medical_writing_fact_intake import (
        _normalize_initial_confirmed_values,
    )

    return _normalize_initial_confirmed_values("study_framing", values)


class FactIntakeSubPhaseEnumTests(unittest.TestCase):
    def test_canonical_subphase_labels_accepted_verbatim(self) -> None:
        """T1a：规范子阶段标签原样受理（现场横幅五值枚举的红案）。"""
        for label in ("IIa期", "IIb期", "Ib期"):
            result = _normalize({"framing.study_phase": label})
            self.assertEqual(label, result["framing.study_phase"], label)

    def test_common_variants_normalized_to_canonical(self) -> None:
        """T1b：常见变体（含现场'ii a/2a'形态）规范化到规范标签。"""
        cases = {
            "iia": "IIa期",
            "ii a": "IIa期",
            "2a": "IIa期",
            "2a期": "IIa期",
            "phase iia": "IIa期",
            "phase 2a": "IIa期",
            "iib": "IIb期",
            "ii b": "IIb期",
            "2b": "IIb期",
            "2b期": "IIb期",
            "phase iib": "IIb期",
            "ib": "Ib期",
            "phase ib": "Ib期",
            "1b": "Ib期",
        }
        for raw, expected in cases.items():
            result = _normalize({"framing.study_phase": raw})
            self.assertEqual(
                expected, result["framing.study_phase"], f"{raw!r} → {expected}"
            )

    def test_existing_enum_behavior_unchanged(self) -> None:
        """T3：既有五值与既有变体不回退。"""
        for label in ("I期", "I/II期", "II期", "II/III期", "III期"):
            result = _normalize({"framing.study_phase": label})
            self.assertEqual(label, result["framing.study_phase"])
        self.assertEqual(
            "II期", _normalize({"framing.study_phase": "phase 2"})["framing.study_phase"]
        )

    def test_project_create_preserves_subphase_label(self) -> None:
        """T2：建项契约不把 'IIa期' 折叠为 'II期'；变体规范化到规范标签。"""
        from packages.contracts.workbench_contracts import UserProjectCreateRequest

        created = UserProjectCreateRequest(
            project_name="子阶段分期研究",
            indication="化脓性汗腺炎",
            study_phase="IIa期",
            actor="medical_manager",
            idempotency_key="p0-1-iia-create",
        )
        self.assertEqual("IIa期", created.study_phase)

        normalized = UserProjectCreateRequest(
            project_name="子阶段分期研究",
            indication="化脓性汗腺炎",
            study_phase="2a期",
            actor="medical_manager",
            idempotency_key="p0-1-iia-create-variant",
        )
        self.assertEqual("IIa期", normalized.study_phase)

    def test_project_create_keeps_plain_phase_rewrites(self) -> None:
        """既有行为不回退：'3期'→'III期'、'phase 2'→'II期'。"""
        from packages.contracts.workbench_contracts import UserProjectCreateRequest

        third = UserProjectCreateRequest(
            project_name="常规分期研究",
            indication="化脓性汗腺炎",
            study_phase="3期",
            actor="medical_manager",
            idempotency_key="p0-1-iii-create",
        )
        self.assertEqual("III期", third.study_phase)


if __name__ == "__main__":
    unittest.main()
