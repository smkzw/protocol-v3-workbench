from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BATCH_SOURCE = (
    ROOT
    / "frontend/src/features/writing-reference/ReferenceTranslationBatchPanel.jsx"
)
REFERENCE_SOURCE = (
    ROOT
    / "frontend/src/features/writing-reference/WritingReferencePanel.jsx"
)
APP_SOURCE = ROOT / "frontend/src/App.jsx"
STYLES_SOURCE = ROOT / "frontend/src/styles.css"


class FrontendMedicalWritingTranslationBatchContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.batch = BATCH_SOURCE.read_text(encoding="utf-8")
        cls.reference = REFERENCE_SOURCE.read_text(encoding="utf-8")
        cls.app = APP_SOURCE.read_text(encoding="utf-8")
        cls.styles = STYLES_SOURCE.read_text(encoding="utf-8")

    def test_batch_panel_is_only_on_the_authoring_translations_surface(self):
        self.assertIn('{ id: "translations", label: "结构与译文确认" }', self.reference)
        self.assertEqual(1, self.reference.count("<ReferenceTranslationBatchPanel"))

        documents_start = self.reference.index('{activeView === "documents" && (')
        translations_start = self.reference.index('{activeView === "translations" && (')
        approved_start = self.reference.index('{activeView === "approved" && (')
        documents = self.reference[documents_start:translations_start]
        translations = self.reference[translations_start:approved_start]
        self.assertIn("authoringMode && (", translations)
        self.assertIn("<ReferenceTranslationBatchPanel", translations)
        self.assertNotIn("ReferenceTranslationBatchPanel", documents)
        self.assertNotIn("ReferenceTranslationBatchPanel", self.app)
        self.assertNotIn("translation-batches", self.app)

    def test_batch_api_contract_uses_snapshot_glossary_and_anchor_scope(self):
        for route in (
            "references/translation-batches/preview?${params.toString()}",
            "references/translation-batches/latest?snapshot_id=${encodeURIComponent(snapshotId)}",
            "references/translation-batches/${encodeURIComponent(batchId)}",
            "references/translation-batches/${encodeURIComponent(batchId)}/retry",
            "references/translation-batches/${encodeURIComponent(batchId)}/medical-review",
        ):
            self.assertIn(route, self.batch)

        self.assertIn("params.append(\"anchor_filter\", anchor)", self.batch)
        create = re.search(
            r"references/translation-batches`, \{\s*method: \"POST\".*?body: JSON\.stringify\(\{(?P<body>.*?)\}\),",
            self.batch,
            re.S,
        )
        self.assertIsNotNone(create, "Translation batch create payload not found")
        create_body = create.group("body")
        for expected in (
            "snapshot_id: snapshotId",
            "glossary_version: glossaryVersion",
            "anchor_filter: selectedAnchors",
            'actor: "medical_manager"',
            "idempotency_key: createKeyRef.current",
        ):
            self.assertIn(expected, create_body)
        self.assertNotIn("span_id", create_body)
        self.assertNotIn("source_span", create_body)

        request_bodies = re.findall(
            r"body: JSON\.stringify\(\{(?P<body>.*?)\}\)", self.batch, re.S
        )
        self.assertGreaterEqual(len(request_bodies), 2)
        for request_body in request_bodies:
            self.assertNotIn("span_id", request_body)
            self.assertNotIn("source_span", request_body)

    def test_batch_confirm_is_one_bounded_batch_action_not_per_item_loop(self):
        # The panel may confirm eligible candidates only through the single
        # batch-scoped medical-review route; per-item review/admission routes
        # stay on the single-fragment surface.
        for forbidden_route in (
            "/admissions",
            "translation-batches/review",
            "translation-batches/admit",
            "references/translations/${",
        ):
            self.assertNotIn(forbidden_route, self.batch)
        batch_review_route = "translation-batches/${encodeURIComponent(batchId)}/medical-review"
        self.assertEqual(1, self.batch.count(batch_review_route))

        actions = set(re.findall(r'data-action="([^"]+)"', self.batch))
        self.assertEqual(
            {
                "start-translation-batch",
                "refresh-translation-batch",
                "retry-translation-failed",
                "batch-confirm-eligible-translations",
                "open-translation-span",
                "cancel-translation-job",
            },
            actions,
        )
        self.assertNotIn("批量批准", self.batch)
        self.assertNotIn("批量准入", self.batch)

    def test_batch_confirm_posts_pinned_targets_then_refreshes(self):
        for contract in (
            "function batchReviewEligibleRow(row)",
            'row.generationStatus === "candidate_ready"',
            'row.fidelityStatus === "passed"',
            'row.authorConfirmationStatus === "not_confirmed"',
            'row.admissionStatus !== "invalidated"',
            "row.translationRevision >= 1",
            "const batchReviewEligibleRows = useMemo(",
            "visibleRows.filter(batchReviewEligibleRow)",
            "translation_id: row.translationId",
            "translation_revision: row.translationRevision",
            'actor: "medical_manager"',
            "idempotency_key: batchReviewKeyRef.current.key",
            'batchReviewKeyRef.current = { batchId: "", key: "" }',
            "await loadBatch(batchId)",
            "await onBatchSettled()",
            "一键确认合格候选",
            "一键确认完成：已确认",
            "一键确认未完成",
            "!batchReviewEligibleRows.length",
        ):
            self.assertIn(contract, self.batch)
        # No automatic approval: the action fires only from the explicit click.
        handler = re.search(
            r'onClick=\{batchConfirmEligible\}[^>]*disabled=\{(?P<disabled>[^}]*)\}',
            self.batch,
        )
        self.assertIsNotNone(handler)
        self.assertIn("Boolean(action)", handler.group("disabled"))
        self.assertIn("active", handler.group("disabled"))

    def test_parent_reconciles_corpus_gate_after_batch_settlement(self):
        handler = "const refreshAuthoringAfterBatchSettled = async () => {"
        self.assertIn(handler, self.reference)
        block_start = self.reference.index(handler)
        block = self.reference[block_start:self.reference.index("  const adoptTriageRun", block_start)]
        for contract in (
            "await refreshWorkspace({ preserveMessage: true })",
            "/authoring-journey/corpus-gate/recalculate",
            "{ method: \"POST\" }",
            "/authoring-journey?allow_missing=true",
            "onJourneyChange(authoritative.available === false ? recalculated : authoritative)",
        ):
            self.assertIn(contract, block)
        self.assertIn("onBatchSettled={refreshAuthoringAfterBatchSettled}", self.reference)

    def test_scope_defaults_to_all_eligible_mapped_anchors_and_shows_preview_counts(self):
        for contract in (
            "preview?.anchor_summaries || []",
            "summary.ich_m11_anchor",
            "summary.eligible_new",
            "summary.existing_candidate",
            "summary.fidelity_blocked",
            'option.value.toLowerCase() !== "unmapped"',
            "setSelectedAnchors(returnedAnchors.map((item) => item.value))",
            'type="checkbox"',
            "selectedAnchors.includes(anchor.value)",
            "M11 结构范围（已选",
            "预计新生成",
            "复用当前契约候选",
            "排除",
        ):
            self.assertIn(contract, self.batch)
        self.assertNotIn("RA 项目", self.batch)

    def test_latest_batch_restores_its_frozen_scope_and_never_mixes_other_preview_counts(self):
        for contract in (
            "setSelectedAnchors([...payload.anchor_filter])",
            "const batchMatchesSelection = Boolean(batch)",
            "selectedScopeMatchesPreview(batch, selectedAnchors)",
            "const visibleBatch = batchMatchesSelection ? batch : null",
            "当前范围批次",
            "当前选择与最近批次的冻结范围不同",
            "!batchMatchesSelection || !batchId",
        ):
            self.assertIn(contract, self.batch)
        self.assertIn("(visibleBatch?.items || []).map(normalizeItem)", self.batch)

    def test_real_typed_statuses_counts_and_preview_scope_drive_the_ui(self):
        for contract in (
            '"completed_with_blocked"',
            '"excluded"',
            '"candidate_ready"',
            '"fidelity_blocked"',
            '"failed_retryable"',
            '"failed_terminal"',
            "counts.candidate_ready_count",
            "counts.fidelity_blocked_count",
            "counts.failed_count",
            "counts.pending_author_confirmation_count",
            "counts.author_confirmed_count",
            "counts.admitted_count",
            "counts.reused_count",
            "counts.excluded_count",
            "preview?.eligible_count",
            "preview?.eligible_new_count",
            "preview?.existing_candidate_count",
            "preview?.fidelity_blocked_count",
        ):
            self.assertIn(contract, self.batch)
        self.assertIn(
            "const previewEligibleCount = previewMatchesSelection ? safeCount(preview?.eligible_count) : 0",
            self.batch,
        )
        self.assertIn("previewEligibleCount === 0", self.batch)
        self.assertNotIn("countValue", self.batch)
        self.assertNotIn("payloadRoots", self.batch)
        self.assertNotIn('"in_progress"', self.batch)
        self.assertNotIn('"completed_with_failures"', self.batch)
        self.assertNotIn("expected_new_count", self.batch)
        self.assertNotIn("generated_count", self.batch)

    def test_document_plan_exclusions_are_terminal_visible_and_not_reviewable(self):
        for contract in (
            'excluded: ["规划后排除", "neutral"]',
            'row.generationStatus === "excluded"',
            "不在所选章节范围，无需生成",
            '<option value="excluded">规划后排除</option>',
            "safeCount(counts.excluded_count, previewExcludedCount)",
        ):
            self.assertIn(contract, self.batch)
        self.assertIn(
            'disabled={row.generationStatus === "excluded" || !row.artifactId || !row.spanId}',
            self.batch,
        )

    def test_author_counts_filters_sort_retry_and_deep_link_are_visible(self):
        for label in (
            "当前批次",
            "符合条件",
            "已生成候选",
            "忠实度阻断",
            "失败",
            "待作者确认",
            "作者已确认",
            "已准入",
            "状态筛选",
            "Anchor 筛选",
            "研究 / 文件",
            "M11 结构与来源定位",
            "生成状态",
            "忠实度",
            "作者确认",
            "准入",
            "下一步",
            "仅重试失败项",
            "核对译文",
            'option value="pending">待生成',
            'option value="running">生成中',
        ):
            self.assertIn(label, self.batch)
        self.assertIn("<SortHeader", self.batch)
        self.assertIn("setSort((current)", self.batch)
        self.assertIn("onOpenSpan({ artifact_id: row.artifactId, span_id: row.spanId", self.batch)
        self.assertIn("data-admission-status={row.admissionStatus}", self.batch)

        for parent_state in (
            "setSelectedArtifactId(item.artifact_id)",
            "setSpanAnchorFilter(anchor)",
            "setSpanOffset(Math.max(0, Number(item.span_offset || 0)))",
            "setSelectedSpanId(item.span_id)",
            'setActiveView("translations")',
            "translationReviewRef.current?.scrollIntoView",
        ):
            self.assertIn(parent_state, self.reference)
        self.assertIn("onOpenSpan={openTranslationBatchSpan}", self.reference)

    def test_zero_eligible_state_is_cross_project_and_creation_is_disabled(self):
        for contract in (
            'data-testid="translation-batch-zero-eligible"',
            "当前范围没有可批量生成的合格片段",
            "零 eligible 是合法结果",
            "没有可用公开Protocol",
            "文件内容核验与结构医学审核双门禁尚未完成",
            "手动导入已取得的Protocol",
            "阶段一处理",
            "previewEligibleCount === 0",
        ):
            self.assertIn(contract, self.batch)

    def test_cross_page_source_keeps_complete_text_primary_and_provenance_collapsible(self):
        for contract in (
            "原始方案内容",
            "selectedSpan.source_text",
            "writing-reference-cross-page-source",
            "selectedSpan.source_fragments?.length > 1",
            "item.source_text",
            "selectedSpan.skipped_interstitials?.length > 0",
            "重复页眉",
            "重复页脚",
        ):
            self.assertIn(contract, self.reference)
        self.assertIn(
            'validation_extraction_stale: "文件内容核验未绑定当前结构解析版本"',
            self.batch,
        )
        self.assertIn(".writing-reference-cross-page-source", self.styles)

    def test_exclusions_are_secondary_grouped_decision_information_not_logs(self):
        self.assertIn('<details className="writing-reference-translation-exclusions">', self.batch)
        self.assertIn("exclusionGroups.map", self.batch)
        self.assertIn("EXCLUSION_EXAMPLE_LIMIT = 4", self.batch)
        self.assertIn("preview?.document_exclusion_reason_counts", self.batch)
        self.assertIn("preview?.span_exclusion_reason_counts", self.batch)
        self.assertIn("group.examples.map", self.batch)
        self.assertIn("项未展开", self.batch)
        self.assertIn("研究待确认", self.batch)
        for forbidden in ("运行日志", "stdout", "stderr", "traceback"):
            self.assertNotIn(forbidden, self.batch.lower())

    def test_anchor_scope_change_invalidates_the_create_idempotency_key(self):
        self.assertIn("const selectedAnchorKey = useMemo", self.batch)
        self.assertIn('createKeyRef.current = "";', self.batch)
        reset_effect = re.search(
            r'useEffect\(\(\) => \{\s*createKeyRef\.current = "";\s*\}, \[selectedAnchorKey\]\)',
            self.batch,
        )
        self.assertIsNotNone(reset_effect)
        self.assertIn("const toggleAnchor = (anchor, checked) => {", self.batch)
        self.assertIn("previewMatchesSelection", self.batch)

    def test_batch_rows_use_the_typed_file_and_document_fields(self):
        self.assertIn('filename: item.filename || ""', self.batch)
        self.assertIn('documentType: item.document_type || ""', self.batch)
        self.assertIn('row.filename || "文件名待后端补充"', self.batch)
        self.assertIn("row.documentType", self.batch)

    def test_chinese_clinical_boundary_and_missing_fields_are_explicit(self):
        for label in (
            "监管中文候选批次",
            "机器忠实度检查只验证候选与原文的一致性；通过后由医学作者一键确认合格候选或逐片段核对，确认即直接准入",
            "逐片段核对并确认",
            "核对原文与忠实度问题",
            "终止失败",
            "完成，有忠实度阻断",
            "当前监管术语契约",
        ):
            self.assertIn(label, self.batch)
        self.assertIn("function safeCount(value, fallback = 0)", self.batch)
        self.assertIn('payload.detail?.message || payload.message || `HTTP ${response.status}`', self.batch)
        self.assertIn("候选范围预览失败", self.batch)
        self.assertIn("当前批次读取失败", self.batch)
        self.assertIn("批次状态轮询", self.batch)

    def test_desktop_table_uses_internal_overflow_without_nested_cards(self):
        for selector in (
            ".writing-reference-translation-batch",
            ".writing-reference-translation-summary",
            ".writing-reference-translation-table-tools",
            ".writing-reference-translation-table-wrap",
            ".writing-reference-translation-table",
            ".writing-reference-translation-exclusions",
        ):
            self.assertIn(selector, self.styles)
        table_wrap = re.search(
            r"\.writing-reference-translation-table-wrap \{(?P<body>.*?)\}",
            self.styles,
            re.S,
        )
        self.assertIsNotNone(table_wrap)
        self.assertIn("overflow-x: auto", table_wrap.group("body"))
        self.assertIn("min-width: 1160px", self.styles)
        self.assertIn("grid-template-columns: repeat(8", self.styles)


if __name__ == "__main__":
    unittest.main()
