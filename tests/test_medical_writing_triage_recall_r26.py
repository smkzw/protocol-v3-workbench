"""R26 自检第4次（本轮）P1-3：AI分诊召回缺陷——同类机制研究全被排除。

现场（proj_user_97c9c19afb20，心衰II期口服sGC 刺激剂项目，ct_run_2459…）：
- NCT01951625 / NCT01951638（vericiguat 同机制剂量探索，适应症维度
  match、无公开Protocol）：被确定性分诊以 reason_code=no_public_protocol
  排除（confidence=1.0，"确定性分诊原因：no_public_protocol"），AI 从未
  评估其医学相关性——直接竞品识别被文档可得性劫持；
- NCT06195930（"Chronic Heart Failure With Reduced Ejection Fraction"，
  项目适应症『射血分数降低的心力衰竭（HFrEF）』）：服务端 lexical 关系
  =cross_language_unresolved，模型未建立双语等价 → 判 mismatch 排除。
  同病（HFrEF=射血分数降低的心力衰竭）被当不同适应症。

修复契约（红先修后）：
- ① 文档可得性与医学相关性分离：无公开Protocol 但适应症关系 exact/mixed
  的候选不再被确定性排除，进入独立AI分诊（下游已有
  study_manual_upload_required 准备项+手动上传通路承接保留的无公开方案
  竞品）；relation=none 的无公开Protocol 候选维持确定性排除；
- ② 心衰射血分数双语桥（沿用 UC/CRSwNP 语义证据先例）：项目适应症建立
  心衰+射血分数方向（降低/保留），候选登记条件的中英文全称或缩写
  （HFrEF/HFpEF）建立同一方向 → 关系 exact/mixed；方向相反不匹配；
  未限定射血分数的泛心衰不由本桥接改判。
"""

from __future__ import annotations

import unittest

from packages.contracts.workbench_contracts import (
    WritingReferenceTrialIntervention,
)
from services.api.app.medical_writing_competitor_triage import (
    _build_chunk_input,
    _build_triage_reduction_plan,
    _candidate_indication_relation,
    _deterministic_triage_disposition,
    _material_facts_hash,
    _snapshot_hash,
)
from tests.test_medical_writing_competitor_triage import (
    TriageTestBase,
    _make_candidate,
    _make_snapshot,
)


def _candidate_payload(journey, candidate):
    return _build_chunk_input(journey, [candidate], 0)["candidates"][0]


class DeterministicNoProtocolRecallTests(TriageTestBase):
    """①：同适应症无公开方案候选必须进入AI分诊。"""

    def _project_facts(self):
        journey = self.journey_service.get(self.project_id)
        return _build_chunk_input(journey, [], 0)["project_facts"]

    def test_same_indication_without_public_protocol_goes_to_ai(self):
        journey = self.journey_service.get(self.project_id)
        candidate = _make_candidate("NCT91000001", docs=[])
        payload = _candidate_payload(journey, candidate)

        disposition = _deterministic_triage_disposition(
            payload, self._project_facts()
        )

        self.assertEqual("requires_ai", disposition.action, (
            "同适应症（relation=exact/mixed）无公开Protocol 的候选是直接"
            "竞品识别的核心召回对象（现场 vericiguat 同机制研究被确定性"
            "排除），必须交由独立AI做医学分类；文档缺口由下游"
            "study_manual_upload_required/手动上传承接。"
        ))

    def test_relation_none_without_public_protocol_stays_deterministic(self):
        journey = self.journey_service.get(self.project_id)
        candidate = _make_candidate(
            "NCT91000002", docs=[], conditions=["Psoriatic Arthritis"]
        )
        payload = _candidate_payload(journey, candidate)

        disposition = _deterministic_triage_disposition(
            payload, self._project_facts()
        )

        self.assertEqual("excluded", disposition.action)
        self.assertEqual("no_public_protocol", disposition.reason_code)

    def test_same_indication_with_device_intervention_still_excluded(self):
        # 守卫：非药物干预不受①影响，仍确定性排除。
        journey = self.journey_service.get(self.project_id)
        candidate = _make_candidate("NCT93000001").model_copy(
            update={
                "interventions": [
                    WritingReferenceTrialIntervention(
                        name="Cardiac resynchronization device",
                        intervention_type="DEVICE",
                    )
                ]
            }
        )
        payload = _candidate_payload(journey, candidate)
        disposition = _deterministic_triage_disposition(
            payload, self._project_facts()
        )
        self.assertEqual("excluded", disposition.action)
        self.assertEqual(
            "explicit_non_pharmacologic_intervention", disposition.reason_code
        )


    def test_reduction_plan_routes_same_indication_no_protocol_to_ai(self):
        journey = self.journey_service.get(self.project_id)
        same_indication_no_docs = [
            _make_candidate(f"NCT91{index:06d}", docs=[])
            for index in range(1, 4)
        ]
        other_indication_no_docs = [
            _make_candidate(
                f"NCT92{index:06d}", docs=[], conditions=["Psoriatic Arthritis"]
            )
            for index in range(1, 3)
        ]
        snapshot = _make_snapshot(
            self.project_id,
            same_indication_no_docs + other_indication_no_docs,
            snapshot_id="wref_search_recall_no_protocol",
        )

        plan = _build_triage_reduction_plan(
            journey,
            snapshot,
            _snapshot_hash(snapshot),
            _material_facts_hash(journey),
        )
        ai_ids = {
            candidate.nct_id
            for chunk in plan.ai_candidate_chunks
            for candidate in chunk
        }
        deterministic_ids = {
            nct_id
            for chunk in plan.deterministic_chunks
            for nct_id in chunk.nct_ids
        }

        self.assertTrue(
            {item.nct_id for item in same_indication_no_docs} <= ai_ids
        )
        self.assertTrue(
            {item.nct_id for item in other_indication_no_docs} <= deterministic_ids
        )


