import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Check,
  Columns3,
  LayoutPanelTop,
  LockKeyhole,
  Merge,
  PanelRightClose,
  PanelRightOpen,
  PencilLine,
  Plus,
  Rows3,
  Sparkles,
  Split,
  StickyNote,
  Table2,
  Trash2,
  X,
} from "lucide-react";
import { TableCellRichEditor } from "./TableCellRichEditor";
import "./structured-table-designer.css";

const SOA_DOMAIN = "schedule_of_activities";
const CELL_ROLES = [
  { value: "body", label: "正文" },
  { value: "header", label: "表头" },
  { value: "section", label: "分区" },
];
const NOTE_TYPES = [
  { value: "item_set", label: "项目集合" },
  { value: "timing_rule", label: "时间规则" },
  { value: "condition", label: "适用条件" },
  { value: "specimen_preparation", label: "样本/准备" },
  { value: "definition", label: "定义" },
  { value: "exception", label: "例外" },
  { value: "operational", label: "执行说明" },
];
const PLAN_STATES = [
  { value: "planned", label: "X", cellText: "X" },
  { value: "conditional", label: "条件", cellText: "条件" },
  { value: "continuous", label: "持续", cellText: "持续" },
  { value: "not_applicable", label: "N/A", cellText: "N/A" },
];

let fallbackIdSequence = 0;

function cloneValue(value) {
  if (typeof globalThis.structuredClone === "function") return globalThis.structuredClone(value);
  return JSON.parse(JSON.stringify(value));
}

function localId(kind) {
  fallbackIdSequence += 1;
  const uuid = globalThis.crypto?.randomUUID?.()
    || `${Date.now().toString(36)}_${fallbackIdSequence.toString(36)}`;
  return `local_${kind}_${uuid}`;
}

function positiveInteger(value, fallback = 1) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function gridIndex(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : fallback;
}

function blockTitle(block) {
  return block?.structured_table?.title
    || block?.title
    || block?.title_hint
    || "未命名表格";
}

function tableDomain(block) {
  return block?.structured_table?.domain || block?.domain || "generic";
}

function inferredSoaHeaderRows(model) {
  const headerLabel = /^(?:研究阶段|试验阶段|访视周|访视天|研究日|访视窗口|访视日期|study period|visit week|study day|visit window)/i;
  let count = 0;
  for (const row of model.rows) {
    const firstVisibleCell = row.cells.find((cell) => !cell.hidden);
    if (!headerLabel.test(String(firstVisibleCell?.text || "").trim())) break;
    count += 1;
  }
  return count;
}

function columnCount(block) {
  let maximum = block?.structured_table?.columns?.length || 0;
  (block?.rows || []).forEach((row) => {
    let cursor = 0;
    (row || []).forEach((cell) => {
      const start = gridIndex(cell?.grid_column_index, cursor);
      const span = positiveInteger(cell?.column_span);
      maximum = Math.max(maximum, start + span);
      cursor = start + span;
    });
  });
  return Math.max(maximum, 1);
}

function structuredColumnMetadata(block, index, tableId) {
  const structured = block?.structured_table || {};
  const explicit = structured.columns?.[index] || {};
  const sourceCell = (block?.rows || [])
    .flatMap((row) => row || [])
    .find((cell) => (
      gridIndex(cell?.grid_column_index) === index
      && (cell?.structure_column_id || cell?.column_id)
    ));
  return {
    ...explicit,
    column_id: explicit.column_id
      || structured.column_ids?.[index]
      || sourceCell?.structure_column_id
      || sourceCell?.column_id
      || `${tableId}_column_${index}`,
    order: index,
    label: explicit.label || structured.column_labels?.[index] || `第 ${index + 1} 列`,
    style_role: explicit.style_role || structured.column_style_roles?.[index] || "body",
    width_twips: explicit.width_twips ?? structured.column_width_twips?.[index] ?? null,
    source_locator: explicit.source_locator || structured.column_source_locators?.[index] || "",
    semantic_role: explicit.semantic_role
      || structured.column_semantic_roles?.[index]
      || sourceCell?.structure_column_semantic_role
      || "",
  };
}

function structuredRowMetadata(block, row, rowIndex, tableId) {
  const structured = block?.structured_table || {};
  const explicit = structured.rows?.[rowIndex] || {};
  const sourceCell = (row || []).find((cell) => cell?.structure_row_id || cell?.row_id);
  return {
    ...explicit,
    row_id: explicit.row_id
      || structured.row_ids?.[rowIndex]
      || sourceCell?.structure_row_id
      || sourceCell?.row_id
      || `${tableId}_row_${rowIndex}`,
    order: rowIndex,
    label: explicit.label || structured.row_labels?.[rowIndex] || "",
    style_role: explicit.style_role || structured.row_style_roles?.[rowIndex] || sourceCell?.style_role || "body",
  };
}

function viewModel(block) {
  const tableId = block?.table_id || block?.structured_table?.table_id || "table";
  const count = columnCount(block);
  const columns = Array.from(
    { length: count },
    (_, index) => structuredColumnMetadata(block, index, tableId),
  );
  const rows = (block?.rows || []).map((row, rowIndex) => {
    const metadata = structuredRowMetadata(block, row, rowIndex, tableId);
    let cursor = 0;
    const cells = (row || []).map((cell, cellIndex) => {
      const start = gridIndex(cell?.grid_column_index, cursor);
      cursor = start + positiveInteger(cell?.column_span);
      return {
        ...cell,
        cell_id: cell?.cell_id || `${tableId}_cell_${rowIndex}_${cellIndex}`,
        grid_column_index: start,
        column_span: positiveInteger(cell?.column_span),
        row_span: positiveInteger(cell?.row_span),
        style_role: cell?.style_role || metadata.style_role || "body",
      };
    });
    return {
      ...metadata,
      row_id: metadata.row_id || cells[0]?.row_id || `${tableId}_row_${rowIndex}`,
      order: rowIndex,
      style_role: metadata.style_role || cells[0]?.style_role || "body",
      cells,
    };
  });
  return { tableId, columns, rows };
}

function synchronizeStructuredTable(block) {
  const structured = block.structured_table || {};
  const model = viewModel(block);
  const previousRows = structured.rows || [];
  const previousCells = new Map(
    previousRows.flatMap((row) => row?.cells || []).map((cell) => [cell.cell_id, cell]),
  );
  block.table_id = block.table_id || structured.table_id || localId("table");
  block.structured_table = {
    ...structured,
    schema_version: structured.schema_version || "structured_table_v1",
    table_id: block.table_id,
    block_id: structured.block_id || block.block_id || localId("block"),
    domain: structured.domain || block.domain || "generic",
    title: structured.title || block.title || block.title_hint || "未命名表格",
    source_locator: structured.source_locator || block.source_locator || "",
    version: Number.isInteger(structured.version) ? structured.version : 0,
    columns: model.columns.map((column, index) => ({
      ...(structured.columns?.[index] || {}),
      ...column,
      order: index,
    })),
    rows: model.rows.map((row, rowIndex) => ({
      ...(previousRows.find((item) => item.row_id === row.row_id) || previousRows[rowIndex] || {}),
      row_id: row.row_id,
      order: rowIndex,
      label: row.label || "",
      style_role: row.style_role || "body",
      source_locator: row.source_locator || "",
      cells: row.cells.map((cell) => ({
        ...(previousCells.get(cell.cell_id) || {}),
        ...cell,
        row_id: row.row_id,
        column_id: model.columns[cell.grid_column_index]?.column_id
          || model.columns[0].column_id,
        structure_row_id: row.row_id,
        structure_column_id: model.columns[cell.grid_column_index]?.column_id
          || model.columns[0].column_id,
        structure_row_order: rowIndex,
        structure_column_order: cell.grid_column_index,
        text: String(cell.text || ""),
      })),
    })),
    notes: Array.isArray(structured.notes) ? structured.notes : [],
    word_layout: {
      orientation: "landscape",
      ...(structured.word_layout || {}),
    },
  };
  block.structured_table.column_ids = block.structured_table.columns.map((column) => column.column_id);
  block.structured_table.column_labels = block.structured_table.columns.map((column) => column.label || "");
  block.structured_table.column_style_roles = block.structured_table.columns.map((column) => column.style_role || "body");
  block.structured_table.column_width_twips = block.structured_table.columns.map((column) => column.width_twips ?? null);
  block.structured_table.column_source_locators = block.structured_table.columns.map((column) => column.source_locator || "");
  block.structured_table.column_semantic_roles = block.structured_table.columns.map((column) => column.semantic_role || "");
  block.structured_table.row_ids = block.structured_table.rows.map((row) => row.row_id);
  block.structured_table.row_labels = block.structured_table.rows.map((row) => row.label || "");
  block.structured_table.row_style_roles = block.structured_table.rows.map((row) => row.style_role || "body");
  block.rows = block.structured_table.rows.map((row, rowIndex) => row.cells.map((cell) => ({
    ...cell,
    row_index: rowIndex,
    structure_column_semantic_role: block.structured_table.columns[cell.grid_column_index]?.semantic_role || "",
  })));
  return block;
}

