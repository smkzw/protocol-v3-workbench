from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "frontend" / "src" / "App.jsx"
WORKSPACE = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "evidence-design"
    / "EvidenceDesignWorkspace.jsx"
)
STYLES = ROOT / "frontend" / "src" / "styles.css"


class FrontendEvidenceDesignContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = APP.read_text(encoding="utf-8")
        cls.workspace = WORKSPACE.read_text(encoding="utf-8")
        cls.styles = STYLES.read_text(encoding="utf-8")

    def test_app_uses_real_workspace_instead_of_legacy_manifest_page(self):
        self.assertIn(
            'import { EvidenceDesignPage } from "./features/evidence-design/EvidenceDesignWorkspace"',
            self.app,
        )
        evidence_route = self.app[self.app.index('if (activePage === "evidenceDesign")') :]
        evidence_route = evidence_route[: evidence_route.index('if (activePage === "eligibility")')]
        self.assertIn("<EvidenceDesignPage", evidence_route)
        self.assertNotIn("<PlannedModulePage", evidence_route)
        self.assertIn(
            'onOpenApprovals={() => refreshDashboard().finally(() => setActivePage("approvals"))}',
            evidence_route,
        )

    def test_workspace_consumes_all_real_operational_endpoints(self):
        for endpoint in (
            "/evidence-design/packages",
            "/candidates?",
            "/review-actions",
            "/evidence-design/picos-workflow?package_id=",
            "/approval-submissions",
            "/writing-handoffs",
            "/ai-revisions",
        ):
            self.assertIn(endpoint, self.workspace)

    def test_candidate_evidence_uses_server_paging_without_silent_slice(self):
        self.assertIn('params.set("page", String(candidatePage))', self.workspace)
        self.assertIn('params.set("page_size", String(candidatePageSize))', self.workspace)
        self.assertIn("candidatePageData?.has_next", self.workspace)
        self.assertIsNone(re.search(r"\.slice\s*\(\s*0\s*,", self.workspace))
        self.assertIn("candidatePageData.items.map", self.workspace)

    def test_project_package_requests_are_independently_abortable(self):
        self.assertIn("function useAbortRegistry()", self.workspace)
        for channel in (
            "packages",
            "candidates",
            "candidate-detail",
            "picos",
            "ai-threads",
        ):
            self.assertIn(f'getAbortSignal("{channel}")', self.workspace)
        self.assertIn("setSelectedPackageId(\"\")", self.workspace)
        self.assertIn("packageIds.has(current)", self.workspace)

    def test_all_review_actions_use_cas_and_required_medical_inputs(self):
        for action in (
            "include",
            "exclude",
            "defer",
            "mark_duplicate",
            "save_extraction",
            "save_appraisal",
            "reset_review",
        ):
            self.assertIn(f'"{action}"', self.workspace)
        self.assertIn("expected_revision: candidateReview?.revision || 0", self.workspace)
        self.assertIn('idempotency_key: idempotencyKey("evidence-review")', self.workspace)
        self.assertIn("!reasonDraft.trim()", self.workspace)
        self.assertIn("!hasExtraction", self.workspace)

    def test_picos_state_is_scoped_and_all_mutations_are_revision_bound(self):
        self.assertIn(
            '`${projectId}:${selectedPackageId}:${questionId}`',
            self.workspace,
        )
        self.assertIn("expected_revision: picosWorkflow?.revision || 0", self.workspace)
        self.assertIn(
            "expected_evidence_package_hash: picosWorkflow?.evidence_package_hash || \"\"",
            self.workspace,
        )
        self.assertIn("证据综合", self.workspace)
        self.assertIn("step.picos_domain", self.workspace)
        for label in ("PICOS方案设计", "作者确认", "撰写交接"):
            self.assertIn(label, self.workspace)

    def test_ai_acceptance_requires_a_separate_explicit_picos_action(self):
        self.assertIn("采纳建议", self.workspace)
        self.assertIn("应用到PICOS", self.workspace)
        self.assertIn("applyAcceptedToPicos", self.workspace)
        accept_block = self.workspace[
            self.workspace.index("const applyAiAction") : self.workspace.index(
                "const applyAcceptedToPicos"
            )
        ]
        self.assertNotIn("submitPicosAction", accept_block)
        self.assertIn("expected_thread_revision: thread.revision", self.workspace)
        self.assertIn("evidence_span_ids", self.workspace)

    def test_ai_is_fail_closed_and_does_not_expose_provider_configuration(self):
        self.assertIn("独立AI未配置或未获私有化执行许可", self.workspace)
        for forbidden in ("deepseek", "kimi", "minimax", "buddy", "opencode", "reasonix"):
            self.assertNotIn(forbidden, self.workspace.lower())
        self.assertNotIn("missing_env", self.workspace)

    def test_semantic_ai_action_requires_literal_boolean_true(self):
        self.assertIn(
            "aiGatewayStatus?.semantic_ai_tasks_enabled === true",
            self.workspace,
        )
        self.assertNotIn(
            "aiGatewayStatus?.semantic_ai_tasks_enabled ?",
            self.workspace,
        )

    def test_author_confirmation_and_handoff_are_current_snapshot_gated(self):
        self.assertIn("allDomainsConfirmed", self.workspace)
        self.assertIn("preConfirmationBlockingGates", self.workspace)
        self.assertIn('"picos:gate:author_confirmation"', self.workspace)
        self.assertIn('"in_medical_review"', self.workspace)
        self.assertIn('"returned_for_revision"', self.workspace)
        self.assertIn('"作者已确认"', self.workspace)
        self.assertIn("保存修订并采用", self.workspace)
        self.assertIn("生成版本快照与撰写交接", self.workspace)
        self.assertNotIn("确认当前域", self.workspace)
        self.assertNotIn("确认并生成快照", self.workspace)
        self.assertNotIn("handoffCreated", self.workspace)
        self.assertNotIn("提交医学批准", self.workspace)
        self.assertNotIn("待医学批准", self.workspace)
        self.assertNotIn("onOpenApprovals?.()", self.workspace)
        self.assertIn("approved_snapshot_id", self.workspace)
        self.assertIn("current_handoff_id", self.workspace)
        self.assertIn("current_handoff_snapshot_id", self.workspace)
        self.assertIn("current_handoff_revision", self.workspace)
        self.assertIn('selectedStep.author_confirmation_status === "confirmed"', self.workspace)
        self.assertIn('target_document_type: "protocol"', self.workspace)

    def test_paths_and_internal_lifecycle_labels_are_not_rendered(self):
        self.assertNotIn("source_root_label", self.workspace)
        self.assertIn("safeMetaValue", self.workspace)
        self.assertIsNone(
            re.search(r"第[一二三四五六七八九0-9]+环节|阶段[0-9一二三四五六七八九]", self.workspace)
        )

    def test_desktop_workspace_has_stable_internal_scroll_contract(self):
        self.assertIn(".evidence-workspace-grid", self.styles)
        self.assertIn("height: clamp(680px, calc(100vh - 210px), 880px)", self.styles)
        self.assertIn(".evidence-table-scroll", self.styles)
        self.assertIn("min-width: 920px", self.styles)
        self.assertIn(".evidence-right-rail", self.styles)
        self.assertIn("overflow: auto", self.styles)

    def test_legacy_approval_center_language_remains_available_for_historical_picos(self):
        self.assertIn('targetType === "evidence_picos_snapshot"', self.app)
        self.assertIn("PICOS方案设计医学批准", self.app)
        self.assertIn("当前证据资料包与PICOS版本快照", self.app)
        self.assertIn(
            '{approvalMessage && <div className="approval-message">{approvalMessage}</div>}',
            self.app,
        )

    def test_internal_pending_user_status_is_rendered_as_medical_confirmation(self):
        self.assertIn('待用户确认: "待医学确认"', self.workspace)
        self.assertIn("picosStatusLabel(step.decision_status)", self.workspace)
        self.assertIn("picosStatusLabel(selectedStep.decision_status)", self.workspace)


if __name__ == "__main__":
    unittest.main()
