from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = ROOT / "frontend" / "src" / "App.jsx"
STYLES_SOURCE = ROOT / "frontend" / "src" / "styles.css"
WRITING_QC_SOURCE = ROOT / "frontend" / "tests" / "medical_writing_real_projects_qc.mjs"
WRITING_QC_MANIFEST_SOURCE = ROOT / "frontend" / "tests" / "medical_writing_manifest_qc.mjs"
WRITING_EDITOR_FORMATTING_QC_SOURCE = (
    ROOT / "frontend" / "tests" / "medical_writing_editor_formatting_qc.mjs"
)
AUTHORING_JOURNEY_QC_SOURCE = (
    ROOT / "frontend" / "tests" / "medical_writing_authoring_journey_qc.mjs"
)
AUTHORING_JOURNEY_SOURCE = (
    ROOT / "frontend" / "src" / "features" / "medical-writing"
    / "MedicalWritingAuthoringJourneySetup.jsx"
)
AUTHORING_JOURNEY_STYLES_SOURCE = (
    ROOT / "frontend" / "src" / "features" / "medical-writing"
    / "MedicalWritingAuthoringJourneySetup.css"
)
WRITING_REFERENCE_SOURCE = (
    ROOT / "frontend" / "src" / "features" / "writing-reference"
    / "WritingReferencePanel.jsx"
)
REFERENCE_PREPARATION_BATCH_SOURCE = (
    ROOT / "frontend" / "src" / "features" / "writing-reference"
    / "ReferencePreparationBatchPanel.jsx"
)
REFERENCE_TRANSLATION_BATCH_SOURCE = (
    ROOT / "frontend" / "src" / "features" / "writing-reference"
    / "ReferenceTranslationBatchPanel.jsx"
)
WRITING_LITERATURE_SOURCE = (
    ROOT / "frontend" / "src" / "features" / "medical-writing"
    / "MedicalWritingLiteraturePanel.jsx"
)
WRITING_LITERATURE_CITATION_QC_SOURCE = (
    ROOT / "frontend" / "tests" / "medical_writing_literature_citation_qc.mjs"
)
STUDY_SCHEMA_EDITOR_SOURCE = (
    ROOT / "frontend" / "src" / "features" / "medical-writing"
    / "StudySchemaEditor.jsx"
)
LEGACY_AUTHORING_BOOTSTRAP_SOURCE = (
    ROOT / "frontend" / "src" / "features" / "medical-writing"
    / "LegacyAuthoringBootstrapPanel.jsx"
)
AUTHORING_JOURNEY_SERVICE_SOURCE = (
    ROOT / "services" / "api" / "app" / "medical_writing_authoring_journey.py"
)


class FrontendMedicalWritingContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP_SOURCE.read_text(encoding="utf-8")
        cls.styles = STYLES_SOURCE.read_text(encoding="utf-8")
        cls.qc_source = WRITING_QC_SOURCE.read_text(encoding="utf-8")
        cls.editor_formatting_qc_source = WRITING_EDITOR_FORMATTING_QC_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.authoring_journey_source = AUTHORING_JOURNEY_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.authoring_journey_styles = AUTHORING_JOURNEY_STYLES_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.authoring_journey_qc = AUTHORING_JOURNEY_QC_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.writing_reference_source = WRITING_REFERENCE_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.reference_preparation_batch_source = (
            REFERENCE_PREPARATION_BATCH_SOURCE.read_text(encoding="utf-8")
        )
        cls.reference_translation_batch_source = (
            REFERENCE_TRANSLATION_BATCH_SOURCE.read_text(encoding="utf-8")
        )
        cls.writing_literature_source = WRITING_LITERATURE_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.writing_literature_citation_qc_source = (
            WRITING_LITERATURE_CITATION_QC_SOURCE.read_text(encoding="utf-8")
        )
        cls.study_schema_editor_source = STUDY_SCHEMA_EDITOR_SOURCE.read_text(
            encoding="utf-8"
        )
        cls.legacy_authoring_bootstrap_source = (
            LEGACY_AUTHORING_BOOTSTRAP_SOURCE.read_text(encoding="utf-8")
        )
        cls.authoring_journey_service_source = (
            AUTHORING_JOURNEY_SERVICE_SOURCE.read_text(encoding="utf-8")
        )

    def _writing_page(self) -> str:
        match = re.search(r"function WritingPage\(.*?function approvalTypeLabel", self.source, re.S)
        self.assertIsNotNone(match, "WritingPage source not found")
        return match.group(0)

    def _source_between(self, source: str, start: str, end: str) -> str:
        start_index = source.find(start)
        self.assertGreaterEqual(start_index, 0, f"Start marker not found: {start}")
        end_index = source.find(end, start_index + len(start))
        self.assertGreaterEqual(end_index, 0, f"End marker not found after {start}: {end}")
        return source[start_index:end_index]

    # --- Existing tests (preserved) ---

    def test_writing_page_fetches_and_submits_revision_threads(self):
        writing = self._writing_page()

        self.assertIn("refreshRevisionThreads", writing)
        self.assertIn("fetch(`/api/projects/${projectId}/revision-threads`)", writing)
        self.assertIn("submitRevisionRequest", writing)
        self.assertIn('method: "POST"', writing)
        self.assertIn("selected_text", writing)
        self.assertIn("user_instruction", writing)
        self.assertIn("requested_by", writing)

    def test_frontend_section_id_maps_to_backend_protocol_section(self):
        self.assertIn('endpoints: "sec_objectives_endpoints"', self.source)
        self.assertIn("isDemoWritingSession ? writingBackendSectionId(selectedSection) : selectedSection", self.source)
        self.assertIn("section_id: backendSectionId", self.source)
        self.assertNotIn('|| "sec_objectives_endpoints"', self.source)

        section_block = re.search(r"const writingSections = \[(?P<body>.*?)\];", self.source, re.S)
        mapping_block = re.search(r"const writingSectionBackendIds = \{(?P<body>.*?)\};", self.source, re.S)
        self.assertIsNotNone(section_block, "writingSections not found")
        self.assertIsNotNone(mapping_block, "writingSectionBackendIds not found")
        section_ids = re.findall(r'id: "([^"]+)"', section_block.group("body"))
        mapped_ids = set(re.findall(r"\n\s*([a-zA-Z0-9_]+):\s*\"sec_", mapping_block.group("body")))
        unmapped_ids = [section_id for section_id in section_ids if section_id not in mapped_ids]

        self.assertTrue(unmapped_ids, "This contract should cover sections that are not backend-bound yet")
        self.assertIn("sectionHasBackendBinding", self.source)
        self.assertIn("暂无后端章节绑定", self.source)
        self.assertIn("!sectionHasBackendBinding", self.source)

    def test_document_editor_and_ai_rail_are_the_only_persistent_workspace_columns(self):
        writing = self._writing_page()

        self.assertIn("writing-layout writing-editor-first-layout", writing)
        self.assertIn("panel editor-panel writing-editor-core", writing)
        self.assertIn('className="panel ai-rail writing-ai-core"', writing)
        self.assertNotIn("<MedicalWritingManifestPanel", writing)
        self.assertNotIn('className="writing-support-zone"', writing)

    def test_authoring_journey_uses_wide_pre_document_workspace_and_enforces_corpus_gate(self):
        writing = self._writing_page()
        setup_index = writing.find("<MedicalWritingAuthoringJourneySetup")
        ai_rail_index = writing.find('className="panel ai-rail writing-ai-core"')

        self.assertIn("MedicalWritingAuthoringJourneySetup", self.source)
        self.assertIn("/medical-writing/authoring-journey", self.authoring_journey_source)
        self.assertIn("/authoring-journey/impact-preview", self.authoring_journey_source)
        self.assertIn("/authoring-journey/corpus-gate/override", self.authoring_journey_source)
        self.assertIn("/medical-writing/greenfield-document", self.authoring_journey_source)
        self.assertIn("研究设计引导", self.authoring_journey_source)
        self.assertIn("当前阻断写作", self.authoring_journey_source)
        self.assertIn("确认例外并放行", self.authoring_journey_source)
        self.assertIn("<details className=\"authoring-override\">", self.authoring_journey_source)
        self.assertIn("未就绪状态和医学理由会持续保留", self.authoring_journey_source)
        self.assertNotIn("greenfieldWritingSectionScaffold", self.source)
        self.assertGreaterEqual(setup_index, 0, "Greenfield setup must render inside the writing workspace")
        self.assertGreaterEqual(ai_rail_index, 0, "AI rail must remain available after document creation")
        self.assertLess(setup_index, ai_rail_index)
        self.assertNotIn('path="/medical-writing/greenfield', self.source)
        self.assertIn("if (error?.status === 404)", writing)
        self.assertIn("setWritingManifest(null)", writing)
        self.assertIn("if (!editorSessionAvailable)", writing)
        self.assertIn("setDocumentSessionMessage(\"\")", writing)
        self.assertIn("[projectId, editorSessionAvailable]", writing)
        self.assertIn("const greenfieldSetupAvailable", writing)
        self.assertIn("&& !(greenfieldSetupAvailable && !editorSessionAvailable)", writing)
        self.assertIn('greenfieldSetupAvailable ? "writing-pre-document-layout"', writing)
        self.assertIn("!greenfieldSetupAvailable && <aside", writing)
        self.assertNotIn('className="writing-support-zone"', writing)
        self.assertNotIn("<MedicalWritingManifestPanel", writing)
        self.assertIn(".writing-layout.writing-pre-document-layout", self.styles)
        self.assertIn(".authoring-journey-shell", self.styles)

    def test_new_project_entry_mode_resumes_without_a_second_mode_choice(self):
        writing = self._writing_page()
        authoring = self.authoring_journey_source

        self.assertIn("projectSourceMode={projectSourceMode}", writing)
        self.assertIn('projectSourceMode={activeManifest?.source_mode || ""}', self.source)
        self.assertIn('user_created_from_zero: "guided_greenfield"', authoring)
        self.assertIn('user_created_synopsis_import: "synopsis_import"', authoring)
        self.assertIn("authoringEntryModeForSourceMode(projectSourceMode)", authoring)
        self.assertIn("autoJourneyAttemptRef", authoring)
        self.assertIn("createJourney(preferredEntryMode)", authoring)
        self.assertIn("无需再次选择", authoring)

    def test_created_document_exposes_controlled_study_definition_change_drawer(self):
        writing = self._writing_page()
        authoring = self.authoring_journey_source

        self.assertIn("authoringJourneyAvailable", writing)
        self.assertIn("setStudyDesignOpen(true)", writing)
        self.assertIn('aria-label="研究设计基线"', writing)
        self.assertIn("projectSourceMode={projectSourceMode}", writing)
        self.assertIn("existingDocument", writing)
        self.assertIn("onJourneyChanged={() => refreshStudyConsistency()}", writing)
        self.assertIn("研究设计受控变更", authoring)
        self.assertIn("existingDocument ?", authoring)
        self.assertIn(
            'disabled={interactionLocked || (readOnly && stage !== "corpus")}',
            authoring,
        )
        self.assertIn('!readOnly && <footer className="authoring-journey-footer"', authoring)
        self.assertIn("调整需进入受控变更流程", authoring)
        self.assertIn(".writing-study-design-drawer", self.styles)

    def test_dynamic_protocol_modules_are_medical_manager_decisions_with_cross_document_propagation(self):
        writing = self._writing_page()
        panel_source = (
            ROOT / "frontend" / "src" / "features" / "medical-writing"
            / "ProtocolModuleResolutionPanel.jsx"
        ).read_text(encoding="utf-8")

        self.assertIn("ProtocolModuleResolutionPanel", writing)
        self.assertIn("/greenfield-document/module-resolutions/${encodeURIComponent(resolution.semantic_node_id)}", writing)
        self.assertIn("render_action: draft.renderAction", writing)
        self.assertIn("reset_approval_count", writing)
        self.assertIn("baselineReady={Boolean(greenfieldState?.baseline_revision", writing)
        self.assertIn("医学经理的设计选择立即应用", writing)
        self.assertIn("纳入方案", panel_source)
        self.assertIn("不适用，隐藏章节", panel_source)
        self.assertIn("不适用，保留“不适用”", panel_source)
        self.assertIn("待确定，暂不呈现", panel_source)
        self.assertIn("延后决定，暂不呈现", panel_source)
        self.assertIn("正在同步方案基线", panel_source)
        self.assertIn("同步更新", panel_source)
        self.assertIn("方案摘要", panel_source)
        self.assertIn("研究流程表", panel_source)
        self.assertIn(".protocol-module-resolution-workspace", self.styles)

    def test_study_definition_changes_are_visible_rebound_and_reconciled_before_approval(self):
        writing = self._writing_page()

        self.assertIn("/medical-writing/study-consistency", writing)
        self.assertIn("/study-consistency/rebind-preview", writing)
        self.assertIn("/study-consistency/rebind", writing)
        self.assertIn("/study-consistency/sections/${selectedSection}/confirm", writing)
        self.assertIn("selectedSectionConsistencyBlocked", writing)
        self.assertIn("studyConsistencyBlocksFinal", writing)
        self.assertIn("确认本章已调和", writing)
        self.assertIn("正文不会被系统静默改写", writing)
        self.assertIn(".writing-study-rebind-drawer", self.styles)
        self.assertIn(".writing-study-consistency-trigger", self.styles)
        self.assertIn(".writing-study-rebind-drawer", self.styles)

    def test_m11_interaction_types_route_to_focused_study_definition_editors(self):
        writing = self._writing_page()
        authoring = self.authoring_journey_source

        self.assertIn("function medicalWritingStructuredTarget(section)", self.source)
        self.assertIn('interactions.has("eligibility_rule_builder")', self.source)
        self.assertIn('group: "population"', self.source)
        self.assertIn('interactions.has("dose_modification_rule_builder")', self.source)
        self.assertIn('interactions.has("non_investigational_intervention_builder")', self.source)
        self.assertIn('interactions.has("concomitant_therapy_rule_builder")', self.source)
        self.assertIn('group: "intervention"', self.source)
        self.assertIn('"assessment_instrument_builder", "aesi_rule_builder"', self.source)
        self.assertIn('group: "outcomes"', self.source)
        self.assertIn("structuredDesignTarget.buttonLabel", writing)
        self.assertIn("initialStage={studyDesignTarget.stage}", writing)
        self.assertIn("initialGroup={studyDesignTarget.group}", writing)
        self.assertIn("focusLabel={studyDesignTarget.label", writing)
        self.assertIn("requestedStageAllowed", authoring)
        self.assertIn("initialGroup", authoring)

    def test_eligibility_and_medication_rules_use_numbered_structured_rows(self):
        source = self.authoring_journey_source

        self.assertIn("function StructuredListField", source)
        self.assertIn('prefix="IN"', source)
        self.assertIn('prefix="EX"', source)
        self.assertIn('prefix="WO"', source)
        self.assertIn('prefix="BG"', source)
        self.assertIn('prefix="CM-A"', source)
        self.assertIn('prefix="CM-P"', source)
        self.assertIn("normalizePicosForWrite", source)
        self.assertIn("hasPopulatedList(picos.inclusion_modules)", source)
        self.assertIn(".authoring-structured-list-row", self.styles)

    def test_target_mechanism_is_enrichment_not_a_frontend_completion_gate(self):
        source = self.authoring_journey_source

        self.assertNotIn(
            "investigational_product?.trim() && framing.target_mechanism?.trim()",
            source,
        )
        self.assertIn(
            'label="靶点/作用机制"><textarea',
            source,
        )
        self.assertIn(
            "未知时可留空，由IB或后续证据补充",
            source,
        )

    def test_existing_document_structured_change_stays_in_the_focused_stage(self):
        source = self.authoring_journey_source

        self.assertIn('if (!existingDocument) { setStage("picos")', source)
        self.assertIn('response.picos_complete && !existingDocument', source)

    def test_authoring_journey_auto_searches_and_preserves_intervention_boundaries(self):
        source = self.authoring_journey_source
        service_source = (
            ROOT / "services" / "api" / "app"
            / "medical_writing_authoring_journey.py"
        ).read_text(encoding="utf-8")

        self.assertIn("ClinicalTrials.gov", source)
        self.assertIn("ClinicalTrials.gov疾病检索词（系统建议，可修改）", source)
        self.assertIn("clinicaltrials_condition_term", source)
        self.assertIn("authoring-journey/competitor-search", source)
        self.assertNotIn("保存三项信息并检索", source)
        self.assertIn("framingSearchReady", source)
        self.assertIn("automaticResearchAttemptRef", source)
        self.assertIn("automaticMinimumSearchLockRef", source)
        self.assertIn("!journey.search_plan?.latest_snapshot_id", source)
        self.assertIn("saveMinimumAndSearch();", source)
        self.assertIn("journey.search_plan?.latest_snapshot_id", source)
        self.assertIn("重试", source)
        self.assertIn("function StudyPhaseInput", source)
        self.assertIn("<datalist id={listId}>", source)
        self.assertIn('listId="medical-writing-study-phase-options"', source)
        self.assertIn('listId="medical-writing-synopsis-phase-options"', source)
        self.assertIn("其他研究目的（自然语言，每行一项）", source)
        self.assertNotIn(
            '<select value={framing.study_phase}',
            source,
        )
        self.assertIn("recommendedClinicalTrialsSearchCandidate", source)
        self.assertIn('"prefill-adopt-minimum-search"', source)
        self.assertIn(
            'candidate.field_path !== "framing.clinicaltrials_condition_term"',
            source,
        )
        self.assertIn('candidate.recommendation_role === "pending_decision"', source)
        self.assertIn('candidate.state === "superseded"', source)
        self.assertNotIn('candidate.evidence_status !== "supported"', source)
        self.assertIn(
            "searchableJourney.prefill_package.journey_revision !== searchableJourney.revision",
            source,
        )
        self.assertIn(
            "Boolean(searchableJourney.framing?.clinicaltrials_condition_term?.trim())",
            source,
        )
        self.assertIn("searchPlan?.registry_filter?.condition_term", source)
        self.assertNotIn("hasEnglishClinicalTrialsConditionTerm", source)
        self.assertNotIn('"试验药物"}治疗${projectHeader?.indication || "目标适应症"', source)
        self.assertNotIn('"PROTOCOL"}-DRAFT', source)
        self.assertIn("public_document_count", source)
        self.assertIn("broad_then_triage", service_source)
        self.assertIn("const approvedFraming = journey.framing", source)
        self.assertIn("const approvedPicos = journey.picos", source)
        self.assertIn("存在未完成提交的研究框架或PICOS草稿", source)
        self.assertIn("/draft`,", source)
        self.assertIn("保存草稿", source)
        self.assertIn("完整第一步仍需单独提交", source)
        self.assertIn("design_archetype", source)
        self.assertIn("医学经理确认该项不适用", source)
        self.assertIn("randomized_confirmatory", source)
        self.assertIn("randomized_exploratory", source)
        self.assertIn("对照/组间比较设计", source)
        self.assertIn("single_arm_early_phase", source)
        self.assertIn("open_label_extension", source)
        self.assertIn("authoring-journey-load-failure", source)
        self.assertIn("setLoadNonce", source)
        self.assertIn("interactionLocked", source)
        self.assertIn('aria-selected={group === item.key}', source)
        self.assertIn('aria-label={`${item.label}不适用理由`}', source)
        self.assertIn('"aria-required": required || undefined', source)
        self.assertIn("patch.reason !== previous.reason", source)
        self.assertIn("next.field_applicability = Object.fromEntries", source)
        self.assertIn(".authoring-journey-fieldset", self.styles)
        self.assertIn("@media (min-width: 1281px) and (max-height: 850px)", self.styles)
        self.assertIn("footer is outside the desktop viewport", self.authoring_journey_qc)
        self.assertIn("nested document and journey scrolling", self.authoring_journey_qc)
        self.assertIn("Changing design archetype retained stale N/A decisions", self.authoring_journey_qc)
        self.assertIn("Authoring accessibility contract is not rendered", self.authoring_journey_qc)
        self.assertIn("<WritingPage key={activeProjectId}", self.source)
        self.assertIn("试验药物、非试验用药和普通CM保持清晰边界", source)
        self.assertIn("必须使用/背景治疗", source)
        self.assertIn("允许使用的合并用药/治疗", source)
        self.assertIn("限制/禁止使用的合并用药/治疗", source)

    def test_authoring_journey_supports_synopsis_import_and_guided_greenfield_entries(self):
        source = self.authoring_journey_source
        api_source = (ROOT / "services" / "api" / "app" / "main.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('onSelect("synopsis_import")', source)
        self.assertIn('onSelect("guided_greenfield")', source)
        self.assertIn("导入方案摘要", source)
        self.assertIn("随机探索性研究", source)
        self.assertIn("从零开始", source)
        self.assertIn("通过两阶段反问确定方案摘要和研究框架", source)
        self.assertIn('entry_mode: mode', source)
        self.assertIn("stableSynopsisUploadKey", source)
        self.assertIn("contentSha256: contentHash", source)
        self.assertIn("synopsisSelectionGenerationRef", source)
        self.assertIn("synopsisReplacementPending", source)
        self.assertIn("setSynopsisAcknowledged([])", source)
        self.assertIn('setSynopsisOverrideReason("")', source)
        self.assertIn("synopsisSelectionGenerationRef.current === selectionGeneration", source)
        self.assertIn("synopsisSelectionGenerationRef.current !== requestGeneration", source)
        self.assertIn("imported.synopsis_import?.source?.content_sha256 !== requestFileIdentity.contentSha256", source)
        self.assertIn("source.content_sha256 === synopsisFileIdentity.contentSha256", source)
        self.assertIn('const requestUploadKey = synopsisUploadKey', source)
        self.assertIn('form.append("expected_revision"', source)
        self.assertIn('form.append("idempotency_key", requestUploadKey)', source)
        self.assertNotIn('form.append("idempotency_key", `authoring-synopsis-import-${Date.now()}`)', source)
        self.assertIn("/authoring-journey/synopsis-import`", source)
        self.assertIn("/authoring-journey/synopsis-import/confirm", source)
        self.assertIn("source_role_status", source)
        self.assertIn("indication_status", source)
        self.assertIn("validation_warnings", source)
        self.assertIn("acknowledged_validation_warnings", source)
        self.assertIn("validation_override_reason", source)
        self.assertIn("synopsisOverrideReason.trim().length >= 10", source)
        self.assertIn('setMessage(`摘要导入失败：${error.message}`)', source)
        self.assertNotIn("synopsisTechnicalOverride", source)
        self.assertIn("activeProjectRef.current !== requestProjectId", source)
        self.assertIn("确认并进入两阶段补全", source)
        self.assertIn("重新解析完成前，当前候选不可确认", source)
        self.assertIn('["synopsis-upload", "synopsis-confirm"].includes(busy)', source)
        self.assertIn('disabled={interactionLocked}', source)
        self.assertIn("setStage(\"framing\")", source)
        self.assertIn(".authoring-entry-mode-options", self.styles)
        self.assertIn(".synopsis-upload-bar", self.styles)
        self.assertIn(".synopsis-source-review", self.styles)
        self.assertIn(".synopsis-extraction-review", self.styles)
        self.assertIn("await run_in_threadpool(", api_source)
        self.assertIn("MAX_SYNOPSIS_BYTES + 1", api_source)

    def test_ai_first_prefill_uses_one_overview_atomic_composite_and_clinical_labels(self):
        source = self.authoring_journey_source
        package_panel = (
            ROOT
            / "frontend"
            / "src"
            / "features"
            / "medical-writing"
            / "AuthoringCandidatePackagePanel.jsx"
        ).read_text(encoding="utf-8")

        self.assertIn("PREFILL_OVERVIEW_SECTIONS", source)
        self.assertIn('label: "项目身份"', source)
        self.assertIn('label: "总体设计"', source)
        self.assertIn('label: "PICOS"', source)
        self.assertIn("authoring-advanced-refinement", source)
        self.assertIn('data-testid="structured-design-fact-editor"', source)
        self.assertIn('data-action="apply-structured-design-suggestion"', source)
        self.assertIn('aria-label={label}', source)
        self.assertIn('aria-label="SRC计划状态"', source)
        self.assertIn('aria-label="DMC计划状态"', source)
        self.assertIn('aria-label="剂型"', source)
        self.assertIn("仅在需要逐字段改写", source)
        self.assertIn('"framing.protocol_id"', source)
        self.assertIn('"framing.document_title"', source)
        self.assertNotIn("LOW_RISK_BATCH_PREFILL_FIELDS", source)
        self.assertNotIn("adoptLowRiskPrefills", source)
        self.assertNotIn("for (const fieldPath of pendingFieldPaths)", source)
        composite_adopt = re.search(
            r"const adoptPrefillComposite = async.*?(?=\n  const runPublicSearch)",
            source,
            re.S,
        )
        self.assertIsNotNone(composite_adopt)
        composite_source = composite_adopt.group(0)
        self.assertEqual(1, composite_source.count("fetch("))
        self.assertIn("prefill-package/adopt-composite", composite_source)
        self.assertIn(
            "expected_package_revision: prefillPackage.package_revision",
            composite_source,
        )
        self.assertIn("path_overrides: pathOverrides || {}", composite_source)
        self.assertIn('"prefill-composite-adopt"', composite_source)
        self.assertIn("reloadJourneyAfterPrefillConflict", composite_source)
        self.assertIn("error.status === 409", composite_source)
        self.assertIn("不会自动重试提交", composite_source)
        self.assertIn("prefillAdoptionLockRef.current", composite_source)
        self.assertIn("activeProjectRef.current !== requestProjectId", composite_source)
        self.assertIn("function compositeAdoptionReady", package_panel)
        self.assertIn("if (!isPendingCompositeCandidate(candidate)) return true;", package_panel)
        self.assertIn("buildCompositePathOverrides", package_panel)
        self.assertIn('data-testid="adopt-composite-button"', package_panel)
        self.assertIn('data-testid="composite-adopt-receipt"', package_panel)
        self.assertIn("receipt.replayed", package_panel)
        self.assertIn("receipt.package_marked_stale", package_panel)
        self.assertIn("conditionTerm = searchPlan?.registry_filter?.condition_term", source)
        self.assertIn("|| nextJourney?.framing?.indication", source)
        self.assertNotIn("hasEnglishClinicalTrialsConditionTerm", source)
        self.assertNotIn("请先采用或填写英文ClinicalTrials.gov疾病检索词", source)
        self.assertIn("automaticResearchTokenRef.current !== researchToken", source)
        self.assertIn("AUTOMATIC_RESEARCH_TIMEOUT_MS", source)
        self.assertIn("controller.abort()", source)
        self.assertIn("error.status === 409 && !conflictRetried", source)
        self.assertIn("baseJourneyOverride: refreshed", source)
        self.assertIn("stale journey revision|expected revision|actual revision", source)
        self.assertIn("公开研究调研暂未完成，可直接重试", source)
        self.assertIn("自动调研未完成", source)
        self.assertIn("公开研究已检索，后续准备未完成", source)
        self.assertIn("重试自动调研", source)
        self.assertIn("function confirmedProjectCandidate(journey, candidateGroup)", source)
        self.assertIn("journey?.study_definition?.field_states?.[candidateGroup.field_path]", source)
        self.assertIn('fieldState?.status !== "confirmed"', source)
        self.assertIn("canonicalWriteJson(candidate.structured_value) === canonicalWriteJson(currentValue)", source)
        self.assertIn("isPrefillFieldConfirmed(journey, candidateGroup)", source)
        self.assertIn("projectConfirmedCandidate={confirmedProjectCandidate(journey, candidateGroup)}", source)
        self.assertIn("DESIGN_ARCHETYPE_LABELS[rawValue]", source)
        self.assertIn('title={rawDisplay && rawDisplay !== display ? rawDisplay : undefined}', source)
        self.assertIn("暂不确定", source)
        self.assertIn("其他/高级微调", source)
        self.assertIn("展开单字段修改与依据", source)
        self.assertIn("一键采用推荐方案", package_panel)
        self.assertIn("export function compositeCandidateBlockedCode", package_panel)
        self.assertIn("export function compositeDecisionPaths", package_panel)
        self.assertIn('data-testid="composite-empty-slot"', package_panel)
        self.assertIn("该分组当前没有推荐方案", package_panel)
        self.assertNotIn("resolvedCompositeDefaults", package_panel)
        self.assertNotIn("pendingCompositeDecisionPaths", package_panel)
        self.assertNotIn("displayCandidates[0]?.candidate_id", package_panel)
        self.assertNotIn("AI已完成其余设计；还需您决定", package_panel)
        self.assertNotIn("fields_blocked_missing_evidence", source)
        self.assertNotIn("第二步已完成", source)
        self.assertNotIn("重新医学批准", source)
        self.assertIn("受影响章节的重绑定、重新核对与审阅", source)
        self.assertNotIn("正文调和和重新审阅", source)
        self.assertIn(".authoring-prefill-workspace", self.styles)
        self.assertIn(".authoring-prefill-impact", self.styles)
        self.assertIn(".authoring-advanced-refinement", self.styles)

    def test_frontend_policy_gating_empty_slot_and_structured_errors(self):
        """Corrective P3 frontend contract: empty recommendation stays no
        recommendation, unsafe field/composite actions are disabled with an
        accurate reason, safe alternatives stay selectable, and policy
        rejections are never presented as concurrency conflicts."""
        source = self.authoring_journey_source
        panel = (
            ROOT
            / "frontend"
            / "src"
            / "features"
            / "medical-writing"
            / "AuthoringCandidatePackagePanel.jsx"
        ).read_text(encoding="utf-8")

        # --- empty recommendation slot stays empty (no fallback promotion) ---
        self.assertNotIn("displayCandidates[0]?.candidate_id", panel)
        self.assertNotIn(
            "candidates.find((item) => !isPendingCompositeCandidate(item))",
            panel,
        )
        self.assertIn("recommendedById && !isPendingCompositeCandidate(recommendedById)", panel)
        self.assertIn('data-testid="composite-empty-slot"', panel)
        self.assertIn("该分组当前没有推荐方案", panel)

        # --- unsafe alternatives are classified and gated ---
        self.assertIn("export function compositeCandidateBlockedCode", panel)
        self.assertIn('adoptionMode === "manual_only"', panel)
        self.assertIn('evidenceStatus === "insufficient"', panel)
        self.assertIn("声称内容未在引用原文中出现：", panel)
        self.assertIn(
            "if (!isPendingCompositeCandidate(candidate)) return true;",
            panel,
        )
        self.assertIn("export function compositeDecisionPaths", panel)
        # AI-resolved values are never carried as implicit overrides for
        # restricted candidates.
        self.assertNotIn("resolvedCompositeDefaults", panel)
        # Safe alternatives remain zero-override adoptable.
        self.assertIn("export function buildCompositePathOverrides", panel)

        # --- dead single-card actions are disabled with a reason ---
        self.assertIn("prefillCandidateBlockedReason", source)
        self.assertIn("isPendingCompositeCandidate,", source)
        self.assertIn(
            "disabled={Boolean(busy) || isPendingCompositeCandidate(recommended)}",
            source,
        )
        self.assertIn(
            "disabled={Boolean(busy) || pendingCandidate}",
            source,
        )
        self.assertIn(
            "disabled={Boolean(busy) || isPendingCompositeCandidate(recommended)} title={isPendingCompositeCandidate(recommended) ? prefillCandidateBlockedReason(recommended)",
            source,
        )

        # --- structured policy errors are distinct from revision conflicts ---
        self.assertIn('const POLICY_REJECTED_CODE = "POLICY_REJECTED"', source)
        self.assertIn("const isPolicyRejection", source)
        self.assertIn("const isSinglePathPolicyRejection", source)
        self.assertIn("error.code = detail.code", source)
        self.assertIn("error.reason = detail.reason", source)

        composite_fn = re.search(
            r"const adoptPrefillComposite = async.*?(?=\n  const runPublicSearch)",
            source,
            re.S,
        )
        self.assertIsNotNone(composite_fn)
        composite_catch = composite_fn.group(0)
        policy_index = composite_catch.find("if (isPolicyRejection(error))")
        conflict_index = composite_catch.find("error.status === 409")
        self.assertGreaterEqual(policy_index, 0, "composite policy branch missing")
        self.assertGreater(conflict_index, policy_index, "policy branch must precede 409 branch")
        policy_block = composite_catch[policy_index:conflict_index]
        self.assertNotIn(
            "reloadJourneyAfterPrefillConflict",
            policy_block,
            "policy rejection must not trigger a concurrency reload",
        )
        self.assertNotIn("不会自动重试提交", policy_block)
        self.assertIn("policyRejectionMessage(error)", policy_block)

        single_fn = re.search(
            r"const adoptPrefillCandidate = async.*?(?=\n  const adoptPrefillComposite)",
            source,
            re.S,
        )
        self.assertIsNotNone(single_fn)
        single_catch = single_fn.group(0)
        single_policy_index = single_catch.find("if (isSinglePathPolicyRejection(error))")
        single_conflict_index = single_catch.find("error.status === 409")
        self.assertGreaterEqual(single_policy_index, 0, "single-path policy branch missing")
        self.assertGreater(single_conflict_index, single_policy_index)
        single_policy_block = single_catch[single_policy_index:single_conflict_index]
        self.assertNotIn("reloadJourneyAfterPrefillConflict", single_policy_block)
        self.assertIn("policyRejectionMessage(error)", single_policy_block)

    def test_study_schema_editor_supports_batch_confirmation_and_reversible_edits(self):
        source = self.study_schema_editor_source

        self.assertIn("confirmAllCandidates", source)
        self.assertIn("确认全部候选", source)
        self.assertIn('["manual_candidate", "extracted_candidate"]', source)
        self.assertIn("const undo = () =>", source)
        self.assertIn("const redo = () =>", source)
        self.assertIn("<Undo2", source)
        self.assertIn("<Redo2", source)
        self.assertIn("undoStack.current", source)
        self.assertIn("redoStack.current", source)
        self.assertIn('requestPreview({ silent: true })', source)
        self.assertIn("wordOrientation", source)
        self.assertIn("横向A4", source)
        self.assertIn("<ZoomIn", source)
        self.assertIn("<ZoomOut", source)
        self.assertIn("committedSchemaStale", source)
        self.assertIn("按当前设计重新生成", source)

    def test_greenfield_document_creation_binds_the_canonical_study_definition(self):
        source = self.authoring_journey_source

        self.assertIn("const studyDefinition = journey.study_definition", source)
        self.assertIn("source_study_definition_id: studyDefinition.definition_id", source)
        self.assertIn("source_study_definition_revision: studyDefinition.revision", source)
        self.assertIn("source_study_definition_sha256: studyDefinition.state_sha256", source)
        self.assertIn('/api/medical-writing/protocol-templates/default', source)
        self.assertIn("template_id: defaultTemplate.template_id", source)
        self.assertIn("template_version: defaultTemplate.template_version", source)
        self.assertNotIn('template_id: "ich_m11_zh_cn"', source)
        self.assertNotIn("sectionScaffold.map", source)
        self.assertNotIn("source_fact_ids:", source)
        self.assertNotIn("initial_text:", source)
        self.assertNotIn("study_definition_revision:${journey.revision}", source)

    def test_synopsis_replacement_invalidates_stale_review_and_guards_async_results(self):
        source = self.authoring_journey_source
        selection = re.search(
            r"const selectSynopsisFile = async \(file\) => \{(?P<body>.*?)\n  \};\n\n  const uploadSynopsis",
            source,
            re.S,
        )
        upload = re.search(
            r"const uploadSynopsis = async \(\) => \{(?P<body>.*?)\n  \};\n\n  const confirmSynopsisImport",
            source,
            re.S,
        )
        self.assertIsNotNone(selection)
        self.assertIsNotNone(upload)
        selection_body = selection.group("body")
        upload_body = upload.group("body")

        self.assertLess(
            selection_body.index("setSynopsisReplacementPending(Boolean(file))"),
            selection_body.index("await stableSynopsisUploadKey(projectId, file)"),
        )
        self.assertLess(
            selection_body.index("setSynopsisAcknowledged([])"),
            selection_body.index("await stableSynopsisUploadKey(projectId, file)"),
        )
        self.assertLess(
            selection_body.index('setSynopsisOverrideReason("")'),
            selection_body.index("await stableSynopsisUploadKey(projectId, file)"),
        )
        self.assertIn(
            "synopsisSelectionGenerationRef.current === selectionGeneration",
            selection_body,
        )
        self.assertIn(
            "synopsisSelectionGenerationRef.current !== requestGeneration",
            upload_body,
        )
        self.assertIn(
            "imported.synopsis_import?.source?.content_sha256 !== requestFileIdentity.contentSha256",
            upload_body,
        )
        self.assertIn('form.append("idempotency_key", requestUploadKey)', upload_body)
        self.assertNotIn("Date.now()", upload_body)
        self.assertIn("!synopsisReplacementPending", source)
        self.assertIn(
            '<fieldset className="authoring-journey-fieldset" disabled={interactionLocked}>',
            source,
        )

    def test_authoring_non_upload_writes_use_content_bound_stable_idempotency_keys(self):
        source = self.authoring_journey_source
        stable_write = re.search(
            r"async function stableAuthoringWriteKey\(.*?\n\}",
            source,
            re.S,
        )

        self.assertIn("async function stableAuthoringWriteKey", source)
        self.assertIsNotNone(stable_write)
        self.assertIn("canonicalWriteJson({ operation, payload, preview_id: previewId, project_id: projectId, source_revision: sourceRevision })", source)
        self.assertIn('crypto.subtle.digest("SHA-256"', source)
        self.assertIn('return `authoring-${operation}-${hash}`.slice(0, 200)', source)
        self.assertNotIn("Date.now()", stable_write.group(0))
        self.assertIn('stableAuthoringWriteKey(requestProjectId, `commit-${targetStage}`, sourceRevision, payload, previewId)', source)
        self.assertIn('stableAuthoringWriteKey(requestProjectId, "create-with-framing", sourceRevision, payload)', source)
        self.assertIn('stableAuthoringWriteKey(requestProjectId, `draft-${targetStage}`, sourceRevision, payload)', source)
        self.assertIn('stableAuthoringWriteKey(requestProjectId, "corpus-override", sourceRevision, overridePayload)', source)
        self.assertIn("const sourceRevision = journey.revision", source)
        self.assertIn("const sourceRevision = baseJourney.revision", source)
        self.assertIn("const sourceRevision = 0", source)
        self.assertIn("expected_revision: sourceRevision", source)
        self.assertIn("impact_preview_id: previewId", source)

    def test_authoring_write_failures_reconcile_without_clearing_user_input(self):
        source = self.authoring_journey_source
        reconcile = re.search(
            r"const reconcileJourneyWrite = async \(requestProjectId, matches\) => \{(?P<body>.*?)\n  \};",
            source,
            re.S,
        )
        self.assertIsNotNone(reconcile)
        reconcile_body = reconcile.group("body")

        self.assertIn("error?.status === 409", source)
        self.assertIn("!Number.isInteger(error?.status)", source)
        self.assertIn("服务器已响应，但结果未完整返回", source)
        self.assertIn("/medical-writing/authoring-journey`).then(readJson)", reconcile_body)
        self.assertIn("!matches(current)", reconcile_body)
        self.assertIn("return current", reconcile_body)
        self.assertNotIn("applyJourneyResponse", reconcile_body)
        self.assertIn("writePayloadMatches(persistedStagePayload(current, targetStage), payload)", source)
        self.assertIn("writePayloadMatches(current?.[`${targetStage}_draft`]?.[targetStage], payload)", source)
        self.assertGreaterEqual(source.count("current.revision > sourceRevision"), 4)
        self.assertIn("current.corpus_gate?.override?.active", source)
        self.assertIn("if (!response) throw error", source)
        self.assertIn("if (!created) throw error", source)

    def test_authoring_reference_workspace_uses_the_exact_journey_snapshot_query(self):
        reference = self.writing_reference_source
        authoring = self.authoring_journey_source

        self.assertIn('variant="authoring"', authoring)
        self.assertIn("snapshotId={searchPlan.latest_snapshot_id}", authoring)
        self.assertIn(
            'const query = authoringMode && snapshotId ? `?snapshot_id=${encodeURIComponent(snapshotId)}` : "";',
            reference,
        )
        self.assertIn(
            "fetch(`/api/projects/${projectId}/medical-writing/references/workspace${query}`)",
            reference,
        )
        self.assertIn(
            "authoringMode && snapshotId && payload.snapshot?.snapshot_id !== snapshotId",
            reference,
        )

    def test_reference_span_selector_uses_source_content_and_cross_page_labels(self):
        reference = self.writing_reference_source

        self.assertIn("function spanOptionLabel(span)", reference)
        self.assertIn("span?.source_text || span?.section_heading", reference)
        self.assertIn('map((item) => `p${item.physical_page}`).join("+")', reference)
        self.assertIn("{spanOptionLabel(item)}", reference)
        self.assertNotIn(
            "p{item.physical_page} · {item.section_heading || item.ich_m11_anchor}",
            reference,
        )

    def test_authoring_reference_hides_independent_search_and_has_no_project_id_defaults(self):
        reference = self.writing_reference_source

        self.assertIn('const authoringMode = variant === "authoring";', reference)
        self.assertIn('!authoringMode && <div className="writing-reference-search">', reference)
        self.assertIn("useState(lockedIndication)", reference)
        self.assertIn('useState(lockedPhase || "PHASE2")', reference)
        self.assertIn("setIndication(lockedIndication)", reference)
        self.assertIn('setPhase(lockedPhase || "PHASE2")', reference)
        self.assertNotRegex(reference, r'projectId\s*===\s*["\']proj_')
        for project_specific_default in (
            'projectId === "proj_d001"',
            'projectId === "proj_rux_03_002"',
            'projectId === "proj_ra_greenfield_sandbox"',
        ):
            self.assertNotIn(project_specific_default, reference)

    def test_authoring_candidate_controls_filter_paginate_and_lock_triage(self):
        reference = self.writing_reference_source

        for state_contract in (
            'const [candidateQuery, setCandidateQuery] = useState("")',
            'const [candidateStatus, setCandidateStatus] = useState("retained")',
            "const [candidatePage, setCandidatePage] = useState(1)",
            "const candidatePageSize = 50",
            "const filteredCandidates = useMemo",
            "const visibleCandidates = filteredCandidates.slice",
        ):
            self.assertIn(state_contract, reference)
        self.assertIn(
            'authoringMode && <div className="writing-reference-candidate-filters">',
            reference,
        )
        self.assertIn("authoringMode && candidatePageCount > 1", reference)
        for control_label in (
            "检索NCT号、标题或申办方",
            "已保留参照",
            "全部状态",
            "待AI分类",
            "上一页",
            "下一页",
            "锁定深度处理篮子",
            "锁定竞品篮子",
        ):
            self.assertIn(control_label, reference)
        self.assertIn(
            '["direct_competitor", "indirect_reference"].includes(item.relevance_status)',
            reference,
        )
        self.assertIn("authoring-journey/corpus-triage/finalize", reference)
        self.assertIn("retained_candidate_ids: relatedDecisionIds", reference)
        self.assertIn("triageReason.trim().length < 10", reference)

    def test_reference_preparation_batch_is_scoped_to_finalized_authoring_documents(self):
        reference = self.writing_reference_source

        self.assertIn(
            'import { ReferencePreparationBatchPanel } from "./ReferencePreparationBatchPanel";',
            reference,
        )
        self.assertIn('const authoringMode = variant === "authoring";', reference)
        self.assertIn('journey?.corpus_triage?.status === "finalized"', reference)
        self.assertIn('journey?.corpus_triage?.snapshot_id === snapshotId', reference)
        self.assertIn('activeView === "documents"', reference)
        self.assertIn("authoringMode && triageFinalized", reference)
        self.assertIn("triageReviewLocked = triageFinalized || (", reference)
        self.assertIn(
            'authoringMode && aiTriageRun?.run?.status === "confirmed"',
            reference,
        )
        self.assertIn("&& !triageReviewLocked", reference)
        self.assertIn("<ReferencePreparationBatchPanel", reference)
        self.assertIn(
            '? viewDefinitions.filter((view) => view.id !== "shared_phase1" || phase1SharedAvailable)',
            reference,
        )
        self.assertIn(
            ': viewDefinitions.filter((view) => view.id === "approved")',
            reference,
        )

    def test_historical_pipeline_failure_does_not_force_open_the_progress_panel(self):
        source = self.authoring_journey_source

        self.assertIn("const [researchProgressOpen, setResearchProgressOpen] = useState(false);", source)
        self.assertNotIn(
            'pipelineStatus?.pipeline?.stage === "failed") {\\n      setResearchProgressOpen(true)',
            source,
        )

    def test_read_only_design_drawer_keeps_corpus_navigation_interactive(self):
        authoring = (
            ROOT
            / "frontend/src/features/medical-writing/MedicalWritingAuthoringJourneySetup.jsx"
        ).read_text()

        self.assertIn(
            'disabled={interactionLocked || (readOnly && stage !== "corpus")}',
            authoring,
        )
        self.assertIn('disabled={readOnly || busy === "search"', authoring)
        self.assertIn('disabled={readOnly || allowed || item.satisfied}', authoring)

    def test_reference_preparation_batch_uses_persisted_job_routes_and_safe_commands(self):
        batch = self.reference_preparation_batch_source

        for route in (
            "references/preparation-batches/latest?snapshot_id=${encodeURIComponent(snapshotId)}",
            "references/preparation-batches/${encodeURIComponent(batchId)}",
            "references/preparation-batches/${encodeURIComponent(batchId)}/advance-stage",
            "references/preparation-batches/${encodeURIComponent(batchId)}/retry",
        ):
            self.assertIn(route, batch)
        create_payload = re.search(
            r"references/preparation-batches`, \{.*?body: JSON\.stringify\(\{(?P<body>.*?)\}\),",
            batch,
            re.S,
        )
        self.assertIsNotNone(create_payload, "Batch create payload not found")
        self.assertIn("snapshot_id: snapshotId", create_payload.group("body"))
        self.assertIn('actor: "medical_manager"', create_payload.group("body"))
        self.assertIn("idempotency_key: createKeyRef.current", create_payload.group("body"))
        self.assertNotIn("nct", create_payload.group("body").lower())
        self.assertIn("ACTIVE_BATCH_STATUSES.has(batchStatus)", batch)
        self.assertIn("TERMINAL_BATCH_STATUSES.has(batchStatus)", batch)
        self.assertIn('const ACTIVE_BATCH_STATUSES = new Set(["accepted", "running"]);', batch)
        for terminal_status in (
            '"completed"',
            '"completed_with_review_required"',
            '"completed_with_manual_upload_required"',
            '"partial_failure"',
            '"failed"',
        ):
            self.assertIn(terminal_status, batch)
        self.assertIn("loadLatest()", batch)
        self.assertIn("loadBatch(batchId, { polling: true })", batch)
        self.assertIn('? item.ingest', batch)
        self.assertIn('? item.extraction', batch)
        self.assertIn(': item.validation', batch)
        self.assertIn(
            'normalizedStatus(item.validation_status, "") || validationStageStatus',
            batch,
        )
        self.assertIn('error_detail: itemStatus === "excluded"', batch)
        self.assertIn(
            ': errorDetailLabels[item.error_code] || item.error_detail || ""',
            batch,
        )
        self.assertIn('item.item_status === "manual_upload_required"', batch)
        self.assertIn('return "手动导入 Protocol"', batch)
        self.assertIn(
            'disabled={!snapshotId || !candidates.length || Boolean(action) || loading}',
            batch,
        )
        self.assertIn("Number(batch?.prepared_count || 0)", batch)
        self.assertIn("Number(batch?.review_required_count || 0)", batch)
        self.assertIn("Number(batch?.manual_upload_required_count || 0)", batch)
        self.assertIn("Number(batch?.failed_count || 0)", batch)
        self.assertIn('batchStatus === "awaiting_stage_admission"', batch)
        self.assertIn('data-action="advance-stage"', batch)
        self.assertIn('idempotency_key: advanceKeyRef.current.key', batch)
        self.assertIn("Number(batch?.item_count || rows.length)", batch)
        for obsolete_contract in (
            '"queued"',
            '"in_progress"',
            '"ready_for_structure_review"',
            '"awaiting_confirmation"',
            "item?.stages",
            "error_message",
            "completed_count",
            "total_count",
        ):
            self.assertNotIn(obsolete_contract, batch)
        for forbidden_command in (
            "content-validation/override",
            "extraction-reviews",
            "references/translations",
            "/medical-review",
            "/admissions",
        ):
            self.assertNotIn(forbidden_command, batch)

    def test_reference_preparation_batch_exposes_desktop_status_and_row_dom_contracts(self):
        batch = self.reference_preparation_batch_source

        self.assertIn('data-testid="reference-preparation-batch"', batch)
        self.assertIn("data-batch-status={batchStatus}", batch)
        self.assertIn('data-testid="reference-preparation-row"', batch)
        self.assertIn('data-testid="reference-preparation-progress"', batch)
        self.assertIn('data-testid="reference-preparation-item-progress"', batch)
        self.assertIn('data-progress-percent={progress.percent}', batch)
        self.assertIn("currentNctId", batch)
        self.assertIn("currentDocumentLabel", batch)
        self.assertIn("progress.completed", batch)
        self.assertIn("progress.total", batch)
        self.assertIn("progress.percent", batch)
        self.assertIn('<progress max="100" value={progress.percent}', batch)
        for progress_label in (
            "正在下载公开 Protocol",
            "正在提取原生文本",
            "正在渲染 OCR 页面",
            "正在完成 OCR 页面识别",
            "正在持久化结构提取结果",
            "正在校验文件内容",
        ):
            self.assertIn(progress_label, batch)
        for attribute in (
            "data-item-status",
            "data-download-status",
            "data-parse-status",
            "data-validation-status",
            'data-stage="download"',
            'data-stage="parse"',
            'data-stage="validation"',
        ):
            self.assertIn(attribute, batch)
        for label in (
            "研究",
            "公开文件",
            "下载",
            "结构解析",
            "内容校验",
            "下一步",
            "开始批量准备",
            "刷新",
            "仅重试失败项",
            "准入下一阶段",
            "处理问题",
            "部分失败",
            "待人工内容确认",
        ):
            self.assertIn(label, batch)
        self.assertIn(".writing-reference-batch-table", self.styles)
        self.assertIn("min-width: 960px", self.styles)

    def test_reference_translation_scope_matches_supported_server_contract(self):
        batch = self.reference_translation_batch_source

        for anchor in (
            '"eligibility"',
            '"objectives_endpoints"',
            '"safety"',
            '"schedule"',
            '"statistics"',
            '"synopsis"',
        ):
            self.assertIn(anchor, batch)
        self.assertIn("SUPPORTED_TRANSLATION_ANCHORS", batch)
        self.assertIn("supportedAnchors", batch)
        self.assertIn(
            "setSelectedAnchors(supportedAnchors(returnedAnchors.map((item) => item.value)))",
            batch,
        )
        self.assertIn(
            'disabled={!SUPPORTED_TRANSLATION_ANCHORS.has(anchor.value)}',
            batch,
        )
        self.assertIn("当前批量翻译合同暂不支持", batch)
        self.assertIn("if (!SUPPORTED_TRANSLATION_ANCHORS.has(anchor)) return;", batch)

    def test_finalized_document_tools_use_retained_candidates_and_keep_full_candidate_tab(self):
        reference = self.writing_reference_source

        self.assertIn("journey?.corpus_triage?.retained_candidate_ids || []", reference)
        self.assertIn(
            "candidates.filter((item) => retainedCandidateIdSet.has(item.nct_id))",
            reference,
        )
        self.assertIn("candidates={documentCandidates}", reference)
        self.assertIn("documentCandidates.map((item)", reference)
        self.assertIn("(authoringMode ? visibleCandidates : candidates).map", reference)
        self.assertIn('data-action="toggle-single-document-tools"', reference)
        self.assertIn("逐文件问题处理", reference)
        self.assertIn("onOpenIssue={openBatchIssue}", reference)
        self.assertIn('item.issue_kind === "content_validation"', reference)
        self.assertIn('setActiveView("translations")', reference)
        self.assertIn('setActiveView("documents")', reference)

    def test_authoring_picos_alignment_is_bound_to_current_picos_and_evidence(self):
        reference = self.writing_reference_source

        self.assertIn("PICOS与语料核对", reference)
        self.assertIn("authoring-journey/picos-corpus-alignment", reference)
        self.assertIn("source_picos_sha256: journey.picos_sha256", reference)
        self.assertIn("evidence_brief_ids: selectedBriefIds.length ? selectedBriefIds : currentBriefIds", reference)
        self.assertIn('option value="no_conflicts">未发现冲突', reference)
        self.assertIn('option value="resolved">发现冲突且已处置', reference)
        self.assertIn("conflict_count:", reference)
        self.assertIn("disposition_summary: alignmentSummary.trim()", reference)
        self.assertIn("记录PICOS核对结论", reference)

    def test_reference_actions_restore_authoritative_journey_hashes_after_gate_recalculation(self):
        reference = self.writing_reference_source

        self.assertIn(
            "authoring-journey?allow_missing=true",
            reference,
        )
        self.assertIn(
            "authoritative.available === false ? recalculated : authoritative",
            reference,
        )
        self.assertIn(
            "derived hashes (notably picos_sha256)",
            reference,
        )

    def test_prefill_refreshes_authoritative_revision_before_external_call(self):
        source = self.authoring_journey_source
        start = source.index("const generatePrefill = async")
        end = source.index("  const selectSynopsisFile", start)
        block = source[start:end]
        for contract in (
            "authoring-journey?allow_missing=true",
            "const effectiveJourney = latestResponse?.available === false ? nextJourney : latestResponse",
            "applyJourneyResponse(effectiveJourney)",
            "onJourneyChanged?.(effectiveJourney)",
            "requestPrefillPackage(effectiveJourney, force, requestProjectId)",
        ):
            self.assertIn(contract, block)

    def test_greenfield_decisions_are_resolved_from_the_existing_review_rail(self):
        writing = self._writing_page()
        self.assertIn("function GreenfieldDecisionReviewPanel", self.source)
        self.assertIn('isGreenfieldSession\n    ? ["AI", "证据", "文献", "审阅", "版本"]', writing)
        self.assertIn("待审核 {greenfieldState?.approval_blocker_count || 0} 项", writing)
        self.assertIn("greenfieldApprovalBlockerCount(", writing)
        self.assertIn(
            "/greenfield-document/decisions/${encodeURIComponent(decisionId)}/resolve",
            writing,
        )
        self.assertIn(
            "expected_baseline_revision: greenfieldState.baseline_revision",
            writing,
        )
        self.assertIn("value: values.value", writing)
        self.assertIn("rationale: values.rationale", writing)
        self.assertIn("source_refs: values.sourceRefs", writing)
        self.assertIn("确认并解除阻断", self.source)
        self.assertIn("未决阻断项不会由AI自行补齐", self.source)
        self.assertIn(".greenfield-decision-review", self.styles)

    def test_document_editor_and_ai_interaction_are_first_screen_core(self):
        writing = self._writing_page()
        layout_index = writing.find("writing-layout writing-editor-first-layout")
        document_map_index = writing.find('className="panel section-tree writing-document-map-drawer"')
        editor_index = writing.find("panel editor-panel writing-editor-core")
        ai_rail_index = writing.find('className="panel ai-rail writing-ai-core"')

        self.assertGreaterEqual(layout_index, 0, "Writing page must use an editor-first desktop layout")
        self.assertGreaterEqual(document_map_index, 0, "Chapter navigation must be available as an on-demand drawer")
        self.assertGreaterEqual(editor_index, 0, "Document editor must be the primary center column")
        self.assertGreaterEqual(ai_rail_index, 0, "AI interaction must be the persistent right rail")
        self.assertLess(layout_index, editor_index, "Document editor must be the first panel inside the core workspace")
        self.assertLess(editor_index, ai_rail_index, "Document editor and AI rail should be adjacent in the core workspace")
        self.assertLess(ai_rail_index, document_map_index, "The document map must be rendered outside the persistent editor + AI grid")
        self.assertNotIn('className="writing-support-zone"', writing)
        self.assertNotIn("writing-section-strip", writing[:layout_index], "Chapter strip must not appear before the editor-first workspace")

    def test_generated_tables_never_fall_back_to_the_first_protocol_source_block(self):
        self.assertIn(
            'const revisionWorkingBlock = workingBlock?.block_type === "heading"',
            self.source,
        )
        self.assertIn("contentBlocksRef.current.find((block)", self.source)
        self.assertNotIn(
            "sourceBlocksRef.current[selectedBlockIndex] || sourceBlocksRef.current[0]",
            self.source,
        )
        self.assertIn('selectedEditorBlockContext.blockType === "table"', self.source)
        self.assertIn("请在全屏表格设计器中选择一个单元格", self.source)

    def test_table_cell_ai_revision_uses_typed_anchor_and_no_paragraph_fallback(self):
        writing = self._writing_page()
        self.assertIn('anchor_type: tableCell ? "table_cell"', writing)
        self.assertIn("table_cell_anchor: tableCell ?", writing)
        self.assertIn("working_copy_revision: workingCopyRevision", writing)
        self.assertIn("table_version: tableCell.tableVersion", writing)
        self.assertIn("cell_id: tableCell.cellId", writing)
        self.assertIn("!selectedEditorBlockContext.tableCell || workingCopyDirty", writing)
        self.assertIn("AI只生成该单元格的完整替换候选", writing)
        self.assertIn('aria-label="表格单元格AI修订前后对照"', writing)
        self.assertIn("activeThread.selected_text", writing)
        self.assertIn("cellRevisionThreads={revisionThreads.filter", self.source)
        self.assertIn(".table-cell-revision-diff", self.styles)

    def test_every_rendered_table_has_an_explicit_picker_and_designer_entry(self):
        self.assertIn('aria-label="选择当前表格"', self.source)
        self.assertIn("tableBlocks.map((block, index)", self.source)
        self.assertIn("selectActiveTable(event.target.value)", self.source)
        self.assertIn('aria-label={readOnly ? "全屏查看当前表格" : "全屏编辑当前表格结构与附注"}', self.source)
        self.assertIn(".rich-table-picker", self.styles)
        self.assertIn("text-overflow: ellipsis", self.styles)

    def test_table_body_title_and_all_notes_are_synchronized_in_the_editor_panel(self):
        self.assertIn("function visibleTableTitle", self.source)
        self.assertIn("block?.table_caption?.text", self.source)
        self.assertIn("function visibleTableNotes", self.source)
        self.assertIn('aria-label="当前表格同步内容"', self.source)
        self.assertIn('aria-label="当前表格完整附注"', self.source)
        self.assertIn("activeTableNotes.map((note, index)", self.source)
        self.assertIn("visibleTableColumnCount(activeTableBlock)", self.source)
        self.assertIn("sourceTableCaptionText", self.source)
        self.assertIn("sourceCaptionDiffers", self.source)
        self.assertIn('className="rich-table-source-caption"', self.source)
        self.assertIn('querySelectorAll?.("table[data-source-block-id]")', self.source)
        self.assertIn("function bindSourceTableDomIdentity", self.source)
        self.assertIn('candidate.querySelectorAll("[data-cell-id]")', self.source)
        self.assertIn('table.setAttribute("data-source-block-id", block.block_id)', self.source)
        self.assertIn("scrollIntoView", self.source)
        self.assertIn("tableSelectionGuardRef", self.source)
        self.assertIn("Date.now() + 500", self.source)
        self.assertIn('behavior: "auto"', self.source)
        self.assertIn("Date.now() < guardedSelection.until", self.source)
        self.assertIn('addEventListener("scroll", synchronizeVisibleTable', self.source)
        self.assertIn("scrollActiveTableHorizontally", self.source)
        self.assertIn('aria-label="宽表横向浏览"', self.source)
        self.assertIn('aria-label="向左浏览表格"', self.source)
        self.assertIn('aria-label="向右浏览表格"', self.source)
        self.assertIn("scroller.scrollWidth - scroller.clientWidth", self.source)
        self.assertIn(".rich-table-scroll-controls", self.styles)
        self.assertIn('className={activeTableBlock ? "protocol-editor has-table-sync-band"', self.source)
        self.assertIn(".rich-table-sync-band", self.styles)
        self.assertIn(".rich-table-sync-notes", self.styles)
        self.assertIn(".rich-table-source-caption", self.styles)

    def test_table_cell_ai_diff_labels_the_original_text_as_a_submission_snapshot(self):
        self.assertIn("提交时单元格快照", self.source)
        self.assertNotIn("<span>当前单元格</span>", self.source)

    def test_editor_never_replaces_table_content_with_placeholder_or_markdown_only_copy(self):
        self.assertIn("content: contentBlocks.map(tiptapNodeFromContentBlock)", self.source)
        self.assertIn("(block.rows || []).map((row, rowIndex)", self.source)
        self.assertIn("tableRowsFromTiptapNode", self.source)
        self.assertNotIn("表格内容已省略", self.source)
        self.assertNotIn("表格暂未渲染", self.source)
        self.assertNotIn("请查看原始 Markdown 表格", self.source)

    def test_irregular_docx_table_fillers_do_not_block_unrelated_text_formatting(self):
        self.assertIn("ProseMirror normalizes irregular DOCX tables", self.source)
        self.assertIn("if (!cellId && !tiptapNodeText(cellNode).trim()) continue;", self.source)
        self.assertIn("if (editedCellsById.size !== visibleSourceRow.length) return null;", self.source)

    def test_rich_editor_browser_qc_covers_three_real_projects_and_docx_export(self):
        qc = self.editor_formatting_qc_source
        for project_id in (
            "proj_rux_03_002",
            "proj_d001",
            "proj_my008_pnh_3_01",
        ):
            self.assertIn(project_id, qc)
        self.assertIn('aria-label="重做"', qc)
        self.assertIn("textBlocksWithRichText", qc)
        self.assertIn("generatedTables", qc)
        self.assertIn("exportDocx", qc)
        self.assertIn("geometry.rowCount !== 2", qc)
        self.assertIn("geometry.toolbar?.height > 86", qc)

    def test_desktop_css_makes_editor_and_ai_the_primary_columns(self):
        self.assertIn('grid-template-areas: "editor ai";', self.styles)
        self.assertIn("grid-area: editor;", self.styles)
        self.assertIn("grid-area: ai;", self.styles)
        layout_match = re.search(r"\.writing-layout\s*\{(?P<body>.*?)\n\}", self.styles, re.S)
        self.assertIsNotNone(layout_match, "Writing layout CSS block not found")
        layout_body = layout_match.group("body")
        self.assertIn("minmax(720px, 1.72fr)", layout_body)
        self.assertIn("minmax(360px, 0.72fr)", layout_body)
        self.assertIn(".writing-document-map-drawer", self.styles)

    def test_revision_actions_call_backend_and_preserve_author_selection_boundary(self):
        writing = self._writing_page()

        self.assertIn("submitRevisionAction", writing)
        self.assertIn("revision-threads/${thread.thread_id}/actions", writing)
        self.assertIn("suggestion_id", writing)
        self.assertIn("request_rewrite", writing)

    def test_revision_ai_rail_renders_versioned_review_ledger(self):
        writing = self.source

        self.assertIn('data-testid="revision-turn-ledger"', writing)
        self.assertIn("activeThread.suggestions || []", writing)
        self.assertIn("suggestion.turn_number", writing)
        self.assertIn("suggestion.parent_suggestion_id", writing)
        self.assertIn("suggestion.user_comment", writing)
        self.assertIn("suggestion.ai_run_id", writing)
        self.assertIn("修订审阅记录", writing)
        self.assertIn("生成下一轮", writing)
        self.assertIn("activeSuggestion?.user_decision === \"pending\"", writing)
        self.assertIn(".revision-turn-ledger", self.styles)
        self.assertIn(".revision-turn.current", self.styles)
        self.assertIn("AI候选，待选择", writing)
        self.assertIn("选用并写入", writing)

    def test_medical_author_selection_is_applied_to_working_copy_without_second_approval(self):
        writing = self._writing_page()

        self.assertIn("applyApprovedRevision", writing)
        self.assertIn("revision-threads/${thread.thread_id}/apply", writing)
        self.assertIn("expected_working_copy_revision: workingCopyRevision", writing)
        self.assertIn("function isRevisionThreadSelectedByAuthor(status)", self.source)
        self.assertIn('"author_selected", "medically_approved", "accepted_pending_medical_approval"', self.source)
        self.assertIn("!isRevisionThreadSelectedByAuthor(thread.status)", writing)
        self.assertIn("activeRevisionApplied", writing)
        self.assertIn("await applyApprovedRevision(payload.thread, { fromSelection: true })", writing)
        self.assertIn("选用并写入", writing)
        self.assertIn("原始 DOCX 未被修改", writing)
        self.assertIn("不再重复设置同角色批准步骤", writing)
        self.assertIn("候选处置已记录，但写入失败", writing)
        self.assertIn("重试写入", writing)
        self.assertIn(".revision-application-band", self.styles)

    def test_revision_errors_surface_backend_detail_text(self):
        writing = self._writing_page()

        self.assertIn("readJsonOrThrow", writing)
        self.assertIn("apiErrorText(error)", writing)
        self.assertIn("error.status = response.status", self.source)
        self.assertIn("error.payload = payload", self.source)
        self.assertNotIn("AI修订提交失败：${error.status || error.message || \"network\"}", writing)

    def test_legacy_accepted_revision_badge_is_not_presented_as_a_new_approval_step(self):
        self.assertIn('accepted_pending_medical_approval: "历史候选，待迁移"', self.source)
        self.assertNotIn('accepted_pending_medical_approval: "已接受，仍待医学批准"', self.source)

    def test_revision_rail_is_not_static_thread_three_demo(self):
        writing = self._writing_page()

        self.assertNotIn("AI 修订线程 #3", writing)
        self.assertNotIn("请把主要终点表述得更符合研究方案写法", writing)

    def test_real_project_editor_loads_registered_document_session_without_demo_fallback(self):
        writing = self._writing_page()

        self.assertIn("/medical-writing/document-session?allow_missing=true`", writing)
        self.assertIn("payload.available === false", writing)
        self.assertIn("/medical-writing/document-session/sections/${selectedSection}", writing)
        self.assertIn("editorSessionAvailable = isDemoWritingSession || documentSession?.project_id === projectId", writing)
        self.assertIn("系统不会回退到其他项目正文", writing)
        self.assertIn("real-document-session-blocked", writing)
        self.assertNotIn("当前真实项目文档已完成来源解析，可编辑文档会话尚未建立", writing)
        self.assertIn("const realWorkingCopyEditable = !isDemoWritingSession", writing)
        self.assertIn("&& !editorFrozen", writing)
        self.assertIn("readOnly={!isDemoWritingSession && !realWorkingCopyEditable}", writing)
        self.assertIn("approvedLocked={editorFrozen}", writing)
        self.assertIn('readOnly ? "来源只读" : "工作副本"', self.source, "Source/work-copy boundary must remain compact")
        self.assertIn("工作副本", self.source, "Working-copy edit mode must include tables")
        self.assertIn("disabled={!enabledWritingRailTabs.includes(tab)}", writing)
        self.assertIn('isGreenfieldSession\n    ? ["AI", "证据", "文献", "审阅", "版本"]', writing)
        self.assertIn(': ["AI", "证据", "文献", "版本"]', writing)
        self.assertIn('setActiveWritingRailTab(tab)', writing)

    def test_competitor_protocol_evidence_drives_audited_candidate_application(self):
        writing = self._writing_page()
        reference_source = (ROOT / "frontend" / "src" / "features" / "writing-reference" / "WritingReferencePanel.jsx").read_text(encoding="utf-8")

        self.assertIn("<WritingReferencePanel", writing)
        self.assertIn("evidence_brief_ids: selectedReferenceBriefIds", writing)
        self.assertIn("可直接采用的版本", writing)
        self.assertIn('submitRevisionAction(activeThread, candidate, "accept")', writing)
        self.assertIn('candidate.user_decision !== "pending"', writing)
        self.assertIn("!canSelectAndApplyRevision", writing)
        self.assertIn("记录医学作者选择并写入版本化工作副本", writing)
        self.assertNotIn("candidateInsertion={candidateInsertion}", writing)
        self.assertNotIn("function replaceCandidateInSourceBlock(editor, insertion)", self.source)
        self.assertNotIn("替换到工作稿", writing)
        self.assertIn("approved_evidence_briefs", reference_source)
        self.assertIn("evidence_brief_history", reference_source)
        self.assertNotIn("insertContent", reference_source)
        self.assertNotIn("editor.commands", reference_source)

    def test_competitor_ai_triage_sends_a_stable_idempotency_key(self):
        reference = self.writing_reference_source

        self.assertIn('const aiTriageCreateKeyRef = useRef("")', reference)
        self.assertIn(
            'aiTriageCreateKeyRef.current = requestKey("competitor-triage")',
            reference,
        )
        start_block = self._source_between(
            reference,
            "const startAiTriage = async () => {",
            "const cancelAiTriage = async () => {",
        )
        self.assertIn("idempotency_key: aiTriageCreateKeyRef.current", start_block)
        self.assertIn(
            'const storageKey = `mw_triage_job_${projectId}`',
            start_block,
        )
        self.assertIn(
            'localStorage.setItem(storageKey, JSON.stringify(locator))',
            start_block,
        )
        self.assertIn('aiTriageCreateKeyRef.current = ""', start_block)

    def test_competitor_ai_triage_recovers_and_confirms_one_complete_partition(self):
        reference = self.writing_reference_source

        self.assertIn(
            "competitor-triage/latest?snapshot_id=${encodeURIComponent(snapshotId)}",
            reference,
        )
        self.assertIn("stored.snapshot_id === snapshotId", reference)
        self.assertIn("run.snapshot_id !== activeSnapshotRef.current", reference)
        self.assertIn('data-section="ai-triage-review"', reference)
        for label in (
            "本次最终分类",
            "AI中文理由",
            "匹配维度",
            "证据缺口",
            "确认并锁定全部",
            "确认全部排除并继续",
            "无合适竞品理由（必填）",
            "手工上传方案或使用通用语料库",
            "部分分块失败",
            "旧结果仅保留审计",
        ):
            self.assertIn(label, reference)
        confirm_block = self._source_between(
            reference,
            "const confirmAiTriageRun = async () => {",
            "// Resume a durable job",
        )
        self.assertIn("final_classifications: finalClassifications", confirm_block)
        self.assertIn("no_suitable_competitor_reason", confirm_block)
        self.assertIn("retained_nct_ids: retainedNctIds", confirm_block)
        self.assertIn("excluded_nct_ids: excludedNctIds", confirm_block)
        self.assertIn("/confirm`", confirm_block)
        self.assertIn("await refreshWorkspace({ preserveMessage: true })", confirm_block)
        self.assertIn("/medical-writing/authoring-journey`", confirm_block)
        self.assertIn("onJourneyChange(latestJourney)", confirm_block)
        self.assertIn("const confirmation = await fetch", confirm_block)
        self.assertIn("pipeline_advanced", confirm_block)
        self.assertIn("研究流水线已开始继续处理原文", confirm_block)
        self.assertIn("研究流水线尚未建立", confirm_block)
        self.assertNotIn("研究流水线正在继续下载方案原文", confirm_block)
        self.assertNotIn("待医学批准", confirm_block)
        self.assertNotIn("无法形成Protocol/SAP深度处理篮子", confirm_block)

    def test_reference_panel_exposes_full_source_review_and_invalidation_workflow(self):
        reference_source = (ROOT / "frontend" / "src" / "features" / "writing-reference" / "WritingReferencePanel.jsx").read_text(encoding="utf-8")

        for label in (
            "候选研究",
            "文档与解析",
            "译文确认",
            "已准入证据",
            "直接竞品",
            "间接参照",
            "文件内容核验",
            "抽取结构医学审核",
            "确认结构完整",
            "退回重新解析",
            "确认沿用当前文件",
            "按作者退回意见生成新译文版本",
            "忠实度校验未通过",
            "来源已失效",
            "作者已确认并准入",
        ):
            self.assertIn(label, reference_source)
        for route in (
            "references/workspace",
            "references/search-snapshots",
            "relevance-decisions",
            "references/documents/ingest",
            "/extract",
            "/extraction-reviews",
            "references/translations",
            "/medical-review",
        ):
            self.assertIn(route, reference_source)
        self.assertNotIn("admitTranslation", reference_source)
        self.assertNotIn("/admissions", reference_source)
        self.assertIn("确认译文并准入", reference_source)
        self.assertIn("pending_medical_approval: [\"历史状态：待迁移\"", reference_source)

    def test_reference_panel_manual_upload_preserves_exact_retry_and_uses_shared_review_flow(self):
        reference = self.writing_reference_source

        for contract in (
            "手动导入 Protocol",
            'accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"',
            'option value="protocol">Protocol',
            'option value="protocol_sap">Protocol + SAP（仅使用Protocol部分）',
            "references/documents/upload",
            'form.append("file", manualFile, manualFile.name)',
            'form.append("idempotency_key", manualUploadKeyRef.current)',
            "await extractArtifact(artifact)",
            'item.source_status === "user_uploaded"',
            "当前候选研究需先完成直接竞品或间接参照分类",
        ):
            self.assertIn(contract, reference)
        self.assertNotIn('option value="sap">SAP', reference)
        self.assertIn("const [manualFile, setManualFile] = useState(null)", reference)
        self.assertIn('const manualUploadKeyRef = useRef("")', reference)
        self.assertIn('manualUploadKeyRef.current = file ? requestKey("reference-manual-upload") : ""', reference)
        self.assertIn("setManualFile(null)", reference)
        self.assertIn("activeProjectRef.current !== requestedProjectId", reference)
        self.assertIn(".writing-reference-manual-upload", self.styles)

    def test_reference_panel_separates_historical_review_from_current_author_confirmation(self):
        reference_source = self.writing_reference_source

        for contract in (
            "selectedTranslationInvalidated",
            "selectedReviewIsCurrentConfirmation",
            "legacyApprovedAwaitingAuthorConfirmation",
            "historicalReviewLabels",
            "仅保留为历史记录，不构成当前作者确认",
            "确认当前译文并准入",
            "请基于当前来源和结构解析重新生成译文后再确认",
            "!selectedReview && !selectedTranslationInvalidated",
        ):
            self.assertIn(contract, reference_source)
        self.assertNotIn(
            "selectedReview?.decision || selectedTranslation.status",
            reference_source,
        )
        self.assertNotIn(
            "dictionary={selectedReview ? reviewLabels : translationStatusLabels}",
            reference_source,
        )

    def test_document_validation_override_requires_explicit_acknowledgement_of_every_issue(self):
        reference_source = (ROOT / "frontend" / "src" / "features" / "writing-reference" / "WritingReferencePanel.jsx").read_text(encoding="utf-8")

        self.assertIn("acknowledgedValidationCodes", reference_source)
        self.assertIn("逐项确认", reference_source)
        self.assertIn("我已核对：{check.label}", reference_source)
        self.assertIn("acknowledgedValidationCodes.length !== validationWarnings.length", reference_source)
        self.assertIn("确认沿用不代表系统判定已转为匹配", reference_source)

    def test_section_switch_clears_previous_content_before_fetching_next_section(self):
        writing = self._writing_page()
        fetch_index = writing.find("Promise.all([")
        clear_index = writing.rfind("setSectionContent(null)", 0, fetch_index)

        self.assertGreaterEqual(fetch_index, 0, "Section and working-copy fetch must exist")
        self.assertGreaterEqual(clear_index, 0, "Previous section content must be cleared before the next fetch")
        self.assertLess(clear_index, fetch_index, "Stale section content must not seed a new editor instance")

    def test_real_document_session_does_not_probe_a_demo_section_before_loading(self):
        writing = self._writing_page()

        self.assertIn('const [selectedSection, setSelectedSection] = useState("");', writing)
        self.assertNotIn('const [selectedSection, setSelectedSection] = useState("endpoints");', writing)

    def test_document_map_preserves_protocol_section_hierarchy(self):
        writing = self._writing_page()

        self.assertIn("parentId: item.parent_id", writing)
        self.assertIn("documentSectionDepths", writing)
        self.assertIn("--writing-section-depth", writing)
        self.assertIn("结构节点", writing)
        self.assertIn("nested-section", self.styles)

    def test_active_revision_thread_is_scoped_to_current_section_first(self):
        writing = self._writing_page()

        section_threads_index = writing.find("const sectionThreads = sectionHasBackendBinding ? revisionThreads.filter((thread) => thread.section_id === backendSectionId) : [];")
        active_thread_index = writing.find("const activeThread =")

        self.assertGreaterEqual(section_threads_index, 0, "sectionThreads must be declared")
        self.assertGreaterEqual(active_thread_index, 0, "activeThread must be declared")
        self.assertLess(section_threads_index, active_thread_index, "activeThread must derive from sectionThreads, not project-wide threads")
        active_thread_block = writing[active_thread_index:writing.find("const activeSuggestion", active_thread_index)]
        self.assertIn("sectionHasBackendBinding", active_thread_block)
        self.assertIn("sectionThreads.find", active_thread_block)
        self.assertIn("[...sectionThreads].reverse().find", active_thread_block)
        self.assertNotIn("revisionThreads[revisionThreads.length - 1]", active_thread_block)

    def test_medical_writing_browser_qc_is_desktop_blocking_mobile_smoke(self):
        # Support both the manifest QC and the real-projects QC file
        for qc_src in [self.qc_source]:
            if "mobile-smoke" in qc_src:
                self.assertIn('const desktopRequired = label === "desktop";', qc_src)
                self.assertIn("if (desktopRequired && metrics.overflowX)", qc_src)
                break
        else:
            # Check manifest QC if loaded separately
            if WRITING_QC_MANIFEST_SOURCE.exists():
                manifest_qc = WRITING_QC_MANIFEST_SOURCE.read_text(encoding="utf-8")
                self.assertIn('const desktopRequired = label === "desktop";', manifest_qc)

    def test_medical_writing_browser_qc_checks_primary_ai_control_and_attribute_leaks(self):
        manifest_qc = WRITING_QC_MANIFEST_SOURCE.read_text(encoding="utf-8")
        self.assertIn("submitAiButtonInFirstViewport", manifest_qc)
        self.assertIn("leaksSourceConfigInOuterHtml", manifest_qc)
        self.assertIn("sourceLeakPattern", manifest_qc)
        self.assertIn("allowed_roots", manifest_qc)
        self.assertIn("source_record_id", manifest_qc)

    # --- NEW: Requirement 12 tests ---

    def test_working_copy_get_post_freeze_routes_in_source(self):
        """Working-copy GET/POST remains, but medical writing uses author freeze instead of approval-gate."""
        writing = self._writing_page()
        self.assertIn("working-copies/", self.source, "Working-copy route must be present in source")
        # GET route pattern
        self.assertTrue(
            re.search(r"working-copies/\$\{.*?\}", self.source) or "working-copies/" in self.source,
            "Working-copy dynamic route must exist",
        )
        self.assertNotIn("/approval-gate", writing, "Medical writing editor must not call the retired approval-gate route")
        self.assertIn("freeze-current-version", writing, "Author freeze route must replace approval-gate")
        self.assertIn("unfreeze", writing, "Author unfreeze route must be reachable")
        self.assertIn("/freeze-history", writing, "Author freeze history must be reachable")
        self.assertIn("/quarantined-history", writing, "Quarantined working-copy history must be reachable")
        self.assertIn("accept-and-bind", writing, "Quarantined draft accept-and-bind must be reachable")
        self.assertIn("revert-authoritative-baseline", writing, "Restore authoritative baseline must be reachable")
        self.assertIn("function ApprovalPage", self.source)
        self.assertIn("/approvals/${selected.id}/actions", self.source)

    def test_document_blocks_and_tables_share_one_tiptap_editing_flow(self):
        # Shared TipTap document for paragraphs + tables (not separate editor trees).
        self.assertIn("const rawEditorNodes = editor.getJSON().content || []", self.source)
        self.assertIn("content: contentBlocks.map(tiptapNodeFromContentBlock)", self.source)
        self.assertIn("function tableRowsFromTiptapNode(block, node)", self.source)
        self.assertIn("return synchronizeTableBlockRows(block, rows)", self.source)
        self.assertIn("function synchronizeTableBlockRows(block, rows)", self.source)
        self.assertIn("const cellContentById = new Map", self.source)
        self.assertIn("function tiptapInlineTextContent(value)", self.source)
        self.assertIn('content.push({ type: "hardBreak" })', self.source)
        self.assertIn("content: tiptapInlineTextContent(text)", self.source)
        self.assertIn("rich_text: {", self.source)
        self.assertIn('const SourceBlock = Node.create({', self.source)
        self.assertIn('name: "sourceBlock"', self.source)

        # Durable onUpdate contracts (implementation may loop/strip trailing empties;
        # do not assert the removed one-shot `trailingNodes = rawEditorNodes.slice(...)` string).
        rich_editor_start = self.source.index("function RichProtocolEditor")
        rich_editor_end = self.source.index("function WritingPage", rich_editor_start)
        rich_editor = self.source[rich_editor_start:rich_editor_end]
        on_update_start = rich_editor.index("onUpdate: ({ editor }) => {")
        on_update = rich_editor[on_update_start:rich_editor.index("onSelectionUpdate:", on_update_start)]

        # Map editor nodes against current source/working-copy blocks by stable
        # source identity rather than by their transient array positions.
        self.assertIn("const currentBlocks = contentBlocksRef.current", on_update)
        self.assertIn("groupEditorNodesBySourceBlockId(", on_update)
        self.assertIn("const editorGroup = grouped.groups[index]", on_update)
        self.assertIn("const editorNode = editorGroup.node", on_update)
        self.assertIn("editorGroup.leadingNodes", on_update)
        self.assertIn("editorGroup.trailingNodes", on_update)
        self.assertIn("if (grouped.error)", on_update)

        # Only an unbound, effectively empty TipTap document tail is discarded.
        self.assertIn("const isEffectivelyEmptyNode = (node) =>", on_update)
        self.assertIn("!editorNodes[editorNodes.length - 1]?.attrs?.sourceBlockId", on_update)
        self.assertIn("isEffectivelyEmptyNode(editorNodes[editorNodes.length - 1])", on_update)
        self.assertIn("editorNodes = editorNodes.slice(0, -1)", on_update)
        # Empty detection must not rely only on plain trim (ZWSP-safe).
        self.assertIn(r"/[\u200b\u200c\u200d\ufeff]/g", on_update)

        # Enter-created body paragraphs remain in a paragraph source block.
        # In particular, heading overflow is routed forward to the immediately
        # following body source block; ambiguous structure fails closed.
        mapping_source = (
            ROOT
            / "frontend"
            / "src"
            / "features"
            / "medical-writing"
            / "editorSourceMapping.js"
        ).read_text(encoding="utf-8")
        self.assertIn("groupsById.get(activeSourceId).trailingNodes.push(node)", mapping_source)
        self.assertIn("pendingHeadingBody", mapping_source)
        self.assertIn("group.leadingNodes.push(...pendingHeadingBody.nodes)", mapping_source)
        self.assertIn('sourceBlock?.block_type !== "paragraph"', mapping_source)
        self.assertIn('if (!["paragraph", "heading"].includes', mapping_source)
        self.assertIn('if (["table", "figure"].includes(activeBlock?.block_type))', mapping_source)
        self.assertIn("来源块顺序发生变化", mapping_source)
        self.assertIn("编辑器缺少来源块", mapping_source)
        self.assertIn('type: "doc"', self.source)
        self.assertIn("plainTextFromRichTextNode", self.source)
        # Reject the old random-id greenfield extra-block generator.
        self.assertNotIn("mwblock_greenfield_new_${Date.now()", self.source)
        self.assertNotIn("Math.random().toString(36)", self.source)

        # Dirty working-copy updates remain gated on real content change.
        self.assertIn(
            "const contentChanged = normalizedEditorJson !== editorBaselineJsonRef.current",
            on_update,
        )
        self.assertIn("contentBlocksRef.current = mappedBlocks", on_update)
        self.assertIn("onContentBlocksChange?.(mappedBlocks)", on_update)

    def test_cross_reference_uses_server_catalog_and_stable_target_identity(self):
        writing = self._writing_page()
        cross_reference = (ROOT / "frontend" / "src" / "features" / "medical-writing" / "CrossReferenceMark.js").read_text(encoding="utf-8")
        cell_editor = (ROOT / "frontend" / "src" / "features" / "medical-writing" / "TableCellRichEditor.jsx").read_text(encoding="utf-8")
        table_designer = (ROOT / "frontend" / "src" / "features" / "medical-writing" / "StructuredTableDesigner.jsx").read_text(encoding="utf-8")
        self.assertIn('name: "crossReference"', cross_reference)
        self.assertIn('attrs: { targetKind, targetId }', cross_reference)
        self.assertNotIn('attrs: { targetKind, targetId, bookmarkName', self.source)
        self.assertIn('/medical-writing/document-index`', writing)
        self.assertIn('aria-label="插入交叉引用"', self.source)
        self.assertIn('documentIndex.tables.map', self.source)
        self.assertIn('documentIndex.figures.map', self.source)
        self.assertIn('insertCrossReference(editor, target)', self.source)
        self.assertIn('CrossReferenceMark,', cell_editor)
        self.assertIn('aria-label="单元格插入交叉引用"', cell_editor)
        self.assertIn('documentIndex={documentIndex}', self.source)
        self.assertIn('documentIndex={documentIndex}', table_designer)
        self.assertIn('.protocol-cross-reference', self.styles)

    def test_captioned_source_docx_images_render_as_immutable_document_blocks(self):
        self.assertIn('name: "sourceDocxImage"', self.source)
        self.assertIn('block.figure_kind === "source_docx_image"', self.source)
        self.assertIn('`data:${block.media_type};base64,${block.image_base64}`', self.source)
        self.assertIn('editorNode?.attrs?.sourceBlockId !== block.block_id', self.source)
        self.assertIn('.source-docx-image figcaption', self.styles)
        self.assertIn('.source-docx-image img', self.styles)
        self.assertIn('content: "block+"', self.source)
        self.assertIn("function richTextFromSourceBlockNode(node)", self.source)
        self.assertIn("rich_text: richText", self.source)
        self.assertIn("function stableJsonStringify(value)", self.source)
        self.assertIn('const editorBaselineJsonRef = useRef("")', self.source)
        self.assertIn("editorBaselineJsonRef.current = stableJsonStringify(editor.getJSON())", self.source)
        self.assertIn("const normalizedEditorJson = stableJsonStringify({", self.source)
        self.assertIn("normalizedEditorJson !== editorBaselineJsonRef.current", self.source)
        self.assertNotIn("stableJsonStringify(block.rich_text || null)", self.source)
        self.assertIn('readOnly ? "来源只读" : "工作副本"', self.source)
        self.assertIn("工作副本", self.source)
        self.assertIn("data-source-block-id", self.source)
        self.assertIn("data-cell-id", self.source)
        self.assertIn("sourceCellsById", self.source)
        rich_editor_start = self.source.index("function RichProtocolEditor")
        rich_editor_end = self.source.index("function WritingPage", rich_editor_start)
        rich_editor = self.source[rich_editor_start:rich_editor_end]
        self.assertNotIn('event.key === "Enter"', rich_editor)
        self.assertNotIn('plainText.replace(/\\s*\\n+\\s*/g, " ")', rich_editor)
        self.assertIn("filter((cell) => !cell?.hidden)", self.source)
        self.assertIn("editedCellsById", self.source)
        self.assertIn("StructuredTableDesigner", self.source)
        self.assertIn("全屏编辑当前表格结构与附注", self.source)
        self.assertIn("content: nextBlocks.map(tiptapNodeFromContentBlock)", self.source)
        self.assertNotIn("本章节正文为表格型内容，请在下方只读表格中查看。", self.source)
        self.assertNotIn("working-copy-readonly-tables", self.source)
        self.assertNotIn("formatUnavailable", self.source)

    def test_server_reload_forces_editor_rehydration_even_when_revision_is_unchanged(self):
        writing = self._writing_page()
        self.assertIn(
            "const [workingCopyHydrationEpoch, setWorkingCopyHydrationEpoch] = useState(0)",
            writing,
        )
        self.assertIn("setWorkingCopyHydrationEpoch((value) => value + 1)", writing)
        self.assertIn(
            'key={`${selectedSection}:${workingCopyRevision}:${workingCopy?.content_sha256 || "no-hash"}:${workingCopyEditing ? "edit" : "source"}:h${workingCopyHydrationEpoch}`}',
            writing,
        )
        load_effect = writing[
            writing.index("Promise.all(["):writing.index(
                "const refreshRevisionThreads = () =>",
                writing.index("Promise.all(["),
            )
        ]
        self.assertIn("setWorkingCopyDraftBlocks(cloneContentBlocks(", load_effect)
        self.assertIn("setWorkingCopyDirty(false)", load_effect)
        self.assertIn("setEditorStructureError(\"\")", load_effect)
        self.assertIn("setWorkingCopyHydrationEpoch((value) => value + 1)", load_effect)
        self.assertLess(
            load_effect.index("setWorkingCopyDraftBlocks(cloneContentBlocks("),
            load_effect.index("setWorkingCopyHydrationEpoch((value) => value + 1)"),
        )

    def test_word_shortcuts_use_shared_explicit_undo_redo_handler(self):
        shortcuts = (ROOT / "frontend" / "src" / "features" / "medical-writing" / "WordEditingShortcuts.js").read_text(encoding="utf-8")
        cell_editor = (ROOT / "frontend" / "src" / "features" / "medical-writing" / "TableCellRichEditor.jsx").read_text(encoding="utf-8")
        self.assertIn('import { redo, undo } from "@tiptap/pm/history"', shortcuts)
        self.assertIn('new PluginKey("wordEditingShortcuts")', shortcuts)
        self.assertIn("key: wordEditingShortcutsPluginKey", shortcuts)
        self.assertIn("event.metaKey || event.ctrlKey", shortcuts)
        self.assertIn("command(view.state, view.dispatch)", shortcuts)
        self.assertIn("WordEditingShortcuts", self.source)
        self.assertIn("WordEditingShortcuts", cell_editor)

    def test_saved_working_copy_can_insert_cross_project_structured_table_templates(self):
        writing = self._writing_page()
        self.assertIn("/api/medical-writing/table-templates", writing)
        self.assertIn("/api/medical-writing/table-domain-profiles", writing)
        self.assertIn("tableDomainProfiles={tableDomainProfiles}", writing)
        self.assertIn("insertTableTemplate", writing)
        self.assertIn("table-templates/${encodeURIComponent(templateId)}/instantiate", writing)
        self.assertIn("workingCopyRevision >= 1", writing)
        self.assertIn("!workingCopyDirty", writing)
        self.assertIn('aria-label="插入结构化表格"', self.source)
        self.assertIn('role="menu" aria-label="结构化表格模板"', self.source)
        self.assertIn("setInsertedTableBlockId", writing)
        self.assertIn("setDesignerOpen(true)", self.source)
        self.assertIn("duplicateTableRequest", self.source)
        self.assertIn('aria-label="确认重复插入结构化表格"', self.source)
        self.assertIn("打开现有表格", self.source)
        self.assertIn("仍插入一张", self.source)
        self.assertIn('query.set("allow_duplicate", "true")', writing)
        self.assertIn(".rich-table-template-popover", self.styles)
        self.assertIn(".rich-table-duplicate-summary", self.styles)

    def test_complete_word_export_has_draft_and_approved_snapshot_boundaries(self):
        writing = self._writing_page()
        self.assertIn("exportMedicalWritingDocument", writing)
        self.assertIn("/medical-writing/document-exports", writing)
        self.assertIn("monitorDocumentExport", writing)
        self.assertIn("pollDurableMwJob", writing)
        self.assertIn("/download", writing)
        self.assertIn("documentExportProgress", writing)
        self.assertIn("正在处理来源与引用", (
            ROOT
            / "services"
            / "api"
            / "app"
            / "medical_writing_document_export_jobs.py"
        ).read_text(encoding="utf-8"))
        self.assertIn('role="progressbar"', writing)
        self.assertIn("documentExportProgress.step", writing)
        self.assertIn("documentExportProgress.percent", writing)
        self.assertIn('exportMedicalWritingDocument("draft_preview")', writing)
        self.assertIn('exportMedicalWritingDocument("approved_final")', writing)
        self.assertIn("allRequiredSectionsFrozen", writing)
        self.assertIn("freezeReadiness?.ready === true", writing)
        self.assertIn("不可变作者冻结快照", writing)
        self.assertNotIn("不可变医学批准快照", writing)
        self.assertIn("预览 Word", writing)
        self.assertIn("正式 Word", writing)
        self.assertIn("workingCopyDirty", writing)

    def test_word_export_quality_gate_uses_plain_language_error(self):
        writing = self._writing_page()
        self.assertIn("function medicalWritingExportErrorText(error)", self.source)
        self.assertIn("终稿暂不能导出：仍有章节含待确认事实或内部标记。请点击“内容核查”逐项修订并重新冻结。", self.source)
        self.assertIn("medical writing content quality", self.source)
        self.assertIn("medicalWritingExportErrorText(error)", writing)
        self.assertEqual(self.source.count("medicalWritingExportErrorText(error)"), 3)
        self.assertNotIn("Word 导出失败：${apiErrorText(error)}", writing)

    def test_read_only_preview_surface_exposes_page_count_truth_boundary(self):
        writing = self._writing_page()
        preview_panel = (
            ROOT
            / "frontend"
            / "src"
            / "features"
            / "medical-writing"
            / "MedicalWritingPreviewPanel.jsx"
        ).read_text(encoding="utf-8")
        self.assertIn("MedicalWritingPreviewPanel", self.source)
        self.assertIn("document-preview?mode=draft_preview", writing)
        self.assertIn("setDocumentPreview", writing)
        self.assertIn("workingCopyDirty", writing)
        self.assertIn("快速估算", preview_panel)
        self.assertIn("Word已核验", preview_panel)
        self.assertIn("不等同于 Word 最终页数", preview_panel)
        self.assertIn("snapshot_sha256", preview_panel)

    def test_ai_provider_preset_switches_role_model_and_expected_model_together(self):
        self.assertIn("role_model: preset.default_model", self.source)
        self.assertIn("expected_response_model: preset.default_model", self.source)

    def test_chinese_command_and_boundary_strings(self):
        """Key Chinese command labels and boundary strings must be present."""
        writing = self._writing_page()
        # Create working copy / Save / Author freeze command text
        self.assertIn("创建工作副本", writing, "Create working copy command must be present")
        self.assertIn("保存工作副本", writing, "Save working copy command must be present")
        self.assertIn("确认并冻结", writing, "Author freeze command must be present")
        self.assertIn("解除冻结", writing, "Author unfreeze command must be present")
        self.assertNotIn("提交审批", writing, "Medical writing must not expose a retired submit-approval command")
        # Boundary strings
        self.assertIn("原始方案只读来源", writing, "Original source read-only boundary must be stated")
        self.assertIn("来源只读", self.source, "The compact source boundary must remain visible")
        self.assertNotIn("源 DOCX 永久保持只读", writing, "Redundant source explanation must not occupy the editor")
        self.assertIn("请先创建并保存工作副本", writing, "Precondition boundary for toolbar must be stated")
        self.assertIn("医学作者点击“选用并写入”即形成医学决定", writing)

    def test_409_version_conflict_handling(self):
        """409 version conflict must be handled with refresh prompt, not silent overwrite."""
        self.assertIn("409", self.source, "409 status code handling must be present")
        # Check for conflict handling pattern
        self.assertTrue(
            re.search(r"status\s*===\s*409|\.status\s*!==?\s*409", self.source),
            "409 comparison must be explicit in source",
        )

    def test_source_only_ai_selection_boundary(self):
        """AI selection must clearly state it is based on original source, not working copy text."""
        writing = self._writing_page()
        # The revision form must show source-only boundary
        self.assertIn("仅基于已登记的原始证据", self.source, "AI must state it works on registered original evidence only")
        # The revision boundary line must be present
        self.assertIn("revision-boundary-line", writing, "Revision boundary line must be rendered")
        self.assertIn("AI输出为可追溯候选", writing, "AI suggestions must be explicitly marked as candidates only")
        self.assertIn("医学作者点击“选用并写入”即形成医学决定", writing)

    def test_default_ai_revision_target_prefers_body_over_section_heading(self):
        """Without an explicit selection, AI must revise current body text rather than the heading."""
        writing = self._writing_page()
        self.assertIn('block.block_type !== "heading"', writing)
        self.assertIn('workingBlock?.block_type === "heading"', self.source)
        self.assertIn("revisionWorkingBlock?.source_locator", self.source)
        self.assertIn("contentBlockText(revisionWorkingBlock)", self.source)
        self.assertIn("defaultRevisionWorkingBlock?.text", writing)
        self.assertIn("defaultRevisionWorkingBlock?.source_locator", writing)
        self.assertNotIn("sectionContent?.content_blocks?.[0]?.text", writing)

    def test_fixed_internal_document_map_scroll(self):
        """Document-map section buttons must have internal overflow scroll, not expand page."""
        self.assertIn("writing-section-buttons", self.styles, "Section buttons container must be styled")
        section_match = re.search(r"\.writing-section-buttons\s*\{(?P<body>.*?)\n\}", self.styles, re.S)
        self.assertIsNotNone(section_match, "writing-section-buttons CSS block must exist")
        section_body = section_match.group("body")
        self.assertIn("overflow", section_body, "Section buttons must have overflow property set")
        self.assertTrue(
            re.search(r"overflow-y:\s*(auto|scroll)", section_body),
            "Section buttons must use overflow-y: auto or scroll for internal scrolling",
        )

    def test_qc_script_uses_import_meta_for_stable_output_path(self):
        """QC script must resolve output path from import.meta.url, not process.cwd()."""
        self.assertIn("import.meta.url", self.qc_source, "QC script must use import.meta.url for path resolution")
        self.assertIn("fileURLToPath", self.qc_source, "QC script must import fileURLToPath")
        self.assertIn("__dirname", self.qc_source, "QC script must derive __dirname from import.meta.url")
        # Must NOT rely on process.cwd() for outputDir
        self.assertNotRegex(
            self.qc_source,
            r"process\.cwd\(\).*records",
            "Output path must not depend on process.cwd()",
        )

    def test_qc_script_no_capture_beyond_viewport(self):
        """QC screenshot must use fixed viewport, not captureBeyondViewport:true."""
        self.assertNotIn("captureBeyondViewport", self.qc_source, "captureBeyondViewport must be removed from QC script")
        self.assertIn("fromSurface: true", self.qc_source, "Screenshot must use fromSurface")

    def test_qc_script_new_runtime_assertions(self):
        """QC script must assert the current editor, on-demand directory, overflow, and path-leak contracts."""
        # Working copy status loaded
        self.assertIn("workingCopyStatusLoaded", self.qc_source, "QC must assert working-copy status loaded")
        # Revision visible
        self.assertIn("revisionVisible", self.qc_source, "QC must assert revision visible")
        # Command boundaries: create/save/freeze
        self.assertIn("workingCopyCommandBoundaryCorrect", self.qc_source, "QC must assert working-copy command state")
        self.assertIn("freezeButtonPresent", self.qc_source, "QC must assert author freeze/unfreeze command present")
        self.assertNotIn("approvalButtonPresent", self.qc_source, "QC must not require retired medical-writing approval command")
        self.assertIn("submitAiButtonPresent", self.qc_source, "QC must assert AI submit button present")
        self.assertIn("aiCommandBoundaryPresent", self.qc_source, "QC must assert AI command boundary present")
        # The directory is an on-demand drawer and must not compress the editor.
        self.assertIn("documentMapHiddenByDefault", self.qc_source, "QC must assert the directory drawer closes after use")
        self.assertIn("sectionButtonCount", self.qc_source, "QC must verify the complete directory was rendered")
        # Editor/AI x-order
        self.assertIn("editorAiOrderCorrect", self.qc_source, "QC must assert editor/AI x-order")
        # No page overflow
        self.assertIn("noPageOverflowX", self.qc_source, "QC must assert no horizontal page overflow")
        # No path leak
        self.assertIn("noLocalPathLeak", self.qc_source, "QC must assert no local path leak")

    def test_writing_layout_editor_ai_columns_and_external_map_drawer(self):
        """The persistent grid contains editor + AI; the map is an external drawer."""
        layout_match = re.search(r"\.writing-layout\s*\{(?P<body>.*?)\n\}", self.styles, re.S)
        self.assertIsNotNone(layout_match, "Writing layout CSS block must exist")
        layout_body = layout_match.group("body")
        self.assertIn("grid-template-areas:", layout_body, "Grid template areas must be defined")
        areas_match = re.search(r'grid-template-areas:\s*"([^"]+)"', layout_body)
        self.assertIsNotNone(areas_match, "grid-template-areas value must be a quoted string")
        areas = areas_match.group(1)
        editor_pos = areas.find("editor")
        ai_pos = areas.find("ai")
        self.assertGreater(editor_pos, -1, "editor must appear in grid-template-areas")
        self.assertGreater(ai_pos, -1, "ai must appear in grid-template-areas")
        self.assertLess(editor_pos, ai_pos, "editor must come before ai in grid-template-areas")
        self.assertNotIn("map", areas, "the document map must not consume a persistent grid column")
        self.assertIn("writing-document-map-backdrop", self.source)
        self.assertIn("writing-document-map-drawer", self.source)

    def test_synopsis_missing_fields_use_medical_chinese_labels(self):
        self.assertIn('"framing.intrinsic_objectives": "内在研究目的"', self.authoring_journey_source)
        self.assertIn('"picos.inclusion_modules": "入选标准"', self.authoring_journey_source)
        self.assertIn('"picos.aesi_definitions": "特别关注的不良事件（AESI）"', self.authoring_journey_source)
        self.assertIn(
            "imported.missing_fields.map((item) => <li key={item} title={item}>{synopsisFieldLabel(item)}</li>)",
            self.authoring_journey_source,
        )

    def test_followup_rewrite_guidance_is_intent_specific_and_never_prefilled(self):
        writing = self._writing_page()

        self.assertIn('useState("")', writing)
        self.assertIn("revisionFollowupPlaceholders[activeRevisionIntent]", writing)
        self.assertIn('medical_writing_revision: "具体指出需要保留的事实', self.source)
        self.assertIn('regulatory_tone: "具体指出义务强度或监管措辞问题', self.source)
        self.assertIn('consistency_check: "具体指出待核对的冲突或口径', self.source)
        self.assertIn('evidence_gap: "具体指出需要补强的主张和允许使用的证据', self.source)
        self.assertIn('setRevisionRewriteInstruction("")', writing)
        self.assertNotIn("请保留原终点名称，并补充与SAP时间窗定义衔接的保守表述", self.source)

    def test_project_literature_tab_inserts_source_bound_citation_mark(self):
        writing = self._writing_page()
        citation_qc = self.writing_literature_citation_qc_source
        self.assertIn('"文献"', writing)
        self.assertIn("MedicalWritingLiteraturePanel", writing)
        self.assertIn("queueCitationInsertion", writing)
        self.assertIn("citationInsertion={citationInsertion}", writing)
        self.assertIn('name: "citation"', self.source)
        self.assertIn('"data-reference-id"', self.source)
        self.assertNotIn("referenceId: {\n        default: null", self.source)
        self.assertIn("normalizeCitationMarkAttributes(block.rich_text)", self.source)
        self.assertIn("normalizeCitationMarkAttributes(cell?.rich_text)", self.source)
        self.assertIn('text: "[待编号]"', self.source)
        self.assertIn("referenceIds: [referenceId]", self.source)
        self.assertNotIn("normalizeProtocolCitationNumbers", self.source)
        self.assertNotIn("legacyReferenceMaxNumber", self.source)
        self.assertNotIn("citationNumberOffset", self.source)
        self.assertNotIn("numberOffset", self.source)
        self.assertIn("savedReferenceIds.includes(reference.reference_id)", citation_qc)
        self.assertIn("inspectUnifiedCitationDocx(docxPath, targetBlock)", citation_qc)
        self.assertIn("docxUnifiedIndex.verified", citation_qc)
        self.assertIn('scope: "frontend_reference_identity_and_exporter_unified_index"', citation_qc)
        self.assertIn("referenceParagraph.text.startsWith(`${citation.text} `)", citation_qc)
        self.assertNotIn("legacyReferenceMaxNumber", citation_qc)
        self.assertNotIn("expectedCitationText", citation_qc)
        self.assertIn("reference.reference_id", self.writing_literature_source)
        self.assertIn("在当前光标处插入引文", self.writing_literature_source)

    def test_authoring_search_plan_separates_registry_filters_from_medical_triage(self):
        self.assertIn("实际发送到注册库的条件", self.authoring_journey_source)
        self.assertIn("检索后医学分诊线索", self.authoring_journey_source)
        self.assertIn("searchPlan?.registry_filter", self.authoring_journey_source)
        self.assertIn("searchPlan?.triage_criteria", self.authoring_journey_source)
        self.assertNotIn("legacyRegistryFilter", self.authoring_journey_source)
        self.assertNotIn("legacyTriageCriteria", self.authoring_journey_source)
        self.assertIn("searchContractIncomplete", self.authoring_journey_source)
        self.assertIn("检索合同版本过旧，请刷新页面后重试", self.authoring_journey_source)
        self.assertNotIn(
            "{searchPlan?.queries?.length > 0 && <ol>",
            self.authoring_journey_source,
        )
        self.assertIn(".authoring-search-contract", self.styles)

    # --- SoA section runtime routing (M11 1.3 -> focused SoA table designer) ---

    def test_soa_section_has_dedicated_table_target_not_picos_execution(self):
        self.assertIn('interactions.has("schedule_of_activities_editor")', self.source)
        self.assertIn('kind: "table"', self.source)
        self.assertIn('templateId: "schedule_of_activities"', self.source)
        self.assertIn('buttonLabel: "研究流程表"', self.source)
        self.assertNotIn(
            '"schedule_of_activities_editor", "analysis_set_builder", "sample_size_builder"',
            self.source,
        )
        # analysis_set / sample_size keep the existing PICOS execution routing
        self.assertIn('"analysis_set_builder", "sample_size_builder"', self.source)
        self.assertIn('group: "execution"', self.source)
        self.assertIn('buttonLabel: "执行与统计"', self.source)

    def test_soa_candidates_match_structured_and_section_native_not_title(self):
        writing = self._writing_page()
        self.assertIn("sectionSoaTableCandidates", writing)
        self.assertIn(
            'section.interactionTypes?.includes("schedule_of_activities_editor")',
            writing,
        )
        self.assertIn('block.block_type === "table" && Array.isArray(block.rows)', writing)
        self.assertIn('block.template_id === "schedule_of_activities"', writing)
        self.assertIn('block.structured_table?.domain === "schedule_of_activities"', writing)
        # section-native table blocks stay pending-mapping candidates; no title-regex identity
        self.assertIn("structured: block.template_id", writing)
        self.assertNotIn("流程表|schedule of", writing)

    def test_unique_soa_candidate_opens_designer_by_stable_block_id(self):
        writing = self._writing_page()
        self.assertIn("openSectionSoaEntry", writing)
        self.assertIn("sectionSoaTableCandidates.length === 1", writing)
        self.assertIn("const [onlyCandidate] = sectionSoaTableCandidates;", writing)
        self.assertIn("setInsertedTableBlockId(onlyCandidate.blockId)", writing)
        self.assertIn("focusTableBlockId={insertedTableBlockId}", writing)

    def test_imported_soa_entry_does_not_require_greenfield_authoring_journey(self):
        writing = self._writing_page()
        self.assertIn("structuredDesignTriggerAvailable", writing)
        self.assertIn(
            '["table", "document_object"].includes(structuredDesignTarget.kind) || authoringJourneyAvailable',
            writing,
        )
        self.assertIn("{structuredDesignTriggerAvailable && (", writing)
        self.assertNotIn(
            "{authoringJourneyAvailable && structuredDesignTarget && !isStudySchemaSection && (",
            writing,
        )

    def test_multiple_soa_candidates_require_explicit_selection_never_first(self):
        writing = self._writing_page()
        self.assertIn("setSoaCandidatePicker(sectionSoaTableCandidates)", writing)

    def test_front_matter_and_synopsis_use_dedicated_document_object_entries(self):
        writing = self._writing_page()
        self.assertIn('kind: "document_object", role: "layout"', self.source)
        self.assertIn('kind: "document_object", role: "protocol_synopsis"', self.source)
        self.assertIn('buttonLabel: "方案首页"', self.source)
        self.assertIn('buttonLabel: "方案摘要"', self.source)
        self.assertIn("sectionDocumentObjectCandidates", writing)
        self.assertIn("openSectionDocumentObjectEntry", writing)
        self.assertIn("setDocumentObjectPicker", writing)
        self.assertIn("data-document-object-block-id", writing)
        self.assertIn("不会进入正文表格编号或表目录", writing)
        self.assertIn('aria-label="选择要打开的研究流程表"', writing)
        self.assertIn("soaCandidatePicker.map", writing)
        self.assertIn("data-soa-candidate-block-id", writing)
        self.assertIn('表格 {index + 1} · {candidate.title || "未命名表格"}', writing)
        self.assertNotIn("sectionSoaTableCandidates[0]", writing)
        self.assertNotIn("aria-activedescendant", writing)
        self.assertNotIn('role="listbox"', writing)
        self.assertIn("function useSoaModalFocusA11y(", self.source)
        self.assertIn("[tabindex]:not([tabindex='-1'])", self.source)
        self.assertIn('event.key === "Escape"', self.source)
        self.assertIn('event.key !== "Tab"', self.source)

    def test_soa_zero_candidate_requires_confirm_then_instantiate_with_gates(self):
        writing = self._writing_page()
        self.assertIn("setSoaCreateConfirmOpen(true)", writing)
        self.assertIn('aria-label="创建研究流程表"', writing)
        self.assertIn("创建并打开", writing)
        self.assertIn("data-gate-reason", writing)
        self.assertIn("soaCreateGateReason", writing)
        self.assertIn("workingCopyRevision < 1", writing)
        self.assertIn("!workingCopyDirty", writing)
        self.assertIn("editorFrozen", writing)
        self.assertIn("当前作者确认版本已冻结，请先解除冻结再编辑", writing)
        self.assertIn("workingCopyActionBusy", writing)
        self.assertIn("selectedSectionConsistencyBlocked", writing)
        self.assertIn('insertTableTemplate("schedule_of_activities")', writing)
        self.assertIn("table-insert-", writing)
        self.assertNotIn("soa/create", self.source)
        insert_body = re.search(r"const insertTableTemplate = .*?\n  \};", writing, re.S)
        self.assertIsNotNone(insert_body, "insertTableTemplate source not found")
        self.assertNotIn(
            "selectedSectionConsistencyBlocked",
            insert_body.group(0),
            "consistency gate must stay local to the SoA create-confirm branch",
        )

    def test_soa_source_table_never_auto_confirms_mapping(self):
        writing = self._writing_page()
        self.assertNotIn('mapping_status: "confirmed_by_user"', writing)
        self.assertIn(
            'suggestedTableDomain={isSoaSection ? "schedule_of_activities" : ""}',
            writing,
        )
        self.assertIn("suggestedDomain={suggestedTableDomain}", self.source)
        self.assertIn("待人工确认映射", writing)

    def test_soa_entry_state_resets_on_section_switch(self):
        writing = self._writing_page()
        effect = re.search(
            r"useEffect\(\(\) => \{\s*setSelectedEditorText\(\"\"\);.*?\}, \[selectedSection\]\);",
            writing,
            re.S,
        )
        self.assertIsNotNone(effect, "section-switch reset effect not found")
        self.assertIn("setSoaCandidatePicker(null)", effect.group(0))
        self.assertIn("setSoaCreateConfirmOpen(false)", effect.group(0))

    def test_intervention_rules_routing_splits_6_4_6_9_6_10(self):
        self.assertIn("function medicalWritingStructuredTarget(section)", self.source)
        self.assertIn('startsWith("6.4")', self.source)
        self.assertIn('startsWith("6.9")', self.source)
        self.assertIn('startsWith("6.10")', self.source)
        self.assertIn('panel: "ip_actions"', self.source)
        self.assertIn('panel: "non_ip"', self.source)
        self.assertIn('panel: "cm"', self.source)
        self.assertIn('label: "试验用药品调整与处置"', self.source)
        self.assertIn('label: "非试验用药与补救治疗"', self.source)
        self.assertIn('label: "合并用药规则"', self.source)
        self.assertNotIn('"dose_modification_rule_builder", "non_investigational_intervention_builder", "concomitant_therapy_rule_builder"', self.source)

    def test_study_design_target_passes_panel_to_authoring_journey(self):
        self.assertIn("panel: \"\"", self.source)
        self.assertIn("target?.panel || \"\"", self.source)
        self.assertIn("initialInterventionPanel={studyDesignTarget.panel}", self.source)

    def test_authoring_journey_wires_intervention_rules_editor_and_panel(self):
        source = self.authoring_journey_source
        self.assertIn("initialInterventionPanel", source)
        self.assertIn("interventionPanel", source)
        self.assertIn("setInterventionPanel", source)
        self.assertIn("intervention_rules: null", source)
        self.assertIn("InterventionRulesEditor", source)
        self.assertIn('value={picos.intervention_rules || null}', source)
        self.assertIn('panel={interventionPanel}', source)
        self.assertIn('onPanelChange={setInterventionPanel}', source)

    def test_authoring_journey_renames_dose_regimen_to_routine_only(self):
        source = self.authoring_journey_source
        self.assertIn('label="试验药物常规用法用量"', source)
        self.assertNotIn('label="试验药物剂量、给药及调整规则"', source)

    def test_intervention_rules_editor_uses_frozen_json_shape(self):
        editor_source = (
            ROOT / "frontend" / "src" / "features" / "medical-writing"
            / "InterventionRulesEditor.jsx"
        ).read_text(encoding="utf-8")
        self.assertIn('"medical_writing_intervention_rules_v1"', editor_source)
        self.assertIn("authority", editor_source)
        self.assertIn("ip_regimens", editor_source)
        self.assertIn("ip_adjustment_policy", editor_source)
        self.assertIn("no_planned_adjustment_statement", editor_source)
        self.assertIn("ip_action_rules", editor_source)
        self.assertIn("non_ip_treatment_rules", editor_source)
        self.assertIn("cross_object_links", editor_source)
        for action_kind in (
            "planned_on_off", "temporary_interruption", "resume",
            "permanent_discontinuation", "discontinuation_taper",
            "post_discontinuation_follow_up",
        ):
            self.assertIn(action_kind, editor_source)
        for rule_class in (
            "background", "allowed_cm", "prohibited_cm",
            "rescue", "other_non_investigational",
        ):
            self.assertIn(rule_class, editor_source)
        self.assertIn("cm_dose_rule", editor_source)
        self.assertIn("linked_non_ip_rule_ids", editor_source)

    def test_intervention_rules_editor_has_segmented_panels_and_no_log_cards(self):
        editor_source = (
            ROOT / "frontend" / "src" / "features" / "medical-writing"
            / "InterventionRulesEditor.jsx"
        ).read_text(encoding="utf-8")
        for panel_key in ('"regimen"', '"ip_actions"', '"non_ip"', '"cm"'):
            self.assertIn(panel_key, editor_source)
        self.assertIn("intervention-rules-segments", editor_source)
        self.assertIn("intervention-rules-row", editor_source)
        self.assertNotIn("intervention-rules-log", editor_source)
        self.assertNotIn("intervention-rules-info-card", editor_source)
        self.assertIn(".intervention-rules-editor", self.styles)
        self.assertIn(".intervention-rules-segments", self.styles)
        self.assertIn(".intervention-rules-row", self.styles)

    def test_intervention_rules_editor_authority_flips_on_structured_use(self):
        editor_source = (
            ROOT / "frontend" / "src" / "features" / "medical-writing"
            / "InterventionRulesEditor.jsx"
        ).read_text(encoding="utf-8")
        self.assertIn('authority === "structured"', editor_source)
        self.assertIn('next.authority = "structured"', editor_source)
        self.assertIn('next.ip_adjustment_policy !== "unspecified"', editor_source)
        self.assertIn("next.no_planned_adjustment_statement.trim()", editor_source)

    def test_intervention_rules_editor_delete_and_cross_object_handlers_exist(self):
        editor_source = (
            ROOT / "frontend" / "src" / "features" / "medical-writing"
            / "InterventionRulesEditor.jsx"
        ).read_text(encoding="utf-8")
        self.assertIn("removeItem: (index)", editor_source)
        self.assertIn("function CrossObjectLinks", editor_source)
        self.assertIn('defaultSourceKind="rescue"', editor_source)
        self.assertIn('defaultSourceKind="cm"', editor_source)

    def test_intervention_rules_projection_is_explicit_and_protects_medical_edits(self):
        writing = self._writing_page()
        self.assertIn("interventionProjectionAvailable", writing)
        self.assertIn("interventionRulePanelHasContent", writing)
        self.assertIn('structuredInterventionRules?.authority !== "structured"', writing)
        self.assertIn('["background", "rescue", "other_non_investigational"]', writing)
        self.assertIn('["allowed_cm", "prohibited_cm"]', writing)
        self.assertIn("applyInterventionRulesToSection", writing)
        self.assertIn("/intervention-rules-projection", writing)
        self.assertIn("expected_intervention_rules_sha256", writing)
        self.assertIn("expected_working_copy_revision", writing)
        self.assertIn("overwrite_medical_edits", writing)
        self.assertIn("应用规则到正文", writing)
        self.assertIn("检测到人工修订", writing)
        self.assertIn("保留人工修订", writing)
        self.assertIn("确认覆盖", writing)
        self.assertIn("workingCopyDirty", writing)
        self.assertIn("editorFrozen", writing)
        self.assertIn("当前作者确认版本已冻结", writing)
        self.assertIn(".writing-intervention-projection-conflict", self.styles)

    def test_legacy_import_bootstrap_is_reachable_from_existing_document(self):
        writing = self._writing_page()
        self.assertIn("LegacyAuthoringBootstrapPanel", self.source)
        self.assertIn("!isDemoWritingSession && editorSessionAvailable && !authoringJourneyAvailable", writing)
        self.assertIn(
            "authoringJourneyAvailable && workingCopy && !workingCopyAuthoritative",
            writing,
        )
        self.assertIn("editorSessionAvailable", writing)
        self.assertIn("onConfirmed={() => refreshStudyConsistency()}", writing)
        self.assertIn("onOpenBinding={openStudyRebind}", writing)

    def test_legacy_import_bootstrap_is_ai_prefilled_and_single_confirmation(self):
        source = self.legacy_authoring_bootstrap_source
        self.assertIn("/legacy-authoring-bootstrap/prepare", source)
        self.assertIn("/legacy-authoring-bootstrap/confirm", source)
        self.assertIn("proposed_framing", source)
        self.assertIn("proposed_picos", source)
        self.assertIn("proposed_synopsis_text", source)
        self.assertIn("AI已预填；仅修订不准确处", source)
        self.assertIn("确认并建立研究设计", source)
        self.assertIn("const poll = async () =>", source)
        self.assertIn("globalThis.setTimeout(poll, 3000)", source)
        self.assertNotIn("globalThis.setTimeout(poll, 1200)", source)
        self.assertIn("正在提取研究设计", source)
        self.assertIn("文件解析", source)
        self.assertIn("合并核对", source)
        self.assertIn("missingCoreFields.length === 0", source)
        self.assertIn("还需补全 {missingCoreFields.length} 项", source)
        self.assertIn('status.state === "failed" ? `-${Date.now()}` : ""', source)
        self.assertNotIn("待医学批准", source)
        self.assertNotIn("提交医学审批", source)

    def test_legacy_import_confirms_only_visible_reviewed_paths(self):
        source = self.legacy_authoring_bootstrap_source
        expected_paths = {
            "framing.protocol_id",
            "framing.version",
            "framing.document_title",
            "framing.indication",
            "framing.study_phase",
            "framing.investigational_product",
            "framing.target_mechanism",
            "framing.design_pattern",
            "framing.population_intent",
            "picos.population_summary",
            "picos.intervention_summary",
            "picos.comparator_summary",
            "picos.primary_endpoint",
        }
        frontend_match = re.search(
            r"LEGACY_BOOTSTRAP_CONFIRMED_PATHS = Object\.freeze\(\[(.*?)\]\);",
            source,
            re.S,
        )
        backend_match = re.search(
            r"LEGACY_BOOTSTRAP_CONFIRMED_PATHS = frozenset\(\s*\{(.*?)\}\s*\)",
            self.authoring_journey_service_source,
            re.S,
        )
        self.assertIsNotNone(frontend_match)
        self.assertIsNotNone(backend_match)
        frontend_paths = set(re.findall(r'"([^"]+)"', frontend_match.group(1)))
        backend_paths = set(re.findall(r'"([^"]+)"', backend_match.group(1)))
        self.assertEqual(expected_paths, frontend_paths)
        self.assertEqual(frontend_paths, backend_paths)
        self.assertIn("LEGACY_BOOTSTRAP_CONFIRMED_PATHS", source)
        self.assertIn("data-confirmed-path={confirmedPath}", source)
        for path in expected_paths:
            self.assertEqual(
                1,
                source.count(f'fieldPath="{path}"'),
                f"{path} must be declared once and bound to one visible input",
            )
        for hidden_path in (
            "picos.inclusion_modules",
            "picos.exclusion_modules",
            "picos.safety_endpoints",
            "picos.aesi_definitions",
            "picos.sample_size_strategy",
            "picos.statistical_strategy",
        ):
            self.assertNotIn(hidden_path, source)

    def test_legacy_import_bootstrap_preserves_detected_role_and_author_override(self):
        source = self.legacy_authoring_bootstrap_source
        self.assertIn("detected_source_role", source)
        self.assertIn("confirmed_source_role", source)
        self.assertIn("source_role_override_reason", source)
        self.assertIn("系统识别只作为建议；您的选择即为本项目确认。", source)
        self.assertIn("roleOverrideReason.trim().length >= 10", source)
        self.assertIn("原提示会持续保留", source)
        self.assertIn("validationOverrideReason.trim().length >= 10", source)
        self.assertIn(".legacy-bootstrap-drawer", self.styles)

    def test_phase1_typed_parts_are_editable_and_persist_through_framing_cas(self):
        source = self.authoring_journey_source
        editor = self._source_between(
            source,
            "function Phase1PartsEditor",
            "function PicosFields",
        )

        for part_code in (
            "SAD",
            "MAD",
            "食物影响",
            "物质平衡",
            "肝损伤",
            "肾损伤",
            "DDI",
            "首次患者",
        ):
            self.assertIn(f'code: "{part_code}"', source)

        for field_name in (
            "population",
            "cohort_dose",
            "pk_pd",
            "safety",
            "stopping_rules",
            "soa_summary",
            "transition_dependencies",
        ):
            self.assertIn(f'key: "{field_name}"', source)
            self.assertIn(f"part[field.key]", editor)

        self.assertIn("framing?.structured_design?.phase1_parts", source)
        self.assertIn('update("structured_design"', editor)
        self.assertIn("phase1_parts: nextParts", editor)
        self.assertIn("phase1_sequence", editor)
        self.assertIn("phase1PartsReady", source)
        self.assertIn("!typedPhase1PartsReady", source)
        self.assertIn('saveDraft("framing", baseJourney)', source)
        self.assertIn("expected_revision: sourceRevision", source)
        self.assertIn(
            "/authoring-journey/stages/${targetStage}/draft",
            source,
        )
        self.assertIn("framingPendingDraft", source)
        self.assertIn("确定性投影继续阻断", editor)
        self.assertNotIn("医学批准", editor)

        for selector in (
            ".phase1-parts-editor",
            ".phase1-part-selector",
            ".phase1-part-list",
            ".phase1-part-item",
            ".phase1-part-fields",
        ):
            self.assertIn(selector, self.authoring_journey_styles)
        self.assertNotIn(".card", self.authoring_journey_styles)

    def test_blank_section_candidates_use_the_product_ai_only(self):
        self.assertNotIn("章节首稿推荐（改选即可）", self.source)
        self.assertNotIn("lazy_text_candidates", self.source)
        self.assertNotIn("懒预填", self.source)
        self.assertIn("生成本章首稿候选", self.source)
        self.assertIn("独立AI将基于已确认研究事实", self.source)
        self.assertIn("onClick={submitRevisionRequest}", self.source)

    def test_authoring_copy_does_not_hard_code_the_switchable_ai_model(self):
        self.assertNotIn("DeepSeek-v4-pro", self.authoring_journey_source)
        self.assertNotIn("qwen3.8-max-preview", self.authoring_journey_source)
        self.assertIn("独立AI拆解为可确认事实", self.authoring_journey_source)

    def test_ai_revision_has_one_entry_and_intent_specific_defaults(self):
        self.assertIn("latestRevisionRoundSuggestions(activeThread)", self.source)
        self.assertIn('setActiveWritingRailTab("AI")', self.source)
        self.assertNotIn("titleAiActions", self.source)
        self.assertIn("handleRevisionIntentChange", self.source)
        self.assertIn("nextIntent.defaultInstruction", self.source)
        for intent in (
            "medical_writing_revision",
            "regulatory_tone",
            "consistency_check",
            "evidence_gap",
        ):
            self.assertIn(f'value: "{intent}"', self.source)

    def test_pipeline_start_fires_before_journey_state_application(self):
        """Release-r9 root cause: research-pipeline/start must be sent
        BEFORE applyJourneyResponse / onJourneyChanged so that the
        React re-render or parent callback triggered by those state
        updates cannot abandon the start request."""
        source = self.authoring_journey_source
        match = re.search(
            r"const runPublicSearch = async.*?(?=\n  const retryAutomaticResearch)",
            source,
            re.S,
        )
        self.assertIsNotNone(match)
        source = match.group(0)

        # Locate the runPublicSearch body (search fetch through pipeline-start).
        search_idx = source.index("authoring-journey/competitor-search")
        start_idx = source.index("research-pipeline/start")
        apply_idx = source.index("applyJourneyResponse(searched)")
        callback_idx = source.index("onJourneyChanged?.(searched)")

        # All four tokens must exist.
        self.assertGreater(search_idx, 0)
        self.assertGreater(start_idx, 0)
        self.assertGreater(apply_idx, 0)
        self.assertGreater(callback_idx, 0)

        # The pipeline-start fetch must appear AFTER the competitor-search
        # fetch (it depends on the search snapshot).
        self.assertGreater(start_idx, search_idx)

        # CRITICAL: pipeline-start must appear BEFORE applyJourneyResponse
        # and onJourneyChanged.  If applyJourneyResponse fires first, the
        # resulting React re-render / parent callback can unmount or navigate
        # away from the component before the start fetch reaches the server.
        self.assertLess(start_idx, apply_idx)
        self.assertLess(start_idx, callback_idx)

    def test_pipeline_start_preserves_search_snapshot_on_failure(self):
        """If pipeline start fails, the search snapshot must still be
        applied to journey state and the failure must be visible/retryable."""
        match = re.search(
            r"const runPublicSearch = async.*?(?=\n  const retryAutomaticResearch)",
            self.authoring_journey_source,
            re.S,
        )
        self.assertIsNotNone(match)
        source = match.group(0)

        start_idx = source.index("research-pipeline/start")
        catch_idx = source.index("catch (pipeError)")
        apply_idx = source.index("applyJourneyResponse(searched)")
        self.assertIn('"pipeline_start_failed"', source)
        self.assertIn("journey: searched", source)
        self.assertLess(start_idx, catch_idx)
        self.assertLess(catch_idx, apply_idx)
        self.assertIn("setResearchRecovery", source)

    def test_pipeline_start_request_is_not_guarded_by_a_second_stale_check(self):
        """The stale check runs once after competitor-search returns.  The
        pipeline-start fetch must follow immediately without a second stale
        check that could skip the start when a concurrent re-render resets
        the token ref."""
        match = re.search(
            r"const runPublicSearch = async.*?(?=\n  const retryAutomaticResearch)",
            self.authoring_journey_source,
            re.S,
        )
        self.assertIsNotNone(match)
        source = match.group(0)

        # Find the region between the stale check return and pipeline-start.
        stale_return = source.index('return { status: "stale_project" };', source.index("competitor-search"))
        start_fetch = source.index("research-pipeline/start")

        # There must NOT be a second stale-check return between the first
        # stale_project return and the pipeline-start fetch.  A second check
        # would skip the start when applyJourneyResponse resets the token.
        between = source[stale_return + len('return { status: "stale_project" };'):start_fetch]
        self.assertNotIn('return { status: "stale_project" }', between)

    def test_pipeline_start_is_not_skipped_by_same_project_ui_token_rotation(self):
        """A same-project remount may rotate the automatic-search UI token.

        The server-side pipeline start is the idempotent continuation of the
        immutable search snapshot and must still be sent; only a project switch
        may suppress it.  The previous token guard returned before the POST,
        leaving a confirmed triage with no pipeline or downstream artifacts.
        """
        match = re.search(
            r"const runPublicSearch = async.*?(?=\n  const retryAutomaticResearch)",
            self.authoring_journey_source,
            re.S,
        )
        self.assertIsNotNone(match)
        source = match.group(0)
        start_idx = source.index("research-pipeline/start")
        before_start = source[:start_idx]
        self.assertIn("activeProjectRef.current !== requestProjectId", before_start)
        # The stale return guarding the start request must not depend on the
        # per-render token; that token is allowed to rotate on a remount.
        self.assertNotIn(
            "automaticResearchTokenRef.current !== researchToken",
            before_start,
        )

    def test_pipeline_start_response_is_ignored_after_project_switch(self):
        match = re.search(
            r"const runPublicSearch = async.*?(?=\n  const retryAutomaticResearch)",
            self.authoring_journey_source,
            re.S,
        )
        self.assertIsNotNone(match)
        source = match.group(0)

        start_idx = source.index("research-pipeline/start")
        post_start_guard = source.index(
            "activeProjectRef.current !== requestProjectId",
            start_idx,
        )
        apply_idx = source.index("applyJourneyResponse(searched)")
        self.assertLess(start_idx, post_start_guard)
        self.assertLess(post_start_guard, apply_idx)

    def test_authoring_writes_are_locked_while_pipeline_owns_frozen_inputs(self):
        source = self.authoring_journey_source
        self.assertIn("const authoringWriteBlocked = Boolean", source)
        self.assertIn("PIPELINE_STABLE_WAITING_STAGES.has(pipelineStage)", source)
        self.assertIn("authoringWriteBlockedMessage", source)
        self.assertIn("disabled={authoringWriteBlocked || Boolean(busy)", source)
        self.assertIn("if (authoringWriteBlocked)", source)

    def test_empty_public_basket_keeps_shared_corpus_fallback_visible(self):
        source = self.authoring_journey_source
        self.assertIn("emptyBasketFallback", source)
        self.assertIn("no_retainable_candidates_after_confirm", source)
        self.assertIn("no_public_protocol_results", source)
        self.assertIn("共享语料或手动上传", source)
        self.assertIn("未发现可下载的公开方案", source)


if __name__ == "__main__":
    unittest.main()
