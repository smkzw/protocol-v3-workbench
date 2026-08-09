from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "frontend/src/features/medical-writing/StructuredTableDesigner.jsx"
STYLES = ROOT / "frontend/src/features/medical-writing/structured-table-designer.css"


def _component() -> str:
    return COMPONENT.read_text(encoding="utf-8")


def _styles() -> str:
    return STYLES.read_text(encoding="utf-8")


def test_component_is_independent_controlled_editor_without_network_or_save_chain():
    source = _component()
    assert "export function StructuredTableDesigner({" in source
    assert "onSelectedCellChange," in source
    assert "onChange?.(next)" in source
    assert "onClose?.()" in source
    assert "fetch(" not in source
    assert "axios" not in source
    assert "localStorage" not in source
    assert "sessionStorage" not in source
    assert "save" not in source.lower()
    assert 'import "./structured-table-designer.css"' in source


def test_component_preserves_unknown_fields_and_materializes_stable_local_ids():
    source = _component()
    assert "cloneValue(tableBlock" in source
    assert "...cell" in source
    assert "...structured" in source
    assert "...block" not in source  # The complete cloned block is mutated, not reconstructed.
    assert "globalThis.crypto?.randomUUID?.()" in source
    assert "fallbackIdSequence" in source
    assert "Math.random" not in source
    assert 'localId("row")' in source
    assert 'localId("column")' in source
    assert 'localId("cell")' in source
    assert '`${tableId}_cell_${rowIndex}_${cellIndex}`' in source
    assert "cell_id" in source
    assert "row_id" in source
    assert "column_id" in source
    assert "source_locator" in source
    assert "rowId: selected.row.row_id" in source
    assert "columnId: selected.column.column_id" in source
    assert "cellId: selected.cell.cell_id" in source
    assert "cellRevisionThreads.find" in source
    assert 'className="std-cell-ai-marker"' in source


def test_designer_rehydrates_parallel_backend_ids_before_persisting_cell_edits():
    source = _component()
    assert "function structuredColumnMetadata(block, index, tableId)" in source
    assert "structured.column_ids?.[index]" in source
    assert "structured.column_labels?.[index]" in source
    assert "sourceCell?.structure_column_id" in source
    assert "function structuredRowMetadata(block, row, rowIndex, tableId)" in source
    assert "structured.row_ids?.[rowIndex]" in source
    assert "sourceCell?.structure_row_id" in source
    assert "structure_column_id: columns[start]?.column_id" in source
    assert "structure_row_id: rowId" in source


def test_real_cells_merges_and_structural_conflicts_are_rendered_and_guarded():
    source = _component()
    assert "rowSpan={cell.row_span}" in source
    assert "colSpan={cell.column_span}" in source
    assert "row.cells.filter((cell) => !cell.hidden)" in source
    assert 'className="std-readonly-cell std-cell-select-button"' in source
    assert "<TableCellRichEditor" in source
    assert "onChange={(patch) =>" in source
    assert "focusRequest={cellEditorFocusRequest}" in source
    assert "onNavigateCell={navigateEditableCell}" in source
    assert "validateStructure(next)" in source
    assert "合并区域发生重叠" in source
    assert "所选区域不是未合并的规则矩形" in source
    assert "存在纵向合并单元格时不能移动行" in source
    assert "存在横向合并单元格时不能移动列" in source
    assert "附注存在空目标或失效目标" in source
    assert 'block?.structured_table?.schedule_of_activities' in source


def test_full_structural_toolbar_and_accessibility_contract_are_present():
    source = _component()
    for label in (
        "新增下一行",
        "删除当前行",
        "当前行上移",
        "当前行下移",
        "新增右侧列",
        "删除当前列",
        "当前列左移",
        "当前列右移",
        "合并所选规则矩形",
        "拆分当前合并单元格",
        "关闭表格设计器",
    ):
        assert label in source
    assert 'aria-label="医学写作结构化表格设计器"' in source
    assert 'aria-label="可水平和垂直滚动的表格画布"' in source
    assert "Alt+方向键移动焦点" in source
    assert 'event.key === "Escape"' in source
    assert "if (!extend || !selectionAnchorId) setSelectionAnchorId(cellId)" in source
    assert "setCellEditorFocusRequest((value) => value + 1)" in source


def test_soa_mode_exposes_manual_mapping_timing_plan_state_and_modular_notes():
    source = _component()
    assert 'const SOA_DOMAIN = "schedule_of_activities"' in source
    assert "function inferredSoaHeaderRows(model)" in source
    assert "isSoa ? inferredSoaHeaderRows(model) : 0" in source
    assert "建立待确认映射" in source
    assert "系统不会标记为 AI 已完成" in source
    assert 'mapping_status: "pending_user_confirmation"' in source
    assert 'mapping_status: "confirmed_by_user"' in source
    assert 'suggestedDomain = ""' in source
    assert "suggestedDomain === SOA_DOMAIN" in source
    assert "adoptSuggestedSoaDomain" in source
    assert "系统不会自动确认或改写原始来源表" in source
    for label in ("阶段", "访视", "研究日/周与时间窗", "活动", "计划状态"):
        assert label in source
    for state in ('label: "X"', 'label: "条件"', 'label: "持续"', 'label: "N/A"'):
        assert state in source
    assert "text: definition.cellText" in source
    assert "rich_text: null" in source
    for note_type in (
        'value: "item_set"',
        'value: "timing_rule"',
        'value: "condition"',
        'value: "specimen_preparation"',
        'value: "definition"',
        'value: "exception"',
        'value: "operational"',
    ):
        assert note_type in source
    assert "note_refs: [...new Set" in source


