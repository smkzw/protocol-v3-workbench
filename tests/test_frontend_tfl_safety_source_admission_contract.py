from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = ROOT / "frontend" / "src" / "App.jsx"
STYLE_SOURCE = ROOT / "frontend" / "src" / "styles.css"


class FrontendTflSafetySourceAdmissionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP_SOURCE.read_text(encoding="utf-8")
        cls.styles = STYLE_SOURCE.read_text(encoding="utf-8")

    def _component(self) -> str:
        match = re.search(
            r"function ModuleSourceAdmissionBand\(.*?const writingSectionBackendIds",
            self.source,
            re.S,
        )
        self.assertIsNotNone(match)
        return match.group(0)

    def test_shared_component_preserves_warning_and_requires_exact_confirmation(self):
        component = self._component()
        self.assertIn("/content-validation/confirm", component)
        self.assertIn("acknowledged_check_codes: acknowledgedCodes", component)
        self.assertIn("expected_revision: target.revision", component)
        self.assertIn("reason.trim().length >= 10", component)
        self.assertIn("不会将原内容状态改为“匹配”", component)
        self.assertIn("已确认沿用", component)
        self.assertNotIn("安全扫描", component)

    def test_tfl_and_safety_place_admission_before_their_review_workbenches(self):
        tfl = re.search(r"function TflManifestPanel\(.*?function SafetyPvManifestPanel", self.source, re.S).group(0)
        safety = re.search(r"function SafetyPvManifestPanel\(.*?function PicosDecisionWorkspace", self.source, re.S).group(0)
        self.assertLess(tfl.index("<ModuleSourceAdmissionBand"), tfl.index('className="tfl-review-workbench"'))
        self.assertLess(safety.index("<ModuleSourceAdmissionBand"), safety.index('className="safety-review-workbench"'))
        self.assertIn('contextLabel="TFL审阅"', tfl)
        self.assertIn('contextLabel="安全信号审阅与PV协同"', safety)

    def test_frontend_gates_only_source_dependent_dispositions(self):
        self.assertIn('["mark_reviewed", "create_writing_candidate"].includes(action)', self.source)
        self.assertIn('["mark_medical_reviewed", "request_pv_confirmation", "accept_no_action"].includes(action)', self.source)
        self.assertIn("需先完成当前来源的内容核验或确认沿用", self.source)
        self.assertIn("标记写作引用候选须同时满足", self.source)
        self.assertIn("基于当前来源版本完成医学审阅", self.source)
        self.assertIn("基于当前来源版本保存医学意见", self.source)

    def test_structured_409_updates_current_admission_state(self):
        self.assertIn("payload.detail?.source_admission", self.source)
        self.assertIn("setTflReviewWorkbench((current)", self.source)
        self.assertIn("setSafetyReviewWorkbench((current)", self.source)
        self.assertIn("apiDetailText(payload", self.source)

    def test_review_action_responses_require_current_project_identity_before_commit(self):
        tfl_match = re.search(
            r"const applyTflReviewAction = async .*?const refreshSafetyManifest",
            self.source,
            re.S,
        )
        self.assertIsNotNone(tfl_match)
        tfl = tfl_match.group(0)
        tfl_guard = "payload?.project_id !== plannedModuleProjectIdRef.current"
        self.assertIn(tfl_guard, tfl)
        self.assertIn("TFL审阅响应项目身份不匹配，未更新当前审阅状态。", tfl)
        self.assertLess(tfl.index(tfl_guard), tfl.index("setTflReviewWorkbench(payload)"))

        safety_match = re.search(
            r"const applySafetyReviewAction = async .*?const registerCandidate",
            self.source,
            re.S,
        )
        self.assertIsNotNone(safety_match)
        safety = safety_match.group(0)
        self.assertIn(tfl_guard, safety)
        self.assertIn("安全信号审阅响应项目身份不匹配，未更新当前审阅状态。", safety)
        self.assertLess(safety.index(tfl_guard), safety.index("const currentSelection = safetySelectionRef.current"))

    def test_shared_source_confirmation_requires_project_identity_before_refresh(self):
        match = re.search(
            r"function ModuleSourceAdmissionBand\(.*?function revisionThreadStatusLabel",
            self.source,
            re.S,
        )
        self.assertIsNotNone(match)
        band = match.group(0)
        guard = "payload?.project_id !== projectId"
        self.assertIn(guard, band)
        self.assertIn("来源确认响应项目身份不匹配，未更新当前来源状态。", band)
        self.assertLess(band.index(guard), band.index("setMessage(\"确认已记录"))
        self.assertLess(band.index(guard), band.index("await onRefresh()"))

    def test_safety_backend_current_status_overrides_stale_persisted_record(self):
        self.assertIn(
            'const currentStatus = reviewWorkbench?.current_status || latestReviewStatus',
            self.source,
        )
        self.assertNotIn(
            'const currentStatus = latestReviewStatus || reviewWorkbench?.current_status',
            self.source,
        )

    def test_layout_is_compact_when_ready_and_bounds_expanded_confirmation(self):
        self.assertIn(".module-source-admission-head", self.styles)
        self.assertIn("grid-template-columns: auto auto minmax(220px, 1fr) auto auto auto;", self.styles)
        self.assertIn("grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));", self.styles)
        self.assertIn("max-height: 44vh;", self.styles)
        self.assertIn("overflow-y: auto;", self.styles)
        self.assertIn("border-radius: 4px", self.styles)


if __name__ == "__main__":
    unittest.main()