function materializeBlock(block) {
  const next = cloneValue(block || { block_type: "table", rows: [] });
  next.rows = Array.isArray(next.rows) ? next.rows : [];
  const tableId = next.table_id || next.structured_table?.table_id || "table";
  const count = columnCount(next);
  const structured = next.structured_table || {};
  const columns = Array.from(
    { length: count },
    (_, index) => structuredColumnMetadata(next, index, tableId),
  );
  const rows = next.rows.map((row, rowIndex) => {
    const oldMeta = structuredRowMetadata(next, row, rowIndex, tableId);
    const rowId = oldMeta.row_id;
    let cursor = 0;
    return (row || []).map((cell, cellIndex) => {
      const start = gridIndex(cell?.grid_column_index, cursor);
      cursor = start + positiveInteger(cell?.column_span);
      return {
        ...cell,
        cell_id: cell?.cell_id || `${tableId}_cell_${rowIndex}_${cellIndex}`,
        row_id: rowId,
        column_id: columns[start]?.column_id || columns[0].column_id,
        structure_row_id: rowId,
        structure_column_id: columns[start]?.column_id || columns[0].column_id,
        structure_row_order: rowIndex,
        structure_column_order: start,
        row_index: rowIndex,
        grid_column_index: start,
        column_span: positiveInteger(cell?.column_span),
        row_span: positiveInteger(cell?.row_span),
        hidden: Boolean(cell?.hidden),
        style_role: cell?.style_role || oldMeta.style_role || "body",
      };
    });
  });
  next.structured_table = { ...structured, columns };
  next.rows = rows;
  return synchronizeStructuredTable(next);
}

function validateStructure(block) {
  const model = viewModel(block);
  const columnIds = model.columns.map((column) => column.column_id);
  const rowIds = model.rows.map((row) => row.row_id);
  const cellIds = model.rows.flatMap((row) => row.cells.map((cell) => cell.cell_id));
  const noteIds = (block?.structured_table?.notes || []).map((note) => note.note_id);
  if (new Set(columnIds).size !== columnIds.length) return "列 ID 冲突，已阻止本次操作。";
  if (new Set(rowIds).size !== rowIds.length) return "行 ID 冲突，已阻止本次操作。";
  if (new Set(cellIds).size !== cellIds.length) return "单元格 ID 冲突，已阻止本次操作。";
  if (new Set(noteIds).size !== noteIds.length) return "附注 ID 冲突，已阻止本次操作。";
  const validTargets = new Set([
    block?.table_id,
    block?.block_id,
    block?.structured_table?.block_id,
    ...columnIds,
    ...rowIds,
    ...cellIds,
  ].filter(Boolean));
  const soaMetadata = block?.structured_table?.soa || block?.structured_table?.schedule_of_activities || {};
  ["epochs", "visits", "activities", "cells"].forEach((collection) => {
    (soaMetadata[collection] || []).forEach((item) => {
      ["epoch_id", "visit_id", "activity_id", "cell_id"].forEach((key) => {
        if (item?.[key]) validTargets.add(item[key]);
      });
    });
  });
  for (const note of block?.structured_table?.notes || []) {
    if (!(note.target_ids || []).length || note.target_ids.some((targetId) => !validTargets.has(targetId))) {
      return "附注存在空目标或失效目标，已阻止本次操作。";
    }
  }
  const occupied = new Set();
  for (let rowIndex = 0; rowIndex < model.rows.length; rowIndex += 1) {
    for (const cell of model.rows[rowIndex].cells) {
      if (cell.hidden) continue;
      const rowSpan = positiveInteger(cell.row_span);
      const columnSpan = positiveInteger(cell.column_span);
      if (cell.grid_column_index + columnSpan > model.columns.length) {
        return "单元格跨列超出表格边界，已阻止本次操作。";
      }
      if (rowIndex + rowSpan > model.rows.length) {
        return "单元格跨行超出表格边界，已阻止本次操作。";
      }
      for (let r = rowIndex; r < rowIndex + rowSpan; r += 1) {
        for (let c = cell.grid_column_index; c < cell.grid_column_index + columnSpan; c += 1) {
          const key = `${r}:${c}`;
          if (occupied.has(key)) return "合并区域发生重叠，已阻止本次操作。";
          occupied.add(key);
        }
      }
    }
  }
  return "";
}

function cellLocation(model, cellId) {
  for (let rowIndex = 0; rowIndex < model.rows.length; rowIndex += 1) {
    const row = model.rows[rowIndex];
    const cell = row.cells.find((item) => item.cell_id === cellId);
    if (cell) {
      const columnIndex = cell.grid_column_index;
      return {
        rowIndex,
        columnIndex,
        row,
        column: model.columns[columnIndex],
        cell,
      };
    }
  }
  return null;
}

function selectedRectangle(model, anchorId, selectedId) {
  const anchor = cellLocation(model, anchorId);
  const selected = cellLocation(model, selectedId);
  if (!anchor || !selected) return null;
  return {
    top: Math.min(anchor.rowIndex, selected.rowIndex),
    bottom: Math.max(anchor.rowIndex, selected.rowIndex),
    left: Math.min(anchor.columnIndex, selected.columnIndex),
    right: Math.max(anchor.columnIndex, selected.columnIndex),
  };
}

function compactSourceBoundary(block) {
  const locator = block?.source_locator || block?.structured_table?.source_locator;
  if (!locator) return "当前工作副本表格；未提供来源定位";
  return `来源边界：${locator}`;
}

function IconButton({ label, icon: Icon, onClick, disabled = false, active = false }) {
  return (
    <button
      type="button"
      className={active ? "std-icon-button active" : "std-icon-button"}
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
    >
      <Icon size={15} aria-hidden="true" />
    </button>
  );
}