def test_promoted_domain_profiles_use_one_schema_driven_inspector():
    source = _component()
    assert "domainProfiles = []" in source
    assert "activeDomainProfile" in source
    assert "领域属性" in source
    assert "语义角色" in source
    assert "确认当前领域映射" in source
    assert "template_roles_attached" in source
    assert "pending_user_confirmation" in source
    assert "confirmed_by_user" in source
    assert "activeDomainProfile.warning_text" in source
    assert "允许自定义输入" in source
    assert 'selectedDomainRole?.control === "date"' in source
    assert 'type="date"' in source
    assert 'aria-label="领域日期字段快速录入"' in source
    assert "project_evidence_confirmed_by_user" in source
    assert "已根据当前项目方案核对阈值、试验用药处置、复测和恢复条件" in source
    assert "每行一条记录" in source
    assert "仅映射字段，不按行校验" in source
    assert "可保存草稿，但不能确认并冻结" in source
    assert "最终内容仍需医学批准" not in source
    assert "activeDomainProfile.column_roles.map" in source
    assert "if (domain === \"objectives_endpoints\")" not in source
    assert "if (domain === \"treatment_dose\")" not in source
    assert "if (domain === \"laboratory_panel\")" not in source
    assert "if (domain === \"version_history\")" not in source
    assert "if (domain === \"dose_modification\")" not in source


def test_column_semantic_roles_are_preserved_in_both_table_representations():
    source = _component()
    assert "semantic_role: explicit.semantic_role" in source
    assert "column_semantic_roles" in source
    assert "updateColumnSemanticRole" in source
    assert "structure_column_semantic_role" in source
    assert "semanticRole: selected.column.semantic_role" in source


def test_word_layout_is_same_table_metadata_not_a_second_document_model():
    source = _component()
    assert "structured_table.word_layout" in source
    assert 'updateWordLayout("landscape")' in source
    assert 'updateWordLayout("portrait")' in source
    assert 'value="repeat_header"' in source
    assert 'value="horizontal_panels"' in source
    assert "分面重复首列数" in source
    assert "第二版本" not in source


def test_front_matter_and_synopsis_roles_open_dedicated_document_object_modes():
    source = _component()
    assert 'objectRole === "layout"' in source
    assert 'objectRole === "protocol_synopsis"' in source
    assert "isDedicatedDocumentObject" in source
    assert "方案首页排版对象" in source
    assert "方案摘要结构化对象" in source
    assert "不进入正文表目录" in source
    assert "对应 M11 1.1" in source
    assert "!isDedicatedDocumentObject && !isSoa" in source


def test_caption_and_notes_are_editable_with_explicit_association_review():
    source = _component()
    assert "updateTableTitle" in source
    assert 'aria-label="表格标题"' in source
    assert "source_caption" in source
    assert "confirmCaptionAssociation" in source
    assert "确认表题关联" in source
    assert "sourceCaptionText" in source
    assert "来源表题：" in source
    assert "confirmNoteAssociation" in source
    assert "确认附注关联" in source
    assert 'source_kind: "working_copy_user_note"' in source
    assert 'review_status: "confirmed"' in source
    assert "association_reason" in source
    assert "note.source_refs.join" in source


def test_desktop_visual_contract_is_dense_scoped_and_overflow_safe():
    styles = _styles()
    assert ".structured-table-designer" in styles
    assert "position: fixed" in styles
    assert "min-width: 1120px" in styles
    assert "grid-template-columns: minmax(0, 1fr) 318px" in styles
    assert ".std-grid-scroll" in styles
    assert "overflow: auto" in styles
    assert ".sticky-first-column" in styles
    assert "position: sticky" in styles
    assert ".sticky-header" in styles
    assert ".std-cell-ai-marker" in styles
    assert "overflow-wrap: anywhere" in styles
    assert "letter-spacing: 0" in styles
    assert "border-radius: 4px" in styles
    assert "linear-gradient" not in styles
    assert "radial-gradient" not in styles


def test_component_module_compiles_independently_with_esbuild(tmp_path):
    esbuild = ROOT / "frontend/node_modules/.bin/esbuild"
    output = tmp_path / "structured-table-designer.js"
    subprocess.run(
        [
            str(esbuild),
            str(COMPONENT),
            "--bundle",
            "--format=esm",
            "--platform=browser",
            "--external:react",
            "--external:lucide-react",
            f"--outfile={output}",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert output.exists()
    assert output.stat().st_size > 20_000
