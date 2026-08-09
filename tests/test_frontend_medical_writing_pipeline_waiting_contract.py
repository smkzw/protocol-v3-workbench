from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-writing"
    / "MedicalWritingAuthoringJourneySetup.jsx"
)
DRAWER = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-writing"
    / "AuthoringCompetitorDrawer.jsx"
)
REFERENCE_PANEL = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "writing-reference"
    / "WritingReferencePanel.jsx"
)
MAIN_API = ROOT / "services" / "api" / "app" / "main.py"


def test_user_action_waiting_stages_are_labeled_and_not_polled() -> None:
    source = SETUP.read_text(encoding="utf-8")

    waiting_stage_block = source.split(
        "const PIPELINE_STABLE_WAITING_STAGES = new Set(", 1
    )[1].split(");", 1)[0]
    assert '"awaiting_document_validation"' in waiting_stage_block
    assert '"awaiting_translation_scope"' in waiting_stage_block
    assert '"awaiting_corpus_analysis"' in waiting_stage_block
    assert '"awaiting_corpus_admission"' in waiting_stage_block
    assert 'awaiting_document_validation: "等待处理文件核验"' in source
    assert 'awaiting_translation_scope: "等待修复翻译范围"' in source
    assert '"awaiting_triage_confirm"' in waiting_stage_block
    assert "!PIPELINE_STABLE_WAITING_STAGES.has(stage)" in source
    assert "!isTerminal && !isWaitingForUser" in source
    assert 'stage !== "awaiting_corpus_admission"' in source
    assert "第一轮竞品语料分析已完成；可继续研究设计" in source


def test_waiting_banner_exposes_source_first_actions_and_resume_route() -> None:
    source = SETUP.read_text(encoding="utf-8")

    assert "check.observed_value" in source
    assert "当前项目预期：" in source
    assert "处理文件问题" in source
    assert "已处理，继续流水线" in source
    assert "/medical-writing/research-pipeline/resume" in source
    assert "expected_pipeline_id" in source
    assert "expected_stage" in source
    assert "status?.pipeline_retryable" in source
    assert "从已完成原文继续" in source
    assert "复用既有原文、解析和OCR结果" in source
    assert 'stage: "preparing"' in source
    assert "setPipelinePollNonce((current) => current + 1)" in source
    assert '"awaiting_translation_scope", "awaiting_corpus_analysis"' in source
    assert "重试后续语料分析" in source
    assert "继续翻译与分析" in source


def test_nonblocking_document_exceptions_are_compact_and_traceable() -> None:
    source = SETUP.read_text(encoding="utf-8")

    assert "pipeline.document_admission_exclusions" in source
    assert "research-pipeline-exclusions" in source
    assert "不适合作为本轮章节语料的原文，不影响其余资料继续" in source
    assert "item.detail || item.reason_code" in source
    assert "Array.isArray(item.checks)" in source
    assert "识别：" in source
    assert "预期：" in source


def test_file_issue_action_targets_existing_reference_processing_panel() -> None:
    setup_source = SETUP.read_text(encoding="utf-8")
    drawer_source = DRAWER.read_text(encoding="utf-8")
    reference_source = REFERENCE_PANEL.read_text(encoding="utf-8")

    assert 'view: "translations"' in setup_source
    assert "requestedArtifactId={referencePanelRequest?.artifactId" in setup_source
    assert "requestedView={requestedView}" in drawer_source
    assert "requestedArtifactId={requestedArtifactId}" in drawer_source
    assert "setActiveView(requestedView)" in reference_source
    assert "setSelectedArtifactId(requestedArtifactId)" in reference_source
    assert "确认沿用当前文件" in reference_source
    assert "确认沿用不代表系统判定已转为匹配" in reference_source


def test_resume_api_is_exposed_as_a_separate_narrow_endpoint() -> None:
    source = MAIN_API.read_text(encoding="utf-8")

    assert (
        '"/api/projects/{project_id}/medical-writing/research-pipeline/resume"'
        in source
    )
    assert "medical_writing_research_pipeline_service.resume_waiting(" in source


def test_banner_renders_persisted_child_progress_without_eta_or_technical_ids() -> None:
    source = SETUP.read_text(encoding="utf-8")

    for field in (
        "pipeline.child_completed",
        "pipeline.child_total",
        "pipeline.child_percent",
        "pipeline.child_label",
        "pipeline.child_context?.current_substep_percent",
        "research-pipeline-current-substep",
    ):
        assert field in source
    assert "pipeline.percent" in source
    assert "etaLabel" not in source
    assert "triageProgress.percent" in source


def test_banner_keeps_waiting_failure_and_success_copy_task_facing() -> None:
    source = SETUP.read_text(encoding="utf-8")

    assert "const taskMessage = isFailed" in source
    assert "研究流水线未完成；可按页面提示重试。" in source
    assert "当前步骤需要处理后才能继续。" in source
    assert "独立AI未返回可解析的最终语料分析JSON" in source
    assert "pipeline.detail" not in source


def test_compact_toolbar_projects_real_pipeline_substep_and_progress() -> None:
    source = SETUP.read_text(encoding="utf-8")

    assert 'data-testid="authoring-automatic-research-progress"' in source
    assert 'aria-label="竞品调研进度"' in source
    assert 'role="progressbar"' in source
    assert "compactResearchPipeline.child_label" in source
    assert "compactResearchChildCompleted" in source
    assert "compactResearchChildTotal" in source
    assert "compactResearchChildPercent" in source
    assert "compactResearchActive || busy" in source
    assert "showCompactResearchProgress" in source
    assert "!PIPELINE_TERMINAL_STAGES.has(compactResearchPipeline.stage)" in source
    assert 'className="authoring-competitor-toolbar-actions"' in source
    assert "competitorToolbarSummary" in source
    assert "已锁定" in source
    assert "公开研究处理已完成" in source
    assert 'compactResearchPipeline.stage === "failed"' in source
    assert "后续处理未完成，请查看原因并重试" in source
    assert "重试后续语料分析" in source
    assert "pipelineStatus?.pipeline_retryable" in source
    assert "独立AI返回的语料分析结构未符合系统合同" in source
    assert 'compactResearchPipeline.stage === "awaiting_preparation_admission"' in source
    assert "准入下一阶段原文" in source
    assert 'compactResearchPipeline.stage === "cancelled"' in source