export function StructuredTableDesigner({
  tableBlock,
  readOnly = false,
  onChange,
  onClose,
  onSelectedCellChange,
  cellRevisionThreads = [],
  documentIndex = null,
  domainProfiles = [],
  suggestedDomain = "",
}) {
  const [draftBlock, setDraftBlock] = useState(() => cloneValue(tableBlock || {}));
  const [selectedCellId, setSelectedCellId] = useState("");
  const [selectionAnchorId, setSelectionAnchorId] = useState("");
  const [cellEditorFocusRequest, setCellEditorFocusRequest] = useState(0);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [inspectorTab, setInspectorTab] = useState("properties");
  const [error, setError] = useState("");

  useEffect(() => {
    setDraftBlock(cloneValue(tableBlock || {}));
  }, [tableBlock]);

  const model = useMemo(() => viewModel(draftBlock), [draftBlock]);
  const domain = tableDomain(draftBlock);
  const objectRole = draftBlock?.structured_table?.role || "unclassified";
  const isLayoutObject = objectRole === "layout";
  const isSynopsisObject = objectRole === "protocol_synopsis";
  const isDedicatedDocumentObject = isLayoutObject || isSynopsisObject;
  const objectRoleLabel = isLayoutObject
    ? "方案首页排版对象"
    : isSynopsisObject
      ? "方案摘要结构化对象"
      : "";
  const isSoa = domain === SOA_DOMAIN;
  const activeDomainProfile = isDedicatedDocumentObject
    ? null
    : domainProfiles.find((profile) => profile.domain === domain) || null;
  const selected = cellLocation(model, selectedCellId);
  const rectangle = selectedRectangle(model, selectionAnchorId, selectedCellId);
  const headerRowCount = Math.max(
    Number(draftBlock?.header_row_count || draftBlock?.structured_table?.header_row_count || 0),
    isSoa ? inferredSoaHeaderRows(model) : 0,
    model.rows.reduce((count, row, rowIndex) => (
      rowIndex === count
      && (row.style_role === "header" || row.cells.some((cell) => cell.style_role === "header"))
        ? count + 1
        : count
    ), 0),
  );
  const notes = draftBlock?.structured_table?.notes || [];
  const sourceCaption = draftBlock?.structured_table?.source_caption || null;
  const sourceCaptionText = String(
    draftBlock?.table_caption?.text || sourceCaption?.text || "",
  ).trim();
  const wordOrientation = draftBlock?.structured_table?.word_layout?.orientation || "landscape";
  const domainProfileState = draftBlock?.structured_table?.word_layout?.domain_profile || {};
  const domainMappingLabel = {
    template_roles_attached: "模板角色已附加，待医学确认",
    pending_user_confirmation: "待人工确认",
    confirmed_by_user: "已确认",
  }[domainProfileState.mapping_status] || "待建立映射";
  const mappedSemanticRoles = new Set(model.columns.map((column) => column.semantic_role).filter(Boolean));
  const missingRequiredRoles = (activeDomainProfile?.column_roles || [])
    .filter((role) => role.required && !mappedSemanticRoles.has(role.role_id));
  const selectedDomainRole = activeDomainProfile?.column_roles?.find(
    (role) => role.role_id === selected?.column?.semantic_role,
  ) || null;
  const domainRecordAxis = domainProfileState.record_axis || "semantic_only";
  const incompleteDomainRows = domainRecordAxis === "rows" && activeDomainProfile
    ? model.rows.slice(headerRowCount).filter((row) => {
      const visibleCells = row.cells.filter((cell) => !cell.hidden);
      if (!visibleCells.some((cell) => String(cell.text || "").trim())) return false;
      return (activeDomainProfile.column_roles || []).some((role) => {
        if (!role.required) return false;
        const roleColumns = model.columns
          .filter((column) => column.semantic_role === role.role_id)
          .map((column) => column.column_id);
        return !roleColumns.length || !visibleCells.some((cell) => (
          roleColumns.includes(cell.column_id) && String(cell.text || "").trim()
        ));
      });
    })
    : [];

  useEffect(() => {
    if (selectedCellId && !cellLocation(model, selectedCellId)) {
      setSelectedCellId("");
      setSelectionAnchorId("");
    }
  }, [model, selectedCellId]);

  useEffect(() => {
    if (!selected) {
      onSelectedCellChange?.(null);
      return;
    }
    onSelectedCellChange?.({
      rowId: selected.row.row_id,
      rowLabel: selected.row.label || "",
      columnId: selected.column.column_id,
      columnLabel: selected.column.label || "",
      semanticRole: selected.column.semantic_role || "",
      cellId: selected.cell.cell_id,
      text: String(selected.cell.text || ""),
      rowIndex: selected.rowIndex,
      columnIndex: selected.columnIndex,
    });
  }, [selectedCellId, draftBlock]);

  const emitMutation = (mutator) => {
    if (readOnly) return;
    const next = materializeBlock(draftBlock);
    const result = mutator(next) || {};
    if (typeof result === "string") {
      setError(result);
      return;
    }
    synchronizeStructuredTable(next);
    const structureError = validateStructure(next);
    if (structureError) {
      setError(structureError);
      return;
    }
    setError("");
    setDraftBlock(next);
    if (result.selectId) {
      setSelectedCellId(result.selectId);
      setSelectionAnchorId(result.selectId);
    }
    onChange?.(next);
  };

  const selectCell = (cellId, extend = false, focusEditor = false) => {
    setSelectedCellId(cellId);
    if (!extend || !selectionAnchorId) setSelectionAnchorId(cellId);
    if (focusEditor && !extend && !readOnly) {
      setCellEditorFocusRequest((value) => value + 1);
    }
  };

  const navigateEditableCell = (direction) => {
    const visibleCells = model.rows.flatMap((row) => row.cells.filter((cell) => !cell.hidden));
    if (!visibleCells.length) return;
    const currentIndex = visibleCells.findIndex((cell) => cell.cell_id === selectedCellId);
    const nextIndex = Math.max(0, Math.min(
      visibleCells.length - 1,
      (currentIndex < 0 ? 0 : currentIndex) + direction,
    ));
    selectCell(visibleCells[nextIndex].cell_id, false, true);
  };

  const updateCell = (cellId, updater) => emitMutation((next) => {
    for (const row of next.rows) {
      const index = row.findIndex((cell) => cell.cell_id === cellId);
      if (index >= 0) {
        row[index] = { ...row[index], ...updater(row[index]) };
        return { selectId: cellId };
      }
    }
    return "未找到目标单元格，已阻止本次操作。";
  });

  const updateDomain = (nextDomain) => emitMutation((next) => {
    const profile = domainProfiles.find((item) => item.domain === nextDomain);
    next.structured_table.domain = nextDomain;
    next.domain = nextDomain;
    next.structured_table.columns = next.structured_table.columns.map((column) => ({
      ...column,
      semantic_role: "",
    }));
    next.rows.forEach((row) => row.forEach((cell) => {
      cell.structure_column_semantic_role = "";
    }));
    if (!profile) {
      next.structured_table.word_layout = {
        ...(next.structured_table.word_layout || {}),
      };
      delete next.structured_table.word_layout.domain_profile;
      return { selectId: selectedCellId };
    }
    next.structured_table.word_layout = {
      ...(next.structured_table.word_layout || {}),
      domain_profile: {
        profile_id: profile.profile_id,
        profile_version: profile.version,
        mapping_status: "pending_user_confirmation",
        confirmed_by_user: false,
        record_axis: "semantic_only",
        source: "working_copy_user_mapping",
      },
    };
    return { selectId: selectedCellId };
  });

  const mapDomainProfile = () => emitMutation((next) => {
    if (!activeDomainProfile) return "请先选择支持领域设计的表格类型。";
    const usedRoles = new Set();
    next.structured_table.columns = next.structured_table.columns.map((column) => {
      if (column.semantic_role) {
        usedRoles.add(column.semantic_role);
        return column;
      }
      const normalizedLabel = String(column.label || "").replace(/[\s/、（）()]/g, "");
      if (!normalizedLabel) return column;
      const match = activeDomainProfile.column_roles.find((role) => {
        const normalizedRole = String(role.label || "").replace(/[\s/、（）()]/g, "");
        return !usedRoles.has(role.role_id)
          && (normalizedLabel.includes(normalizedRole) || normalizedRole.includes(normalizedLabel));
      });
      if (!match) return column;
      usedRoles.add(match.role_id);
      return { ...column, semantic_role: match.role_id };
    });
    next.structured_table.word_layout = {
      ...(next.structured_table.word_layout || {}),
      domain_profile: {
        ...(next.structured_table.word_layout?.domain_profile || {}),
        profile_id: activeDomainProfile.profile_id,
        profile_version: activeDomainProfile.version,
        mapping_status: "pending_user_confirmation",
        confirmed_by_user: false,
      },
    };
    return { selectId: selectedCellId };
  });

  const updateColumnSemanticRole = (semanticRole) => emitMutation((next) => {
    const current = viewModel(next);
    const location = cellLocation(current, selectedCellId);
    if (!location) return "请先选择要映射的列。";
    next.structured_table.columns[location.columnIndex] = {
      ...next.structured_table.columns[location.columnIndex],
      semantic_role: semanticRole,
    };
    next.rows.forEach((row) => row.forEach((cell) => {
      if (cell.grid_column_index === location.columnIndex) {
        cell.structure_column_semantic_role = semanticRole;
      }
    }));
    next.structured_table.word_layout = {
      ...(next.structured_table.word_layout || {}),
      domain_profile: {
        ...(next.structured_table.word_layout?.domain_profile || {}),
        profile_id: activeDomainProfile?.profile_id || domain,
        profile_version: activeDomainProfile?.version || "",
        mapping_status: "pending_user_confirmation",
        confirmed_by_user: false,
      },
    };
    return { selectId: selectedCellId };
  });

  const confirmDomainMapping = () => {
    if (missingRequiredRoles.length) {
      setError(`仍有必需字段未映射：${missingRequiredRoles.map((role) => role.label).join("、")}`);
      return;
    }
    emitMutation((next) => {
      next.structured_table.word_layout = {
        ...(next.structured_table.word_layout || {}),
        domain_profile: {
          ...(next.structured_table.word_layout?.domain_profile || {}),
          profile_id: activeDomainProfile.profile_id,
          profile_version: activeDomainProfile.version,
          mapping_status: "confirmed_by_user",
          confirmed_by_user: true,
        },
      };
      return { selectId: selectedCellId };
    });
  };

  const updateProjectEvidenceConfirmation = (confirmed) => emitMutation((next) => {
    next.structured_table.word_layout = {
      ...(next.structured_table.word_layout || {}),
      domain_profile: {
        ...(next.structured_table.word_layout?.domain_profile || {}),
        project_evidence_confirmed_by_user: confirmed,
      },
    };
    return { selectId: selectedCellId };
  });

  const updateDomainRecordAxis = (recordAxis) => emitMutation((next) => {
    next.structured_table.word_layout = {
      ...(next.structured_table.word_layout || {}),
      domain_profile: {
        ...(next.structured_table.word_layout?.domain_profile || {}),
        record_axis: recordAxis,
        mapping_status: "pending_user_confirmation",
        confirmed_by_user: false,
      },
    };
    return { selectId: selectedCellId };
  });

  const addRow = () => emitMutation((next) => {
    const current = viewModel(next);
    const location = cellLocation(current, selectedCellId);
    const insertionIndex = location ? location.rowIndex + 1 : current.rows.length;
    const crossing = current.rows.some((row, rowIndex) => row.cells.some((cell) => (
      !cell.hidden && rowIndex < insertionIndex && rowIndex + cell.row_span > insertionIndex
    )));
    if (crossing) return "新增位置穿过纵向合并区域，请先拆分相关单元格。";
    const rowId = localId("row");
    const cells = current.columns.map((column, columnIndex) => ({
      cell_id: localId("cell"),
      row_id: rowId,
      column_id: column.column_id,
      row_index: insertionIndex,
      grid_column_index: columnIndex,
      column_span: 1,
      row_span: 1,
      hidden: false,
      text: "",
      style_role: "body",
      source_locator: "",
      provenance_lineage: [],
      note_refs: [],
    }));
    next.rows.splice(insertionIndex, 0, cells);
    next.structured_table.rows.splice(insertionIndex, 0, {
      row_id: rowId,
      order: insertionIndex,
      label: "",
      style_role: "body",
      source_locator: "",
      cells,
    });
    return { selectId: cells[0].cell_id };
  });

  const deleteRow = () => emitMutation((next) => {
    const current = viewModel(next);
    const location = cellLocation(current, selectedCellId);
    if (!location) return "请先选择要删除的行。";
    if (current.rows.length <= 1) return "表格至少保留一行。";
    const rowTouchesMerge = current.rows.some((row, rowIndex) => row.cells.some((cell) => (
      cell.hidden && rowIndex === location.rowIndex
    ) || (!cell.hidden && rowIndex <= location.rowIndex && rowIndex + cell.row_span > location.rowIndex && cell.row_span > 1)));
    if (rowTouchesMerge) return "目标行处于纵向合并区域，请先拆分相关单元格。";
    next.rows.splice(location.rowIndex, 1);
    next.structured_table.rows.splice(location.rowIndex, 1);
    const fallback = next.rows[Math.min(location.rowIndex, next.rows.length - 1)]?.find((cell) => !cell.hidden);
    return { selectId: fallback?.cell_id || "" };
  });

  const moveRow = (direction) => emitMutation((next) => {
    const current = viewModel(next);
    const location = cellLocation(current, selectedCellId);
    if (!location) return "请先选择要移动的行。";
    if (current.rows.some((row) => row.cells.some((cell) => cell.hidden || cell.row_span > 1))) {
      return "存在纵向合并单元格时不能移动行，请先拆分相关区域。";
    }
    const target = location.rowIndex + direction;
    if (target < 0 || target >= next.rows.length) return "目标行已位于边界。";
    [next.rows[location.rowIndex], next.rows[target]] = [next.rows[target], next.rows[location.rowIndex]];
    [next.structured_table.rows[location.rowIndex], next.structured_table.rows[target]] = [
      next.structured_table.rows[target],
      next.structured_table.rows[location.rowIndex],
    ];
    return { selectId: selectedCellId };
  });

  const addColumn = () => emitMutation((next) => {
    const current = viewModel(next);
    const location = cellLocation(current, selectedCellId);
    const insertionIndex = location ? location.columnIndex + 1 : current.columns.length;
    const crossing = current.rows.some((row) => row.cells.some((cell) => (
      !cell.hidden && cell.grid_column_index < insertionIndex
      && cell.grid_column_index + cell.column_span > insertionIndex
    )));
    if (crossing) return "新增位置穿过横向合并区域，请先拆分相关单元格。";
    const column = {
      column_id: localId("column"),
      order: insertionIndex,
      label: `第 ${insertionIndex + 1} 列`,
      style_role: "body",
      source_locator: "",
      semantic_role: "",
    };
    next.structured_table.columns.splice(insertionIndex, 0, column);
    let firstCellId = "";
    next.rows.forEach((row, rowIndex) => {
      row.forEach((cell) => {
        if (cell.grid_column_index >= insertionIndex) cell.grid_column_index += 1;
      });
      const rowId = next.structured_table.rows[rowIndex].row_id;
      const cell = {
        cell_id: localId("cell"),
        row_id: rowId,
        column_id: column.column_id,
        row_index: rowIndex,
        grid_column_index: insertionIndex,
        column_span: 1,
        row_span: 1,
        hidden: false,
        text: "",
        style_role: "body",
        source_locator: "",
        provenance_lineage: [],
        note_refs: [],
      };
      row.push(cell);
      row.sort((left, right) => left.grid_column_index - right.grid_column_index);
      if (!firstCellId) firstCellId = cell.cell_id;
    });
    return { selectId: firstCellId };
  });

  const deleteColumn = () => emitMutation((next) => {
    const current = viewModel(next);
    const location = cellLocation(current, selectedCellId);
    if (!location) return "请先选择要删除的列。";
    if (current.columns.length <= 1) return "表格至少保留一列。";
    const intersectsMerge = current.rows.some((row) => row.cells.some((cell) => (
      !cell.hidden
      && cell.grid_column_index <= location.columnIndex
      && cell.grid_column_index + cell.column_span > location.columnIndex
      && cell.column_span > 1
    )));
    if (intersectsMerge) return "目标列处于横向合并区域，请先拆分相关单元格。";
    next.rows.forEach((row) => {
      const index = row.findIndex((cell) => cell.grid_column_index === location.columnIndex);
      if (index >= 0) row.splice(index, 1);
      row.forEach((cell) => {
        if (cell.grid_column_index > location.columnIndex) cell.grid_column_index -= 1;
      });
    });
    next.structured_table.columns.splice(location.columnIndex, 1);
    const fallback = next.rows[location.rowIndex]?.find((cell) => !cell.hidden);
    return { selectId: fallback?.cell_id || "" };
  });

  const moveColumn = (direction) => emitMutation((next) => {
    const current = viewModel(next);
    const location = cellLocation(current, selectedCellId);
    if (!location) return "请先选择要移动的列。";
    if (current.rows.some((row) => row.cells.some((cell) => cell.column_span > 1))) {
      return "存在横向合并单元格时不能移动列，请先拆分相关区域。";
    }
    const target = location.columnIndex + direction;
    if (target < 0 || target >= current.columns.length) return "目标列已位于边界。";
    next.rows.forEach((row) => {
      row.forEach((cell) => {
        if (cell.grid_column_index === location.columnIndex) cell.grid_column_index = target;
        else if (cell.grid_column_index === target) cell.grid_column_index = location.columnIndex;
      });
      row.sort((left, right) => left.grid_column_index - right.grid_column_index);
    });
    [next.structured_table.columns[location.columnIndex], next.structured_table.columns[target]] = [
      next.structured_table.columns[target],
      next.structured_table.columns[location.columnIndex],
    ];
    return { selectId: selectedCellId };
  });

  const mergeCells = () => emitMutation((next) => {
    const current = viewModel(next);
    const range = selectedRectangle(current, selectionAnchorId, selectedCellId);
    if (!range || (range.top === range.bottom && range.left === range.right)) {
      return "按住 Shift 选择一个规则矩形后再合并。";
    }
    const targets = [];
    for (let rowIndex = range.top; rowIndex <= range.bottom; rowIndex += 1) {
      for (let columnIndex = range.left; columnIndex <= range.right; columnIndex += 1) {
        const cell = current.rows[rowIndex].cells.find((item) => (
          !item.hidden && item.grid_column_index === columnIndex
        ));
        if (!cell || cell.row_span !== 1 || cell.column_span !== 1) {
          return "所选区域不是未合并的规则矩形，已阻止合并。";
        }
        targets.push({ rowIndex, columnIndex, cell });
      }
    }
    if (targets.filter(({ cell }) => String(cell.text || "").trim()).length > 1) {
      return "所选区域含多个非空单元格，请先保留一个主单元格内容后再合并。";
    }
    const parent = targets[0].cell;
    next.rows[range.top] = next.rows[range.top].map((cell) => (
      cell.cell_id === parent.cell_id
        ? { ...cell, row_span: range.bottom - range.top + 1, column_span: range.right - range.left + 1 }
        : cell
    ));
    targets.slice(1).forEach(({ rowIndex, cell }) => {
      next.rows[rowIndex] = next.rows[rowIndex].map((item) => (
        item.cell_id === cell.cell_id
          ? {
            ...item,
            hidden: true,
            merge_parent_cell_id: parent.cell_id,
            merge_parent_row_index: range.top,
            merge_parent_grid_column_index: range.left,
          }
          : item
      ));
    });
    return { selectId: parent.cell_id };
  });

  const splitCell = () => emitMutation((next) => {
    const current = viewModel(next);
    const location = cellLocation(current, selectedCellId);
    if (!location || (location.cell.row_span === 1 && location.cell.column_span === 1)) {
      return "当前单元格没有可拆分的合并区域。";
    }
    const parent = location.cell;
    for (let rowIndex = location.rowIndex; rowIndex < location.rowIndex + parent.row_span; rowIndex += 1) {
      for (let columnIndex = location.columnIndex; columnIndex < location.columnIndex + parent.column_span; columnIndex += 1) {
        const row = next.rows[rowIndex];
        const existingIndex = row.findIndex((cell) => cell.grid_column_index === columnIndex);
        if (rowIndex === location.rowIndex && columnIndex === location.columnIndex) {
          row[existingIndex] = { ...row[existingIndex], row_span: 1, column_span: 1 };
        } else if (existingIndex >= 0) {
          row[existingIndex] = {
            ...row[existingIndex],
            hidden: false,
            merge_parent_cell_id: null,
            merge_parent_row_index: null,
            merge_parent_grid_column_index: null,
            row_span: 1,
            column_span: 1,
          };
        } else {
          row.push({
            cell_id: localId("cell"),
            row_id: next.structured_table.rows[rowIndex].row_id,
            column_id: next.structured_table.columns[columnIndex].column_id,
            row_index: rowIndex,
            grid_column_index: columnIndex,
            column_span: 1,
            row_span: 1,
            hidden: false,
            text: "",
            style_role: "body",
            source_locator: "",
            provenance_lineage: [],
            note_refs: [],
          });
          row.sort((left, right) => left.grid_column_index - right.grid_column_index);
        }
      }
    }
    return { selectId: parent.cell_id };
  });

  const setRowRole = (role) => emitMutation((next) => {
    const current = viewModel(next);
    const location = cellLocation(current, selectedCellId);
    if (!location) return "请先选择目标行。";
    next.rows[location.rowIndex] = next.rows[location.rowIndex].map((cell) => ({ ...cell, style_role: role }));
    next.structured_table.rows[location.rowIndex] = {
      ...next.structured_table.rows[location.rowIndex],
      style_role: role,
    };
    return { selectId: selectedCellId };
  });

  const addNote = () => emitMutation((next) => {
    const noteId = localId("note");
    const targetId = selectedCellId || next.table_id;
    next.structured_table.notes.push({
      note_id: noteId,
      marker: String(next.structured_table.notes.length + 1),
      note_type: "operational",
      text: "",
      target_ids: [targetId],
      module_ref: "",
      project_override: false,
      source_refs: [],
      source_kind: "working_copy_user_note",
      review_status: "confirmed",
      association_reason: "由医学用户在当前工作副本中新增。",
    });
    if (selectedCellId) {
      next.rows = next.rows.map((row) => row.map((cell) => (
        cell.cell_id === selectedCellId
          ? { ...cell, note_refs: [...new Set([...(cell.note_refs || []), noteId])] }
          : cell
      )));
    }
    setInspectorTab("notes");
    return { selectId: selectedCellId };
  });

  const updateNote = (noteId, patch) => emitMutation((next) => {
    next.structured_table.notes = next.structured_table.notes.map((note) => (
      note.note_id === noteId ? { ...note, ...patch } : note
    ));
    return { selectId: selectedCellId };
  });

  const deleteNote = (noteId) => emitMutation((next) => {
    next.structured_table.notes = next.structured_table.notes.filter((note) => note.note_id !== noteId);
    next.rows = next.rows.map((row) => row.map((cell) => ({
      ...cell,
      note_refs: (cell.note_refs || []).filter((ref) => ref !== noteId),
    })));
    return { selectId: selectedCellId };
  });

  const updateTableTitle = (title) => emitMutation((next) => {
    next.title = title;
    next.structured_table.title = title;
    return { selectId: selectedCellId };
  });

  const confirmCaptionAssociation = () => emitMutation((next) => {
    if (!next.structured_table.source_caption) return "当前表格没有待确认的来源表题。";
    next.structured_table.source_caption = {
      ...next.structured_table.source_caption,
      review_status: "confirmed",
    };
    if (next.table_caption) {
      next.table_caption = { ...next.table_caption, review_status: "confirmed" };
    }
    return { selectId: selectedCellId };
  });

  const confirmNoteAssociation = (noteId) => emitMutation((next) => {
    let found = false;
    next.structured_table.notes = next.structured_table.notes.map((note) => {
      if (note.note_id !== noteId) return note;
      found = true;
      return { ...note, review_status: "confirmed" };
    });
    next.structured_table.source_note_metadata = (
      next.structured_table.source_note_metadata || []
    ).map((metadata) => (
      metadata.note_id === noteId
        ? { ...metadata, review_status: "confirmed" }
        : metadata
    ));
    return found ? { selectId: selectedCellId } : "未找到待确认附注。";
  });

  const mapSoaMetadata = () => emitMutation((next) => {
    next.structured_table.soa = {
      ...(next.structured_table.soa || {}),
      mapping_status: "pending_user_confirmation",
      mapping_method: "mapped_from_current_table",
      confirmed_by_user: false,
    };
    return { selectId: selectedCellId };
  });

  const adoptSuggestedSoaDomain = () => emitMutation((next) => {
    next.structured_table.domain = SOA_DOMAIN;
    next.domain = SOA_DOMAIN;
    next.structured_table.soa = {
      ...(next.structured_table.soa || {}),
      mapping_status: "pending_user_confirmation",
      mapping_method: "mapped_from_current_table",
      confirmed_by_user: false,
    };
    return { selectId: selectedCellId };
  });

  const updateSoaCell = (patch) => {
    if (!selectedCellId) {
      setError("请先选择要设置研究流程属性的单元格。");
      return;
    }
    updateCell(selectedCellId, (cell) => ({
      soa: {
        ...(cell.soa || {}),
        mapping_status: cell.soa?.mapping_status || "pending_user_confirmation",
        ...patch,
      },
    }));
  };

  const updatePlanState = (state) => {
    const definition = PLAN_STATES.find((item) => item.value === state);
    if (!definition || !selectedCellId) return;
    updateCell(selectedCellId, (cell) => ({
      text: definition.cellText,
      rich_text: null,
      soa: {
        ...(cell.soa || {}),
        plan_state: state,
        mapping_status: cell.soa?.mapping_status || "pending_user_confirmation",
      },
    }));
  };

  const updateWordLayout = (orientation) => emitMutation((next) => {
    next.structured_table.word_layout = {
      ...(next.structured_table.word_layout || {}),
      orientation,
    };
    return { selectId: selectedCellId };
  });

  const moveSelection = (rowDelta, columnDelta) => {
    if (!selected) return;
    const targetRow = model.rows[selected.rowIndex + rowDelta];
    if (!targetRow) return;
    const targetColumn = Math.max(0, Math.min(
      model.columns.length - 1,
      selected.columnIndex + columnDelta,
    ));
    const target = targetRow.cells.find((cell) => (
      !cell.hidden
      && cell.grid_column_index <= targetColumn
      && cell.grid_column_index + cell.column_span > targetColumn
    ));
    if (target) selectCell(target.cell_id);
  };

  const handleKeyDown = (event) => {
    if (event.key === "Escape") {
      if (error) setError("");
      else onClose?.();
      return;
    }
    if (!event.altKey) return;
    const moves = {
      ArrowUp: [-1, 0],
      ArrowDown: [1, 0],
      ArrowLeft: [0, -1],
      ArrowRight: [0, 1],
    };
    const move = moves[event.key];
    if (move) {
      event.preventDefault();
      moveSelection(...move);
    }
  };

  return (
    <section
      className={`structured-table-designer ${inspectorOpen ? "inspector-open" : "inspector-closed"} ${isDedicatedDocumentObject ? `document-object ${objectRole}` : ""}`}
      aria-label="医学写作结构化表格设计器"
      onKeyDown={handleKeyDown}
    >
      <header className="std-titlebar">
        <div className="std-title-identity">
          <Table2 size={18} aria-hidden="true" />
          <div>
            <strong title={blockTitle(draftBlock)}>{blockTitle(draftBlock)}</strong>
            <span title={compactSourceBoundary(draftBlock)}>{compactSourceBoundary(draftBlock)}</span>
          </div>
        </div>
        <div className="std-title-status">
          <span className={readOnly ? "std-status read-only" : "std-status editable"}>
            {readOnly ? <LockKeyhole size={13} aria-hidden="true" /> : <PencilLine size={13} aria-hidden="true" />}
            {readOnly ? "原始来源只读" : "工作副本可编辑"}
          </span>
          <span className="std-domain-label">{objectRoleLabel || (isSoa ? "研究流程表" : (activeDomainProfile?.label || "通用结构化表格"))}</span>
          <IconButton label={inspectorOpen ? "收起属性检查器" : "展开属性检查器"} icon={inspectorOpen ? PanelRightClose : PanelRightOpen} onClick={() => setInspectorOpen((value) => !value)} />
          <IconButton label="关闭表格设计器" icon={X} onClick={() => onClose?.()} />
        </div>
      </header>

      <div className="std-toolbar" role="toolbar" aria-label="表格结构工具">
        {isDedicatedDocumentObject && (
          <div className="std-document-object-boundary">
            <strong>{objectRoleLabel}</strong>
            <span>{isLayoutObject ? "用于首页、签字页或联系信息排版，不进入正文表目录。" : "对应 M11 1.1；按实际 Word 表格编辑，不参与正文表格编号。"}</span>
          </div>
        )}
        <div className="std-tool-group">
          <span><Rows3 size={14} aria-hidden="true" />行</span>
          <IconButton label="新增下一行" icon={Plus} disabled={readOnly} onClick={addRow} />
          <IconButton label="删除当前行" icon={Trash2} disabled={readOnly || !selected} onClick={deleteRow} />
          <IconButton label="当前行上移" icon={ArrowUp} disabled={readOnly || !selected} onClick={() => moveRow(-1)} />
          <IconButton label="当前行下移" icon={ArrowDown} disabled={readOnly || !selected} onClick={() => moveRow(1)} />
        </div>
        <div className="std-tool-group">
          <span><Columns3 size={14} aria-hidden="true" />列</span>
          <IconButton label="新增右侧列" icon={Plus} disabled={readOnly} onClick={addColumn} />
          <IconButton label="删除当前列" icon={Trash2} disabled={readOnly || !selected} onClick={deleteColumn} />
          <IconButton label="当前列左移" icon={ArrowLeft} disabled={readOnly || !selected} onClick={() => moveColumn(-1)} />
          <IconButton label="当前列右移" icon={ArrowRight} disabled={readOnly || !selected} onClick={() => moveColumn(1)} />
        </div>
        <div className="std-tool-group">
          <span><LayoutPanelTop size={14} aria-hidden="true" />结构</span>
          <IconButton label="合并所选规则矩形" icon={Merge} disabled={readOnly || !selected} onClick={mergeCells} />
          <IconButton label="拆分当前合并单元格" icon={Split} disabled={readOnly || !selected} onClick={splitCell} />
          {CELL_ROLES.map((role) => (
            <button
              key={role.value}
              type="button"
              className="std-text-button"
              disabled={readOnly || !selected}
              aria-label={`设为${role.label}行`}
              onClick={() => setRowRole(role.value)}
            >
              {role.label}
            </button>
          ))}
        </div>
        <div className="std-tool-hint">Shift+点击选择矩形；Alt+方向键移动焦点</div>
      </div>

      <TableCellRichEditor
        key={selected?.cell?.cell_id || "no-selected-cell"}
        cell={selected ? {
          ...selected.cell,
          rowIndex: selected.rowIndex,
          columnIndex: selected.columnIndex,
        } : null}
        readOnly={readOnly}
        documentIndex={documentIndex}
        focusRequest={cellEditorFocusRequest}
        onNavigateCell={navigateEditableCell}
        onChange={(patch) => {
          if (!selected?.cell?.cell_id) return;
          updateCell(selected.cell.cell_id, () => patch);
        }}
      />

      <div className="std-feedback-row">
        {error && (
          <div className="std-error" role="alert">
            <AlertTriangle size={15} aria-hidden="true" />
            <span>{error}</span>
            <button type="button" aria-label="关闭错误提示" onClick={() => setError("")}><X size={14} /></button>
          </div>
        )}
      </div>

      <div className="std-workspace">
        <main className="std-grid-region" aria-label="结构化表格网格">
          <div className="std-grid-meta">
            <span>{model.rows.length} 行 × {model.columns.length} 列</span>
            <span>{headerRowCount} 行冻结表头</span>
            <span>{notes.length} 条附注</span>
            {rectangle && (rectangle.top !== rectangle.bottom || rectangle.left !== rectangle.right) && (
              <span className="selection-summary">已选 {rectangle.bottom - rectangle.top + 1} × {rectangle.right - rectangle.left + 1}</span>
            )}
          </div>
          <div className="std-grid-scroll" tabIndex={0} aria-label="可水平和垂直滚动的表格画布">
            <table className="std-grid-table">
              <tbody>
                {model.rows.map((row, rowIndex) => {
                  const headerIndex = row.style_role === "header" || rowIndex < headerRowCount
                    ? Math.min(rowIndex, headerRowCount - 1)
                    : -1;
                  return (
                    <tr key={row.row_id} data-row-id={row.row_id} data-style-role={row.style_role}>
                      {row.cells.filter((cell) => !cell.hidden).map((cell) => {
                        const inSelection = rectangle
                          && rowIndex >= rectangle.top
                          && rowIndex <= rectangle.bottom
                          && cell.grid_column_index >= rectangle.left
                          && cell.grid_column_index <= rectangle.right;
                        const isSelected = cell.cell_id === selectedCellId;
                        const cellRevision = cellRevisionThreads.find((thread) => (
                          thread?.table_cell_anchor?.cell_id === cell.cell_id
                          && thread?.table_cell_anchor?.table_id === (draftBlock?.table_id || draftBlock?.structured_table?.table_id)
                          && thread.status !== "rejected"
                        ));
                        const CellTag = headerIndex >= 0
                          || cell.style_role === "header"
                          || row.style_role === "header"
                          ? "th"
                          : "td";
                        return (
                          <CellTag
                            key={cell.cell_id}
                            rowSpan={cell.row_span}
                            colSpan={cell.column_span}
                            data-cell-id={cell.cell_id}
                            data-style-role={cell.style_role}
                            className={`${cell.grid_column_index === 0 ? "sticky-first-column" : ""} ${headerIndex >= 0 ? "sticky-header" : ""} ${isSelected ? "selected" : ""} ${inSelection ? "in-selection" : ""}`}
                            style={{ "--std-header-index": Math.max(headerIndex, 0) }}
                            onClick={(event) => selectCell(cell.cell_id, event.shiftKey, !event.shiftKey)}
                          >
                            <button
                              type="button"
                              className="std-readonly-cell std-cell-select-button"
                              aria-label={`${readOnly ? "选择" : "编辑"}第 ${rowIndex + 1} 行第 ${cell.grid_column_index + 1} 列：${String(cell.text || "空白")}`}
                              title={String(cell.text || "")}
                              onClick={(event) => {
                                event.stopPropagation();
                                selectCell(cell.cell_id, event.shiftKey, !event.shiftKey);
                              }}
                            >
                              {String(cell.text || "")}
                            </button>
                            {(cell.note_refs || []).length > 0 && (
                              <span className="std-cell-note-marker" title="该单元格含结构化附注">
                                {(cell.note_refs || []).length}
                              </span>
                            )}
                            {cellRevision && (
                              <span
                                className="std-cell-ai-marker"
                                title={cellRevision.status === "medically_approved" ? "该单元格有医学已批准的AI修订" : "该单元格有待医学处置的AI修订"}
                                aria-label="该单元格有AI修订线程"
                              >
                                <Sparkles size={10} />
                              </span>
                            )}
                          </CellTag>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </main>

        {inspectorOpen && (
          <aside className="std-inspector" aria-label="表格属性检查器">
            <div className={`std-inspector-tabs ${activeDomainProfile ? "has-domain" : ""}`} role="tablist" aria-label="属性检查器视图">
              <button type="button" role="tab" aria-selected={inspectorTab === "properties"} className={inspectorTab === "properties" ? "active" : ""} onClick={() => setInspectorTab("properties")}>属性</button>
              {activeDomainProfile && <button type="button" role="tab" aria-selected={inspectorTab === "domain"} className={inspectorTab === "domain" ? "active" : ""} onClick={() => setInspectorTab("domain")}>领域</button>}
              <button type="button" role="tab" aria-selected={inspectorTab === "notes"} className={inspectorTab === "notes" ? "active" : ""} onClick={() => setInspectorTab("notes")}>附注 {notes.length}</button>
              <button type="button" role="tab" aria-selected={inspectorTab === "layout"} className={inspectorTab === "layout" ? "active" : ""} onClick={() => setInspectorTab("layout")}>Word</button>
            </div>

            {inspectorTab === "properties" && (
              <div className="std-inspector-body">
                <section className="std-property-section">
                  <div className="std-section-heading">
                    <h3>{isLayoutObject ? "排版对象信息" : isSynopsisObject ? "方案摘要表信息" : "表格信息"}</h3>
                    {sourceCaption && (
                      sourceCaption.review_status === "confirmed"
                        ? <span className="std-confirmed"><Check size={12} />表题已确认</span>
                        : <span className="std-pending">表题待确认</span>
                    )}
                  </div>
                  <label className="std-field">
                    <span>{isLayoutObject ? "对象名称" : isSynopsisObject ? "摘要名称" : "表题"}</span>
                    <input
                      value={blockTitle(draftBlock) === "未命名表格" ? "" : blockTitle(draftBlock)}
                      disabled={readOnly}
                      aria-label="表格标题"
                      placeholder="输入表题"
                      onChange={(event) => updateTableTitle(event.target.value)}
                    />
                  </label>
                  {!isDedicatedDocumentObject && !isSoa && suggestedDomain === SOA_DOMAIN && (
                    <div className="std-mapping-boundary">
                      当前表格来自研究流程表章节，尚未建立研究流程语义。可在工作副本中建立待确认映射；系统不会自动确认或改写原始来源表。
                      <button type="button" disabled={readOnly} onClick={adoptSuggestedSoaDomain}>建立待确认映射</button>
                    </div>
                  )}
                  {!isDedicatedDocumentObject && !isSoa && (
                    <label className="std-field">
                      <span>表格类型</span>
                      <select
                        value={domain}
                        disabled={readOnly}
                        aria-label="结构化表格类型"
                        onChange={(event) => updateDomain(event.target.value)}
                      >
                        <option value="generic">通用结构化表格</option>
                        {domainProfiles.map((profile) => (
                          <option key={profile.profile_id} value={profile.domain}>{profile.label}</option>
                        ))}
                      </select>
                    </label>
                  )}
                  {sourceCaption && (
                    <div className="std-association-detail">
                      {sourceCaptionText && (
                        <p><strong>来源表题：</strong>{sourceCaptionText}</p>
                      )}
                      {sourceCaption.association_reason && <p>{sourceCaption.association_reason}</p>}
                      {sourceCaption.source_locator && (
                        <small title={sourceCaption.source_locator}>来源：{sourceCaption.source_locator}</small>
                      )}
                      {sourceCaption.review_status !== "confirmed" && (
                        <button
                          type="button"
                          className="std-confirm-button"
                          disabled={readOnly}
                          onClick={confirmCaptionAssociation}
                        ><Check size={14} />确认表题关联</button>
                      )}
                    </div>
                  )}
                </section>
                <section className="std-property-section">
                  <h3>当前单元格</h3>
                  {selected ? (
                    <>
                      <dl className="std-identity-list">
                        <div><dt>稳定 ID</dt><dd title={selected.cell.cell_id}>{selected.cell.cell_id}</dd></div>
                        <div><dt>位置</dt><dd>第 {selected.rowIndex + 1} 行 / 第 {selected.columnIndex + 1} 列</dd></div>
                        <div><dt>跨度</dt><dd>{selected.cell.row_span} 行 × {selected.cell.column_span} 列</dd></div>
                      </dl>
                      <label className="std-field">
                        <span>样式角色</span>
                        <select
                          value={selected.cell.style_role || "body"}
                          disabled={readOnly}
                          aria-label="当前单元格样式角色"
                          onChange={(event) => updateCell(selected.cell.cell_id, () => ({ style_role: event.target.value }))}
                        >
                          {CELL_ROLES.map((role) => <option key={role.value} value={role.value}>{role.label}</option>)}
                        </select>
                      </label>
                    </>
                  ) : <p className="std-empty">选择单元格后查看和修改属性。</p>}
                </section>

                {isSoa && (
                  <section className="std-property-section soa-properties">
                    <div className="std-section-heading">
                      <h3>研究流程属性</h3>
                      {draftBlock?.structured_table?.soa?.confirmed_by_user
                        ? <span className="std-confirmed"><Check size={12} />已确认</span>
                        : <span className="std-pending">待人工确认</span>}
                    </div>
                    {!draftBlock?.structured_table?.soa && (
                      <div className="std-mapping-boundary">
                        当前仅有原始表格结构。可建立待确认映射，再由医学用户逐项确认；系统不会标记为 AI 已完成。
                        <button type="button" disabled={readOnly} onClick={mapSoaMetadata}>建立待确认映射</button>
                      </div>
                    )}
                    <label className="std-field">
                      <span>单元格类型</span>
                      <select
                        value={selected?.cell?.soa?.kind || "activity_plan"}
                        disabled={readOnly || !selected}
                        aria-label="研究流程单元格类型"
                        onChange={(event) => updateSoaCell({ kind: event.target.value })}
                      >
                        <option value="epoch">阶段</option>
                        <option value="visit">访视</option>
                        <option value="timing">研究日/周与时间窗</option>
                        <option value="activity">活动</option>
                        <option value="activity_plan">计划状态</option>
                      </select>
                    </label>
                    <div className="std-field-row">
                      <label className="std-field"><span>研究日</span><input type="number" value={selected?.cell?.soa?.nominal_day ?? ""} disabled={readOnly || !selected} aria-label="名义研究日" onChange={(event) => updateSoaCell({ nominal_day: event.target.value === "" ? null : Number(event.target.value) })} /></label>
                      <label className="std-field"><span>研究周</span><input type="number" step="0.5" value={selected?.cell?.soa?.nominal_week ?? ""} disabled={readOnly || !selected} aria-label="名义研究周" onChange={(event) => updateSoaCell({ nominal_week: event.target.value === "" ? null : Number(event.target.value) })} /></label>
                    </div>
                    <div className="std-field-row">
                      <label className="std-field"><span>窗前（天）</span><input type="number" min="0" value={selected?.cell?.soa?.window_before_days ?? ""} disabled={readOnly || !selected} aria-label="访视窗提前天数" onChange={(event) => updateSoaCell({ window_before_days: event.target.value === "" ? null : Number(event.target.value) })} /></label>
                      <label className="std-field"><span>窗后（天）</span><input type="number" min="0" value={selected?.cell?.soa?.window_after_days ?? ""} disabled={readOnly || !selected} aria-label="访视窗延后天数" onChange={(event) => updateSoaCell({ window_after_days: event.target.value === "" ? null : Number(event.target.value) })} /></label>
                    </div>
                    <label className="std-field"><span>活动分组</span><input value={selected?.cell?.soa?.activity_group || ""} disabled={readOnly || !selected} aria-label="研究活动分组" onChange={(event) => updateSoaCell({ activity_group: event.target.value })} placeholder="例如：安全性评估" /></label>
                    <fieldset className="std-plan-states" disabled={readOnly || !selected}>
                      <legend>计划状态</legend>
                      {PLAN_STATES.map((state) => (
                        <button
                          type="button"
                          key={state.value}
                          className={selected?.cell?.soa?.plan_state === state.value ? "active" : ""}
                          aria-label={`设为${state.label}`}
                          onClick={() => updatePlanState(state.value)}
                        >{state.label}</button>
                      ))}
                    </fieldset>
                    <button
                      type="button"
                      className="std-confirm-button"
                      disabled={readOnly || !draftBlock?.structured_table?.soa}
                      onClick={() => emitMutation((next) => {
                        next.structured_table.soa = {
                          ...(next.structured_table.soa || {}),
                          mapping_status: "confirmed_by_user",
                          confirmed_by_user: true,
                        };
                        return { selectId: selectedCellId };
                      })}
                    ><Check size={14} />确认当前映射</button>
                  </section>
                )}
              </div>
            )}

            {inspectorTab === "domain" && activeDomainProfile && (
              <div className="std-inspector-body">
                <section className="std-property-section std-domain-profile-properties">
                  <div className="std-section-heading">
                    <h3>领域属性</h3>
                    {domainProfileState.confirmed_by_user
                      ? <span className="std-confirmed"><Check size={12} />已确认</span>
                      : <span className="std-pending">{domainMappingLabel}</span>}
                  </div>
                  <p className="std-domain-purpose">{activeDomainProfile.purpose}</p>
                  {activeDomainProfile.warning_text && (
                    <div className="std-domain-warning"><AlertTriangle size={14} />{activeDomainProfile.warning_text}</div>
                  )}
                  {activeDomainProfile.designer_status === "guarded" && (
                    <label className="std-domain-confirmation">
                      <input
                        type="checkbox"
                        checked={Boolean(domainProfileState.project_evidence_confirmed_by_user)}
                        disabled={readOnly}
                        onChange={(event) => updateProjectEvidenceConfirmation(event.target.checked)}
                      />
                      <span>已根据当前项目方案核对阈值、试验用药处置、复测和恢复条件</span>
                    </label>
                  )}
                  <div className="std-mapping-boundary">
                    领域映射只描述当前表格各列的业务含义，不会把其他项目的医学内容带入本项目。
                    <button type="button" disabled={readOnly} onClick={mapDomainProfile}>建立待确认映射</button>
                  </div>
                  <label className="std-field">
                    <span>记录方向</span>
                    <select
                      value={domainRecordAxis}
                      disabled={readOnly}
                      aria-label="领域表格记录方向"
                      onChange={(event) => updateDomainRecordAxis(event.target.value)}
                    >
                      <option value="semantic_only">仅映射字段，不按行校验</option>
                      <option value="rows">每行一条记录</option>
                    </select>
                  </label>
                  <label className="std-field">
                    <span>当前列语义角色</span>
                    <select
                      value={selected?.column?.semantic_role || ""}
                      disabled={readOnly || !selected}
                      aria-label="当前列语义角色"
                      onChange={(event) => updateColumnSemanticRole(event.target.value)}
                    >
                      <option value="">未映射</option>
                      {activeDomainProfile.column_roles.map((role) => (
                        <option key={role.role_id} value={role.role_id}>
                          {role.label}{role.required ? "（必需）" : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                  {selectedDomainRole && (
                    <div className="std-role-detail">
                      <strong>{selectedDomainRole.label}</strong>
                      <p>{selectedDomainRole.description}</p>
                    </div>
                  )}
                  {selectedDomainRole?.options?.length > 0 && selected && (
                    <label className="std-field">
                      <span>当前单元格快速录入</span>
                      <input
                        list={`std-options-${activeDomainProfile.profile_id}-${selectedDomainRole.role_id}`}
                        value={String(selected.cell.text || "")}
                        disabled={readOnly}
                        aria-label="领域字段快速录入"
                        onChange={(event) => updateCell(selected.cell.cell_id, () => ({ text: event.target.value }))}
                      />
                      <datalist id={`std-options-${activeDomainProfile.profile_id}-${selectedDomainRole.role_id}`}>
                        {selectedDomainRole.options.map((option) => <option key={option} value={option} />)}
                      </datalist>
                      <small>可从建议项选择，也允许自定义输入；当前医学经理确认后写入工作副本。</small>
                    </label>
                  )}
                  {selectedDomainRole?.control === "date" && selected && (
                    <label className="std-field">
                      <span>当前单元格日期</span>
                      <input
                        type="date"
                        value={String(selected.cell.text || "")}
                        disabled={readOnly}
                        aria-label="领域日期字段快速录入"
                        onChange={(event) => updateCell(selected.cell.cell_id, () => ({ text: event.target.value }))}
                      />
                      <small>日期写入当前可见表格单元格，并随同一工作副本和 Word 导出链保存。</small>
                    </label>
                  )}
                  <div className="std-domain-role-list" aria-label="领域字段映射概览">
                    {activeDomainProfile.column_roles.map((role) => (
                      <div key={role.role_id} className={mappedSemanticRoles.has(role.role_id) ? "mapped" : "unmapped"}>
                        <span>{role.label}{role.required ? " *" : ""}</span>
                        <strong>{mappedSemanticRoles.has(role.role_id) ? "已映射" : "未映射"}</strong>
                      </div>
                    ))}
                  </div>
                  {domainRecordAxis === "rows" && (
                    <p className={incompleteDomainRows.length ? "std-domain-row-check warning" : "std-domain-row-check"}>
                      {incompleteDomainRows.length
                        ? `${incompleteDomainRows.length} 行仍缺少必需内容；可保存草稿，但不能确认并冻结。`
                        : "当前已填写记录未发现必需字段缺失。"}
                    </p>
                  )}
                  <button
                    type="button"
                    className="std-confirm-button"
                    disabled={readOnly}
                    onClick={confirmDomainMapping}
                  ><Check size={14} />确认当前领域映射</button>
                </section>
              </div>
            )}

            {inspectorTab === "notes" && (
              <div className="std-inspector-body">
                <div className="std-section-heading">
                  <h3>结构化附注</h3>
                  <button type="button" className="std-add-note" disabled={readOnly} onClick={addNote}><Plus size={14} />新增</button>
                </div>
                <p className="std-note-boundary">附注绑定稳定对象 ID；单元格坐标仅用于当前显示。</p>
                <div className="std-note-list">
                  {notes.map((note) => (
                    <article key={note.note_id} className="std-note-item">
                      <div className="std-note-head">
                        <span><StickyNote size={13} />附注 {note.marker || "-"}</span>
                        <span className={note.review_status === "confirmed" ? "std-confirmed" : "std-pending"}>
                          {note.review_status === "confirmed" ? <><Check size={12} />已确认</> : "待确认"}
                        </span>
                        <IconButton label="删除附注" icon={Trash2} disabled={readOnly} onClick={() => deleteNote(note.note_id)} />
                      </div>
                      <label className="std-field"><span>类型</span><select value={note.note_type || "operational"} disabled={readOnly} aria-label={`附注 ${note.marker || note.note_id} 类型`} onChange={(event) => updateNote(note.note_id, { note_type: event.target.value })}>{NOTE_TYPES.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}</select></label>
                      <label className="std-field"><span>内容</span><textarea value={note.text || ""} disabled={readOnly} rows={4} aria-label={`附注 ${note.marker || note.note_id} 内容`} onChange={(event) => updateNote(note.note_id, { text: event.target.value })} /></label>
                      <div className="std-note-provenance">
                        {note.association_reason && <p>{note.association_reason}</p>}
                        <small title={(note.target_ids || []).join("；")}>绑定：{(note.target_ids || []).join("；") || "未绑定"}</small>
                        {(note.source_refs || []).length > 0 && (
                          <small title={note.source_refs.join("；")}>来源：{note.source_refs.join("；")}</small>
                        )}
                      </div>
                      {note.review_status !== "confirmed" && (
                        <button
                          type="button"
                          className="std-confirm-button"
                          disabled={readOnly}
                          onClick={() => confirmNoteAssociation(note.note_id)}
                        ><Check size={14} />确认附注关联</button>
                      )}
                    </article>
                  ))}
                  {!notes.length && <p className="std-empty">暂无结构化附注。</p>}
                </div>
              </div>
            )}

            {inspectorTab === "layout" && (
              <div className="std-inspector-body">
                <section className="std-property-section">
                  <h3>Word 页面方向</h3>
                  <div className="std-orientation-control" role="group" aria-label="Word 页面方向">
                    <button type="button" className={wordOrientation === "landscape" ? "active" : ""} disabled={readOnly} onClick={() => updateWordLayout("landscape")}>横向</button>
                    <button type="button" className={wordOrientation === "portrait" ? "active" : ""} disabled={readOnly} onClick={() => updateWordLayout("portrait")}>纵向</button>
                  </div>
                  <label className="std-field"><span>长表拆页</span><select value={draftBlock?.structured_table?.word_layout?.split_strategy || "repeat_header"} disabled={readOnly} aria-label="Word 长表拆页策略" onChange={(event) => emitMutation((next) => {
                    next.structured_table.word_layout = { ...(next.structured_table.word_layout || {}), split_strategy: event.target.value };
                    return { selectId: selectedCellId };
                  })}><option value="repeat_header">自动拆页并重复表头</option><option value="horizontal_panels">按列分面拆页</option></select></label>
                  <label className="std-field"><span>分面重复首列数</span><input type="number" min="0" max={model.columns.length} value={draftBlock?.structured_table?.word_layout?.frozen_column_count ?? 1} disabled={readOnly} aria-label="Word 分面重复首列数量" onChange={(event) => emitMutation((next) => {
                    next.structured_table.word_layout = { ...(next.structured_table.word_layout || {}), frozen_column_count: Number(event.target.value) };
                    return { selectId: selectedCellId };
                  })} /></label>
                </section>
              </div>
            )}
          </aside>
        )}
      </div>
    </section>
  );
}

export default StructuredTableDesigner;
