from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = ROOT / "frontend" / "src" / "App.jsx"
STYLE_SOURCE = ROOT / "frontend" / "src" / "styles.css"


class FrontendEligibilityContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP_SOURCE.read_text(encoding="utf-8")
        cls.styles = STYLE_SOURCE.read_text(encoding="utf-8")

    def _eligibility_page(self) -> str:
        match = re.search(r"function EligibilityPage\(.*?const writingSectionBackendIds", self.source, re.S)
        self.assertIsNotNone(match, "EligibilityPage source not found")
        return match.group(0)

    def test_eligibility_primary_surface_uses_raw_source_not_legacy_subject_results(self):
        page = self._eligibility_page()

        self.assertIn("候选受试者池", page)
        self.assertIn("受试者逐条标准审阅", page)
        self.assertIn("/eligibility/raw-intake/subjects/${selectedRawSubjectId}/review", page)
        self.assertIn("入选 IN", page)
        self.assertIn("排除 EX", page)
        self.assertIn("/eligibility/raw-intake/subjects", page)
        self.assertIn("系统不会使用其他项目结果填充", page)
        self.assertIn("不作出正式资格审核结论或随机化放行", page)
        self.assertIn("rawTaskPlan", page)
        self.assertIn("rawForbiddenInputs", page)
        self.assertNotIn('dataset?.source_project_code || "MG-K10-SAR-III"', page)
        self.assertNotIn("来自 criteria_rules.md", page)

    def test_legacy_adapter_is_visibly_bounded_to_comparison_area(self):
        page = self._eligibility_page()

        self.assertIn("legacyDataset = dataset", page)
        self.assertIn("legacy-comparison", page)
        self.assertIn("历史系统对照", page)
        self.assertIn("不得用于当前 D001/MY009 原始资料审核输入", page)

    def test_raw_subject_summary_and_pending_state_are_wrapped(self):
        self.assertIn(".eligibility-subject-summary", self.styles)
        self.assertIn(".raw-pending-state", self.styles)
        self.assertIn("overflow-wrap: anywhere;", self.styles)
        self.assertIn(".legacy-comparison", self.styles)
        self.assertIn(".eligibility-criterion-list", self.styles)
        self.assertIn(".eligibility-inspector-scroll", self.styles)
        self.assertIn("height: min(730px, calc(100vh - 270px));", self.styles)

    def test_subject_switch_clears_stale_detail_and_rejects_late_responses(self):
        page = self._eligibility_page()

        self.assertIn("const rawSubjectRequestIdRef = useRef(0);", page)
        self.assertIn("const handleRawSubjectSelect = (subjectId) =>", page)
        self.assertIn("setSelectedRawSubject(null);", page)
        self.assertIn("requestId === rawSubjectRequestIdRef.current", page)
        self.assertIn("data.project_id === data.subject?.project_id", page)
        self.assertIn("data.subject?.subject_id === selectedRawSubjectId", page)
        self.assertIn("onClick={() => handleRawSubjectSelect(row.subject_id)}", page)

    def test_medical_actions_are_versioned_evidence_bound_and_conflict_visible(self):
        page = self._eligibility_page()

        self.assertIn("expected_state_revision: selectedCriterionState?.state_revision || 0", page)
        self.assertIn("expected_rule_revision: reviewPackage.rule_revision", page)
        self.assertIn("expected_subject_source_revision: reviewPackage.subject_source_revision", page)
        self.assertIn("evidence_ids: actionEvidenceIds", page)
        self.assertIn('response.status === 409', page)
        self.assertIn("刷新审阅状态", page)
        self.assertIn('submitReviewAction("request_evidence")', page)
        self.assertIn('submitReviewAction("defer_review")', page)
        self.assertIn('submitReviewAction("reset_after_source_change")', page)

    def test_ai_draft_and_medical_decision_are_separate_and_reason_is_never_auto_filled(self):
        page = self._eligibility_page()

        self.assertIn("AI 草稿", page)
        self.assertIn("医学判断", page)
        self.assertIn("医学理由（必填）", page)
        self.assertIn('value={reviewReason}', page)
        self.assertIn('preservedReviewReasonRef', page)
        self.assertIn('reloadReviewPackage(true)', page)
        self.assertIn('重新载入审阅包', page)
        for label in ["未开始", "排队中", "处理中", "部分完成", "已完成", "提取失败", "待视觉复核", "不适用"]:
            self.assertIn(label, self.source)

        for forbidden_conclusion in [
            "资格审核通过",
            "正式资格结论：合格",
            "筛选通过",
            "可随机化",
            "允许随机化",
            "入组合格",
            "不合格",
        ]:
            self.assertNotIn(forbidden_conclusion, page)
        self.assertIn('setReviewReason(event.target.value)', page)
        self.assertNotIn('setReviewReason("Current versioned evidence', page)
        self.assertIn('submitReviewAction("accept_ai_draft")', page)

    def test_inclusion_and_exclusion_use_distinct_decision_options(self):
        page = self._eligibility_page()

        self.assertIn('{ value: "met", label: "符合该纳入条件" }', page)
        self.assertIn('{ value: "not_met", label: "不符合该纳入条件" }', page)
        self.assertIn('{ value: "absent", label: "未发现该排除条件" }', page)
        self.assertIn('{ value: "present", label: "存在该排除条件" }', page)
        self.assertIn("证据不足", page)
        self.assertIn("需研究者判断", page)

    def test_source_admission_is_loaded_confirmable_and_preserves_warning_fact(self):
        page = self._eligibility_page()

        self.assertIn("/eligibility/source-admission/refresh", page)
        self.assertIn("/content-validation/confirm", page)
        self.assertIn("expected_revision: admissionConfirmationTarget.expectedRevision", page)
        self.assertIn("acknowledged_check_codes: admissionAcknowledgedCodes", page)
        self.assertIn("确认沿用不代表系统判定已转为匹配", page)
        self.assertIn("目录及文件构成核验，不代表已完成逐文件医学内容核验", page)
        self.assertIn("已确认沿用", page)
        self.assertNotIn("确认溯用", page)
        self.assertNotIn("已确认溯用", page)

    def test_source_admission_guards_all_eligibility_write_actions_but_not_read_only_qc(self):
        page = self._eligibility_page()

        self.assertIn("const sourceAdmissionReady = Boolean(sourceAdmission?.ready_for_use);", page)
        self.assertIn("&& sourceAdmissionReady", page)
        self.assertIn("reviewActionBusy || !sourceAdmissionReady", page)
        self.assertIn("eligibility_source_confirmation_required", page)
        self.assertIn("原始资料视觉 QC", page)
        self.assertNotIn("disabled={!sourceAdmissionReady}", page.split("原始资料视觉 QC", 1)[0])

    def test_source_admission_layout_is_desktop_first_and_bounded(self):
        self.assertIn(".source-admission-band", self.styles)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr));", self.styles)
        self.assertIn("overflow-wrap: anywhere;", self.styles)
        self.assertIn("border-radius: 4px", self.styles)


if __name__ == "__main__":
    unittest.main()