class HeartFailureEjectionFractionBridgeTests(TriageTestBase):
    """②：心衰射血分数方向的中英双语桥接。"""

    def _hf_project_facts(self, indication):
        facts = dict(_build_chunk_input(
            self.journey_service.get(self.project_id), [], 0
        )["project_facts"])
        facts["indication"] = indication
        facts["clinicaltrials_condition_term"] = indication
        return facts

    def test_reduced_ef_english_condition_matches_chinese_hfref_project(self):
        # 现场 NCT06195930：项目『射血分数降低的心力衰竭（HFrEF）』，
        # 候选 "Chronic Heart Failure With Reduced Ejection Fraction"。
        facts = self._hf_project_facts("射血分数降低的心力衰竭（HFrEF）")
        relation = _candidate_indication_relation(
            {
                "conditions": [
                    "Chronic Heart Failure With Reduced Ejection Fraction"
                ],
                "condition_count": 1,
            },
            facts,
        )
        self.assertEqual("exact", relation)

    def test_reduced_ef_abbreviation_matches(self):
        facts = self._hf_project_facts("射血分数降低的心力衰竭（HFrEF）")
        relation = _candidate_indication_relation(
            {"conditions": ["Heart Failure with Reduced Ejection Fraction (HFrEF)"], "condition_count": 1},
            facts,
        )
        self.assertEqual("exact", relation)

    def test_preserved_ef_does_not_match_reduced_project(self):
        facts = self._hf_project_facts("射血分数降低的心力衰竭（HFrEF）")
        relation = _candidate_indication_relation(
            {
                "conditions": [
                    "Chronic Heart Failure With Preserved Ejection Fraction"
                ],
                "condition_count": 1,
            },
            facts,
        )
        self.assertEqual("none", relation)

    def test_reduced_ef_english_project_matches_chinese_candidate(self):
        facts = self._hf_project_facts(
            "Heart Failure With Reduced Ejection Fraction"
        )
        relation = _candidate_indication_relation(
            {"conditions": ["慢性射血分数降低的心力衰竭"], "condition_count": 1},
            facts,
        )
        self.assertEqual("exact", relation)

    def test_unqualified_heart_failure_is_not_forced_to_match(self):
        facts = self._hf_project_facts("射血分数降低的心力衰竭（HFrEF）")
        relation = _candidate_indication_relation(
            {"conditions": ["Heart Failure"], "condition_count": 1},
            facts,
        )
        # 泛心衰人群宽于项目限定人群，不由本桥接改判；交给通用词法/AI。
        self.assertEqual("none", relation)

    def test_mixed_condition_list_with_matching_reduced_ef_is_mixed(self):
        facts = self._hf_project_facts("射血分数降低的心力衰竭（HFrEF）")
        relation = _candidate_indication_relation(
            {
                "conditions": [
                    "Chronic Heart Failure With Reduced Ejection Fraction",
                    "Type 2 Diabetes Mellitus",
                ],
                "condition_count": 2,
            },
            facts,
        )
        self.assertEqual("mixed", relation)

if __name__ == "__main__":
    unittest.main()
