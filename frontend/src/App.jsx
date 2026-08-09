import { Component, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { EditorContent, useEditor } from "@tiptap/react";
import { Extension, Mark, Node, mergeAttributes } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import TextAlign from "@tiptap/extension-text-align";
import Highlight from "@tiptap/extension-highlight";
import Subscript from "@tiptap/extension-subscript";
import Superscript from "@tiptap/extension-superscript";
import {
  Color,
  FontFamily,
  FontSize,
  TextStyle,
} from "@tiptap/extension-text-style";
import { Table } from "@tiptap/extension-table";
import { TableCell } from "@tiptap/extension-table-cell";
import { TableHeader } from "@tiptap/extension-table-header";
import { TableRow } from "@tiptap/extension-table-row";
import {
  AlertTriangle,
  AlignCenter,
  AlignJustify,
  AlignLeft,
  AlignRight,
  ArrowLeft,
  Bell,
  Bold,
  BookOpenText,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  Clock3,
  Database,
  Download,
  Eraser,
  FileCheck2,
  FileText,
  FolderSearch2,
  GitCompare,
  Heading1,
  Highlighter,
  History,
  Italic,
  IndentDecrease,
  IndentIncrease,
  LayoutDashboard,
  Link2,
  List,
  ListOrdered,
  ListChecks,
  MessageSquareText,
  Maximize2,
  Minimize2,
  PanelRightOpen,
  Palette,
  PencilLine,
  Plus,
  RefreshCw,
  Redo2,
  RotateCcw,
  Search,
  Settings2,
  ScanSearch,
  ShieldAlert,
  Sparkles,
  Subscript as SubscriptIcon,
  Superscript as SuperscriptIcon,
  Table2,
  Upload,
  Underline as UnderlineIcon,
  Undo2,
  UserRoundCheck,
  ZoomIn,
  ZoomOut,
  XCircle,
} from "lucide-react";
import logo from "./assets/header_logo.png";
import { EvidenceDesignPage } from "./features/evidence-design/EvidenceDesignWorkspace";
import MedicalMonitoringBatchPanel from "./features/medical-monitoring/MedicalMonitoringBatchPanel";
import MedicalMonitoringAssurancePanel from "./features/medical-monitoring/MedicalMonitoringAssurancePanel";
import MedicalMonitoringRiskChecklist from "./features/medical-monitoring/MedicalMonitoringRiskChecklist";
import MedicalMonitoringScopeSummary from "./features/medical-monitoring/MedicalMonitoringScopeSummary.jsx";
import MedicalMonitoringRiskHistoryTrend from "./features/medical-monitoring/MedicalMonitoringRiskHistoryTrend.jsx";
import MedicalMonitoringRiskEvidenceContext from "./features/medical-monitoring/MedicalMonitoringRiskEvidenceContext.jsx";
import { createMedicalMonitoringApi } from "./features/medical-monitoring/medicalMonitoringApi.mjs";
import {
  DEFAULT_RISK_CHECKLIST_QUERY,
  normalizeRiskChecklistQuery,
  resetRiskChecklistForQueryChange,
  riskChecklistApiQuery,
  riskChecklistQueryFromRoute,
  riskChecklistQuerySignature,
  riskChecklistRoutePatch,
} from "./features/medical-monitoring/medicalMonitoringChecklistState.mjs";
import {
  PatientProfilePage as MedicalMonitoringPatientProfilePage,
  ReferenceTimelineSvg as MedicalMonitoringReferenceTimelineSvg,
  SubjectTimelinePage as MedicalMonitoringSubjectTimelinePage,
  TrendSparkline as MedicalMonitoringTrendSparkline,
} from "./features/medical-monitoring/MedicalMonitoringSubjectViews";
import {
  eventCategoryClassName as monitoringEventCategoryClassName,
  normalizeMonitoringSubjectProfile,
  plannedVisitAxis as monitoringPlannedVisitAxis,
  referenceTimelineLanes as monitoringReferenceTimelineLanes,
  timelineEventCategoryLabel as monitoringTimelineEventCategoryLabel,
} from "./features/medical-monitoring/medicalMonitoringSubjectModels.mjs";
import {
  monitoringAiReadiness,
  monitoringRiskRowsFromInbox,
  riskIndexRowsFromApi,
  riskStatusLabel,
  ruxDispositionStateFromStatus,
  ruxDispositionStepTone,
  severityLabel,
  terminalDispositionLabels,
} from "./features/medical-monitoring/medicalMonitoringModels.mjs";
import { monitoringSourceReadiness } from "./features/medical-monitoring/medicalMonitoringSourceReadiness.mjs";
import { metricConfigurationContextFromMonitoring } from "./features/medical-monitoring/medicalMonitoringMetricConfiguration.mjs";
import { normalizeMedicalMonitoringScrollTop } from "./features/medical-monitoring/medicalMonitoringScrollState.mjs";
import { useMedicalMonitoringScrollRestoration } from "./features/medical-monitoring/medicalMonitoringScrollRestoration.mjs";
import {
  clearMedicalMonitoringRouteState,
  clearMedicalMonitoringRiskFocusState,
  parseMedicalMonitoringRouteState,
  resolveMedicalMonitoringProjectRoute,
  resolveMedicalMonitoringRiskRoute,
  resolveMedicalMonitoringSiteRoute,
  resolveMedicalMonitoringSubjectRoute,
  serializeMedicalMonitoringRouteState,
} from "./features/medical-monitoring/medicalMonitoringRouteState.mjs";
import { WritingReferencePanel } from "./features/writing-reference/WritingReferencePanel";
import { StructuredTableDesigner } from "./features/medical-writing/StructuredTableDesigner";
import { MedicalWritingAuthoringJourneySetup } from "./features/medical-writing/MedicalWritingAuthoringJourneySetup";
import { LegacyAuthoringBootstrapPanel } from "./features/medical-writing/LegacyAuthoringBootstrapPanel";
import { MedicalWritingSynopsisProjectIntake } from "./features/medical-writing/MedicalWritingSynopsisProjectIntake";
import { MedicalWritingLiteraturePanel } from "./features/medical-writing/MedicalWritingLiteraturePanel";
import { ProtocolModuleResolutionPanel } from "./features/medical-writing/ProtocolModuleResolutionPanel";
import { StudySchemaEditor } from "./features/medical-writing/StudySchemaEditor";
import { WordEditingShortcuts } from "./features/medical-writing/WordEditingShortcuts";
import { MedicalWritingPreviewPanel } from "./features/medical-writing/MedicalWritingPreviewPanel";
import { groupEditorNodesBySourceBlockId } from "./features/medical-writing/editorSourceMapping";
import {
  pollDurableMwJob,
  buildLocator,
  shouldClearLocator,
  shouldBlockStart,
  shouldBlockStartForOperation,
  classifyPollOutcome,
  extractArtifactThreadId,
  extractArtifactSuggestionIds,
  isStaleCompletion,
  resolveRetryJobId,
  mergeRetryLocator,
  createScreenGeneration,
  isScreenGenerationCurrent,
  acknowledgeRevisionDomain,
  emptyRevisionJobMap,
  setOperationJob,
  clearOperationJob,
  pickFocusedRevisionJob,
  isTerminal,
} from "./features/medical-writing/useDurableMwJob";
import {
  CrossReferenceMark,
  insertCrossReference,
} from "./features/medical-writing/CrossReferenceMark";
import {
  assessRuntimeReadiness,
  runtimeExpectation,
} from "./runtimeReadiness.js";

export { CrossReferenceMark } from "./features/medical-writing/CrossReferenceMark";

export const CitationMark = Mark.create({
  name: "citation",
  inclusive: false,
  excludes: "superscript subscript",
  addAttributes() {
    return {
      referenceIds: {
        default: null,
        parseHTML: (element) => {
          try {
            const value = JSON.parse(element.getAttribute("data-reference-ids") || "null");
            if (Array.isArray(value)) return value;
          } catch {
            // Fall through to the legacy single-reference HTML attribute.
          }
          const legacyReferenceId = String(element.getAttribute("data-reference-id") || "").trim();
          return legacyReferenceId ? [legacyReferenceId] : null;
        },
        renderHTML: (attributes) => Array.isArray(attributes.referenceIds)
          ? { "data-reference-ids": JSON.stringify(attributes.referenceIds) }
          : {},
      },
    };
  },
  parseHTML() {
    return [{ tag: "sup[data-reference-id], sup[data-reference-ids]" }];
  },
  renderHTML({ HTMLAttributes }) {
    return ["sup", mergeAttributes(HTMLAttributes, { class: "protocol-citation" }), 0];
  },
});

export function normalizeCitationMarkAttributes(value) {
  if (Array.isArray(value)) return value.map(normalizeCitationMarkAttributes);
  if (!value || typeof value !== "object") return value;
  const normalized = Object.fromEntries(
    Object.entries(value).map(([key, child]) => [key, normalizeCitationMarkAttributes(child)]),
  );
  if (normalized.type !== "citation" || !normalized.attrs) return normalized;
  const referenceIds = Array.isArray(normalized.attrs.referenceIds)
    ? normalized.attrs.referenceIds
    : [normalized.attrs.referenceId];
  return {
    ...normalized,
    attrs: {
      referenceIds: referenceIds
        .map((referenceId) => String(referenceId || "").trim())
        .filter(Boolean),
    },
  };
}

const SourceTable = Table.extend({
  addAttributes() {
    return {
      ...(this.parent?.() || {}),
      sourceBlockId: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-source-block-id"),
        renderHTML: (attributes) => attributes.sourceBlockId
          ? { "data-source-block-id": attributes.sourceBlockId }
          : {},
      },
      sourceTableId: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-source-table-id"),
        renderHTML: (attributes) => attributes.sourceTableId
          ? { "data-source-table-id": attributes.sourceTableId }
          : {},
      },
    };
  },
});

const SourceDocxImage = Node.create({
  name: "sourceDocxImage",
  group: "block",
  atom: true,
  selectable: true,
  draggable: false,
  addAttributes() {
    return {
      sourceBlockId: { default: null },
      imageId: { default: null },
      title: { default: "" },
      sourceLocator: { default: "" },
      semanticRole: { default: "figure" },
      src: { default: "" },
      alt: { default: "" },
    };
  },
  parseHTML() {
    return [{ tag: "figure[data-source-docx-image-id]" }];
  },
  renderHTML({ HTMLAttributes }) {
    const {
      sourceBlockId,
      imageId,
      title,
      sourceLocator,
      semanticRole,
      src,
      alt,
    } = HTMLAttributes;
    return [
      "figure",
      {
        class: "source-docx-image",
        "data-source-block-id": sourceBlockId,
        "data-source-docx-image-id": imageId,
        "data-source-locator": sourceLocator,
        "data-semantic-role": semanticRole,
        contenteditable: "false",
      },
      ["figcaption", {}, title],
      ["img", { src, alt: alt || title }],
    ];
  },
});

const SourceBlock = Node.create({
  name: "sourceBlock",
  group: "block",
  content: "block+",
  defining: true,
  isolating: true,
  addAttributes() {
    return {
      sourceBlockId: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-source-block-id"),
        renderHTML: (attributes) => attributes.sourceBlockId
          ? { "data-source-block-id": attributes.sourceBlockId }
          : {},
      },
    };
  },
  parseHTML() {
    return [{ tag: "div[data-protocol-source-block]" }];
  },
  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, {
      "data-protocol-source-block": "true",
      class: "protocol-source-block",
    }), 0];
  },
});

const SourceBlockEnter = Extension.create({
  name: "sourceBlockEnter",
  priority: 1100,
  addKeyboardShortcuts() {
    return {
      Enter: () => {
        const { state, view } = this.editor;
        const { selection } = state;
        const { $from, $to } = selection;
        if (!$from?.parent?.isTextblock || !$to?.parent?.isTextblock) return false;

        const nearestSourceDepth = ($position) => Array.from(
          { length: $position.depth + 1 },
          (_, depth) => depth,
        ).reverse().find((depth) => $position.node(depth).type.name === "sourceBlock");
        const sourceDepth = nearestSourceDepth($from);
        if (
          sourceDepth === undefined
          || nearestSourceDepth($to) !== sourceDepth
          || $from.node(sourceDepth).attrs.sourceBlockId !== $to.node(sourceDepth).attrs.sourceBlockId
          || $from.depth !== sourceDepth + 1
          || $to.depth !== sourceDepth + 1
        ) return false;

        const transaction = state.tr;
        if (!selection.empty) transaction.deleteSelection();
        const $head = transaction.selection.$head;
        if (
          !$head?.parent?.isTextblock
          || $head.depth !== sourceDepth + 1
          || $head.node(sourceDepth).type.name !== "sourceBlock"
        ) return false;

        const atHeadingEnd = $head.parent.type.name === "heading"
          && $head.parentOffset === $head.parent.content.size;
        const typesAfter = atHeadingEnd && state.schema.nodes.paragraph
          ? [{ type: state.schema.nodes.paragraph }]
          : undefined;
        try {
          transaction.split($head.pos, 1, typesAfter);
        } catch {
          return false;
        }
        view.dispatch(transaction.scrollIntoView());
        return true;
      },
    };
  },
});

const PROTOCOL_PARAGRAPH_ATTRIBUTE_DEFAULTS = {
  stylePreset: null,
  lineHeight: null,
  spacingBeforePt: null,
  spacingAfterPt: null,
  leftIndentChars: null,
  rightIndentChars: null,
  firstLineIndentChars: null,
};

function numericDataAttribute(element, name) {
  const value = element.getAttribute(name);
  if (value === null || value === "") return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

const ProtocolParagraphFormatting = Extension.create({
  name: "protocolParagraphFormatting",
  addGlobalAttributes() {
    return [{
      types: ["paragraph", "heading"],
      attributes: {
        stylePreset: {
          default: null,
          parseHTML: (element) => element.getAttribute("data-style-preset"),
          renderHTML: (attributes) => attributes.stylePreset
            ? { "data-style-preset": attributes.stylePreset }
            : {},
        },
        lineHeight: {
          default: null,
          parseHTML: (element) => numericDataAttribute(element, "data-line-height"),
          renderHTML: (attributes) => attributes.lineHeight == null
            ? {}
            : {
              "data-line-height": attributes.lineHeight,
              style: `line-height: ${attributes.lineHeight}`,
            },
        },
        spacingBeforePt: {
          default: null,
          parseHTML: (element) => numericDataAttribute(element, "data-spacing-before-pt"),
          renderHTML: (attributes) => attributes.spacingBeforePt == null
            ? {}
            : {
              "data-spacing-before-pt": attributes.spacingBeforePt,
              style: `margin-top: ${attributes.spacingBeforePt}pt`,
            },
        },
        spacingAfterPt: {
          default: null,
          parseHTML: (element) => numericDataAttribute(element, "data-spacing-after-pt"),
          renderHTML: (attributes) => attributes.spacingAfterPt == null
            ? {}
            : {
              "data-spacing-after-pt": attributes.spacingAfterPt,
              style: `margin-bottom: ${attributes.spacingAfterPt}pt`,
            },
        },
        leftIndentChars: {
          default: null,
          parseHTML: (element) => numericDataAttribute(element, "data-left-indent-chars"),
          renderHTML: (attributes) => attributes.leftIndentChars == null
            ? {}
            : {
              "data-left-indent-chars": attributes.leftIndentChars,
              style: `margin-left: ${attributes.leftIndentChars}em`,
            },
        },
        rightIndentChars: {
          default: null,
          parseHTML: (element) => numericDataAttribute(element, "data-right-indent-chars"),
          renderHTML: (attributes) => attributes.rightIndentChars == null
            ? {}
            : {
              "data-right-indent-chars": attributes.rightIndentChars,
              style: `margin-right: ${attributes.rightIndentChars}em`,
            },
        },
        firstLineIndentChars: {
          default: null,
          parseHTML: (element) => numericDataAttribute(element, "data-first-line-indent-chars"),
          renderHTML: (attributes) => attributes.firstLineIndentChars == null
            ? {}
            : {
              "data-first-line-indent-chars": attributes.firstLineIndentChars,
              style: `text-indent: ${attributes.firstLineIndentChars}em`,
            },
        },
      },
    }];
  },
});

const SourceTableRow = TableRow.extend({
  addAttributes() {
    return {
      ...(this.parent?.() || {}),
      rowId: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-row-id"),
        renderHTML: (attributes) => attributes.rowId ? { "data-row-id": attributes.rowId } : {},
      },
    };
  },
});

function sourceCellAttributes(extension) {
  return {
    ...(extension.parent?.() || {}),
    cellId: {
      default: null,
      parseHTML: (element) => element.getAttribute("data-cell-id"),
      renderHTML: (attributes) => attributes.cellId ? { "data-cell-id": attributes.cellId } : {},
    },
    sourceLocator: {
      default: null,
      parseHTML: (element) => element.getAttribute("data-source-locator"),
      renderHTML: (attributes) => attributes.sourceLocator
        ? { "data-source-locator": attributes.sourceLocator }
        : {},
    },
    gridColumnIndex: {
      default: null,
      parseHTML: (element) => {
        const value = element.getAttribute("data-grid-column-index");
        return value === null ? null : Number(value);
      },
      renderHTML: (attributes) => Number.isInteger(attributes.gridColumnIndex)
        ? { "data-grid-column-index": String(attributes.gridColumnIndex) }
        : {},
    },
    styleRole: {
      default: "body",
      parseHTML: (element) => element.getAttribute("data-style-role") || "body",
      renderHTML: (attributes) => ({ "data-style-role": attributes.styleRole || "body" }),
    },
  };
}

const SourceTableCell = TableCell.extend({
  addAttributes() {
    return sourceCellAttributes(this);
  },
});

const SourceTableHeader = TableHeader.extend({
  addAttributes() {
    return sourceCellAttributes(this);
  },
});

const INITIAL_PROJECT_ID = import.meta.env.VITE_PROJECT_ID || "";
const DEFAULT_SUBJECT_ID = import.meta.env.VITE_SUBJECT_ID || "";

const navItems = [
  { key: "overview", label: "项目总看板", icon: LayoutDashboard },
  { key: "evidenceDesign", label: "证据调研与方案设计", icon: Search },
  { key: "eligibility", label: "入排审核", icon: UserRoundCheck },
  { key: "monitoring", label: "医学监查", icon: ShieldAlert },
  { key: "tfl", label: "数据分析与TFL", icon: Database },
  { key: "writing", label: "医学写作", icon: BookOpenText },
  { key: "safety", label: "安全信号与PV协同", icon: AlertTriangle },
  { key: "sourceRegistry", label: "来源台账", icon: FolderSearch2 },
  { key: "approvals", label: "审批中心", icon: ClipboardCheck },
];

const moduleLabels = {
  dashboard: "项目总看板",
  evidence_design: "证据调研与方案设计",
  eligibility_review: "入排审核",
  medical_monitoring: "医学监查",
  data_analysis_tfl: "数据分析与TFL",
  medical_writing: "医学写作",
  safety_pv: "安全信号与PV协同",
  source_registry: "来源台账",
  approvals: "审批中心",
};

const moduleToPage = {
  dashboard: "overview",
  evidence_design: "evidenceDesign",
  eligibility_review: "eligibility",
  medical_monitoring: "monitoring",
  data_analysis_tfl: "tfl",
  medical_writing: "writing",
  safety_pv: "safety",
  source_registry: "sourceRegistry",
  approvals: "approvals",
};

const pageToModule = {
  overview: "dashboard",
  evidenceDesign: "evidence_design",
  eligibility: "eligibility_review",
  monitoring: "medical_monitoring",
  subjectTimeline: "medical_monitoring",
  patientProfile: "medical_monitoring",
  tfl: "data_analysis_tfl",
  writing: "medical_writing",
  safety: "safety_pv",
  sourceRegistry: "source_registry",
  approvals: "approvals",
};

function apiErrorText(error) {
  return error?.message || error?.status || "network";
}

function medicalWritingExportErrorText(error) {
  const message = apiErrorText(error);
  if (/medical writing content quality|frozen final export blocked|content-quality/i.test(message)) {
    return "终稿暂不能导出：仍有章节含待确认事实或内部标记。请点击“内容核查”逐项修订并重新冻结。";
  }
  if (/unresolved drafting markers|全文初稿|candidate/i.test(message)) {
    return "终稿暂不能导出：全文候选仍有未完成内容，请先完成章节审核与事实补齐。";
  }
  return message;
}

function apiDetailText(payload, fallback = "") {
  const detail = payload?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") return detail.detail || detail.message || JSON.stringify(detail);
  return fallback;
}

function readJsonOrThrow(response) {
  if (response.ok) return response.json();
  return response
    .json()
    .catch(() => ({}))
    .then((payload) => {
      const error = new Error(apiDetailText(payload, `${response.status}`));
      error.status = response.status;
      error.payload = payload;
      const detail = payload?.detail;
      error.code = detail && typeof detail === "object"
        ? String(detail.code || detail.detail?.code || "").trim()
        : "";
      throw error;
    });
}

function monitoringReadErrorInfo(error, surface = "医学监查数据") {
  const code = String(
    error?.code
      || error?.payload?.detail?.code
      || error?.payload?.detail?.detail?.code
      || "",
  ).trim();
  const surfaceLabel = {
    dashboard: "项目总览",
    workbench_inbox: "工作收件箱",
    ai_runs: "独立 AI 运行记录",
    monitoring_subjects: "受试者目录",
    monitoring_profile: "受试者画像",
    monitoring_inbox: "监查工作收件箱",
    monitoring_source_manifest: "医学监查来源清单",
    monitoring_raw: "原始监查资料",
  }[surface] || surface;
  const messages = {
    monitoring_principal_unavailable: {
      title: `${surfaceLabel}暂不可用`,
      message: "服务器尚未提供可验证的当前用户身份；为保护项目数据，本次读取已阻断。",
    },
    monitoring_read_action_unconfigured: {
      title: `${surfaceLabel}读取动作尚未启用`,
      message: "该读取面尚未完成显式权限、来源快照和审计链配置；系统未将其显示为“无数据”。",
    },
    monitoring_project_scope_denied: {
      title: `${surfaceLabel}项目范围不匹配`,
      message: "当前身份没有读取该项目的明确范围；系统未更新当前页面数据。",
    },
    monitoring_route_context_invalid: {
      title: `${surfaceLabel}身份上下文无效`,
      message: "服务器身份或项目绑定未通过校验；系统未使用不明数据继续展示。",
    },
    monitoring_response_project_mismatch: {
      title: `${surfaceLabel}响应项目身份不匹配`,
      message: "服务器返回的数据未绑定当前项目；系统已阻止写入，避免跨项目数据串入当前页面。",
    },
  };
  const selected = messages[code] || {
    title: `${surfaceLabel}读取失败`,
    message: "本次读取未完成；系统未把失败结果当作零风险、空收件箱或无受试者。",
  };
  const status = Number(error?.status || 0);
  const transport = error?.readSource === "contract"
    ? "客户端契约校验"
    : status
      ? `HTTP ${status}`
      : "网络未响应";
  const technical = [
    transport,
    code ? `code=${code}` : "",
  ].filter(Boolean).join(" · ");
  return { ...selected, code, technical };
}

function monitoringReadContractError(message) {
  const error = new Error(message);
  error.code = "monitoring_response_project_mismatch";
  error.readSource = "contract";
  return error;
}

function MonitoringReadUnavailable({ surface, error, compact = false }) {
  const info = monitoringReadErrorInfo(error, surface);
  return (
    <section
      className={`panel monitoring-read-unavailable ${compact ? "is-compact" : ""}`}
      data-read-state="unavailable"
      data-read-code={info.code || "unknown"}
      role="alert"
      aria-label={info.title}
    >
      <ShieldAlert size={compact ? 18 : 22} aria-hidden="true" />
      <div>
        <strong>{info.title}</strong>
        <p>{info.message}</p>
        {info.technical && <small>{info.technical}</small>}
      </div>
    </section>
  );
}

const writingSections = [
  { id: "synopsis", title: "方案概要", status: "已批准", coverage: 100, revisions: 0 },
  { id: "background", title: "研究背景", status: "AI 草稿", coverage: 68, revisions: 2 },
  { id: "endpoints", title: "研究目的与终点", status: "医学审阅中", coverage: 35, revisions: 3 },
  { id: "population", title: "研究人群", status: "医学审阅中", coverage: 76, revisions: 1 },
  { id: "eligibility", title: "入选与排除标准", status: "AI 草稿", coverage: 72, revisions: 2 },
  { id: "soa", title: "研究流程与评估时间表", status: "医学审阅中", coverage: 58, revisions: 1 },
  { id: "safety", title: "安全性评估", status: "AI 草稿", coverage: 64, revisions: 1 },
  { id: "statistics", title: "统计学考虑", status: "未开始", coverage: 18, revisions: 0 },
];

function statusClass(value) {
  if (["critical", "高风险复核", "需行动", "不通过"].includes(value)) return "danger";
  if (["failed"].includes(value)) return "danger";
  if (["high", "中风险复核", "复核中", "待确认", "待补证", "医学审阅中", "待医学批准", "溯源提醒", "blocked"].includes(value)) return "warning";
  if (["已关闭", "通过", "已批准", "可进入筛选", "completed"].includes(value)) return "success";
  return "info";
}

function verdictLabel(value) {
  return {
    pass: "通过",
    pass_verify: "通过（需溯源验证）",
    fail: "不通过",
    insufficient: "证据不足",
    investigator: "需研究者判定",
    needs_evidence: "需补充资料",
    not_reviewed: "未审核",
    parse_error: "解析失败",
    na: "不适用",
  }[value] || value || "未审核";
}

function verdictTone(value) {
  if (value === "fail" || value === "parse_error") return "danger";
  if (["insufficient", "investigator", "needs_evidence", "pass_verify"].includes(value)) return "warning";
  if (value === "pass") return "success";
  return "info";
}

function ruleTypeLabel(value) {
  return value === "exclusion" ? "排除标准" : "入选标准";
}

function requestKey(prefix) {
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  return `${prefix}-${suffix}`;
}

function candidateStatusLabel(value) {
  return {
    pending: "待处理",
    processing: "处理中",
    reviewed: "已审核",
    error: "异常",
    ready_for_review: "待审核",
    action_required: "需行动",
    awaiting_site_response: "待中心回复",
    ready_for_randomization: "可随机",
    screen_failed: "筛败",
  }[value] || value || "未记录";
}

function shortPath(value) {
  if (!value) return "";
  const parts = String(value).split("/");
  return parts.slice(-4).join("/");
}

function sourceTypeLabel(value) {
  return {
    XLSX: "XLSX",
    CSV: "CSV",
    DOCX: "DOCX",
    Directory: "目录",
  }[value] || value;
}

function parserStatusLabel(status) {
  return {
    parsed: "已解析",
    inventory_only: "仅登记清单",
    document_registered: "已登记文件",
    pending: "待解析",
    failed: "解析失败",
  }[status] || status;
}

function sourceKindLabel(kind) {
  return {
    listing_file: "列表数据",
    protocol_docx: "研究方案",
    raw_subject_bundle_inventory: "受试者资料清单",
    tfl_dataset_package_inventory: "TFL数据包清单",
    tfl_output_package_inventory: "TFL输出包清单",
    safety_signal_package_inventory: "安全资料包清单",
    pv_safety_package_inventory: "PV资料包清单",
    clinical_safety_summary_inventory: "安全总结清单",
    safety_medical_review_listing: "安全性医学复核listing",
  }[kind] || kind;
}

function sourceLedgerTitle(entry) {
  const title = entry?.public_title || "未命名来源";
  return title.includes("_清单") ? sourceKindLabel(entry.source_kind) : title;
}

function sourceSystemDisplayLabel(value) {
  return {
    "source_registry/raw_source": "原始资料登记",
    "enrollment-review-app": "旧版入排审核系统",
  }[value] || (value ? "已登记资料来源" : "原始资料登记");
}

function eligibilityInputScopeLabel(value) {
  return {
    protocol_docx_spans: "方案正文段落",
    protocol_rules_pending: "待生成的方案规则",
    raw_subject_file_inventory: "受试者原始资料清单",
    raw_subject_ocr_vlm_pending: "待OCR/VLM识别资料",
  }[value] || "已登记原始资料";
}

function forbiddenLegacyInputLabel(value) {
  return {
    "enrollment-review-app": "旧版入排审核系统结果",
    legacy_evidence_bundle: "旧版证据包",
    legacy_review_report: "旧版审核报告",
    legacy_llm_output: "旧模型输出",
    legacy_project_reports: "旧项目报告",
  }[value] || "旧版衍生产物";
}

function eligibilitySourceTypeLabel(value) {
  return {
    pdf: "PDF",
    image: "图像",
    doc: "Word DOC",
    docx: "Word DOCX",
    archive: "压缩包",
    other: "其他资料",
  }[value] || value || "待分类资料";
}

function eligibilityExtractionStatusLabel(value) {
  return {
    pending_ocr_vlm: "待OCR/VLM",
    pending_text_extraction_or_ocr: "待文本提取/OCR",
    pending_safe_unpack: "待安全解包",
    pending_text_extraction: "待文本提取",
    pending_source_classification: "待资料分类",
  }[value] || value || "待处理";
}

function eligibilityEvidenceProcessingLabel(value) {
  return {
    not_started: "未开始",
    queued: "排队中",
    running: "处理中",
    partial: "部分完成",
    completed: "已完成",
    failed: "提取失败",
    needs_visual_qc: "待视觉复核",
    not_applicable: "不适用",
  }[value] || value || "未开始";
}

function eligibilityEvidenceProcessingTone(value) {
  if (value === "completed") return "success";
  if (value === "failed") return "danger";
  if (["queued", "running"].includes(value)) return "info";
  if (["partial", "needs_visual_qc"].includes(value)) return "warning";
  return "neutral";
}

function aiTaskDisplayName(task) {
  return {
    disease_background_research: "适应症背景调研",
    competitive_intelligence: "竞品情报整理",
    protocol_design_synthesis: "方案设计建议综合分析",
    picos_design_coach: "PICOS问答式设计",
    tfl_generation_assist: "TFL清单与字段映射辅助",
    analysis_result_explanation: "分析结果医学解释",
    safety_case_medical_review: "安全个案医学复核建议",
    signal_narrative_synthesis: "安全信号叙述草案",
  }[task] || task;
}

function tflOutputTypeLabel(value) {
  return {
    table: "表",
    figure: "图",
    listing: "Listing",
    document: "文档",
  }[value] || value;
}

function tflReviewActionLabel(action) {
  return {
    mark_reviewed: "标记医学已审阅",
    request_statistical_review: "发起统计复核",
    create_writing_candidate: "标记写作引用候选",
    return_for_dataset_check: "退回数据集核对",
    reset_review: "重置状态",
  }[action] || action;
}

function safetyReviewActionLabel(action) {
  return {
    mark_medical_reviewed: "保存医学意见",
    request_pv_confirmation: "标记PV协同确认",
    return_for_source_check: "退回补充资料",
    accept_no_action: "关闭为暂无需处理",
    reset_review: "重置处置",
  }[action] || action;
}

function parserStatusDisplay(status) {
  return {
    parsed: "已读取",
    inventory_only: "仅登记清单",
    document_registered: "已登记文件",
    inventory_only_sas7bdat_requires_pyreadstat: "仅登记清单，需SAS解析器",
    parse_failed: "读取失败",
    pending: "待解析",
  }[status] || status || "未记录";
}

function formatMaybeNumber(value) {
  return value === null || value === undefined ? "未读取" : Number(value).toLocaleString("zh-CN");
}

function safetyGateTone(status) {
  return {
    ok: "success",
    warning: "warning",
    blocker: "danger",
    blocked: "danger",
  }[status] || "info";
}

function gateStatusLabel(status) {
  return {
    ok: "通过",
    warning: "需确认",
    blocker: "阻断",
    blocked: "阻断",
  }[status] || status || "未记录";
}

function picosStatusTone(status) {
  return {
    写作候选: "success",
    待医学确认: "warning",
    待补医学理由: "warning",
    退回补证: "danger",
    待用户确认: "info",
  }[status] || statusClass(status);
}

function picosActionLabel(action) {
  return {
    select_option: "选择候选",
    save_rationale: "保存理由",
    mark_writing_candidate: "标记写作候选",
    return_for_evidence: "退回补证",
    reset_decision: "重置",
  }[action] || action;
}

function riskToneFromEvent(event) {
  if (["protocol_deviation", "query"].includes(event.event_type)) return "critical";
  if (event.related_risk_ids?.length) return event.event_type === "lab" ? "warning" : "critical";
  if (event.event_type === "efficacy_score") return "good";
  if (event.event_type === "medical_history") return "source";
  return "normal";
}

function subjectStatusFromPrompts(prompts = []) {
  if (prompts.some((item) => ["critical", "high"].includes(item.severity))) return "高风险复核";
  if (prompts.some((item) => item.severity === "medium")) return "中风险复核";
  return "医学复核";
}

function buildSubjectView(profile, subjectId, risk, subjectCatalog = []) {
  const local = subjectCatalog.find((item) => item.id === subjectId);
  const normalizedProfile = normalizeMonitoringSubjectProfile(profile);
  if (!normalizedProfile) {
    return {
      id: subjectId,
      site: risk?.site || "-",
      status: "待载入",
      profile: "完整个例下钻资料待生成；当前仅显示风险登记入口。",
      ...local,
      rawProfile: null,
      efficacyMetrics: [],
      safetyMetrics: [],
      efficacy: [],
      timeline: [],
      timelineUnavailableReason: "个例资料尚未载入；当前未生成 Subject Timeline 事件。",
      risks: risk ? [risk.title] : [],
      labs: [],
      queries: [],
      prompts: [],
      reviewFocus: [],
    };
  }

  const primaryEfficacy = normalizedProfile.efficacy_trends[0];
  const efficacy = primaryEfficacy?.points?.map((point) => ({
    visit: point.visit_code || point.visit_label,
    rTNSS: point.value,
    risk: point.risk_flag ? "warning" : "normal",
  })) || [];

  const timeline = normalizedProfile.timeline.map((event) => ({
    day: event.visit_code || `D${event.study_day}`,
    lane: laneForEvent(event),
    label: event.title,
    risk: riskToneFromEvent(event),
  }));

  const labs = normalizedProfile.safety_trends.map((metric) => {
    const latest = metric.points?.[metric.points.length - 1] || {};
    const abnormal = latest.risk_flag || (latest.normality && !["normal", "not_applicable"].includes(latest.normality));
    return {
      name: metric.metric_label,
      value: latest.value !== undefined ? `${latest.value}${metric.unit ? ` ${metric.unit}` : ""}` : "-",
      trend: abnormal ? "需复核" : "最新正常",
      flag: abnormal ? "warning" : "normal",
    };
  });

  return {
    id: normalizedProfile.subject_id,
    site: normalizedProfile.subject?.site_id || "-",
    status: subjectStatusFromPrompts(normalizedProfile.risk_prompts),
    rawProfile: normalizedProfile,
    efficacyMetrics: normalizedProfile.efficacy_trends,
    safetyMetrics: normalizedProfile.safety_trends,
    profile: [
      normalizedProfile.subject?.treatment_arm,
      normalizedProfile.subject?.latest_visit_label,
      normalizedProfile.subject?.enrollment_status,
    ].filter(Boolean).join(" / "),
    efficacy,
    timeline,
    risks: normalizedProfile.risk_prompts.map((prompt) => prompt.title),
    labs,
    queries: normalizedProfile.risk_prompts.filter((prompt) => prompt.query_id).map((prompt) => `${prompt.query_id}：${prompt.recommended_action}`),
    prompts: normalizedProfile.risk_prompts,
    reviewFocus: normalizedProfile.review_focus,
  };
}

function formatBatchDisplay(batch) {
  if (!batch) return "未登记批次";
  if (batch.batch_label) return batch.batch_label;
  if (batch.batch_id) return batch.batch_id.replace("batch_", "Batch ");
  return "未登记批次";
}

function sourceContextForPage(activePage, sourceManifests, activeProjectId) {
  const moduleKey = pageToModule[activePage] || "dashboard";
  const manifest = sourceManifests?.[activeProjectId] || null;
  const binding = manifest?.route_bindings?.[moduleKey] || null;
  const header = manifest?.header_project || null;
  const registryPage = activePage === "sourceRegistry";
  const label = registryPage ? "项目级来源台账" : binding?.label || moduleLabels[moduleKey] || "当前模块";
  const sourceCode = header?.project_code || activeProjectId;
  const sourceMode = manifest?.source_mode || "unknown";
  const routeProjectId = binding?.route_project_id || "";
  const effectiveRouteProjectId = registryPage ? activeProjectId : routeProjectId;
  return {
    moduleKey,
    label,
    projectId: activeProjectId,
    routeProjectId: effectiveRouteProjectId,
    manifest,
    binding,
    header,
    sourceCode,
    sourceMode,
    displayBatch: binding?.display_batch || null,
    configured: registryPage || Boolean(binding),
  };
}

class WorkbenchErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidUpdate(previousProps) {
    if (previousProps.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  componentDidCatch(error, info) {
    console.error("Workbench module render failed", error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="page">
        <section className="panel module-error-state" role="alert">
          <AlertTriangle size={22} />
          <div>
            <strong>当前页面加载失败</strong>
            <p>其他模块仍可继续使用。请重新进入当前模块；若问题持续，请保留当前项目与章节信息。</p>
          </div>
          <button onClick={() => this.setState({ error: null })}>重新加载当前页面</button>
        </section>
      </main>
    );
  }
}

const EMPTY_NEW_PROJECT = {
  project_code: "",
  project_name: "",
  indication: "",
  product_name: "",
  study_phase: "",
  protocol_id: "",
  protocol_version: "草案",
  protocol_date: "",
  entry_mode: "from_zero",
};

const DIRECT_MEDICAL_DECISION_ITEM_TYPES = new Set([
  "risk",
  "approval",
  "handoff",
  "picos_decision",
  "eligibility_action",
]);

const CONTENT_DECISION_SIGNAL = /内容(?:不一致|校验|核对|确认)|适应症(?:不一致|核对)|文件(?:角色|类型)(?:不一致|核对)|误用|错用|确认沿用|是否采用|需医学(?:判断|确认)|PICOS(?:确认|决策)/i;

function isUnreadMedicalDecisionItem(item) {
  if (!item?.unread || !item?.needs_action) return false;
  if (DIRECT_MEDICAL_DECISION_ITEM_TYPES.has(item.item_type)) return true;
  if (!["source_ready", "data_health", "quality_gate"].includes(item.item_type)) return false;
  const decisionSignal = [
    item.title,
    item.summary,
    item.status,
    item.action_label,
    item.source_type,
  ].filter(Boolean).join(" ");
  return CONTENT_DECISION_SIGNAL.test(decisionSignal);
}

function medicalDecisionItems(workbenchInbox) {
  return (workbenchInbox?.items || []).filter(isUnreadMedicalDecisionItem);
}

function EmptyProjectOverview({
  loading,
  error,
  routeError,
  onRetryProjects,
  onClearRoute,
  onCreateProject,
  aiGatewayStatus,
  onAiGatewayStatusChange,
}) {
  const unavailable = Boolean(error || routeError);
  const effectiveError = routeError || error;
  const routeUnavailable = Boolean(routeError);
  const emptyProjectMetricValue = loading || unavailable ? "—" : "0";
  return (
    <main className="page empty-project-overview" data-project-state={loading ? "loading" : unavailable ? "unavailable" : "empty"}>
      <SectionTitle
        eyebrow="项目总看板"
        title={loading ? "正在加载项目" : routeUnavailable ? "链接项目不可用" : unavailable ? "项目服务暂不可用" : "暂无项目"}
        action={(
          <div className="empty-project-actions">
            <AiGatewayPanel
              status={aiGatewayStatus}
              onStatusChange={onAiGatewayStatusChange}
              compact
            />
            {unavailable && !routeUnavailable && (
              <button type="button" className="icon-text-button" onClick={onRetryProjects}>
                <RefreshCw size={16} /> 重新读取
              </button>
            )}
            {routeUnavailable && (
              <button type="button" className="icon-text-button" onClick={onClearRoute}>
                <ArrowLeft size={16} /> 返回项目列表
              </button>
            )}
            {!loading && !unavailable && (
              <button type="button" className="primary-button empty-project-create" onClick={onCreateProject}>
                <Plus size={17} /> 新建项目
              </button>
            )}
          </div>
        )}
      />
      <section className="panel empty-project-panel" aria-live="polite">
        <div className="empty-project-metrics">
          {[
            ["项目数", emptyProjectMetricValue],
            ["模块进度", emptyProjectMetricValue],
            ["开放风险", emptyProjectMetricValue],
            ["待审批", emptyProjectMetricValue],
          ].map(([label, value]) => (
            <div key={label}>
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
        <div className="empty-project-message">
          <FolderSearch2 size={24} />
          <strong>{loading ? "正在读取项目列表" : routeUnavailable ? "链接项目未加载" : unavailable ? "项目列表读取失败" : "暂无项目数据"}</strong>
          {routeUnavailable ? (
            <span>{effectiveError} 已阻止加载其他研究，避免跨项目串读。</span>
          ) : unavailable ? (
            <span>{effectiveError}</span>
          ) : !loading && (
            <span>新建项目后开始医学工作。</span>
          )}
        </div>
      </section>
    </main>
  );
}

function AppShell({
  activePage,
  setActivePage,
  dashboard,
  projects,
  projectsLoaded,
  projectsLoadError,
  projectRouteError,
  activeProjectId,
  requestProjectChange,
  onRetryProjects,
  onClearProjectRoute,
  sourceManifests,
  workbenchInbox,
  workbenchInboxError,
  aiGatewayStatus,
  onAiGatewayStatusChange,
  onProjectCreated,
  children,
}) {
  const [newProjectOpen, setNewProjectOpen] = useState(false);
  const [newProjectDraft, setNewProjectDraft] = useState(EMPTY_NEW_PROJECT);
  const [newProjectBusy, setNewProjectBusy] = useState(false);
  const [newProjectMessage, setNewProjectMessage] = useState("");
  const [newProjectErrors, setNewProjectErrors] = useState({});
  const hasActiveProject = Boolean(
    activeProjectId && projects.some((item) => item.project_id === activeProjectId),
  );
  const sourceContext = sourceContextForPage(activePage, sourceManifests, activeProjectId);
  const project = hasActiveProject ? (dashboard.project || sourceContext.header || {
    project_code: "项目未加载",
    indication: "-",
    protocol_version: "-",
  }) : null;
  const latestBatch = hasActiveProject ? dashboard.latest_batch || null : null;
  const visibleActivePage = ["subjectTimeline", "patientProfile"].includes(activePage) ? "monitoring" : activePage;
  const activeBatch = hasActiveProject && sourceContext.displayBatch?.batch_label
    ? sourceContext.displayBatch
    : latestBatch;
  const activeBatchDate = activeBatch?.extract_date || "";
  const decisionItems = hasActiveProject && !workbenchInboxError ? medicalDecisionItems(workbenchInbox) : [];
  const unavailableCount = workbenchInboxError ? "—" : null;
  const pendingApprovalCount = unavailableCount || decisionItems.filter((item) => item.item_type === "approval").length;
  const highRiskCount = unavailableCount || decisionItems.filter((item) => item.item_type === "risk" && ["critical", "high"].includes(item.priority)).length;
  const handoffDecisionCount = unavailableCount || decisionItems.filter((item) => item.item_type === "handoff").length;
  const updateNewProjectField = (field, value) => {
    setNewProjectDraft((current) => ({ ...current, [field]: value }));
    setNewProjectErrors((current) => {
      if (!current[field]) return current;
      const next = { ...current };
      delete next[field];
      return next;
    });
    setNewProjectMessage("");
  };
  const createNewProject = async (event) => {
    event.preventDefault();
    if (newProjectDraft.entry_mode === "synopsis_import") return;
    const requiredFields = [
      ["product_name", "试验药物"],
      ["indication", "适应症"],
      ["study_phase", "研究分期"],
    ];
    const errors = Object.fromEntries(
      requiredFields
        .filter(([field]) => !String(newProjectDraft[field] || "").trim())
        .map(([field, label]) => [field, `请填写${label}`]),
    );
    if (Object.keys(errors).length) {
      setNewProjectErrors(errors);
      setNewProjectMessage("请先补全标记为必填的项目信息。后续研究设计细节可在两阶段反问中继续确认。");
      globalThis.requestAnimationFrame?.(() => {
        document.querySelector(".new-project-field-error + input, .new-project-fields [aria-invalid='true']")?.focus();
      });
      return;
    }
    setNewProjectBusy(true);
    setNewProjectMessage("");
    setNewProjectErrors({});
    try {
      const response = await fetch("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...newProjectDraft,
          product_name: newProjectDraft.product_name.trim(),
          actor: "medical_manager",
          idempotency_key: `create-project-${Date.now()}-${Math.random().toString(16).slice(2)}`,
        }),
      });
      const payload = await readJsonOrThrow(response);
      onProjectCreated?.(payload.project, payload.entry_mode);
      setNewProjectDraft(EMPTY_NEW_PROJECT);
      setNewProjectOpen(false);
    } catch (error) {
      setNewProjectMessage(`创建失败：${apiErrorText(error)}`);
    } finally {
      setNewProjectBusy(false);
    }
  };
  return (
    <div className={`app ${activePage === "writing" ? "writing-active" : ""}`}>
      <aside className="sidebar">
        <button className="brand" onClick={() => setActivePage("overview")} aria-label="返回项目总看板">
          <img src={logo} alt="康哲药业" />
        </button>
        <nav className="nav">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.key}
                className={`nav-item ${visibleActivePage === item.key ? "active" : ""}`}
                onClick={() => setActivePage(item.key)}
                title={item.label}
                disabled={!hasActiveProject && item.key !== "overview"}
              >
                <Icon size={18} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
        <div className="sidebar-footer">
          <span>最后更新</span>
          <strong>{hasActiveProject ? "09:00" : projectsLoadError ? "连接失败" : "暂无数据"}</strong>
        </div>
      </aside>
      <section className="workspace">
        <header className="topbar">
          <div className="project-meta">
            <label className="project-switcher">
              <span className="meta-label">项目</span>
              <select
                aria-label="选择临床研究项目"
                aria-busy={!projectsLoaded}
                disabled={!projectsLoaded || Boolean(projectsLoadError) || !projects.length}
                value={hasActiveProject ? activeProjectId : ""}
                onChange={(event) => requestProjectChange(event.target.value)}
              >
                {!hasActiveProject && (
                  <option value="">{projectsLoadError ? "读取失败" : projectsLoaded ? "暂无项目" : "正在加载项目"}</option>
                )}
                {projects.map((item) => {
                  const product = String(item.product_name || "").trim();
                  const indication = String(item.indication || "").trim();
                  const phase = String(item.study_phase || "").trim();
                  const code = String(item.project_code || item.project_id || "").trim();
                  const label = [product || null, indication || null, phase || null, code || null]
                    .filter(Boolean)
                    .join(" · ");
                  return (
                    <option key={item.project_id} value={item.project_id} title={item.project_name || label}>
                      {label || item.project_id}
                    </option>
                  );
                })}
              </select>
            </label>
            <button
              type="button"
              className={`new-project-trigger ${!hasActiveProject ? "primary-button" : ""}`}
              disabled={!projectsLoaded || Boolean(projectsLoadError)}
              onClick={() => {
                setNewProjectMessage("");
                setNewProjectOpen(true);
              }}
              title={!projectsLoaded || projectsLoadError ? "项目列表尚未就绪，暂不能新建项目" : "新建中国临床试验方案写作项目"}
            >
              <Plus size={16} /> 新建项目
            </button>
            <div>
              <span className="meta-label">适应症</span>
              <strong>{hasActiveProject ? project?.indication : "暂无项目数据"}</strong>
            </div>
            <div>
              <span className="meta-label">方案版本</span>
              <strong>{hasActiveProject ? project?.protocol_version : "暂无项目数据"}</strong>
            </div>
            <div>
              <span className="meta-label">数据批次</span>
              <strong title={hasActiveProject && activeBatchDate ? `数据日期：${activeBatchDate}` : undefined}>
                {hasActiveProject ? formatBatchDisplay(activeBatch) : "暂无项目数据"}
              </strong>
            </div>
            <div className={!hasActiveProject || !sourceContext.configured ? "source-context-unconfigured" : ""}>
              <span className="meta-label">当前来源</span>
              <strong title={hasActiveProject ? `来源项目：${sourceContext.sourceCode}` : undefined}>
                {hasActiveProject ? (sourceContext.configured ? sourceContext.label : "未配置当前模块") : "未选择项目"}
              </strong>
            </div>
          </div>
          <div className="top-actions">
            <Metric icon={Bell} label="未读决策" value={unavailableCount || decisionItems.length} tone="warning" />
            <Metric icon={AlertTriangle} label="高风险开放" value={highRiskCount} tone="danger" />
            <Metric icon={Sparkles} label="待交接" value={handoffDecisionCount} tone="info" />
            <Metric icon={FileCheck2} label="待审批" value={pendingApprovalCount} tone="success" />
            <button className="icon-button" title="通知中心尚未开放" disabled>
              <Bell size={18} />
            </button>
          </div>
        </header>
        {hasActiveProject ? children : (
          <EmptyProjectOverview
            loading={!projectsLoaded}
            error={projectsLoadError}
            routeError={projectRouteError}
            onRetryProjects={onRetryProjects}
            onClearRoute={onClearProjectRoute}
            aiGatewayStatus={aiGatewayStatus}
            onAiGatewayStatusChange={onAiGatewayStatusChange}
            onCreateProject={() => {
              setNewProjectMessage("");
              setNewProjectOpen(true);
            }}
          />
        )}
      </section>
      {newProjectOpen && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget && !newProjectBusy) setNewProjectOpen(false);
        }}>
          <form className="panel new-project-dialog" onSubmit={createNewProject} noValidate role="dialog" aria-modal="true" aria-label="新建医学写作项目">
            <header>
              <div>
                <span>医学写作</span>
                <h2>新建研究方案项目</h2>
              </div>
              <button type="button" className="icon-button" onClick={() => setNewProjectOpen(false)} disabled={newProjectBusy} title="关闭">
                <XCircle size={18} />
              </button>
            </header>
            <div className="new-project-entry-mode" role="radiogroup" aria-label="建项方式">
              <button type="button" className={newProjectDraft.entry_mode === "from_zero" ? "active" : ""} onClick={() => setNewProjectDraft((current) => ({ ...current, entry_mode: "from_zero" }))}>
                <PencilLine size={17} /><strong>从零开始</strong><span>两阶段反问确定研究框架与 PICOS</span>
              </button>
              <button type="button" className={newProjectDraft.entry_mode === "synopsis_import" ? "active" : ""} onClick={() => setNewProjectDraft((current) => ({ ...current, entry_mode: "synopsis_import" }))}>
                <Upload size={17} /><strong>导入方案摘要</strong><span>先解析文件，确认提取结果后创建项目</span>
              </button>
            </div>
            {newProjectDraft.entry_mode === "synopsis_import" ? (
              <MedicalWritingSynopsisProjectIntake
                disabled={newProjectBusy}
                onCreated={(payload) => {
                  onProjectCreated?.(payload.project, payload.entry_mode);
                  setNewProjectDraft(EMPTY_NEW_PROJECT);
                  setNewProjectOpen(false);
                }}
              />
            ) : (
              <>
                <div className="new-project-fields">
                  <label>试验药物<input required aria-required="true" aria-invalid={Boolean(newProjectErrors.product_name)} aria-describedby={newProjectErrors.product_name ? "new-project-product-error" : undefined} maxLength={160} value={newProjectDraft.product_name} onChange={(event) => updateNewProjectField("product_name", event.target.value)} placeholder="药物代号或通用名" />{newProjectErrors.product_name && <small id="new-project-product-error" className="new-project-field-error">{newProjectErrors.product_name}</small>}</label>
                  <label>适应症<input required aria-required="true" aria-invalid={Boolean(newProjectErrors.indication)} aria-describedby={newProjectErrors.indication ? "new-project-indication-error" : undefined} maxLength={120} value={newProjectDraft.indication} onChange={(event) => updateNewProjectField("indication", event.target.value)} placeholder="例如 类风湿关节炎" />{newProjectErrors.indication && <small id="new-project-indication-error" className="new-project-field-error">{newProjectErrors.indication}</small>}</label>
                  <label>研究分期<select required aria-required="true" aria-invalid={Boolean(newProjectErrors.study_phase)} aria-describedby={newProjectErrors.study_phase ? "new-project-phase-error" : undefined} value={newProjectDraft.study_phase} onChange={(event) => updateNewProjectField("study_phase", event.target.value)}><option value="">请选择</option><option value="I期">I期</option><option value="I/II期">I/II期</option><option value="II期">II期</option><option value="II/III期">II/III期</option><option value="III期">III期</option></select>{newProjectErrors.study_phase && <small id="new-project-phase-error" className="new-project-field-error">{newProjectErrors.study_phase}</small>}</label>
                </div>
                {newProjectMessage && <p className="new-project-message">{newProjectMessage}</p>}
                <footer>
                  <button type="button" onClick={() => setNewProjectOpen(false)} disabled={newProjectBusy} title={newProjectBusy ? "项目正在创建，请稍候" : "取消新建项目"}>取消</button>
                  <button type="submit" className="primary-button" disabled={newProjectBusy} title={newProjectBusy ? "项目正在创建，请稍候" : "创建项目并进入写作工作台"}>{newProjectBusy ? "创建中" : "创建并进入写作"}</button>
                </footer>
              </>
            )}
          </form>
        </div>
      )}
    </div>
  );
}

function Metric({ icon: Icon, label, value, tone }) {
  return (
    <div className={`metric ${tone}`}>
      <Icon size={17} />
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function SectionTitle({ eyebrow, title, action }) {
  return (
    <div className="section-title">
      <div>
        {eyebrow && <span>{eyebrow}</span>}
        <h2>{title}</h2>
      </div>
      {action}
    </div>
  );
}

function Tag({ children, tone = "neutral" }) {
  return <span className={`tag ${tone}`}>{children}</span>;
}

function Progress({ value }) {
  return (
    <div className="progress">
      <span style={{ width: `${Math.round(value * 100)}%` }} />
      <em>{Math.round(value * 100)}%</em>
    </div>
  );
}

function priorityTone(priority) {
  if (priority === "critical" || priority === "high") return "danger";
  if (priority === "medium") return "warning";
  if (priority === "low") return "info";
  return "neutral";
}

function itemTypeLabel(type) {
  return {
    risk: "风险",
    approval: "审批",
    handoff: "交接",
    ai_review: "AI",
    picos_decision: "PICOS",
    quality_gate: "质量门",
    source_ready: "来源登记",
    data_health: "数据健康",
    eligibility_action: "入排待办",
  }[type] || type;
}

function compactLabel(value, maxLength = 42) {
  if (!value) return "";
  const text = String(value);
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
}

function safeSourceRefLabel(value, maxLength = 58) {
  if (!value) return "";
  const text = String(value)
    .replace(/\/Users\/[^\s；，,]+/gi, "本地来源已隐藏")
    .replace(/file:\/\/[^\s；，,]+/gi, "本地来源已隐藏")
    .replace(/\b(root_path|file_path|absolute_path|allowed_roots|content_hash|preview_hash|storage_key|server_path|source_record_id)\b/gi, "来源字段已隐藏");
  return compactLabel(text, maxLength);
}

function workItemObjectLabel(item) {
  return compactLabel(item.source_refs?.[0]?.label || item.target_id || item.source_id || item.item_id);
}

function sourceRefTypeLabel(type) {
  return {
    protocol_rule: "方案条款定位",
    listing_data_row: "原始数据 listing 行",
    evidence_span: "证据片段",
    rule: "规则ID",
  }[type] || type;
}

function conciseEditorBlockerReason(value) {
  const original = String(value || "").trim();
  if (!original) return "当前版本尚未满足冻结条件，请查看版本状态。";
  const withoutInternalPrefix = original
    .replace(/^writing document is unbound or stale for the current StudyDefinition:\s*/i, "")
    .trim();
  if (!withoutInternalPrefix || (!/[\u3400-\u9fff]/.test(withoutInternalPrefix) && /[A-Za-z]{4,}/.test(withoutInternalPrefix))) {
    return "当前文档与研究设计尚未完成一致性绑定。";
  }
  return compactLabel(withoutInternalPrefix, 72);
}

function OverviewPage({ projectId, dashboard, dashboardError, workbenchInbox, workbenchInboxError, setActivePage, setSelectedSubject, aiGatewayStatus, setAiGatewayStatus, aiRuns, aiRunsError, refreshWorkbenchInbox }) {
  const [actionError, setActionError] = useState("");
  if (dashboardError) {
    return (
      <main className="page" data-dashboard-state="unavailable">
        <SectionTitle eyebrow="项目总览" title="项目总览暂不可用" />
        <MonitoringReadUnavailable surface="dashboard" error={dashboardError} />
        <p className="inbox-boundary-note">当前未显示风险计数、模块进度或待审批数量；请在身份与读取动作恢复后重新读取。</p>
      </main>
    );
  }
  const dashboardReady = dashboard?.project?.project_id === projectId;
  if (!dashboardReady) {
    return (
      <main className="page" data-dashboard-state="pending">
        <SectionTitle eyebrow="项目总览" title="项目总览读取中" />
        <section className="panel monitoring-read-pending" role="status" aria-live="polite">
          <strong>正在读取当前项目总览</strong>
          <p>风险计数、模块进度和待审批数量尚未确认；当前不以初始化空值代替真实项目数据。</p>
        </section>
      </main>
    );
  }
  const modules = dashboard.modules || [];
  const riskCountValue = (severity) => {
    const value = dashboard.risk_counts_by_severity?.[severity];
    return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : "—";
  };
  const decisionItems = medicalDecisionItems(workbenchInbox);
  const openItem = async (item) => {
    setActionError("");
    if (item.unread) {
      try {
        const response = await fetch(`/api/projects/${projectId}/workbench-inbox/${encodeURIComponent(item.item_id)}/actions`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "mark_read", actor: "medical_manager", comment: "opened_from_overview", expected_source_version: item.source_version }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || `API ${response.status}`);
        if (data?.project_id !== projectId) {
          throw new Error("总览收件箱响应项目身份不匹配，未更新当前收件箱。");
        }
        refreshWorkbenchInbox?.(data);
      } catch (error) {
        setActionError(`总览收件箱动作失败：${error.message || "network"}`);
        refreshWorkbenchInbox?.();
        return;
      }
    }
    if (item.module === "medical_monitoring" && item.target_id) {
      setSelectedSubject?.(item.target_id);
    }
    setActivePage(item.target_page || moduleToPage[item.module] || "overview");
  };
  return (
    <main className="page">
      <SectionTitle
        eyebrow="项目全览"
        title={`统一工作收件箱 · ${decisionItems.length} 项待决策`}
        action={<button className="primary-button" disabled={!decisionItems.length} title={decisionItems.length ? "打开最高优先级医学决策项" : "当前无未读医学决策项"} onClick={() => decisionItems[0] && openItem(decisionItems[0])}>处理最高优先级</button>}
      />
      {actionError && <p className="gate-error overview-action-error" role="alert">{actionError}</p>}
      <section className="triage-panel workbench-inbox-panel">
        {workbenchInboxError ? (
          <MonitoringReadUnavailable surface="workbench_inbox" error={workbenchInboxError} compact />
        ) : (
          <>
            <div className="table-header inbox-cols">
              <span>优先级</span>
              <span>来源模块</span>
              <span>事项</span>
              <span>对象</span>
              <span>下一步</span>
              <span>状态</span>
            </div>
            {decisionItems.slice(0, 10).map((item) => (
              <button
                className={`table-row inbox-cols clickable ${item.unread ? "unread-row" : "read-row"}`}
                key={item.item_id}
                onClick={() => openItem(item)}
                title={item.boundary_note}
              >
                <span><Tag tone={priorityTone(item.priority)}>{severityLabel(item.priority)}</Tag></span>
                <span>{item.module_label}</span>
                <strong>
                  {item.unread && <em className="unread-dot" aria-label="未读" />}
                  {item.title}
                  <small>{item.summary}</small>
                </strong>
                <span title={item.source_refs?.[0]?.label || item.target_id || item.source_id}>{workItemObjectLabel(item)}</span>
                <span>{item.action_label}</span>
                <span><Tag tone={item.needs_action ? "warning" : "info"}>{item.status || itemTypeLabel(item.item_type)}</Tag></span>
              </button>
            ))}
            {!decisionItems.length && (
              <div className="empty-unread">
                当前无未读医学决策项。已处理内容及系统运行记录仍可在对应模块中查看。
              </div>
            )}
            <p className="inbox-scope-note">仅显示需要医学经理作出项目或内容判断的未读事项。</p>
          </>
        )}
      </section>
      <div className="overview-grid">
        <section className="panel">
            <SectionTitle title="模块状态矩阵" />
          <div className="module-list">
            {modules.map((module) => {
              const sourceOnly = module.implementation_status === "source_manifest_only";
              return (
              <button
                className={`module-row ${sourceOnly ? "module-row-source-only" : ""}`}
                key={module.module}
                disabled={sourceOnly}
                aria-disabled={sourceOnly}
                title={sourceOnly ? "仅来源登记，尚未开放该模块动作" : "打开模块"}
                onClick={() => setActivePage(moduleToPage[module.module] || "overview")}
              >
                <div>
                  <strong>{moduleLabels[module.module] || module.label}</strong>
                  <span>
                    {sourceOnly
                      ? "仅来源登记，等待结构解析与激活"
                      : `待决策 ${decisionItems.filter((item) => item.module === module.module).length}`}
                  </span>
                </div>
                <Progress value={module.completion_rate} />
                {sourceOnly ? <Tag tone="warning">未启用</Tag> : <ChevronRight size={16} />}
              </button>
              );
            })}
          </div>
        </section>
        <section className="panel">
          <SectionTitle title="项目风险摘要" />
          <div className="risk-severity-summary">
            {["critical", "high", "medium", "low"].map((severity) => (
              <button key={severity} onClick={() => setActivePage("monitoring")}>
                <Tag tone={priorityTone(severity)}>{severityLabel(severity)}</Tag>
                <strong>{riskCountValue(severity)}</strong>
                <span>开放风险</span>
              </button>
            ))}
          </div>
          <p className="inbox-boundary-note">中心×风险类型热力图仅在后端返回真实风险矩阵后展示；当前不使用固定示例值替代项目风险数据。</p>
        </section>
        <section className="panel">
          <SectionTitle title="独立 AI" />
          <AiGatewayPanel status={aiGatewayStatus} runs={aiRuns} onStatusChange={setAiGatewayStatus} />
          {aiRunsError && <MonitoringReadUnavailable surface="ai_runs" error={aiRunsError} compact />}
        </section>
      </div>
    </main>
  );
}

function AiGatewayPanel({ status, runs = [], onStatusChange, compact = false }) {
  const configured = status?.configured === true;
  const semanticAiReady = status?.semantic_ai_tasks_enabled === true;
  const gatewayReady = configured && semanticAiReady;
  const gatewayLabel = gatewayReady
    ? "可运行"
    : configured
      ? "已配置但不可运行"
      : "未配置";
  const providerLabel = status?.provider && status.provider !== "openai_compatible" ? status.provider : "兼容接口";
  const modelLabel = status?.model || "模型未配置";
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settings, setSettings] = useState(null);
  const [activeRoleId, setActiveRoleId] = useState("independent_ai");
  const [form, setForm] = useState(null);
  const [discoveredModels, setDiscoveredModels] = useState([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const roleScopedProfiles = (settings?.profiles || []).filter(
    (profile) => profile.profile_id === form?.profile_id || profile.profile_id.startsWith(`${activeRoleId}__`),
  );
  const visibleInventoryModels = (
    discoveredModels.filter((item) => /ocr|hy-mt/i.test(item)).length
      ? discoveredModels.filter((item) => /ocr|hy-mt/i.test(item))
      : discoveredModels.slice(0, 6)
  );

  const selectRole = (payload, roleId) => {
    const role = (payload?.roles || []).find((item) => item.role_id === roleId);
    if (!role) return;
    const profile = (payload?.profiles || []).find(
      (item) => item.profile_id === role.profile_id,
    );
    setActiveRoleId(roleId);
    setDiscoveredModels(role.available_models || []);
    setForm(profile ? {
      ...profile,
      role_id: roleId,
      role_model: role.model,
      thinking: role.thinking || "disabled",
      reasoning_effort: role.reasoning_effort || "low",
      api_key: "",
    } : {
      profile_id: "",
      provider: "",
      label: "",
      base_url: "",
      model: role.model,
      role_id: roleId,
      role_model: role.model,
      thinking: role.thinking || "disabled",
      reasoning_effort: role.reasoning_effort || "low",
      transport: "openai_compatible",
      deployment_profile: "local_private_clinical",
      expected_response_model: role.model,
      api_key_env: "",
      deployment_scope: "cloud",
      discovery_mode: "models_endpoint",
      enabled: true,
      api_key: "",
    });
  };

  const loadSettings = async () => {
    setBusy(true);
    setNotice("");
    try {
      const payload = await fetch("/api/ai-gateway/settings").then(readJsonOrThrow);
      setSettings(payload);
      selectRole(payload, activeRoleId);
      setSettingsOpen(true);
    } catch (error) {
      setNotice(error?.message || "无法读取 AI 角色配置。");
    } finally {
      setBusy(false);
    }
  };

  const choosePreset = (presetId) => {
    const preset = (settings?.presets || []).find((item) => item.preset_id === presetId);
    if (!preset) return;
    setForm((current) => ({
      ...(current || {}),
      profile_id: current?.provider === preset.provider && current.profile_id?.startsWith(`${activeRoleId}__`)
        ? current.profile_id
        : `${activeRoleId}__ui_${preset.provider}`,
      provider: preset.provider,
      label: preset.label,
      base_url: preset.base_url,
      model: preset.default_model,
      role_model: preset.default_model,
      transport: preset.transport,
      expected_response_model: preset.default_model,
      api_key_env: preset.api_key_env,
      deployment_scope: preset.deployment_scope,
      discovery_mode: preset.discovery_mode,
      enabled: true,
    }));
  };

  const chooseProfile = (profileId) => {
    const profile = (settings?.profiles || []).find((item) => item.profile_id === profileId);
    if (!profile) return;
    const role = (settings?.roles || []).find((item) => item.role_id === activeRoleId);
    setForm({
      ...profile,
      role_id: activeRoleId,
      role_model: profile.model,
      thinking: role?.thinking || "disabled",
      reasoning_effort: role?.reasoning_effort || "low",
      api_key: "",
    });
    setDiscoveredModels(role?.profile_id === profileId ? role.available_models || [] : []);
    setNotice("");
  };

  const saveRoleConfiguration = async () => {
    if (!form) return;
    setBusy(true);
    setNotice("正在保存连接与角色绑定…");
    try {
      const profilePayload = {
        profile_id: form.profile_id,
        provider: form.provider,
        label: form.label,
        base_url: form.base_url,
        model: form.role_model,
        transport: form.transport || "openai_compatible",
        deployment_profile: form.deployment_profile || "local_private_clinical",
        timeout_seconds: form.timeout_seconds || 300,
        expected_response_model: form.role_model,
        api_key_env: form.api_key_env || "",
        deployment_scope: form.deployment_scope || "cloud",
        discovery_mode: form.discovery_mode || "models_endpoint",
        enabled: form.enabled !== false,
        api_key: form.api_key || null,
        activate: activeRoleId === "independent_ai",
      };
      await fetch(`/api/ai-gateway/profiles/${encodeURIComponent(form.profile_id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(profilePayload),
      }).then(readJsonOrThrow);
      const saved = await fetch(`/api/ai-gateway/roles/${encodeURIComponent(activeRoleId)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          profile_id: form.profile_id,
          model: form.role_model,
          enabled: form.enabled !== false,
          thinking: form.thinking || "disabled",
          reasoning_effort: form.reasoning_effort || "low",
        }),
      }).then(readJsonOrThrow);
      setSettings(saved);
      selectRole(saved, activeRoleId);
      const role = (saved.roles || []).find((item) => item.role_id === activeRoleId);
      if (activeRoleId === "independent_ai") {
        const nextStatus = await fetch("/api/ai-gateway/status").then(readJsonOrThrow);
        onStatusChange?.(nextStatus);
      }
      setNotice(role?.ready
        ? `已保存：${role.label} · ${role.model}`
        : `已保存，但当前不可运行：${role?.blocked_reason || "连接或模型尚未就绪"}`);
    } catch (error) {
      setNotice(error?.message || "角色配置保存失败。");
    } finally {
      setBusy(false);
    }
  };

  const discoverAvailableModels = async () => {
    if (!form) return;
    setBusy(true);
    setNotice("正在读取模型列表…");
    try {
      const result = await fetch("/api/ai-gateway/discover-models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          profile_id: form.profile_id,
          model: form.role_model,
        }),
      }).then(readJsonOrThrow);
      setDiscoveredModels(result.models || []);
      setNotice(result.models?.length
        ? `已发现 ${result.models.length} 个模型；当前角色模型${result.configured_model_present ? "已存在" : "不在目录中"}。`
        : "该 Provider 使用官方目录加合成探针，不提供动态模型列表。");
    } catch (error) {
      setNotice(error?.message || "模型发现失败。请先保存当前连接。");
    } finally {
      setBusy(false);
    }
  };

  const probeOcrVisualCapability = async () => {
    if (!form || activeRoleId !== "ocr") return;
    setBusy(true);
    setNotice("正在发送真实图像并验证文字识别能力…");
    try {
      const result = await fetch("/api/ai-gateway/roles/ocr/probe-visual", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          profile_id: form.profile_id,
          model: form.role_model,
        }),
      }).then(readJsonOrThrow);
      setSettings(result);
      selectRole(result, "ocr");
      setNotice(`视觉能力验证通过：${result.visual_probe?.model || form.role_model}`);
    } catch (error) {
      setNotice(error?.message || "视觉能力验证失败。");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`ai-gateway-card ${compact ? "ai-gateway-card-compact" : ""}`}>
      <div className="ai-gateway-header">
        <div>
          <Tag tone={gatewayReady ? "success" : "warning"}>{gatewayLabel}</Tag>
          <span>{compact ? `AI 设置 · ${providerLabel} · ${modelLabel}` : `${providerLabel} · ${modelLabel}`}</span>
        </div>
        <button className="icon-button" type="button" onClick={loadSettings} title="配置全系统 AI 角色" disabled={busy}>
          <Settings2 size={17} />
        </button>
      </div>
      {(status?.missing_env?.length > 0 || (configured && !semanticAiReady)) && (
        <p className="ai-gateway-warning">
          {configured && !semanticAiReady
            ? status?.disabled_reason || "独立AI已配置，但未满足批准部署边界；医学监查语义任务保持阻断。"
            : "连接不可用；请在设置中检查当前 AI 角色。"}
        </p>
      )}
      {settingsOpen && form && (
        <div className="ai-settings-backdrop" role="dialog" aria-modal="true" aria-label="全系统 AI 角色配置">
          <div className="ai-settings-dialog">
            <header>
              <div>
                <strong>全系统 AI 角色</strong>
                <span>连接保存凭据；角色决定具体流程使用哪个连接与模型。</span>
              </div>
              <button className="icon-button" type="button" onClick={() => setSettingsOpen(false)} title="关闭">
                <XCircle size={18} />
              </button>
            </header>
            <div className="ai-role-settings-layout">
              <nav className="ai-role-nav" aria-label="AI 角色">
                {(settings?.roles || []).map((role) => (
                  <button
                    type="button"
                    key={role.role_id}
                    className={role.role_id === activeRoleId ? "is-active" : ""}
                    onClick={() => {
                      setNotice("");
                      selectRole(settings, role.role_id);
                    }}
                  >
                    <span>{role.label}</span>
                    <small>{role.ready ? "可用" : role.blocked_reason || "待配置"}</small>
                  </button>
                ))}
              </nav>
              <div className="ai-role-editor">
                {(() => {
                  const role = (settings?.roles || []).find((item) => item.role_id === activeRoleId);
                  return (
                    <>
                      <div className="ai-role-editor-heading">
                        <div>
                          <strong>{role?.label}</strong>
                          <span>{role?.description}</span>
                        </div>
                        <Tag tone={role?.ready ? "success" : "warning"}>
                          {role?.ready ? "当前可用" : "当前受阻"}
                        </Tag>
                      </div>
                      {role?.blocked_reason && (
                        <p className="ai-role-blocker">{role.blocked_reason}</p>
                      )}
                      {role?.warning && <p className="ai-role-warning">{role.warning}</p>}
                      {role?.recommendation && <p className="ai-role-recommendation">{role.recommendation}</p>}
                      <div className="ai-settings-grid">
                        <label className="wide">
                          <span>已有连接</span>
                          <select value={form.profile_id || ""} onChange={(event) => chooseProfile(event.target.value)}>
                            {roleScopedProfiles.map((profile) => (
                              <option key={profile.profile_id} value={profile.profile_id}>
                                {profile.label} · {profile.provider}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label>
                          <span>Provider 模板</span>
                          <select
                            value={(settings?.presets || []).find((item) => item.provider === form.provider)?.preset_id || "openai_compatible"}
                            onChange={(event) => choosePreset(event.target.value)}
                          >
                            {(settings?.presets || []).map((preset) => (
                              <option key={preset.preset_id} value={preset.preset_id}>{preset.label}</option>
                            ))}
                          </select>
                        </label>
                        <label>
                          <span>角色模型</span>
                          <input
                            list={`ai-model-options-${activeRoleId}`}
                            value={form.role_model || ""}
                            onChange={(event) => setForm({ ...form, role_model: event.target.value })}
                          />
                          <datalist id={`ai-model-options-${activeRoleId}`}>
                            {discoveredModels.map((model) => <option key={model} value={model} />)}
                          </datalist>
                          {visibleInventoryModels.length > 0 && (
                            <small className="ai-model-inventory">
                              当前目录：{visibleInventoryModels.join("、")}
                            </small>
                          )}
                          {role?.capability_status === "blocked_unverified_visual" && (
                            <small className="ai-role-blocker">{role.capability_reason}</small>
                          )}
                        </label>
                        {role?.thinking_configurable && (
                          <>
                            <label>
                              <span>思考模式</span>
                              <select
                                value={form.thinking || "disabled"}
                                onChange={(event) => setForm({ ...form, thinking: event.target.value })}
                              >
                                <option value="disabled">关闭思考</option>
                                <option value="enabled">开启思考</option>
                              </select>
                              <small>仅控制当前角色的模型请求；不会改变 OCR 或正文翻译的专用 transport。</small>
                            </label>
                            <label>
                              <span>思考强度</span>
                              <select
                                value={form.reasoning_effort || "low"}
                                onChange={(event) => setForm({ ...form, reasoning_effort: event.target.value })}
                              >
                                {(role.reasoning_efforts || ["low"]).map((level) => (
                                  <option key={level} value={level}>
                                {{ low: "低", medium: "中", high: "高", xhigh: "极高", max: "最大" }[level] || level}
                                  </option>
                                ))}
                              </select>
                            </label>
                          </>
                        )}
                        <label className="wide">
                          <span>Base URL</span>
                          <input
                            value={form.base_url || ""}
                            placeholder={form.transport === "paddle_async_job"
                              ? "https://paddleocr.aistudio-app.com"
                              : "https://provider.example.com/v1"}
                            onChange={(event) => setForm({ ...form, base_url: event.target.value })}
                          />
                          <small>
                            {form.transport === "paddle_async_job"
                              ? "PaddleOCR 使用官方异步 Job API 地址；其他连接填写 OpenAI 兼容格式的 API Base URL。"
                              : "填写 OpenAI 兼容格式的 API Base URL。"}
                          </small>
                        </label>
                        <label className="wide">
                          <span>API Key</span>
                          <input
                            type="password"
                            value={form.api_key || ""}
                            placeholder={form.api_key_configured ? "已保存；留空则保持不变" : "输入后仅写入本机凭据存储"}
                            onChange={(event) => setForm({ ...form, api_key: event.target.value })}
                            autoComplete="new-password"
                          />
                        </label>
                      </div>
                    </>
                  );
                })()}
              </div>
            </div>
            <p className="ai-settings-boundary">
              四类角色分别保存连接、Base URL、模型和本地凭据；oMLX 仅负责 OCR/翻译工作负载租约与并发限制。非专用 OCR 模型在真实视觉探针接入前保持不可用。
            </p>
            {notice && <p className="ai-settings-notice">{notice}</p>}
            <footer>
              {activeRoleId === "ocr" && form?.transport !== "paddle_async_job" && (
                <button
                  type="button"
                  className="secondary-button"
                  onClick={probeOcrVisualCapability}
                  disabled={busy || !form.role_model || !form.profile_id}
                  title="使用真实 PNG 校验所选模型的视觉文字识别能力"
                >
                  <ScanSearch size={15} /> 验证视觉能力
                </button>
              )}
              <button
                type="button"
                className="secondary-button"
                onClick={discoverAvailableModels}
                disabled={busy}
                title={busy ? "请等待当前配置操作完成" : "读取所选连接公开的模型目录"}
              >
                <RefreshCw size={15} /> 发现模型
              </button>
              <button
                type="button"
                className="primary-button"
                onClick={saveRoleConfiguration}
                disabled={busy || !form.role_model || !form.base_url || !form.profile_id}
                title={
                  busy
                    ? "请等待当前配置操作完成"
                    : !form.profile_id || !form.base_url
                      ? "请先选择连接并填写 Base URL"
                    : !form.role_model
                        ? "请先填写角色模型"
                        : "保存连接、凭据和当前角色绑定"
                }
              >
                <CheckCircle2 size={15} /> 保存角色配置
              </button>
            </footer>
          </div>
        </div>
      )}
    </div>
  );
}

function SourceHealthList({ items, onOpen }) {
  if (!items.length) {
    return <p className="quiet-text">暂无来源或数据健康告警。</p>;
  }
  return (
    <div className="source-health-list">
      {items.map((item) => (
        <button className="source-health-row" key={item.item_id} onClick={() => onOpen(item)} title={item.boundary_note}>
          <span><Tag tone={item.item_type === "data_health" ? "warning" : "info"}>{item.status}</Tag></span>
          <strong>{item.title}</strong>
          <small>{item.module_label} · {item.action_label}</small>
        </button>
      ))}
    </div>
  );
}

function HandoffList({ items, onOpen }) {
  if (!items.length) {
    return <p className="quiet-text">暂无跨模块交接候选。TFL写作引用候选、安全/PV确认候选和PICOS写作候选会在这里汇总。</p>;
  }
  return (
    <div className="handoff-list">
      {items.map((item) => (
        <button className="handoff-row" key={item.item_id} onClick={() => onOpen(item)} title={item.boundary_note}>
          <span><Tag tone={priorityTone(item.priority)}>{item.module_label}</Tag></span>
          <strong>{item.title}</strong>
          <small>{item.summary}</small>
        </button>
      ))}
    </div>
  );
}

function TaskList({ items, onOpen }) {
  if (!items.length) {
    return <p className="quiet-text">当前无待我处理项。</p>;
  }
  return (
    <div className="task-list">
      {items.map((item) => (
        <button className="task-row" key={item.item_id} onClick={() => onOpen(item)}>
          <span><Tag tone={priorityTone(item.priority)}>{severityLabel(item.priority)}</Tag></span>
          <strong>{item.title}</strong>
          <span>{item.module_label}</span>
          <span>{item.status}</span>
        </button>
      ))}
    </div>
  );
}

const riskBatchDeltaLabels = {
  baseline: "基线批次",
  new: "新增",
  changed: "变化",
  persisting: "持续",
  resolved_by_data: "数据解除",
  superseded_by_engine: "已由事件级风险替代",
  reopened: "重开",
  requires_rereview: "需重审",
  unclassified: "本批次",
};

async function fetchCompleteMonitoringRiskIndex(
  projectId,
  { safetyPvOnly = false, expectedProjectId = projectId } = {},
) {
  const api = createMedicalMonitoringApi();
  const pageSize = 200;
  const requireProjectIdentity = (payload) => {
    if (payload?.project_id !== expectedProjectId) {
      throw new Error("安全性风险响应项目身份不匹配。");
    }
    return payload;
  };
  const riskPage = (page, snapshotId = "") => api.getRiskSnapshot(projectId, {
    snapshotId,
    page,
    pageSize,
    sortBy: "updated_at",
    sortDirection: "desc",
  }).then(requireProjectIdentity);
  const [moduleSummary, first] = await Promise.all([
    api.getModuleSummary(projectId).then(requireProjectIdentity),
    riskPage(1),
  ]);
  const pageCount = Math.ceil((first.total || 0) / pageSize);
  const remainingPages = pageCount <= 1 ? [] : await Promise.all(
    Array.from({ length: pageCount - 1 }, (_, index) => index + 2).map((page) => (
      riskPage(page, first.snapshot_id)
    )),
  );
  const items = [first, ...remainingPages]
    .flatMap((payload) => payload.items || [])
    .filter((risk) => !safetyPvOnly || risk.safety_pv_flag === true);
  if (items.length !== first.total) {
    if (!safetyPvOnly) {
      throw new Error(`风险分页不完整：预期 ${first.total} 条，实际 ${items.length} 条。`);
    }
  }
  return {
    ...first,
    module_summary: moduleSummary,
    items,
    total: items.length,
  };
}

function monitoringRiskQueryErrorText(error) {
  const code = error?.detail?.detail?.code || error?.detail?.code || "";
  if (error?.status === 409 && code === "medical_monitoring_snapshot_not_found") {
    return "该风险快照已不可用。请切换到最新快照后继续。";
  }
  if (error?.status === 422) {
    return "当前筛选或排序条件无效，请清除相关条件后重试。";
  }
  return `项目风险读取失败：${apiErrorText(error)}`;
}

function activePageFromMonitoringRoute(routeState) {
  if (routeState?.view === "timeline") return "subjectTimeline";
  if (routeState?.view === "profile") return "patientProfile";
  return "monitoring";
}

function monitoringViewFromActivePage(activePage, fallback = "checklist") {
  if (activePage === "subjectTimeline") return "timeline";
  if (activePage === "patientProfile") return "profile";
  if (activePage === "monitoring") return "checklist";
  return "";
}

function initialMonitoringBrowserState() {
  if (typeof window === "undefined" || window.location.pathname !== "/monitoring") {
    return {};
  }
  return parseMedicalMonitoringRouteState(window.location.search);
}

function MonitoringPage({
  monitoringProjectId,
  sourceManifest,
  selectedSubject,
  setSelectedSubject,
  subjectProfile,
  subjectCatalog = [],
  setActivePage,
  onOpenSubjectView,
  refreshDashboard,
  workbenchInbox,
  refreshWorkbenchInbox,
  initialRiskId = "",
  initialRiskView = "checklist",
  initialEvidenceTab = "disposition",
  initialRiskScope = "trial",
  initialRiskSiteId = "",
  initialRiskScrollTop = "",
  initialChecklistQuery = DEFAULT_RISK_CHECKLIST_QUERY,
  onRiskScopeChange,
  onRiskFocusChange,
  onRiskFocusClear,
  onEvidenceTabChange,
  onChecklistQueryChange,
  onRiskScrollTopChange,
  onInitialRiskConsumed,
  monitoringDataError = "",
  subjectRouteError = "",
  aiGatewayStatus = null,
}) {
  const [selectedRiskId, setSelectedRiskId] = useState("");
  const [uploadGateOpen, setUploadGateOpen] = useState(false);
  const [riskActionLoading, setRiskActionLoading] = useState(false);
  const [riskActionMessage, setRiskActionMessage] = useState("");
  const [rawMonitoring, setRawMonitoring] = useState(null);
  const [rawMonitoringLoading, setRawMonitoringLoading] = useState(false);
  const [rawMonitoringError, setRawMonitoringError] = useState("");
  const [riskIndex, setRiskIndex] = useState(null);
  const [riskIndexLoading, setRiskIndexLoading] = useState(false);
  const [riskIndexError, setRiskIndexError] = useState("");
  const [riskIndexReloadNonce, setRiskIndexReloadNonce] = useState(0);
  const riskIndexControllerRef = useRef(null);
  const [riskExportLoading, setRiskExportLoading] = useState(false);
  const [assuranceOpen, setAssuranceOpen] = useState(false);
  const [riskTaxonomy, setRiskTaxonomy] = useState(null);
  const [focusedRiskRow, setFocusedRiskRow] = useState(null);
  const [riskQuery, setRiskQuery] = useState(() => normalizeRiskChecklistQuery(initialChecklistQuery));
  const [riskScope, setRiskScope] = useState(initialRiskScope || "trial");
  const [riskDockOpen, setRiskDockOpen] = useState(false);
  const [riskFocusMessage, setRiskFocusMessage] = useState("");
  const initialChecklistSignature = riskChecklistQuerySignature(initialChecklistQuery);
  const monitoringBinding = sourceManifest?.route_bindings?.medical_monitoring;
  const monitoringReadiness = monitoringSourceReadiness(monitoringBinding);
  const monitoringExecutionReady = monitoringReadiness.canRead === true;
  const expectedMonitoringProjectId = sourceManifest?.project_id || monitoringProjectId;
  const monitoringBatchDisplay = monitoringBinding?.display_batch?.extract_date
    || monitoringBinding?.display_batch?.batch_label
    || "";
  const rawMonitoringUnavailable = Boolean(rawMonitoringError);
  const monitoringAiStatus = monitoringAiReadiness(
    rawMonitoring?.ai_gateway_status || aiGatewayStatus || {},
  );
  const unclassifiedMonitoringSheets = Array.isArray(rawMonitoring?.unclassified_sheet_names)
    ? rawMonitoring.unclassified_sheet_names.filter((sheetName) => String(sheetName || "").trim())
    : [];
  const realInboxRiskRows = useMemo(
    () => monitoringRiskRowsFromInbox(workbenchInbox, monitoringBatchDisplay),
    [workbenchInbox, monitoringBatchDisplay],
  );
  const indexedActionRows = useMemo(
    () => monitoringRiskRowsFromInbox({ items: riskIndex?.work_items || [] }, monitoringBatchDisplay),
    [riskIndex?.work_items, monitoringBatchDisplay],
  );
  const indexedRiskRows = useMemo(
    () => riskIndexRowsFromApi(riskIndex, [...indexedActionRows, ...realInboxRiskRows]),
    [riskIndex, realInboxRiskRows, indexedActionRows],
  );
  const visibleRiskRows = indexedRiskRows;
  const monitoringSourceHeader = sourceManifest?.header_project;
  const monitoringSourceLabel = monitoringSourceHeader
    ? `${monitoringSourceHeader.project_code} ${monitoringSourceHeader.indication}`
    : monitoringProjectId;
  const initialRiskResolution = resolveMedicalMonitoringRiskRoute(
    initialRiskId,
    visibleRiskRows,
    focusedRiskRow ? [focusedRiskRow] : [],
  );
  const initialRiskMatch = initialRiskResolution.status === "matched"
    ? initialRiskResolution.risk
    : null;
  const selectedRisk = initialRiskMatch
    || visibleRiskRows.find((risk) => risk.id === selectedRiskId)
    || null;
  const subject = selectedRisk
    ? buildSubjectView(subjectProfile, selectedSubject, selectedRisk, subjectCatalog)
    : null;
  const riskScopeSiteId = initialRiskSiteId || "";
  const constrainedRiskSiteId = riskScope === "site" ? riskScopeSiteId : "";
  const constrainedRiskSubjectId = riskScope === "subject" ? selectedSubject : "";
  const siteRiskRollups = Array.isArray(riskIndex?.rollup?.sites) ? riskIndex.rollup.sites : [];
  const subjectRiskRollups = Array.isArray(riskIndex?.rollup?.subjects) ? riskIndex.rollup.subjects : [];
  const siteScopeResolution = resolveMedicalMonitoringSiteRoute(
    riskScope === "site" ? riskScopeSiteId : "",
    subjectCatalog,
    siteRiskRollups,
  );
  const scopedRiskRollup = riskScope === "site"
    ? siteRiskRollups.find((item) => item?.scope_id === constrainedRiskSiteId)
    : riskScope === "subject"
      ? subjectRiskRollups.find((item) => item?.scope_id === constrainedRiskSubjectId)
      : riskIndex?.rollup?.trial;
  const openRiskCount = riskIndex
    ? scopedRiskRollup?.needs_action_count
      ?? visibleRiskRows.filter((risk) => risk.needsAction).length
    : null;
  const riskReadUnavailable = Boolean(riskIndexError);
  const riskDataPending = !riskIndex && !riskIndexError;
  const riskCountDisplay = riskReadUnavailable || riskDataPending
    ? "—"
    : riskIndex?.total ?? "—";
  const riskOpenCountDisplay = riskReadUnavailable || riskDataPending
    ? "—"
    : openRiskCount ?? "—";
  const riskSubjectsDisplay = riskReadUnavailable
    ? "—"
    : riskIndex?.subjects_evaluated ?? rawMonitoring?.listing?.subject_count ?? "-";
  const riskScopeConstraints = {
    scope: riskScope,
    siteId: constrainedRiskSiteId,
    subjectId: constrainedRiskSubjectId,
  };
  useMedicalMonitoringScrollRestoration({
    enabled: monitoringExecutionReady,
    scrollTop: initialRiskScrollTop,
    restoreKey: [
      monitoringProjectId,
      riskScope,
      constrainedRiskSiteId,
      constrainedRiskSubjectId,
      riskChecklistQuerySignature(riskQuery),
    ].join("|"),
    onScrollTopChange: onRiskScrollTopChange,
  });
  useEffect(() => {
    if (selectedRisk?.id && selectedRisk.id !== selectedRiskId) {
      setSelectedRiskId(selectedRisk.id);
    }
  }, [selectedRisk?.id, selectedRiskId]);
  useEffect(() => {
    setRiskScope(initialRiskScope || "trial");
  }, [initialRiskScope]);
  useEffect(() => {
    const next = normalizeRiskChecklistQuery(initialChecklistQuery);
    setRiskQuery((current) => (
      riskChecklistQuerySignature(current) === riskChecklistQuerySignature(next)
        ? current
        : next
    ));
  }, [initialChecklistSignature]);
  useEffect(() => {
    if (!initialRiskId) {
      setRiskFocusMessage("");
      return;
    }
    const focusedRisk = initialRiskMatch;
    if (!focusedRisk) return;
    setRiskFocusMessage("");
    setSelectedRiskId(focusedRisk.id);
    setRiskDockOpen(true);
    if (focusedRisk.subject && focusedRisk.subject !== "-") setSelectedSubject(focusedRisk.subject);
    onInitialRiskConsumed?.();
  }, [initialRiskId, initialRiskMatch, setSelectedSubject, onInitialRiskConsumed]);
  useEffect(() => {
    if (!monitoringExecutionReady) {
      setRiskIndex(null);
      setRiskTaxonomy(null);
      setRiskIndexError("");
      setRiskIndexLoading(false);
      return undefined;
    }
    const controller = new AbortController();
    let active = true;
    riskIndexControllerRef.current = controller;
    setRiskIndexLoading(true);
    setRiskIndexError("");
    const api = createMedicalMonitoringApi();
    api.getRiskSnapshot(
      monitoringProjectId,
      {
        ...riskChecklistApiQuery(riskQuery, riskScopeConstraints),
        signal: controller.signal,
      },
    )
      .then((data) => {
        if (!active) return;
        if (data?.project_id !== expectedMonitoringProjectId) {
          setRiskIndex(null);
          setRiskTaxonomy(null);
          setRiskIndexError("风险快照响应项目身份不匹配，已阻止写入当前监查视图。");
          return;
        }
        setRiskIndex(data);
        if (data.taxonomy) setRiskTaxonomy(data.taxonomy);
        if (data.snapshot_id && data.snapshot_id !== riskQuery.snapshotId) {
          const pinnedQuery = normalizeRiskChecklistQuery({
            ...riskQuery,
            snapshotId: data.snapshot_id,
          });
          setRiskQuery(pinnedQuery);
          onChecklistQueryChange?.(pinnedQuery);
        }
      })
      .catch((error) => {
        if (active && error.name !== "AbortError") {
          setRiskIndex(null);
          setRiskIndexError(monitoringRiskQueryErrorText(error));
        }
      })
      .finally(() => {
        if (riskIndexControllerRef.current === controller) {
          riskIndexControllerRef.current = null;
        }
        if (active) setRiskIndexLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
      if (riskIndexControllerRef.current === controller) {
        riskIndexControllerRef.current = null;
      }
    };
  }, [
    monitoringProjectId,
    riskChecklistQuerySignature(riskQuery),
    riskScope,
    constrainedRiskSiteId,
    constrainedRiskSubjectId,
    expectedMonitoringProjectId,
    monitoringExecutionReady,
    riskIndexReloadNonce,
  ]);
  useEffect(() => {
    if (!monitoringExecutionReady) {
      setRiskTaxonomy(null);
      return undefined;
    }
    const controller = new AbortController();
    createMedicalMonitoringApi().getRiskTaxonomy(
      monitoringProjectId,
      { signal: controller.signal },
    )
      .then((data) => {
        if (data?.project_id !== expectedMonitoringProjectId) {
          setRiskTaxonomy(null);
          setRiskIndexError("风险分类响应项目身份不匹配，已阻止写入当前监查视图。");
          return;
        }
        setRiskTaxonomy(data);
      })
      .catch((error) => {
        if (error.name !== "AbortError") {
          setRiskTaxonomy(null);
          setRiskIndexError(`风险分类读取失败：${monitoringRiskQueryErrorText(error)}`);
        }
      });
    return () => controller.abort();
  }, [monitoringProjectId, expectedMonitoringProjectId, monitoringExecutionReady]);
  useEffect(() => {
    if (!monitoringExecutionReady || !initialRiskId || initialRiskMatch || !monitoringProjectId) {
      if (!initialRiskId) {
        setFocusedRiskRow(null);
        setRiskFocusMessage("");
      } else if (initialRiskMatch) {
        setRiskFocusMessage("");
      }
      return undefined;
    }
    const controller = new AbortController();
    setRiskFocusMessage("");
    createMedicalMonitoringApi().getRiskSnapshot(monitoringProjectId, {
      riskInstanceId: initialRiskId,
      page: 1,
      pageSize: 1,
      signal: controller.signal,
    })
      .then((payload) => {
        if (payload?.project_id !== expectedMonitoringProjectId) {
          setFocusedRiskRow(null);
          setRiskIndexError("风险定位响应项目身份不匹配，已阻止写入当前监查视图。");
          return;
        }
        const row = riskIndexRowsFromApi(payload, realInboxRiskRows)[0] || null;
        setFocusedRiskRow(row);
        setRiskFocusMessage(
          row
            ? ""
            : `链接中的风险“${initialRiskId}”未在当前项目的风险快照中找到；系统未自动打开其他风险。请确认风险实例、数据批次或风险快照。`,
        );
      })
      .catch((error) => {
        if (error.name !== "AbortError") {
          setFocusedRiskRow(null);
          setRiskFocusMessage("");
          setRiskIndexError(`风险定位读取失败：${monitoringRiskQueryErrorText(error)}`);
        }
      });
    return () => controller.abort();
  }, [initialRiskId, initialRiskMatch, monitoringProjectId, expectedMonitoringProjectId, realInboxRiskRows, monitoringExecutionReady]);
  const applyRiskChecklistQuery = (nextQuery) => {
    const normalized = normalizeRiskChecklistQuery(nextQuery);
    setRiskQuery(normalized);
    onChecklistQueryChange?.(normalized);
  };
  const closeRiskEvidenceDock = () => {
    setRiskDockOpen(false);
    setSelectedRiskId("");
    setFocusedRiskRow(null);
    onRiskFocusClear?.();
  };
  const retryRiskIndex = useCallback(() => {
    setRiskIndexReloadNonce((current) => current + 1);
  }, []);
  const cancelRiskIndexLoad = useCallback(() => {
    const controller = riskIndexControllerRef.current;
    if (!controller) return;
    controller.abort();
    riskIndexControllerRef.current = null;
    setRiskIndexLoading(false);
    setRiskIndexError("风险快照读取已取消；当前页面保留上一份结果，可点击“重试读取”继续。");
  }, []);
  const toggleBatchWorkspace = () => {
    if (uploadGateOpen) {
      setUploadGateOpen(false);
      return;
    }
    if (riskDockOpen) closeRiskEvidenceDock();
    setUploadGateOpen(true);
  };
  const toggleAssuranceWorkspace = () => {
    if (assuranceOpen) {
      setAssuranceOpen(false);
      return;
    }
    if (riskDockOpen) closeRiskEvidenceDock();
    setUploadGateOpen(false);
    setAssuranceOpen(true);
  };
  const refreshCurrentRiskSnapshot = () => {
    applyRiskChecklistQuery(resetRiskChecklistForQueryChange(riskQuery, {}));
  };
  const exportCurrentRiskSnapshot = async () => {
    setRiskExportLoading(true);
    setRiskIndexError("");
    try {
      const result = await createMedicalMonitoringApi().exportRiskSnapshot(
        monitoringProjectId,
        riskChecklistApiQuery(riskQuery, riskScopeConstraints),
      );
      const downloadUrl = URL.createObjectURL(result.blob);
      const anchor = document.createElement("a");
      anchor.href = downloadUrl;
      anchor.download = result.filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 0);
    } catch (error) {
      setRiskIndexError(`风险及证据导出失败：${apiErrorText(error)}`);
    } finally {
      setRiskExportLoading(false);
    }
  };
  useEffect(() => {
    if (!monitoringExecutionReady) {
      setRawMonitoring(null);
      setRawMonitoringLoading(false);
      setRawMonitoringError("");
      return undefined;
    }
    let cancelled = false;
    setRawMonitoring(null);
    setRawMonitoringLoading(true);
    setRawMonitoringError("");
    fetch(`/api/projects/${monitoringProjectId}/monitoring/raw-intake`)
      .then((response) => readJsonOrThrow(response))
      .then((data) => {
        if (cancelled) return;
        if (data?.project_id !== expectedMonitoringProjectId) {
          setRawMonitoring(null);
          setRawMonitoringError("原始监查响应项目身份不匹配，已阻止写入当前项目数据。");
          return;
        }
        setRawMonitoring(data);
      })
      .catch((error) => {
        if (!cancelled) {
          setRawMonitoring(null);
          const info = monitoringReadErrorInfo(error, "monitoring_raw");
          setRawMonitoringError(`${info.title}：${info.message}（${info.technical}）`);
        }
      })
      .finally(() => {
        if (!cancelled) setRawMonitoringLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [monitoringProjectId, expectedMonitoringProjectId, monitoringExecutionReady]);
  const markRiskRead = async (risk) => {
    if (!risk?.inboxItemId) {
      setRiskActionMessage("当前风险来自本次上传规则结果，进入收件箱后才能写入已读审计。");
      return;
    }
    setRiskActionLoading(true);
    setRiskActionMessage("");
    try {
      const response = await fetch(`/api/projects/${monitoringProjectId}/workbench-inbox/${encodeURIComponent(risk.inboxItemId)}/actions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "mark_read", comment: "opened_from_monitoring_detail", expected_source_version: risk.sourceVersion }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || `API ${response.status}`);
      if (payload?.project_id !== expectedMonitoringProjectId) {
        throw new Error("已读动作响应项目身份不匹配，未更新当前收件箱。");
      }
      refreshWorkbenchInbox?.(payload);
      refreshCurrentRiskSnapshot();
      setRiskActionMessage("已标记已读并写入收件箱审计。");
    } catch (error) {
      setRiskActionMessage(`已读动作失败：${error.message}`);
    } finally {
      setRiskActionLoading(false);
    }
  };
  const applyRiskDisposition = async (risk, action, payload = {}) => {
    if (!risk?.inboxItemId) {
      setRiskActionMessage("当前风险来自本次上传规则结果，进入收件箱后才能写入医学处置审计。");
      return;
    }
    setRiskActionLoading(true);
    setRiskActionMessage("");
    try {
      const response = await fetch(`/api/projects/${monitoringProjectId}/workbench-inbox/${encodeURIComponent(risk.inboxItemId)}/risk-disposition`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action,
          disposition_kind: payload.disposition_kind || null,
          comment: payload.comment || "",
          query_draft_text: payload.query_draft_text || "",
          expected_source_version: payload.expected_source_version || risk.sourceVersion,
          medical_judgments: payload.medical_judgments || null,
          expected_disposition_state: payload.expected_disposition_state || "",
          basis_disposition_record_id: payload.basis_disposition_record_id || "",
          reassessment_change_reason: payload.reassessment_change_reason || "",
        }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || `API ${response.status}`);
      if (result?.project_id !== expectedMonitoringProjectId) {
        throw new Error("医学处置响应项目身份不匹配，未更新当前风险状态。");
      }
      refreshWorkbenchInbox?.(result);
      refreshCurrentRiskSnapshot();
      if (action === "submitted_for_approval") refreshDashboard?.();
      const reviewedMessage = payload.disposition_kind && payload.disposition_kind !== "center_query"
        ? `${terminalDispositionLabels[payload.disposition_kind] || "医学处置已完成"}，已保留来源版本、医学判断和处置审计。`
        : "已记录医学复核，风险仍保留在医学监查闭环中。";
      setRiskActionMessage({
        reviewed: reviewedMessage,
        query_draft: "已记录Query草稿，尚未执行对外动作或归档动作。",
        submitted_for_approval: "已提交项目内部审批；尚未记录对外发送或归档动作。",
        reopen: "风险已重新打开，原处置保留在历史中并进入新一轮医学复核。",
      }[action] || "医学处置已写入审计。");
    } catch (error) {
      setRiskActionMessage(`医学处置失败：${error.message}`);
    } finally {
      setRiskActionLoading(false);
    }
  };
  if (!monitoringExecutionReady) {
    const sourceHeader = sourceManifest?.header_project || {};
    return (
      <main className="page monitoring-page monitoring-source-only" data-monitoring-state={monitoringReadiness.kind}>
        <SectionTitle
          eyebrow="医学监查"
          title={monitoringReadiness.kind === "source_only" ? "来源已登记，尚未启用医学监查" : "医学监查来源状态待确认"}
          action={<button type="button" onClick={() => setActivePage("overview")}>返回项目总览</button>}
        />
        <section className="panel monitoring-source-only-panel" aria-live="polite">
          <div className="monitoring-project-identity">
            <Database size={18} />
            <div>
              <span>{sourceHeader.project_code || monitoringProjectId}</span>
              <strong>{sourceHeader.indication || "当前项目"}</strong>
            </div>
            <Tag tone="warning">{monitoringReadiness.label}</Tag>
          </div>
          <p className="inbox-boundary-note">{monitoringReadiness.message}</p>
          <ul className="monitoring-source-only-list">
            <li>已登记来源只用于后续结构核对，不代表已生成风险、受试者或中心结论。</li>
            <li>完成 listing 结构解析、方案语义核对、独立 AI 与医学监查适配器确认后，才会开放批次、风险和医学处置动作。</li>
            <li>当前不会读取或写入受试者数据、运行规则或提交 AI 任务。</li>
          </ul>
        </section>
      </main>
    );
  }
  return (
    <main className="page monitoring-page">
      <SectionTitle
        eyebrow="医学监查"
        title="原始数据批次驱动的风险复核"
        action={<div className="monitoring-head-actions">
          <button type="button" title="打开锁库前与核查前保障工作区" onClick={toggleAssuranceWorkspace}><ClipboardCheck size={16} /> 锁库 / 核查工作区</button>
          <button type="button" className="primary-button" title="上传新的data listing批次" onClick={toggleBatchWorkspace}><Upload size={16} /> 上传新批次</button>
        </div>}
      />
      {monitoringDataError && (
        <p className="gate-error monitoring-data-identity-error" role="alert">
          {monitoringDataError}
        </p>
      )}
      {subjectRouteError && (
        <section className="monitoring-structure-warning" role="alert" aria-label="受试者深链未找到">
          <AlertTriangle size={17} aria-hidden="true" />
          <div>
            <strong>受试者深链未在当前项目中找到</strong>
            <span>{subjectRouteError} 系统未自动替换为其他受试者。</span>
            <button
              type="button"
              className="monitoring-structure-warning-action"
              onClick={() => onRiskScopeChange?.("trial", {})}
            >
              返回试验范围并重新选择
            </button>
          </div>
        </section>
      )}
      {riskFocusMessage && (
        <section className="monitoring-structure-warning" role="alert" aria-label="风险深链未找到">
          <AlertTriangle size={17} aria-hidden="true" />
          <div>
            <strong>风险深链未在当前项目中找到</strong>
            <span>{riskFocusMessage}</span>
            <button
              type="button"
              className="monitoring-structure-warning-action"
              onClick={() => {
                setRiskFocusMessage("");
                onRiskFocusClear?.();
              }}
            >
              返回当前风险清单
            </button>
          </div>
        </section>
      )}
      {siteScopeResolution.status === "unavailable" && (
        <section className="monitoring-structure-warning" role="alert" aria-label="中心深链未找到">
          <AlertTriangle size={17} aria-hidden="true" />
          <div>
            <strong>中心深链未在当前项目中找到</strong>
            <span>中心“{siteScopeResolution.requestedSiteId}”不在当前项目的受试者目录或风险汇总中；系统未将其替换为其他中心。</span>
            <button
              type="button"
              className="monitoring-structure-warning-action"
              onClick={() => onRiskScopeChange?.("trial", {})}
            >
              返回整个试验范围
            </button>
          </div>
        </section>
      )}
      <section className="monitoring-command-surface" aria-label="医学监查项目与筛选">
        <div className="monitoring-project-strip">
          <div className="monitoring-project-identity">
            <Database size={18} />
            <div>
              <span>当前医学监查项目</span>
              <strong>{rawMonitoring?.project_label || monitoringSourceLabel}</strong>
              <small>{monitoringBatchDisplay || "来源批次待登记"}</small>
            </div>
            <Tag tone={rawMonitoringLoading || rawMonitoringUnavailable ? "warning" : monitoringAiStatus.ready ? "success" : "warning"}>
              {rawMonitoringLoading ? "来源读取中" : rawMonitoringUnavailable ? "来源暂不可用" : monitoringAiStatus.label}
            </Tag>
          </div>
          <div className="monitoring-project-facts" aria-label="项目监查资料概览">
            <div><strong>{riskCountDisplay}</strong><span>当前风险</span></div>
            <div><strong>{rawMonitoringUnavailable ? "—" : rawMonitoring?.listing?.subject_count ?? "—"}</strong><span>受试者</span></div>
            <div><strong>{rawMonitoringUnavailable ? "—" : formatMaybeNumber(rawMonitoring?.listing?.sheet_count)}</strong><span>数据表</span></div>
            <div><strong>{rawMonitoringUnavailable ? "—" : formatMaybeNumber(rawMonitoring?.listing?.row_count)}</strong><span>数据行</span></div>
            <div><strong>{rawMonitoringUnavailable ? "—" : rawMonitoring?.protocol?.span_count ?? "—"}</strong><span>方案段落/表格</span></div>
            <div><strong>{rawMonitoringUnavailable ? "—" : rawMonitoring?.domain_groups?.study_drug_change?.sheet_names?.length ?? "—"}</strong><span>试验药物变更表</span></div>
          </div>
          <div className="monitoring-scope-control">
            <span>汇总范围</span>
            <div className="risk-scope-switch" aria-label="风险汇总范围">
              {[['trial', '整个试验'], ['site', '中心'], ['subject', '受试者']].map(([value, label]) => (
                <button
                  className={riskScope === value ? "active" : ""}
                  key={value}
                  onClick={() => {
                    const scopeSubjectId = selectedRisk?.subject && selectedRisk.subject !== "-"
                      ? selectedRisk.subject
                      : selectedSubject || "";
                    if (value === "subject" && scopeSubjectId && scopeSubjectId !== selectedSubject) {
                      setSelectedSubject(scopeSubjectId);
                    }
                    setRiskScope(value);
                    onRiskScopeChange?.(value, {
                      siteId: selectedRisk?.site || subject?.site || "",
                      subjectId: scopeSubjectId,
                    });
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
            {riskScope === "site" && riskScopeSiteId && <small>中心 {riskScopeSiteId}</small>}
            {riskScope === "subject" && selectedSubject && <small>受试者 {selectedSubject}</small>}
          </div>
        </div>
      </section>
      {unclassifiedMonitoringSheets.length > 0 && (
        <section className="monitoring-structure-warning" role="status" aria-label="未分类数据表">
          <AlertTriangle size={17} aria-hidden="true" />
          <div>
            <strong>{unclassifiedMonitoringSheets.length} 张数据表尚未归入监查数据域</strong>
            <span>系统不会把这些表自动纳入风险结论；请先完成字段结构映射并由医学监察员确认。</span>
            <small title={unclassifiedMonitoringSheets.join("、")}>
              {unclassifiedMonitoringSheets.slice(0, 3).join("、")}
              {unclassifiedMonitoringSheets.length > 3 ? ` 等 ${unclassifiedMonitoringSheets.length} 张` : ""}
            </small>
            <button
              type="button"
              className="monitoring-structure-warning-action"
              title="打开批次准备与字段映射工作区"
              onClick={toggleBatchWorkspace}
            >
              打开批次与字段映射
            </button>
          </div>
        </section>
      )}
      <MedicalMonitoringScopeSummary
        rollup={riskIndex?.rollup}
        loading={riskIndexLoading}
        error={riskIndexError}
        activeScope={riskScope}
        selectedSiteId={riskScopeSiteId}
        selectedSubjectId={selectedSubject}
        taxonomy={riskTaxonomy || riskIndex?.taxonomy}
        onScopeChange={onRiskScopeChange}
      />
      <MedicalMonitoringAssurancePanel
        projectId={monitoringProjectId}
        open={assuranceOpen}
        onClose={() => setAssuranceOpen(false)}
        onOpenSubjectView={onOpenSubjectView}
        onRiskScopeChange={onRiskScopeChange}
        onSelectSubject={setSelectedSubject}
        currentSnapshot={riskIndex}
        sourceManifest={sourceManifest}
        rawMonitoring={rawMonitoring}
      />
      {uploadGateOpen && (
        <MedicalMonitoringBatchPanel
          projectId={monitoringProjectId}
          aiStatus={monitoringAiStatus}
          onClose={() => setUploadGateOpen(false)}
        />
      )}
      {/* Legacy intake removed; use the project-bound MedicalMonitoringBatchPanel above. */}
      <div className="monitoring-layout unified-risk-layout">
        <section className="panel ledger-panel unified-risk-ledger">
          <div className="risk-ledger-head">
            <div>
              <strong>项目医学风险 Checklist</strong>
              {riskIndexLoading ? (
                <span className="risk-index-loading-status" role="status" aria-live="polite">
                  正在读取当前条件风险快照{riskIndex ? "；下方保留上一份已读结果" : "；尚未收到当前结果"}
                  <button type="button" className="icon-text-button" onClick={cancelRiskIndexLoad}>取消读取</button>
                </span>
              ) : (
                <span>已评估 {riskSubjectsDisplay} 例 · 当前条件 {riskCountDisplay} 条 · 点击风险查看证据与医学处置</span>
              )}
            </div>
            <Tag tone="warning">待行动 {riskOpenCountDisplay}</Tag>
          </div>
          {!riskIndexLoading && riskIndex?.snapshot_status === "empty" && (
            <div className="monitoring-empty-snapshot">
              <span>当前项目尚无风险快照。请从本批次医学监查进入正式运行流程。</span>
              <button
                type="button"
                onClick={toggleBatchWorkspace}
                title="查看当前批次准备状态"
              >
                查看准备状态
              </button>
            </div>
          )}
          <MedicalMonitoringRiskChecklist
            key={monitoringProjectId}
            rows={visibleRiskRows}
            selectedRiskId={selectedRisk?.id}
            query={riskQuery}
            onQueryChange={applyRiskChecklistQuery}
            taxonomy={riskTaxonomy || riskIndex?.taxonomy}
            total={riskIndex ? riskIndex.total : null}
            loading={riskIndexLoading}
            error={riskIndexError}
            onRetry={retryRiskIndex}
            isCurrentSnapshot={riskIndex?.is_current_snapshot !== false}
            onRefreshCurrent={refreshCurrentRiskSnapshot}
            onExport={exportCurrentRiskSnapshot}
            exporting={riskExportLoading}
            lockedFilterKeys={riskScope === "subject"
              ? ["subjectId"]
              : riskScope === "site"
                ? ["siteId"]
                : []}
            onSelect={(risk) => {
              setSelectedRiskId(risk.id);
              setRiskActionMessage("");
              setRiskDockOpen(true);
              onRiskFocusChange?.(risk);
              if (risk.unread) markRiskRead(risk);
              if (risk.subject && risk.subject !== "-") setSelectedSubject(risk.subject);
            }}
          />
        </section>
        {selectedRisk && riskDockOpen ? (
          <RiskEvidenceDock
            projectId={monitoringProjectId}
            canonicalProjectId={expectedMonitoringProjectId}
            risk={selectedRisk}
            subject={subject}
            queryWorkflowPolicy={riskIndex?.query_workflow_policy}
            initialView={initialEvidenceTab || initialRiskView}
            onTabChange={onEvidenceTabChange}
            onOpenSubjectView={onOpenSubjectView}
            onClose={closeRiskEvidenceDock}
            onApplyDisposition={applyRiskDisposition}
            actionLoading={riskActionLoading}
            actionMessage={riskActionMessage}
          />
        ) : null}
      </div>
      <footer className="monitoring-boundary-note">
        <strong>使用边界</strong>
        <span>{rawMonitoringError || realInboxRiskRows[0]?.boundaryNote || `当前条件展示 ${riskCountDisplay} 条医学风险；Safety/PV仅作额外标记，仍属于同一风险台账。`}</span>
        <span>CM/CM1仅作为非试验用药；试验药物暂停、重启、剂量调整使用独立数据域。</span>
      </footer>
    </main>
  );
}

function riskSourceGroups(risk) {
  function riskSourceText(value) {
    return typeof value === "string" && value.trim() ? value.trim() : "";
  }

  const refs = (Array.isArray(risk.sourceRefs) ? risk.sourceRefs : [])
    .filter((ref) => ref && typeof ref === "object" && !Array.isArray(ref))
    .map((ref) => {
      const type = riskSourceText(ref.source_type) || "other";
      const locator = riskSourceText(ref.locator)
        || riskSourceText(ref.label)
        || riskSourceText(ref.source_id);
      const label = riskSourceText(ref.label)
        || riskSourceText(ref.locator)
        || riskSourceText(ref.source_id);
      return locator ? { type, locator, label } : null;
    })
    .filter(Boolean);
  (Array.isArray(risk.evidenceLocators) ? risk.evidenceLocators : []).forEach((locator) => {
    const cleanLocator = riskSourceText(locator);
    if (!cleanLocator || refs.some((ref) => ref.locator === cleanLocator)) return;
    refs.push({
      type: cleanLocator.startsWith("docx:") || cleanLocator.startsWith("protocol:") ? "protocol" : "listing",
      locator: cleanLocator,
      label: cleanLocator,
    });
  });
  const groups = [
    { key: "listing", label: "原始数据", refs: refs.filter((ref) => ["listing", "raw_data", "edc"].includes(ref.type) || /^(xlsx|xls|listing|edc):/.test(ref.locator)) },
    { key: "protocol", label: "方案依据", refs: refs.filter((ref) => ["protocol", "protocol_clause", "docx"].includes(ref.type) || /^(docx|protocol):/.test(ref.locator)) },
  ];
  const assigned = new Set(groups.flatMap((group) => group.refs.map((ref) => ref.locator)));
  groups.push({ key: "other", label: "系统规则", refs: refs.filter((ref) => !assigned.has(ref.locator)) });
  return groups.filter((group) => group.refs.length);
}

function canOpenRiskSource(ref) {
  return /^(docx|listing):/.test(ref.locator);
}

function RiskEvidenceSequence({ risk, groups: providedGroups = null, sourcePreviews = {}, sourcePreviewsLoading = false, onOpenSource, compact = false, className = "" }) {
  const groups = providedGroups || riskSourceGroups(risk);
  const stages = [
    {
      key: "listing",
      className: "fact",
      label: "1 原始事实",
      hint: "冻结的 listing 记录摘要；只展示已绑定证据，不补写缺失事实。",
      empty: "未绑定原始数据正文；不能仅凭风险标题判定发生了什么。",
    },
    {
      key: "protocol",
      className: "protocol",
      label: "2 方案依据",
      hint: "与当前风险绑定的方案原文或条款摘要。",
      empty: "未绑定方案原文；请在来源登记中核对适用条款。",
    },
    {
      key: "other",
      className: "rule",
      label: "3 系统规则 / 计算",
      hint: "确定性规则、阈值或计算判定；不替代医学经理的最终判断。",
      empty: "当前风险未提供可展开的规则引用。",
    },
  ];
  return (
    <div className={`risk-evidence-sequence risk-source-groups ${className} ${compact ? "compact" : ""}`} aria-label="风险证据顺序">
      {stages.map((stage) => {
        const group = groups.find((item) => item.key === stage.key)
          || { key: stage.key, label: stage.label, refs: [] };
        const refs = group.refs;
        const visibleRefs = compact ? refs.slice(0, 2) : refs;
        return (
          <section className={`risk-evidence-stage ${stage.className}`} key={stage.key}>
            <header>
              <strong>{stage.label}</strong>
              <span>{stage.hint}</span>
            </header>
            {stage.key === "other" && (
              <div className="risk-evidence-rule-copy">
                <span>风险判定理由</span>
                <p>{risk.rationale || "判定理由未提供；不能据此视为规则已解释。"}</p>
                {risk.recommendedAction && <em>推荐动作：{risk.recommendedAction}</em>}
              </div>
            )}
            {visibleRefs.length > 0 ? visibleRefs.map((ref) => (
              <RiskSourceReference
                group={group}
                sourceRef={ref}
                risk={risk}
                preview={sourcePreviews[ref.locator]}
                previewLoading={sourcePreviewsLoading}
                onOpen={onOpenSource}
                hideRuleCopy={stage.key === "other"}
                key={`${stage.key}-${ref.locator || ref.label}`}
              />
            )) : (
              <p className="risk-evidence-missing">{stage.empty}</p>
            )}
            {compact && refs.length > visibleRefs.length && (
              <small className="risk-evidence-more">另有 {refs.length - visibleRefs.length} 条绑定证据，请打开“来源证据”查看。</small>
            )}
          </section>
        );
      })}
      <section className="risk-evidence-stage locator">
        <header>
          <strong>4 来源定位</strong>
          <span>定位是复核入口，不作为事实正文；展开后查看文件/工作表/行号或段落定位。</span>
        </header>
        <p className="risk-evidence-missing">每条证据的定位已收在“查看来源定位”折叠项中。</p>
      </section>
    </div>
  );
}

function RiskSourceReference({ group, sourceRef, risk, preview, previewLoading, onOpen, hideRuleCopy = false }) {
  const canOpen = canOpenRiskSource(sourceRef);
  const isRule = group.key === "other";
  const primaryText = isRule
    ? (hideRuleCopy ? `规则引用：${sourceRef.label || sourceRef.locator}` : `规则判定：${risk.rationale}`)
    : preview?.primary_summary
      || (preview?.error ? "源信息读取失败；可点击“查看原文”重试。" : previewLoading ? "正在读取风险绑定的源信息。" : "源信息待读取。 ");
  const contextText = isRule
    ? `医学处置建议：${risk.recommendedAction || "待医学复核"}`
    : preview?.risk_context ? `关联风险：${preview.risk_context}` : `关联风险：${risk.title}`;
  return (
    <div className="risk-source-reference">
      <div className="risk-source-primary">
        <span>{primaryText}</span>
        <em>{contextText}</em>
      </div>
      <footer>
        <div className="risk-source-reference-actions">
          {canOpen && <button type="button" className="icon-text-button" title="在当前工作区打开完整只读原文" onClick={() => onOpen?.(sourceRef)}><ScanSearch size={14} />查看原文</button>}
          <details className="risk-source-locator">
            <summary>查看来源定位</summary>
            <code title={sourceRef.locator || sourceRef.label}>{sourceRef.locator || sourceRef.label}</code>
          </details>
        </div>
      </footer>
    </div>
  );
}

function EmbeddedRiskTimeline({ subject, focusRiskId, onOpenFull }) {
  const rawEvents = subject?.rawProfile?.timeline || [];
  const visits = monitoringPlannedVisitAxis(subject, rawEvents);
  const lanes = monitoringReferenceTimelineLanes(rawEvents.filter((event) => event.event_type !== "visit"));
  const focusedEvents = rawEvents.filter((event) => event.related_risk_ids?.includes(focusRiskId));
  return (
    <div className="risk-dock-evidence-view embedded-risk-timeline">
      <div className="risk-dock-view-head">
        <div><strong>{subject?.id || "-"} 访视轴与事件泳道</strong><span>橙色外框为当前风险直接关联事件；泳道显示该受试者完整事件上下文。</span></div>
        <button onClick={onOpenFull}>打开完整 Subject Timeline</button>
      </div>
      <div className="risk-focus-summary">
        <strong>当前风险定位</strong>
        {focusedEvents.length ? focusedEvents.map((event) => (
          <div className={`timeline-detail-row risk-focus-event ${monitoringEventCategoryClassName(event)}`} key={event.event_id}>
            <Tag tone="warning">{monitoringTimelineEventCategoryLabel(event)}</Tag>
            <div><strong>{event.visit_code || `D${event.study_day}`} · {event.title}</strong><span>{event.detail}</span><em>{event.source_locator || event.source_record_id}</em></div>
          </div>
        )) : <p className="quiet-text">当前风险未匹配到事件级定位；请在来源证据中核对原始行和方案条款。</p>}
      </div>
      <section className="reference-timeline-shell">
        <div className="reference-timeline-scroll">
          <div className="reference-timeline-canvas">
            <MedicalMonitoringReferenceTimelineSvg visits={visits} lanes={lanes} focusRiskId={focusRiskId} />
          </div>
        </div>
      </section>
    </div>
  );
}

function EmbeddedRiskProfile({ subject, focusRiskId, onOpenFull }) {
  const metrics = [...(subject?.efficacyMetrics || []), ...(subject?.safetyMetrics || [])]
    .sort((left, right) => {
      const leftFocused = (left.points || []).some((point) => point.related_risk_ids?.includes(focusRiskId));
      const rightFocused = (right.points || []).some((point) => point.related_risk_ids?.includes(focusRiskId));
      return Number(rightFocused) - Number(leftFocused);
    });
  const focusedPointCount = metrics.reduce((sum, metric) => sum + (metric.points || []).filter((point) => point.related_risk_ids?.includes(focusRiskId)).length, 0);
  return (
    <div className="risk-dock-evidence-view embedded-risk-profile">
      <div className="risk-dock-view-head">
        <div><strong>{subject?.id || "-"} 疗效与安全性历时变化</strong><span>显示全部可用指标；橙色标记为当前风险直接关联趋势点（{focusedPointCount} 个）。</span></div>
        <button onClick={onOpenFull}>打开完整 Patient Profile</button>
      </div>
      <div className="metric-chart-grid">
        {metrics.length ? metrics.map((metric) => (
          <MedicalMonitoringTrendSparkline metric={metric} focusRiskId={focusRiskId} compact key={metric.metric_key || metric.metric_label} />
        )) : <div className="empty-state">当前受试者暂无可绘制的疗效或安全性指标。</div>}
      </div>
    </div>
  );
}

function RiskHistoryView({ history, loading, error, onReassess }) {
  const actionLabels = {
    reviewed: "医学复核",
    query_draft: "Query草稿",
    submitted_for_approval: "提交内部审批",
    reopen: "重新打开",
  };
  if (loading) return <div className="empty-state">正在读取该风险的跨批次历史。</div>;
  if (error) return <p className="gate-error">{error}</p>;
  if (!history) return <div className="empty-state">当前风险尚无可读取的批次历史。</div>;
  return (
    <div className="risk-dock-evidence-view risk-history-view">
      <div className="risk-dock-view-head">
        <div><strong>同一医学风险的跨批次链路</strong><span>{history.boundary_note}</span></div>
        <Tag tone="info">{history.instances?.length || 0} 个实例</Tag>
      </div>
      <MedicalMonitoringRiskHistoryTrend instances={history.instances} />
      <div className="risk-history-table" role="table" aria-label="风险跨批次历史">
        <div className="risk-history-row header" role="row"><span>批次状态</span><span>风险状态</span><span>来源批次</span><span>规则/引擎</span><span>快照时间</span><span>实例关系</span></div>
        {(history.instances || []).map((entry) => {
          const instanceDispositions = (history.dispositions || []).filter((record) => (
            record.snapshot_id === entry.snapshot_id
            || record.risk_instance_id === entry.risk.risk_instance_id
          ));
          return (
            <div className={`risk-history-entry ${entry.is_current ? "current" : ""}`} key={`${entry.snapshot_id}-${entry.risk.risk_instance_id}`}>
              <div className="risk-history-row" role="row">
                <span><Tag tone={entry.is_current ? "warning" : "neutral"}>{entry.is_current ? "当前 · " : ""}{riskBatchDeltaLabels[entry.risk.batch_delta] || entry.risk.batch_delta}</Tag></span>
                <span>{riskStatusLabel(entry.risk.status)}</span>
                <span>{entry.risk.source_batch_id || "未登记"}<small>{entry.change_reason}</small></span>
                <span>{entry.rule_profile_revision}<small>{entry.engine_version}</small></span>
                <span>{new Date(entry.snapshot_created_at).toLocaleString("zh-CN", { hour12: false })}</span>
                <span className="risk-history-instance-cell"><strong>{entry.transition?.label || riskBatchDeltaLabels[entry.risk.batch_delta] || entry.risk.batch_delta}</strong><code title={entry.risk.risk_instance_id}>{entry.risk.risk_instance_id}</code>{entry.transition?.supersedes_risk_instance_id && <small>取代：{entry.transition.supersedes_risk_instance_id}</small>}{entry.transition?.kind === "reopen" && <small>旧处置仅作历史上下文</small>}</span>
              </div>
              <details className="risk-history-evidence">
                <summary>
                  {entry.frozen_evidence_count
                    ? `查看当时证据 ${entry.frozen_evidence_count}`
                    : "当时证据未冻结"}
                </summary>
                <div className="risk-history-evidence-list">
                  {(entry.frozen_evidence || []).map((captured) => {
                    const fragment = captured.fragment || {};
                    const directText = fragment.primary_summary
                      || fragment.text
                      || (fragment.fields || []).map((field) => `${field.field}：${field.value}`).join("；")
                      || `证据不可用：${captured.error_code || "未记录正文"}`;
                    return (
                      <div key={`${entry.snapshot_id}-${captured.locator}`}>
                        <strong>{fragment.source_type === "protocol" ? "方案依据" : "原始数据"}</strong>
                        <p>{directText}</p>
                        <code>{captured.locator}</code>
                      </div>
                    );
                  })}
                  {!entry.frozen_evidence?.length && <p>该旧快照未冻结原文，系统不会以当前文件内容替代。</p>}
                  {instanceDispositions.map((record) => (
                    <div className="risk-history-prior-disposition" key={record.record_id}>
                      <strong>当时医学处置</strong>
                      <p>{record.comment || "未填写处置意见"}</p>
                      <small>{actionLabels[record.action] || record.action} · {record.actor}</small>
                      {!entry.is_current && record.action !== "reopen" && (
                        <button
                          type="button"
                          onClick={() => onReassess?.(record, entry)}
                        >
                          基于该结论重新评估
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </details>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function riskDockTabFromRouteView(view) {
  if (["disposition", "timeline", "profile", "ae_mh", "sources", "history"].includes(view)) {
    return view;
  }
  if (view === "evidence") return "sources";
  if (view === "ae-mh") return "ae_mh";
  return "disposition";
}

function RiskEvidenceDock({ projectId, canonicalProjectId, risk, subject, queryWorkflowPolicy, initialView = "checklist", onTabChange, onOpenSubjectView, onClose, onApplyDisposition, actionLoading, actionMessage }) {
  const initialTab = riskDockTabFromRouteView(initialView);
  const [activeTab, setActiveTab] = useState(initialTab);
  const [riskHistory, setRiskHistory] = useState(null);
  const [riskHistoryLoading, setRiskHistoryLoading] = useState(false);
  const [riskHistoryError, setRiskHistoryError] = useState("");
  const [reassessmentSeed, setReassessmentSeed] = useState(null);
  const [sourceFragment, setSourceFragment] = useState(null);
  const [sourceFragmentLoading, setSourceFragmentLoading] = useState(false);
  const [sourceFragmentError, setSourceFragmentError] = useState("");
  const [sourcePreviews, setSourcePreviews] = useState({});
  const [sourcePreviewsError, setSourcePreviewsError] = useState("");
  const [sourcePreviewsLoading, setSourcePreviewsLoading] = useState(false);
  const expectedEvidenceProjectId = canonicalProjectId || projectId;
  const sourceFragmentRequestId = useRef(0);
  const sourcePreviewRequestId = useRef(0);
  useEffect(() => {
    setActiveTab(initialTab);
    setRiskHistory(null);
    setRiskHistoryError("");
    setReassessmentSeed(null);
    sourceFragmentRequestId.current += 1;
    setSourceFragment(null);
    setSourceFragmentError("");
    setSourceFragmentLoading(false);
    sourcePreviewRequestId.current += 1;
    setSourcePreviews({});
    setSourcePreviewsError("");
    setSourcePreviewsLoading(false);
  }, [risk.id, initialTab, expectedEvidenceProjectId]);
  useEffect(() => {
    onTabChange?.(activeTab);
  }, [activeTab, onTabChange]);
  useEffect(() => {
    if (activeTab !== "history" || !projectId || !risk.riskKey || riskHistory) return undefined;
    const controller = new AbortController();
    let active = true;
    setRiskHistoryLoading(true);
    setRiskHistoryError("");
    fetch(`/api/projects/${projectId}/monitoring/risks/${encodeURIComponent(risk.riskKey)}/history`, { signal: controller.signal })
      .then((response) => readJsonOrThrow(response))
      .then((payload) => {
        if (!active) return;
        if (payload?.project_id !== expectedEvidenceProjectId) {
          setRiskHistory(null);
          setRiskHistoryError("批次历史响应项目身份不匹配，已阻止写入当前风险证据视图。");
          return;
        }
        setRiskHistory(payload);
      })
      .catch((error) => {
        if (active && error.name !== "AbortError") setRiskHistoryError(`批次历史读取失败：${apiErrorText(error)}`);
      })
      .finally(() => { if (active) setRiskHistoryLoading(false); });
    return () => {
      active = false;
      controller.abort();
    };
  }, [activeTab, projectId, expectedEvidenceProjectId, risk.riskKey, riskHistory]);
  useEffect(() => {
    if (!["disposition", "sources"].includes(activeTab) || !projectId || !risk.id) return undefined;
    setSourcePreviewsError("");
    const refs = riskSourceGroups(risk)
      .flatMap((group) => group.refs)
      .filter(canOpenRiskSource);
    if (!refs.length) {
      setSourcePreviewsLoading(false);
      return undefined;
    }
    const requestId = sourcePreviewRequestId.current + 1;
    sourcePreviewRequestId.current = requestId;
    const controller = new AbortController();
    setSourcePreviewsLoading(true);
    Promise.all(refs.map(async (ref) => {
      const query = new URLSearchParams({ locator: ref.locator });
      try {
        const fragment = await fetch(
          `/api/projects/${projectId}/monitoring/risks/${encodeURIComponent(risk.id)}/evidence-fragment?${query.toString()}`,
          { signal: controller.signal },
        ).then((response) => readJsonOrThrow(response));
        return [ref.locator, fragment];
      } catch (error) {
        if (error.name === "AbortError") throw error;
        return [ref.locator, { error: apiErrorText(error) }];
      }
    }))
      .then((entries) => {
        if (sourcePreviewRequestId.current !== requestId) return;
        const identityMismatch = entries.some(([, fragment]) => (
          !fragment?.error && fragment?.project_id !== expectedEvidenceProjectId
        ));
        if (identityMismatch) {
          setSourcePreviews({});
          setSourcePreviewsError("来源证据响应项目身份不匹配，已阻止写入当前风险证据视图。");
          return;
        }
        setSourcePreviews(Object.fromEntries(entries));
      })
      .catch((error) => {
        if (error.name !== "AbortError" && sourcePreviewRequestId.current === requestId) {
          setSourcePreviews({});
          setSourcePreviewsError(`来源证据片段读取失败：${apiErrorText(error)}`);
        }
      })
      .finally(() => {
        if (sourcePreviewRequestId.current === requestId) setSourcePreviewsLoading(false);
      });
    return () => controller.abort();
  }, [activeTab, projectId, expectedEvidenceProjectId, risk.id]);
  const rawTimeline = subject?.rawProfile?.timeline || [];
  const compactTimeline = rawTimeline.length ? rawTimeline : subject?.timeline || [];
  const aeMhEvents = compactTimeline.filter((event) => ["adverse_event", "medical_history", "AE", "MH"].includes(event.event_type || event.lane));
  const openSourceFragment = (ref) => {
    const requestId = sourceFragmentRequestId.current + 1;
    sourceFragmentRequestId.current = requestId;
    setSourceFragmentLoading(true);
    setSourceFragmentError("");
    setSourceFragment(null);
    const cached = sourcePreviews[ref.locator];
    if (cached && !cached.error) {
      setSourceFragment(cached);
      setSourceFragmentLoading(false);
      return;
    }
    const query = new URLSearchParams({ locator: ref.locator });
    fetch(`/api/projects/${projectId}/monitoring/risks/${encodeURIComponent(risk.id)}/evidence-fragment?${query.toString()}`)
      .then((response) => readJsonOrThrow(response))
      .then((payload) => {
        if (sourceFragmentRequestId.current === requestId) {
          if (payload?.project_id !== expectedEvidenceProjectId) {
            setSourceFragment(null);
            setSourceFragmentError("原文片段响应项目身份不匹配，已阻止写入当前风险证据视图。");
            return;
          }
          setSourceFragment(payload);
          setSourcePreviews((current) => ({ ...current, [ref.locator]: payload }));
        }
      })
      .catch((error) => {
        if (sourceFragmentRequestId.current === requestId) setSourceFragmentError(`原文片段读取失败：${apiErrorText(error)}`);
      })
      .finally(() => {
        if (sourceFragmentRequestId.current === requestId) setSourceFragmentLoading(false);
      });
  };
  const tabs = [
    ["disposition", "风险处置"],
    ["timeline", "Subject Timeline"],
    ["profile", "Patient Profile"],
    ["ae_mh", "AE/MH核查"],
    ["sources", "来源证据"],
    ["history", "批次历史"],
  ];
  return (
    <section className="risk-evidence-dock" aria-label="风险证据工作区">
      <header className="risk-evidence-dock-head">
        <div><Tag tone={statusClass(risk.severity)}>{severityLabel(risk.severity)}</Tag><strong>{risk.title}</strong><span>{risk.scopeLabel}</span></div>
        {risk.sourceEvidenceShape === "malformed" && <span className="risk-evidence-shape-warning" role="alert">来源证据字段形状异常，未按有效证据展示</span>}
        <button className="icon-button" title="关闭证据工作区" onClick={onClose}><XCircle size={18} /></button>
      </header>
      <nav className="risk-evidence-tabs" aria-label="风险证据视图">
        {tabs.map(([value, label]) => <button className={activeTab === value ? "active" : ""} key={value} onClick={() => setActiveTab(value)}>{label}</button>)}
      </nav>
      <MedicalMonitoringRiskEvidenceContext risk={risk} />
      <div className="risk-evidence-dock-body">
        {activeTab === "disposition" && <RiskDetail risk={risk} subject={subject} queryWorkflowPolicy={queryWorkflowPolicy} sourcePreviews={sourcePreviews} sourcePreviewsLoading={sourcePreviewsLoading} onOpenSource={(ref) => { setActiveTab("sources"); openSourceFragment(ref); }} onOpenSubjectView={onOpenSubjectView} onApplyDisposition={onApplyDisposition} actionLoading={actionLoading} actionMessage={actionMessage} reassessmentSeed={reassessmentSeed} onClearReassessment={() => setReassessmentSeed(null)} embedded />}
        {activeTab === "timeline" && <EmbeddedRiskTimeline subject={subject} focusRiskId={risk.id} onOpenFull={() => onOpenSubjectView?.("subjectTimeline", risk.id)} />}
        {activeTab === "profile" && <EmbeddedRiskProfile subject={subject} focusRiskId={risk.id} onOpenFull={() => onOpenSubjectView?.("patientProfile", risk.id)} />}
        {activeTab === "ae_mh" && (
          <div className="risk-dock-evidence-view">
            <div className="risk-dock-view-head"><div><strong>AE/MH 与 Safety/PV 关联核查</strong><span>Safety/PV 仅作为风险标签和协作投影，继续使用同一风险编号与来源证据。</span></div><Tag tone={(risk.tags || []).includes("safety_pv") ? "warning" : "neutral"}>{(risk.tags || []).includes("safety_pv") ? "Safety/PV关注" : "一般医学风险"}</Tag></div>
            <div className="risk-dock-event-list">{aeMhEvents.slice(0, 24).map((event, index) => <div key={event.event_id || `${event.day}-${index}`}><Tag tone="warning">{timelineEventCategoryLabel(event)}</Tag><strong>{event.visit_name || event.visit_code || event.day || event.event_date || "-"}</strong><span>{event.title || event.label || event.event_label || event.description || "AE/MH记录"}</span></div>)}{!aeMhEvents.length && <p className="quiet-text">当前时间线未发现可直接展示的 AE/MH 事件；不能据此判定不存在漏报。</p>}</div>
          </div>
        )}
        {activeTab === "sources" && (
            <div className="risk-dock-evidence-view">
              <div className="risk-dock-view-head"><div><strong>风险证据链</strong><span>按固定顺序核对原始事实、方案依据、系统规则/计算，再按需展开来源定位。</span></div></div>
            {sourcePreviewsError && <p className="gate-error" role="alert">{sourcePreviewsError}</p>}
            {(sourceFragmentLoading || sourceFragmentError || sourceFragment) && (
              <section className="source-fragment-panel" aria-label="只读来源原文片段" aria-live="polite">
                {sourceFragmentLoading && <div className="empty-state">正在读取当前风险绑定的原文片段。</div>}
                {sourceFragmentError && <p className="gate-error">{sourceFragmentError}</p>}
                {sourceFragment && <>
                  <div className="source-fragment-head"><div><strong>{sourceFragment.display_locator}</strong><span>{sourceFragment.source_type === "protocol" ? "研究方案原文" : "data listing原始记录"} · 只读</span></div><Tag tone={sourceFragment.source_type === "protocol" ? "info" : "warning"}>{sourceFragment.locator_kind}</Tag></div>
                  <div className="source-fragment-lineage"><span>关联风险：{sourceFragment.risk_context || risk.title}</span><span>溯源：{sourceFragment.source_type === "protocol" ? "研究方案原文" : "data listing原始记录"} · {sourceFragment.locator_kind || "定位已绑定"}</span></div>
                  {sourceFragment.context_before?.length > 0 && <div className="source-fragment-context"><span>上文</span>{sourceFragment.context_before.map((text, index) => <p key={`before-${index}`}>{text}</p>)}</div>}
                  {sourceFragment.text && <blockquote>{sourceFragment.text}</blockquote>}
                  {sourceFragment.fields?.length > 0 && <div className="source-fragment-fields">{sourceFragment.fields.map((field, index) => <div key={`${field.field}-${index}`}><span>{field.field}</span><strong>{field.value}</strong></div>)}</div>}
                  {sourceFragment.context_after?.length > 0 && <div className="source-fragment-context"><span>下文</span>{sourceFragment.context_after.map((text, index) => <p key={`after-${index}`}>{text}</p>)}</div>}
                  <details className="source-fragment-locator">
                    <summary>查看来源定位</summary>
                    <code>{sourceFragment.locator}</code>
                  </details>
                </>}
              </section>
            )}
            <RiskEvidenceSequence
              risk={risk}
              sourcePreviews={sourcePreviews}
              sourcePreviewsLoading={sourcePreviewsLoading}
              onOpenSource={openSourceFragment}
              className="risk-source-groups"
            />
          </div>
        )}
        {activeTab === "history" && <RiskHistoryView
          history={riskHistory}
          loading={riskHistoryLoading}
          error={riskHistoryError}
          onReassess={(record, entry) => {
            setReassessmentSeed({ record, entry });
            setActiveTab("disposition");
          }}
        />}
      </div>
    </section>
  );
}

function riskQueryDraft(risk) {
  const subjectId = risk.subject && risk.subject !== "-" ? risk.subject : "";
  const siteId = risk.site && risk.site !== "-" ? risk.site : "";
  const scope = subjectId ? `受试者 ${subjectId}` : siteId ? `中心 ${siteId}` : "项目层面";
  const recipient = subjectId ? "请中心" : "请项目组";
  return `${recipient}核对${scope}“${risk.title}”相关原始记录，并结合方案要求补充数据更正或医学解释。`;
}

function RiskDetail({ risk, subject, queryWorkflowPolicy, sourcePreviews = {}, sourcePreviewsLoading = false, onOpenSource, onOpenSubjectView, onApplyDisposition, actionLoading, actionMessage, reassessmentSeed = null, onClearReassessment, embedded = false }) {
  const dispositionState = risk.dispositionState || ruxDispositionStateFromStatus(risk.status);
  const internalApprovalRequired = queryWorkflowPolicy?.internal_approval_required !== false;
  const evidenceGroups = riskSourceGroups(risk);
  const sourcePreviewCount = evidenceGroups.reduce(
    (count, group) => count + group.refs.filter((ref) => sourcePreviews[ref.locator]).length,
    0,
  );
  const [dispositionComment, setDispositionComment] = useState("已核对原始listing、方案条款和个例时间线，需进入医学处置闭环。");
  const [queryDraftText, setQueryDraftText] = useState(riskQueryDraft(risk));
  const [reopenReason, setReopenReason] = useState("");
  const [reassessmentChangeReason, setReassessmentChangeReason] = useState("");
  const [dispositionKind, setDispositionKind] = useState(risk.dispositionKind || "center_query");
  const emptyMedicalJudgments = {
    patient_safety_impact: false,
    key_data_impact: false,
    query_required: false,
    lock_or_export_impact: false,
    review_completed: false,
  };
  const [medicalJudgments, setMedicalJudgments] = useState(risk.medicalJudgments || emptyMedicalJudgments);
  useEffect(() => {
    const historicalRecord = reassessmentSeed?.record;
    setDispositionComment(historicalRecord?.comment || "已核对原始listing、方案条款和个例时间线，需进入医学处置闭环。");
    setQueryDraftText(historicalRecord?.query_draft_text || riskQueryDraft(risk));
    setReopenReason("");
    setReassessmentChangeReason("");
    setDispositionKind(historicalRecord?.disposition_kind || risk.dispositionKind || "center_query");
    setMedicalJudgments(
      historicalRecord?.medical_judgments
        ? { ...historicalRecord.medical_judgments, review_completed: false }
        : risk.medicalJudgments || emptyMedicalJudgments
    );
  }, [
    risk.id,
    risk.subject,
    risk.dispositionState,
    risk.dispositionKind,
    risk.sourceVersion,
    reassessmentSeed?.record?.record_id,
  ]);
  const terminalDispositionLabel = terminalDispositionLabels[dispositionState] || "";
  const dispositionSteps = terminalDispositionLabel
    ? [["pending_review", "待医学复核"], [dispositionState, terminalDispositionLabel]]
    : [
      ["pending_review", "待医学复核"],
      ["reviewed", "已医学复核"],
      ["query_draft", "Query草稿"],
      ...(internalApprovalRequired ? [["submitted_for_approval", "已提交内部审批"]] : []),
    ];
  const applyDisposition = (action) => {
    const payload = {
      comment: action === "query_draft" ? queryDraftText : dispositionComment,
      query_draft_text: action === "query_draft" ? queryDraftText : "",
      disposition_kind: dispositionKind,
      expected_source_version: risk.sourceVersion,
      expected_disposition_state: dispositionState,
      medical_judgments: action === "reviewed" ? medicalJudgments : null,
      basis_disposition_record_id: action === "reviewed" ? reassessmentSeed?.record?.record_id || "" : "",
      reassessment_change_reason: action === "reviewed" ? reassessmentChangeReason : "",
    };
    onApplyDisposition?.(risk, action, payload);
  };
  const canReview = dispositionState === "pending_review"
    && dispositionComment.trim()
    && medicalJudgments.review_completed
    && (!reassessmentSeed || reassessmentChangeReason.trim().length >= 4);
  const canDraftQuery = dispositionState === "reviewed" && dispositionKind === "center_query" && queryDraftText.trim();
  const canSubmitApproval = internalApprovalRequired && dispositionState === "query_draft" && dispositionComment.trim();
  return (
    <section className={embedded ? "risk-detail risk-detail-embedded" : "panel risk-detail"}>
      <SectionTitle eyebrow="风险详情" title={risk.title} />
      <div className="risk-meta">
        <Tag tone={statusClass(risk.severity)}>{severityLabel(risk.severity)}</Tag>
        <Tag tone="warning">{risk.status}</Tag>
        <Tag tone="info">{risk.source}</Tag>
      </div>
      <div className="evidence-chain" aria-label={`核心证据，已读取 ${sourcePreviewCount} 条来源片段`}>
        <h3>核心证据</h3>
        {sourcePreviewCount === 0 && <p className="quiet-text">当前风险未绑定可直接展示的原始数据或方案正文；系统不会以风险标题补写事实。</p>}
        <RiskEvidenceSequence
          risk={risk}
          groups={evidenceGroups}
          sourcePreviews={sourcePreviews}
          sourcePreviewsLoading={sourcePreviewsLoading}
          onOpenSource={onOpenSource}
          compact
        />
      </div>
      <div className="checklist">
        <h3>医学复核要点</h3>
        {[
          ["patient_safety_impact", "患者安全影响"],
          ["key_data_impact", "关键疗效/安全性数据影响"],
          ["query_required", "需要发起Query"],
          ["lock_or_export_impact", "影响锁库/数据导出"],
        ].map(([key, item]) => (
          <label key={key}>
            <input
              type="checkbox"
              checked={Boolean(medicalJudgments[key])}
              disabled={actionLoading || dispositionState !== "pending_review"}
              onChange={(event) => setMedicalJudgments((current) => ({ ...current, [key]: event.target.checked }))}
            />
            <span>{item}</span>
          </label>
        ))}
        <label className="checklist-confirmation">
          <input
            type="checkbox"
            checked={Boolean(medicalJudgments.review_completed)}
            disabled={actionLoading || dispositionState !== "pending_review"}
            onChange={(event) => setMedicalJudgments((current) => ({ ...current, review_completed: event.target.checked }))}
          />
          <span>已完成以上四项医学判断</span>
        </label>
      </div>
      <div className="query-box">
        <h3>医学处置闭环</h3>
        {reassessmentSeed && (
          <div className="risk-reassessment-seed">
            <div>
              <strong>已引用历史处置作为可编辑草稿</strong>
              <span>
                {reassessmentSeed.entry?.risk?.source_batch_id || "历史批次"} ·
                {reassessmentSeed.entry?.change_reason || "跨批次重新判断"}
              </span>
              <small>尚未写入当前实例。请结合当前冻结证据复核全部判断，并说明本次重新判断原因。</small>
            </div>
            <button type="button" onClick={onClearReassessment} disabled={actionLoading}>取消引用</button>
          </div>
        )}
        <div className="disposition-steps">
          {dispositionSteps.map(([step, label]) => (
            <span key={step} className={`disposition-step ${step === dispositionState ? "current" : ""}`}>
              <Tag tone={ruxDispositionStepTone(dispositionState, step)}>{label}</Tag>
            </span>
          ))}
        </div>
        <label className="disposition-field">
          医学处置分支
          <select value={dispositionKind} onChange={(event) => setDispositionKind(event.target.value)} disabled={actionLoading || dispositionState !== "pending_review"}>
            <option value="explained_no_external_action">已有充分解释，无需外部动作</option>
            <option value="center_query">向中心发起 Query</option>
            <option value="data_correction">数据更正</option>
            <option value="follow_up">追加随访</option>
            <option value="pd_update">补充或更新 PD</option>
            <option value="safety_pv_collaboration">Safety/PV 协作</option>
            <option value="continue_observation">继续观察</option>
            <option value="duplicate_not_applicable">重复项或不适用</option>
          </select>
        </label>
        <label className="disposition-field">
          医学处置意见
          <textarea value={dispositionComment} onChange={(event) => setDispositionComment(event.target.value)} disabled={actionLoading || Boolean(terminalDispositionLabel) || dispositionState === "submitted_for_approval"} />
        </label>
        {reassessmentSeed && (
          <label className="disposition-field">
            重新判断原因
            <textarea
              value={reassessmentChangeReason}
              onChange={(event) => setReassessmentChangeReason(event.target.value)}
              disabled={actionLoading || dispositionState !== "pending_review"}
              placeholder="说明当前批次数据、证据、规则或医学判断相较历史结论的变化"
            />
          </label>
        )}
        <label className="disposition-field">
          Query草稿
          <textarea value={queryDraftText} onChange={(event) => setQueryDraftText(event.target.value)} disabled={actionLoading || dispositionState === "submitted_for_approval" || dispositionKind !== "center_query"} />
        </label>
        <p className="quiet-text">{dispositionKind === "center_query" ? (internalApprovalRequired ? "当前项目要求内部审批；提交审批不代表对外发送或归档已经完成。" : "当前项目不要求内部审批；Query草稿保存后进入项目约定的发送流程。") : "当前分支不生成中心 Query；医学复核记录仍保留来源版本、处置理由和审计轨迹。"}</p>
        {!terminalDispositionLabel && <div className="button-row">
          <button className={canReview ? "primary-button" : ""} disabled={actionLoading || !risk.inboxItemId || !canReview} title={canReview ? "保存医学复核结论" : "需填写医学处置意见并确认四项医学判断"} onClick={() => applyDisposition("reviewed")}>
            {actionLoading ? "写入中" : dispositionKind === "center_query" ? "标记已复核" : "完成医学处置"}
          </button>
          <button className={canDraftQuery ? "primary-button" : ""} disabled={actionLoading || !risk.inboxItemId || !canDraftQuery} title={canDraftQuery ? "保存内部Query草稿" : dispositionKind !== "center_query" ? "当前处置分支不生成中心Query" : "完成医学复核并填写Query草稿后可用"} onClick={() => applyDisposition("query_draft")}>
            {actionLoading ? "写入中" : "记录Query草稿"}
          </button>
          {internalApprovalRequired && <button className={canSubmitApproval ? "primary-button" : ""} disabled={actionLoading || !risk.inboxItemId || !canSubmitApproval} title={canSubmitApproval ? "提交内部医学审批" : "先形成Query草稿并填写处置意见"} onClick={() => applyDisposition("submitted_for_approval")}>
            {actionLoading ? "写入中" : "提交内部审批"}
          </button>}
        </div>}
        {terminalDispositionLabel && <>
          <label className="disposition-field">
            重新打开原因
            <textarea value={reopenReason} onChange={(event) => setReopenReason(event.target.value)} disabled={actionLoading} placeholder="说明新信息、数据变化或重新判断的原因" />
          </label>
          <div className="button-row">
            <button className={reopenReason.trim() ? "primary-button" : ""} disabled={actionLoading || !risk.inboxItemId || !reopenReason.trim()} onClick={() => onApplyDisposition?.(risk, "reopen", {
              comment: reopenReason,
              expected_source_version: risk.sourceVersion,
              expected_disposition_state: dispositionState,
            })}>
              重新打开风险
            </button>
          </div>
        </>}
        {actionMessage && <p className="gate-result">{actionMessage}</p>}
      </div>
      {subject && <div className="subject-shortcut">
        <div>
          <strong>{subject.id} 个例工作面</strong>
          <span>{subject.profile}</span>
        </div>
        <div className="button-row">
          <button onClick={() => onOpenSubjectView?.("subjectTimeline", risk.id)}>进入 Subject Timeline</button>
          <button onClick={() => onOpenSubjectView?.("patientProfile", risk.id)}>进入 Patient Profile</button>
        </div>
      </div>}
    </section>
  );
}

const timelineLaneDefs = [
  { key: "AE", label: "AE", types: ["adverse_event"] },
  { key: "IP", label: "试验药物变更", types: ["dose_adjustment"] },
  { key: "CM", label: "合并用药（非试验用药）", types: ["concomitant_medication"] },
  { key: "MH", label: "病史", types: ["medical_history"] },
  { key: "LAB", label: "实验室/疗效", types: ["lab", "efficacy_score"] },
  { key: "PD_QUERY", label: "PD / Query", types: ["protocol_deviation", "query"] },
];


const timelineEventCategoryDefs = {
  adverse_event: { label: "AE记录", className: "event-category-adverse-event" },
  adverse_event_review: { label: "AE复核提示", className: "event-category-adverse-event-review" },
  dose_adjustment: { label: "试验药物变更", className: "event-category-dose-adjustment" },
  dose_adjustment_paused: { label: "试验药物暂停", className: "event-category-dose-adjustment-paused" },
  dose_adjustment_resumed: { label: "试验药物恢复", className: "event-category-dose-adjustment-resumed" },
  concomitant_medication: { label: "CM非试验用药", className: "event-category-concomitant-medication" },
  concomitant_medication_risk: { label: "禁限用药/洗脱风险", className: "event-category-concomitant-medication-risk" },
  medical_history: { label: "病史", className: "event-category-medical-history" },
  lab: { label: "实验室", className: "event-category-lab" },
  lab_hematology: { label: "血常规异常", className: "event-category-lab-hematology" },
  lab_chemistry: { label: "血生化异常", className: "event-category-lab-chemistry" },
  efficacy_score: { label: "疗效", className: "event-category-efficacy-score" },
  protocol_deviation: { label: "PD", className: "event-category-protocol-deviation" },
  query: { label: "Query", className: "event-category-query" },
};

function timelineEventCategoryKey(event) {
  const text = [event.title, event.detail, event.clinical_interpretation].filter(Boolean).join(" ");
  if (event.event_type === "dose_adjustment") {
    if (text.includes("暂停用药")) return "dose_adjustment_paused";
    if (text.includes("重新用药") || text.includes("恢复")) return "dose_adjustment_resumed";
    return "dose_adjustment";
  }
  if (event.event_type === "lab") {
    if (event.source_domain === "LBHEMA") return "lab_hematology";
    if (event.source_domain === "LBCHEM") return "lab_chemistry";
    return "lab";
  }
  if (event.event_type === "concomitant_medication") {
    if (/禁用|限制|洗脱|违背|风险|PD|query/i.test(text)) return "concomitant_medication_risk";
    return "concomitant_medication";
  }
  if (event.event_type === "adverse_event") {
    if (event.related_risk_ids?.length || /复核|漏报|给药调整|实验室|关系|医学/.test(text)) return "adverse_event_review";
    return "adverse_event";
  }
  return event.event_type;
}

function timelineEventCategoryDef(event) {
  return timelineEventCategoryDefs[timelineEventCategoryKey(event)] || {
    label: event.source_domain || "事件",
    className: "event-category-other",
  };
}


function timelineEventCategoryLabel(event) {
  return timelineEventCategoryDef(event).label;
}


function laneForEvent(event) {
  return timelineLaneDefs.find((lane) => lane.types.includes(event.event_type))?.key || "LAB";
}



const visualQcResultLabels = {
  sampled_pass: "核对通过",
  sampled_fail: "核对不通过",
  manual_review_required: "需人工专项复核",
};

function visualQcTone(result) {
  if (result === "sampled_pass") return "success";
  if (result === "sampled_fail") return "danger";
  if (result === "manual_review_required") return "warning";
  return "info";
}

function visualQcLocatorText(locator) {
  if (!locator || typeof locator !== "object") return "未提供定位信息";
  const fields = [
    ["page", "第 {value} 页"],
    ["sheet", "工作表 {value}"],
    ["row", "第 {value} 行"],
    ["cell", "单元格 {value}"],
    ["section", "章节 {value}"],
  ];
  const parts = fields
    .filter(([key]) => locator[key] !== undefined && locator[key] !== null && locator[key] !== "")
    .map(([key, template]) => template.replace("{value}", String(locator[key])));
  return parts.join(" · ") || "原始资料定位单元";
}

function visualQcMediaClassLabel(value) {
  return {
    text_document_image: "扫描文本图像",
    pdf_text_page: "可检索 PDF 页",
    image: "图像",
    pdf: "PDF 页面",
    doc: "Word 文档",
    docx: "Word 文档",
  }[String(value || "").toLowerCase()] || "待分类资料";
}

function EligibilityVisualQcWorkspace({ routeProjectId, subjectId, onReturn }) {
  const queueRequestIdRef = useRef(0);
  const [queue, setQueue] = useState({
    items: [], total: 0, overallTotal: 0, offset: 0, limit: 50, statusCounts: {},
  });
  const [selectedEvidenceId, setSelectedEvidenceId] = useState("");
  const [statusFilter, setStatusFilter] = useState("pending");
  const [qcResult, setQcResult] = useState("sampled_pass");
  const [reasonCode, setReasonCode] = useState("visual_match");
  const [userReason, setUserReason] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [notice, setNotice] = useState("");
  const [fitImage, setFitImage] = useState(true);
  const [zoom, setZoom] = useState(1);
  const [naturalSize, setNaturalSize] = useState({ width: 0, height: 0 });

  const loadQueue = async (
    offset = queue.offset,
    preferredEvidenceId = selectedEvidenceId,
    requestedStatus = statusFilter,
  ) => {
    if (!subjectId) return;
    const requestId = ++queueRequestIdRef.current;
    setLoading(true);
    setError("");
    try {
      const response = await fetch(
        `/api/projects/${routeProjectId}/eligibility/raw-intake/subjects/${subjectId}/visual-qc-queue?offset=${offset}&limit=${queue.limit}&qc_status=${requestedStatus}`,
      );
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(apiDetailText(payload, `读取失败：${response.status}`));
      if (requestId !== queueRequestIdRef.current) return;
      const items = Array.isArray(payload.items) ? payload.items : [];
      setQueue({
        items,
        total: Number(payload.total || 0),
        overallTotal: Number(payload.overall_total || 0),
        offset: Number(payload.offset || 0),
        limit: Number(payload.limit || queue.limit),
        statusCounts: payload.status_counts || {},
      });
      setSelectedEvidenceId(
        items.some((item) => item.evidence_id === preferredEvidenceId)
          ? preferredEvidenceId
          : items[0]?.evidence_id || "",
      );
      setConflict(false);
    } catch (loadError) {
      if (requestId === queueRequestIdRef.current) {
        setError(`视觉复核队列读取失败：${apiErrorText(loadError)}`);
      }
    } finally {
      if (requestId === queueRequestIdRef.current) setLoading(false);
    }
  };

  useEffect(() => {
    setSelectedEvidenceId("");
    setStatusFilter("pending");
    setNotice("");
    setConflict(false);
    loadQueue(0, "", "pending");
  }, [routeProjectId, subjectId]);

  useEffect(() => {
    if (!queue.items.some((item) => item.evidence_id === selectedEvidenceId)) {
      setSelectedEvidenceId(queue.items[0]?.evidence_id || "");
    }
  }, [queue.items, selectedEvidenceId]);

  const selectedItem = queue.items.find((item) => item.evidence_id === selectedEvidenceId) || null;
  const reviewedCount = (queue.statusCounts.sampled_pass || 0)
    + (queue.statusCounts.sampled_fail || 0)
    + (queue.statusCounts.manual_review_required || 0);
  const overallProgress = queue.overallTotal
    ? Math.round((reviewedCount / queue.overallTotal) * 100)
    : 0;
  const pageStart = queue.total ? queue.offset + 1 : 0;
  const pageEnd = Math.min(queue.offset + queue.items.length, queue.total);
  const canGoBack = queue.offset > 0 && !loading;
  const canGoForward = queue.offset + queue.limit < queue.total && !loading;
  const imageUrl = selectedItem
    ? `/api/projects/${routeProjectId}/eligibility/raw-intake/subjects/${subjectId}/visual-qc-artifacts/${selectedItem.image_artifact_id}/content`
    : "";

  useEffect(() => {
    setQcResult("sampled_pass");
    setReasonCode("visual_match");
    setUserReason("");
    setConflict(false);
    setFitImage(true);
    setZoom(1);
    setNaturalSize({ width: 0, height: 0 });
  }, [selectedEvidenceId]);

  const chooseResult = (result) => {
    setQcResult(result);
    setReasonCode({
      sampled_pass: "visual_match",
      sampled_fail: "ocr_content_mismatch",
      manual_review_required: "requires_manual_review",
    }[result]);
  };

  const submitVisualQc = async () => {
    if (!selectedItem || !userReason.trim() || submitting) return;
    const idempotencyKey = globalThis.crypto?.randomUUID?.()
      || `eligibility-visual-qc-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const payload = {
      expected_qc_revision: selectedItem.visual_qc?.qc_revision || 0,
      expected_source_revision: selectedItem.source_revision,
      expected_extraction_revision: selectedItem.extraction_revision,
      idempotency_key: idempotencyKey,
      result: qcResult,
      reason_code: reasonCode,
      user_reason: userReason.trim(),
      policy_version: "eligibility_visual_qc_policy_v1",
      actor: "medical_manager",
    };
    if (qcResult !== "manual_review_required") {
      payload.sample_plan_id = "medical_manager_visual_sampling_v1";
      payload.sample_unit = {
        evidence_id: selectedItem.evidence_id,
        locator: selectedItem.locator,
      };
    }
    setSubmitting(true);
    setError("");
    setNotice("");
    setConflict(false);
    try {
      const response = await fetch(
        `/api/projects/${routeProjectId}/eligibility/raw-intake/subjects/${subjectId}/evidence-spans/${selectedItem.evidence_id}/visual-qc-records`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
      );
      const responsePayload = await response.json().catch(() => ({}));
      if (!response.ok) {
        if (response.status === 409) {
          await loadQueue(queue.offset, selectedItem.evidence_id);
          setConflict(true);
          setError("该证据的来源、提取或复核版本已更新，已重新读取当前队列。请核对原图与文字后再次提交。");
          return;
        }
        throw new Error(apiDetailText(responsePayload, `提交失败：${response.status}`));
      }
      setNotice(`已记录“${visualQcResultLabels[qcResult]}”，复核版本 ${responsePayload.qc_revision}。`);
      setUserReason("");
      await loadQueue(queue.offset, selectedItem.evidence_id);
    } catch (submitError) {
      setError(`视觉复核记录未保存：${apiErrorText(submitError)}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="page eligibility-qc-page">
      <SectionTitle
        eyebrow="入排审核"
        title={`${subjectId} · 原始资料视觉 QC`}
        action={(
          <button className="secondary-button eligibility-qc-return" onClick={onReturn}>
            <ArrowLeft size={16} /> 返回审阅账本
          </button>
        )}
      />
      <div className="eligibility-qc-boundary" role="note">
        <ScanSearch size={17} />
        <span><strong>视觉 QC 边界：</strong>本工作区只核对原图与 OCR 文本的一致性和可读性，不判断受试者是否符合入排标准，也不构成随机化放行。</span>
      </div>
      {(error || notice) && (
        <div className={`eligibility-qc-message ${error ? "error" : "success"} ${conflict ? "conflict" : ""}`}>
          <span>{error || notice}</span>
          {error && (
            <button className="secondary-button" onClick={() => loadQueue(queue.offset, selectedEvidenceId)} disabled={loading}>
              <RefreshCw size={15} /> 刷新当前队列
            </button>
          )}
        </div>
      )}

      <div className="eligibility-qc-overflow">
        <section className="eligibility-qc-workspace" aria-label="原始资料视觉复核工作区">
          <aside className="eligibility-qc-queue-pane">
            <div className="eligibility-qc-pane-head">
              <div>
                <strong>复核队列</strong>
                <span>{pageStart}-{pageEnd} / {queue.total} 个证据单元</span>
              </div>
              <button className="icon-button" title="刷新视觉复核队列" onClick={() => loadQueue(queue.offset, selectedEvidenceId)} disabled={loading}>
                <RefreshCw size={16} className={loading ? "spin" : ""} />
              </button>
            </div>
            <div className="eligibility-qc-progress">
              <div><span>全部已复核 {reviewedCount}/{queue.overallTotal}</span><strong>{overallProgress}%</strong></div>
              <span><i style={{ width: `${overallProgress}%` }} /></span>
            </div>
            <div className="eligibility-qc-filters" role="group" aria-label="复核状态筛选">
              {[
                ["pending", "待复核"],
                ["sampled_pass", "通过"],
                ["sampled_fail", "不通过"],
                ["manual_review_required", "专项复核"],
                ["all", "全部"],
              ].map(([value, label]) => (
                <button
                  key={value}
                  className={statusFilter === value ? "active" : ""}
                  onClick={() => {
                    setStatusFilter(value);
                    loadQueue(0, "", value);
                  }}
                >
                  {label} {value === "all" ? queue.overallTotal : (queue.statusCounts[value] || 0)}
                </button>
              ))}
            </div>
            <div className="eligibility-qc-queue-list">
              {queue.items.map((item) => (
                <button
                  key={item.evidence_id}
                  className={selectedEvidenceId === item.evidence_id ? "selected" : ""}
                  onClick={() => {
                    setNotice("");
                    setSelectedEvidenceId(item.evidence_id);
                  }}
                >
                  <span className="eligibility-qc-sequence">{String(queue.offset + queue.items.indexOf(item) + 1).padStart(3, "0")}</span>
                  <span className="eligibility-qc-queue-copy">
                    <strong>{visualQcLocatorText(item.locator)}</strong>
                    <small>{visualQcMediaClassLabel(item.media_class)} · OCR {item.text_character_count?.toLocaleString("zh-CN") || 0} 字</small>
                  </span>
                  <Tag tone={visualQcTone(item.visual_qc?.result)}>{visualQcResultLabels[item.visual_qc?.result] || "待复核"}</Tag>
                </button>
              ))}
              {!queue.items.length && <p className="eligibility-qc-empty">当前受试者没有符合此状态的证据单元。</p>}
            </div>
            <div className="eligibility-qc-paging">
              <button
                disabled={!canGoBack}
                title={canGoBack ? "查看上一页证据单元" : "当前已是第一页"}
                onClick={() => loadQueue(Math.max(0, queue.offset - queue.limit), "")}
              >上一页</button>
              <span>第 {queue.total ? Math.floor(queue.offset / queue.limit) + 1 : 0} / {Math.ceil(queue.total / queue.limit) || 0} 页</span>
              <button
                disabled={!canGoForward}
                title={canGoForward ? "查看下一页证据单元" : "当前已是最后一页"}
                onClick={() => loadQueue(queue.offset + queue.limit, "")}
              >下一页</button>
            </div>
          </aside>

          <section className="eligibility-qc-image-pane">
            <div className="eligibility-qc-pane-head">
              <div>
                <strong>原始资料</strong>
                <span>{selectedItem ? visualQcLocatorText(selectedItem.locator) : "请选择证据单元"}</span>
              </div>
              <div className="eligibility-qc-image-tools" role="group" aria-label="原图缩放工具">
                <button className={fitImage ? "active" : ""} onClick={() => { setFitImage(true); setZoom(1); }}>适应</button>
                <button className={!fitImage && zoom === 1 ? "active" : ""} onClick={() => { setFitImage(false); setZoom(1); }}>100%</button>
                <button title="缩小原图" onClick={() => { setFitImage(false); setZoom((value) => Math.max(0.25, Number((value - 0.25).toFixed(2)))); }} disabled={!selectedItem || zoom <= 0.25}><ZoomOut size={16} /></button>
                <span>{Math.round(zoom * 100)}%</span>
                <button title="放大原图" onClick={() => { setFitImage(false); setZoom((value) => Math.min(3, Number((value + 0.25).toFixed(2)))); }} disabled={!selectedItem || zoom >= 3}><ZoomIn size={16} /></button>
              </div>
            </div>
            <div className="eligibility-qc-image-stage">
              {selectedItem ? (
                <img
                  key={selectedItem.image_artifact_id}
                  src={imageUrl}
                  alt={`受试者 ${subjectId} ${visualQcLocatorText(selectedItem.locator)}原始资料`}
                  className={fitImage ? "fit" : ""}
                  style={!fitImage && naturalSize.width ? { width: `${naturalSize.width * zoom}px`, height: `${naturalSize.height * zoom}px` } : undefined}
                  onLoad={(event) => setNaturalSize({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })}
                  onError={() => setError("原始资料图像读取失败或完整性校验未通过，请刷新队列后重试。")}
                />
              ) : (
                <div className="eligibility-qc-empty-stage"><ScanSearch size={28} /><span>从左侧队列选择一个证据单元。</span></div>
              )}
            </div>
          </section>

          <aside className="eligibility-qc-review-pane">
            <div className="eligibility-qc-pane-head">
              <div>
                <strong>OCR 文本与复核记录</strong>
                <span>用户主动提交后写入不可变复核记录</span>
              </div>
              {selectedItem && <Tag tone={visualQcTone(selectedItem.visual_qc?.result)}>{visualQcResultLabels[selectedItem.visual_qc?.result] || "待复核"}</Tag>}
            </div>
            {selectedItem ? (
              <div className="eligibility-qc-review-scroll">
                <dl className="eligibility-qc-meta">
                  <div><dt>资料定位</dt><dd>{visualQcLocatorText(selectedItem.locator)}</dd></div>
                  <div><dt>媒体类型</dt><dd>{visualQcMediaClassLabel(selectedItem.media_class)}</dd></div>
                  <div><dt>文字长度</dt><dd>{selectedItem.text_character_count?.toLocaleString("zh-CN") || 0} 字</dd></div>
                  <div><dt>当前复核版本</dt><dd>{selectedItem.visual_qc?.qc_revision || 0}</dd></div>
                </dl>
                <div className="eligibility-qc-text-block">
                  <div><strong>OCR 提取文本</strong><span>请逐项对照左侧原图</span></div>
                  <pre>{selectedItem.text || "当前证据单元未提取到可显示文字。"}</pre>
                </div>
                <div className="eligibility-qc-form">
                  <strong>视觉复核结论</strong>
                  <div className="eligibility-qc-result-options" role="radiogroup" aria-label="视觉复核结论">
                    {Object.entries(visualQcResultLabels).map(([value, label]) => (
                      <button key={value} className={qcResult === value ? `active ${visualQcTone(value)}` : ""} onClick={() => chooseResult(value)}>{label}</button>
                    ))}
                  </div>
                  <label>
                    <span>复核理由分类</span>
                    <select value={reasonCode} onChange={(event) => setReasonCode(event.target.value)}>
                      {qcResult === "sampled_pass" && <option value="visual_match">原图与 OCR 文本一致</option>}
                      {qcResult === "sampled_fail" && <option value="ocr_content_mismatch">OCR 文字缺失、错识别或顺序异常</option>}
                      {qcResult === "sampled_fail" && <option value="source_unreadable">原始资料模糊、遮挡或不可读</option>}
                      {qcResult === "manual_review_required" && <option value="requires_manual_review">需人工专项复核</option>}
                      {qcResult === "manual_review_required" && <option value="source_unreadable">原始资料模糊、遮挡或不可读</option>}
                    </select>
                  </label>
                  <label>
                    <span>复核说明（必填）</span>
                    <textarea rows={4} value={userReason} onChange={(event) => setUserReason(event.target.value)} placeholder="记录核对范围、差异位置和处理依据；不得在此填写受试者资格结论。" />
                  </label>
                  <p>提交仅确认该证据单元的视觉质量，不更新 IN/EX 医学判断。</p>
                  <button
                    className="primary-button eligibility-qc-submit"
                    disabled={!userReason.trim() || submitting}
                    title={!userReason.trim() ? "请填写复核说明" : submitting ? "复核记录正在写入" : "提交视觉复核记录"}
                    onClick={submitVisualQc}
                  >
                    <FileCheck2 size={16} /> {submitting ? "正在写入复核记录" : "提交视觉复核记录"}
                  </button>
                </div>
              </div>
            ) : (
              <div className="eligibility-qc-empty-stage"><span>当前筛选下未选择证据单元。</span></div>
            )}
          </aside>
        </section>
      </div>
    </main>
  );
}

function EligibilityPage({ projectId, routeProjectId }) {
  const rawSubjectRequestIdRef = useRef(0);
  const reviewIdentityRef = useRef("");
  const preservedReviewReasonRef = useRef(null);
  const [dataset, setDataset] = useState(null);
  const [rawIntake, setRawIntake] = useState(null);
  const [rawSubjects, setRawSubjects] = useState([]);
  const [selectedRuleType, setSelectedRuleType] = useState("inclusion");
  const [selectedRawSubject, setSelectedRawSubject] = useState(null);
  const [selectedRawSubjectId, setSelectedRawSubjectId] = useState("");
  const [reviewPackage, setReviewPackage] = useState(null);
  const [selectedCriterionUid, setSelectedCriterionUid] = useState("");
  const [selectedEvidenceIds, setSelectedEvidenceIds] = useState([]);
  const [medicalDecisionDraft, setMedicalDecisionDraft] = useState("");
  const [reviewReason, setReviewReason] = useState("");
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewActionBusy, setReviewActionBusy] = useState(false);
  const [reviewError, setReviewError] = useState("");
  const [reviewConflict, setReviewConflict] = useState(false);
  const [reviewReloadToken, setReviewReloadToken] = useState(0);
  const [query, setQuery] = useState({ subjectId: "", phaseId: "" });
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [rawLoading, setRawLoading] = useState(false);
  const [error, setError] = useState("");
  const [rawError, setRawError] = useState("");
  const [eligibilityView, setEligibilityView] = useState("ledger");
  const [sourceAdmission, setSourceAdmission] = useState(null);
  const [sourceAdmissionLoading, setSourceAdmissionLoading] = useState(false);
  const [sourceAdmissionError, setSourceAdmissionError] = useState("");
  const [admissionConfirmationTarget, setAdmissionConfirmationTarget] = useState(null);
  const [admissionConfirmationReason, setAdmissionConfirmationReason] = useState("");
  const [admissionAcknowledgedCodes, setAdmissionAcknowledgedCodes] = useState([]);
  const [admissionConfirmedRecord, setAdmissionConfirmedRecord] = useState(null);
  const sourceAdmissionRequestIdRef = useRef(0);

  const resetSourceAdmissionForm = (clearConfirmedRecord = true) => {
    setAdmissionConfirmationTarget(null);
    setAdmissionConfirmationReason("");
    setAdmissionAcknowledgedCodes([]);
    if (clearConfirmedRecord) setAdmissionConfirmedRecord(null);
  };

  const refreshSourceAdmission = async () => {
    const requestId = ++sourceAdmissionRequestIdRef.current;
    setSourceAdmissionLoading(true);
    setSourceAdmissionError("");
    try {
      const response = await fetch(`/api/projects/${routeProjectId}/eligibility/source-admission/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      const payload = await response.json().catch(() => ({}));
      if (requestId !== sourceAdmissionRequestIdRef.current) return;
      if (!response.ok) throw new Error(apiDetailText(payload, `来源准入刷新失败：${response.status}`));
      setSourceAdmission(payload);
    } catch (admissionError) {
      if (requestId !== sourceAdmissionRequestIdRef.current) return;
      setSourceAdmissionError(apiErrorText(admissionError));
    } finally {
      if (requestId === sourceAdmissionRequestIdRef.current) setSourceAdmissionLoading(false);
    }
  };

  const submitAdmissionConfirmation = async () => {
    if (!admissionConfirmationTarget) return;
    const requestId = ++sourceAdmissionRequestIdRef.current;
    setSourceAdmissionLoading(true);
    setSourceAdmissionError("");
    try {
      const response = await fetch(`/api/projects/${routeProjectId}/sources/${admissionConfirmationTarget.entry.entry_id}/content-validation/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          reason: admissionConfirmationReason.trim(),
          acknowledged_check_codes: admissionAcknowledgedCodes,
          expected_revision: admissionConfirmationTarget.expectedRevision,
          idempotency_key: admissionConfirmationTarget.idempotencyKey,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (requestId !== sourceAdmissionRequestIdRef.current) return;
      if (!response.ok) throw new Error(apiDetailText(payload, `确认记录失败：${response.status}`));
      setAdmissionConfirmedRecord({
        entryId: admissionConfirmationTarget.entry.entry_id,
        sourceKind: admissionConfirmationTarget.entry.source_kind,
        contentStatus: payload.content_status || admissionConfirmationTarget.contentStatus,
        useStatus: payload.use_status || "confirmed_after_warning",
        reason: admissionConfirmationReason.trim(),
        actor: payload.actor || "服务器核验身份",
        at: new Date().toLocaleString("zh-CN"),
      });
      resetSourceAdmissionForm(false);
      await refreshSourceAdmission();
    } catch (confirmationError) {
      if (requestId !== sourceAdmissionRequestIdRef.current) return;
      setSourceAdmissionError(apiErrorText(confirmationError));
    } finally {
      if (requestId === sourceAdmissionRequestIdRef.current) setSourceAdmissionLoading(false);
    }
  };

  const reloadReviewPackage = (preserveReason = false) => {
    preservedReviewReasonRef.current = preserveReason ? reviewReason : null;
    setReviewReloadToken((value) => value + 1);
  };

  useEffect(() => {
    if (projectId !== "proj_mgk10_sar_demo") {
      setDataset(null);
      setLoading(false);
      setError("");
      return undefined;
    }
    let cancelled = false;
    const params = new URLSearchParams();
    if (query.subjectId) params.set("subject_id", query.subjectId);
    if (query.phaseId) params.set("phase_id", query.phaseId);
    setLoading(true);
    setError("");
    fetch(`/api/projects/${projectId}/eligibility${params.toString() ? `?${params.toString()}` : ""}`)
      .then((response) => (response.ok ? response.json() : Promise.reject(response)))
      .then((data) => {
        if (!cancelled) setDataset(data);
      })
      .catch((response) => {
        if (!cancelled) setError(`入排审核数据读取失败：${response.status || "network"}`);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, query.subjectId, query.phaseId]);

  useEffect(() => {
    let cancelled = false;
    setRawLoading(true);
    setRawError("");
    fetch(`/api/projects/${routeProjectId}/eligibility/raw-intake`)
      .then((response) => (response.ok ? response.json() : Promise.reject(response)))
      .then((data) => {
        if (!cancelled) setRawIntake(data);
      })
      .catch((response) => {
        if (!cancelled) setRawError(`原始资料池读取失败：${response.status || "network"}`);
      })
      .finally(() => {
        if (!cancelled) setRawLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [routeProjectId]);

  useEffect(() => {
    let cancelled = false;
    const requestId = ++sourceAdmissionRequestIdRef.current;
    resetSourceAdmissionForm();
    setSourceAdmission(null);
    setSourceAdmissionError("");
    setSourceAdmissionLoading(true);
    fetch(`/api/projects/${routeProjectId}/eligibility/source-admission/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    })
      .then(readJsonOrThrow)
      .then((data) => {
        if (!cancelled && requestId === sourceAdmissionRequestIdRef.current) setSourceAdmission(data);
      })
      .catch((error) => {
        if (!cancelled && requestId === sourceAdmissionRequestIdRef.current) setSourceAdmissionError(`来源准入刷新失败：${apiErrorText(error)}`);
      })
      .finally(() => {
        if (!cancelled && requestId === sourceAdmissionRequestIdRef.current) setSourceAdmissionLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [routeProjectId]);

  useEffect(() => {
    let cancelled = false;
    rawSubjectRequestIdRef.current += 1;
    reviewIdentityRef.current = "";
    preservedReviewReasonRef.current = null;
    setSelectedRuleType("inclusion");
    setRawSubjects([]);
    setSelectedRawSubject(null);
    setSelectedRawSubjectId("");
    setEligibilityView("ledger");
    fetch(`/api/projects/${routeProjectId}/eligibility/raw-intake/subjects`)
      .then(readJsonOrThrow)
      .then((data) => {
        if (cancelled) return;
        const subjects = Array.isArray(data.subjects) ? data.subjects : [];
        setRawSubjects(subjects);
        setSelectedRawSubjectId(subjects[0]?.subject_id || "");
      })
      .catch((response) => {
        if (!cancelled) setRawError(`候选受试者清单读取失败：${apiErrorText(response)}`);
      });
    return () => {
      cancelled = true;
    };
  }, [routeProjectId]);

  useEffect(() => {
    if (!selectedRawSubjectId) {
      reviewIdentityRef.current = "";
      preservedReviewReasonRef.current = null;
      setSelectedRawSubject(null);
      setReviewPackage(null);
      setSelectedCriterionUid("");
      setSelectedEvidenceIds([]);
      setMedicalDecisionDraft("");
      setReviewReason("");
      return undefined;
    }
    let cancelled = false;
    const requestId = ++rawSubjectRequestIdRef.current;
    const reviewIdentity = `${routeProjectId}::${selectedRawSubjectId}`;
    const identityChanged = reviewIdentityRef.current !== reviewIdentity;
    reviewIdentityRef.current = reviewIdentity;
    if (identityChanged) {
      preservedReviewReasonRef.current = null;
      setSelectedRawSubject(null);
      setReviewPackage(null);
      setSelectedCriterionUid("");
      setSelectedEvidenceIds([]);
      setMedicalDecisionDraft("");
      setReviewReason("");
    }
    setReviewError("");
    setReviewConflict(false);
    setReviewLoading(true);
    fetch(`/api/projects/${routeProjectId}/eligibility/raw-intake/subjects/${selectedRawSubjectId}/review`)
      .then(readJsonOrThrow)
      .then((data) => {
        if (
          !cancelled
          && requestId === rawSubjectRequestIdRef.current
          && data.project_id === data.subject?.project_id
          && data.subject?.subject_id === selectedRawSubjectId
        ) {
          setSelectedRawSubject(data.subject);
          setReviewPackage(data);
          setSelectedCriterionUid((currentCriterionUid) => {
            const currentCriterion = (data.criteria || []).find(
              (item) => item.criterion_uid === currentCriterionUid && item.criterion_kind === selectedRuleType,
            );
            const firstCriterion = (data.criteria || []).find((item) => item.criterion_kind === selectedRuleType)
              || data.criteria?.[0];
            return currentCriterion?.criterion_uid || firstCriterion?.criterion_uid || "";
          });
        }
      })
      .catch((response) => {
        if (!cancelled) setReviewError(`受试者审阅包读取失败：${apiErrorText(response)}`);
      })
      .finally(() => {
        if (!cancelled && requestId === rawSubjectRequestIdRef.current) setReviewLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [routeProjectId, selectedRawSubjectId, reviewReloadToken]);

  const handleRawSubjectSelect = (subjectId) => {
    if (subjectId === selectedRawSubjectId) return;
    rawSubjectRequestIdRef.current += 1;
    reviewIdentityRef.current = "";
    preservedReviewReasonRef.current = null;
    setSelectedRawSubject(null);
    setReviewPackage(null);
    setSelectedCriterionUid("");
    setSelectedEvidenceIds([]);
    setMedicalDecisionDraft("");
    setReviewReason("");
    setRawError("");
    setReviewError("");
    setReviewConflict(false);
    resetSourceAdmissionForm();
    setSelectedRawSubjectId(subjectId);
  };

  useEffect(() => {
    const matchingCriteria = (reviewPackage?.criteria || []).filter(
      (item) => item.criterion_kind === selectedRuleType,
    );
    if (!matchingCriteria.some((item) => item.criterion_uid === selectedCriterionUid)) {
      setSelectedCriterionUid(matchingCriteria[0]?.criterion_uid || "");
    }
  }, [reviewPackage, selectedCriterionUid, selectedRuleType]);

  const reviewCriteria = reviewPackage?.criteria || [];
  const criteriaForSelectedKind = reviewCriteria.filter(
    (item) => item.criterion_kind === selectedRuleType,
  );
  const selectedCriterion = reviewCriteria.find(
    (item) => item.criterion_uid === selectedCriterionUid,
  ) || null;
  const selectedCriterionState = selectedCriterion?.state || null;
  const reviewEvidence = reviewPackage?.evidence || [];
  const evidenceById = new Map(reviewEvidence.map((item) => [item.evidence_id, item]));
  const selectedEvidence = selectedEvidenceIds
    .map((evidenceId) => evidenceById.get(evidenceId))
    .filter(Boolean);
  const selectedEvidenceCompleted = selectedEvidence.length > 0
    && selectedEvidence.every((item) => item.processing_state === "completed");
  const reviewStateHasDrift = Boolean(
    selectedCriterionState
    && (
      selectedCriterionState.rule_revision !== reviewPackage?.rule_revision
      || selectedCriterionState.subject_source_revision !== reviewPackage?.subject_source_revision
    ),
  );

  useEffect(() => {
    const stateEvidenceIds = (selectedCriterionState?.evidence_ids || []).filter(
      (evidenceId) => evidenceById.has(evidenceId),
    );
    setSelectedEvidenceIds(stateEvidenceIds);
    setMedicalDecisionDraft(selectedCriterionState?.medical_decision || "");
    setReviewReason(preservedReviewReasonRef.current ?? "");
    preservedReviewReasonRef.current = null;
    setReviewError("");
    setReviewConflict(false);
  }, [
    reviewPackage,
    selectedCriterionUid,
  ]);

  const decisionOptions = selectedCriterion?.criterion_kind === "exclusion"
    ? [
      { value: "absent", label: "未发现该排除条件" },
      { value: "present", label: "存在该排除条件" },
      { value: "insufficient_evidence", label: "证据不足" },
      { value: "requires_investigator_judgment", label: "需研究者判断" },
      { value: "not_applicable", label: "不适用" },
    ]
    : [
      { value: "met", label: "符合该纳入条件" },
      { value: "not_met", label: "不符合该纳入条件" },
      { value: "insufficient_evidence", label: "证据不足" },
      { value: "requires_investigator_judgment", label: "需研究者判断" },
      { value: "not_applicable", label: "不适用" },
    ];
  const decisionLabel = (decision) => decisionOptions.find((item) => item.value === decision)?.label || "未形成判断";
  const decisiveDecision = ["met", "not_met", "absent", "present"].includes(medicalDecisionDraft);
  const insufficientDecision = medicalDecisionDraft === "insufficient_evidence";
  const medicalDecisionEvidenceReady = !decisiveDecision || selectedEvidenceCompleted;
  const insufficientEvidenceReady = !insufficientDecision || selectedEvidenceCompleted;
  const sourceAdmissionReady = Boolean(sourceAdmission?.ready_for_use);
  const canSaveMedicalDecision = Boolean(
    selectedCriterion
    && medicalDecisionDraft
    && reviewReason.trim()
    && medicalDecisionEvidenceReady
    && insufficientEvidenceReady
    && !reviewActionBusy
    && sourceAdmissionReady,
  );
  const canAcceptAiDraft = Boolean(
    selectedCriterionState?.ai_draft_decision
    && selectedEvidenceCompleted
    && reviewReason.trim()
    && !reviewActionBusy
    && sourceAdmissionReady,
  );

  const submitReviewAction = async (action, decision = null) => {
    if (!selectedCriterion || !reviewPackage || !reviewReason.trim()) return;
    const actionEvidenceIds = action === "reset_after_source_change" ? [] : selectedEvidenceIds;
    let evidenceProcessingState = "not_started";
    if (action === "request_evidence") evidenceProcessingState = "queued";
    else if (action === "reset_after_source_change") evidenceProcessingState = "not_started";
    else if (decision === "not_applicable") evidenceProcessingState = "not_applicable";
    else if (selectedEvidence.length) evidenceProcessingState = selectedEvidenceCompleted ? "completed" : "partial";
    else if (selectedCriterionState?.evidence_processing_state) {
      evidenceProcessingState = selectedCriterionState.evidence_processing_state;
    }
    const idempotencyKey = globalThis.crypto?.randomUUID?.()
      || `eligibility-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const payload = {
      criterion_kind: selectedCriterion.criterion_kind,
      expected_state_revision: selectedCriterionState?.state_revision || 0,
      expected_rule_revision: reviewPackage.rule_revision,
      expected_subject_source_revision: reviewPackage.subject_source_revision,
      idempotency_key: idempotencyKey,
      actor: "medical_manager",
      action,
      reason: reviewReason.trim(),
      evidence_ids: actionEvidenceIds,
      evidence_processing_state: evidenceProcessingState,
    };
    if (decision !== null) payload.decision = decision;
    setReviewActionBusy(true);
    setReviewError("");
    setReviewConflict(false);
    try {
      const response = await fetch(
        `/api/projects/${routeProjectId}/eligibility/raw-intake/subjects/${selectedRawSubjectId}/criteria/${selectedCriterion.criterion_uid}/actions`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
      );
      const responsePayload = await response.json().catch(() => ({}));
      if (!response.ok) {
        if (response.status === 409) {
          const detail = responsePayload?.detail;
          if (detail && typeof detail === "object" && detail.code === "eligibility_source_confirmation_required") {
            setSourceAdmissionError(detail.message || detail.detail || "来源内容存在警告或不一致，需确认沿用后才能保存审阅动作。");
            await refreshSourceAdmission();
            return;
          }
          setReviewConflict(true);
          setReviewError("审阅状态或来源版本已更新。请刷新后重新确认本条标准。");
          return;
        }
        throw new Error(apiDetailText(responsePayload, `提交失败：${response.status}`));
      }
      preservedReviewReasonRef.current = null;
      setReviewReason("");
      reloadReviewPackage(false);
    } catch (actionError) {
      setReviewError(`审阅动作未保存：${apiErrorText(actionError)}`);
    } finally {
      setReviewActionBusy(false);
    }
  };

  const legacyDataset = dataset;
  const rawTaskPlan = rawIntake?.ai_task_plan || [];
  const rawForbiddenInputs = rawIntake?.forbidden_legacy_inputs || [];
  const rawAiStatuses = rawIntake?.ai_task_plan?.map((task) => task.status) || [];
  const rawAiBlocked = rawAiStatuses.some((status) => status === "blocked_external_ai_not_configured");
  const rawSourceTypes = rawIntake?.subject_pool?.source_type_counts || {};
  const rawSourceTypeLabel = Object.entries(rawSourceTypes)
    .map(([key, value]) => `${key} ${value}`)
    .join(" / ");
  const rawEligibilityReviewReady = rawTaskPlan.some((task) => task.task_type === "eligibility_rule_review" && task.status === "completed");
  const subjectRows = rawSubjects;
  const normalizedSearch = search.trim().toLowerCase();
  const filteredRows = subjectRows.filter((row) => {
    if (!normalizedSearch) return true;
    return [row.subject_id, row.subject_token, ...Object.keys(row.source_type_counts || {})]
      .some((value) => String(value || "").toLowerCase().includes(normalizedSearch));
  });
  const selected = selectedRawSubject;
  const inclusionCount = reviewCriteria.filter((item) => item.criterion_kind === "inclusion").length;
  const exclusionCount = reviewCriteria.filter((item) => item.criterion_kind === "exclusion").length;
  const reviewedInclusionCount = reviewCriteria.filter(
    (item) => item.criterion_kind === "inclusion" && item.state?.medical_decision,
  ).length;
  const reviewedExclusionCount = reviewCriteria.filter(
    (item) => item.criterion_kind === "exclusion" && item.state?.medical_decision,
  ).length;
  const aggregateStatusLabels = {
    blocked_by_incomplete_review: "逐条医学审阅未完成",
    blocked_by_missing_rules: "方案规则缺失",
    has_gaps: "存在证据缺口",
    has_investigator_judgment: "存在需研究者判断项",
    has_inclusion_failure: "存在不符合的纳入标准",
    has_exclusion: "存在符合的排除标准",
    medical_review_pending: "待医学审阅",
  };

  if (eligibilityView === "visual_qc") {
    return (
      <EligibilityVisualQcWorkspace
        routeProjectId={routeProjectId}
        subjectId={selectedRawSubjectId}
        onReturn={() => setEligibilityView("ledger")}
      />
    );
  }

  return (
    <main className="page">
      <SectionTitle
        eyebrow="入排审核"
        title="受试者逐条标准审阅"
        action={(
          <div className="eligibility-head-actions">
            <Tag tone="warning">待医学确认的工作内容</Tag>
            <button
              className="secondary-button eligibility-qc-entry"
              disabled={!selectedRawSubjectId}
              title={selectedRawSubjectId ? "进入当前受试者原始资料视觉 QC" : "请先选择受试者"}
              onClick={() => setEligibilityView("visual_qc")}
            >
              <ScanSearch size={16} /> 原始资料视觉 QC
            </button>
          </div>
        )}
      />
      <SourceAdmissionBand
        sourceAdmission={sourceAdmission}
        loading={sourceAdmissionLoading}
        error={sourceAdmissionError}
        confirmationTarget={admissionConfirmationTarget}
        setConfirmationTarget={setAdmissionConfirmationTarget}
        confirmationReason={admissionConfirmationReason}
        setConfirmationReason={setAdmissionConfirmationReason}
        acknowledgedCodes={admissionAcknowledgedCodes}
        setAcknowledgedCodes={setAdmissionAcknowledgedCodes}
        confirmedRecord={admissionConfirmedRecord}
        onConfirm={submitAdmissionConfirmation}
        onRefresh={refreshSourceAdmission}
      />
      <section className="eligibility-status panel">
        <div>
          <strong>{rawIntake?.project_label || "原始入排资料池"}</strong>
          <span>{rawIntake?.protocol?.filename || "读取当前研究方案中"}</span>
        </div>
        <div>
          <strong>{reviewPackage?.aggregate?.reviewed_count ?? 0} / {reviewPackage?.aggregate?.criterion_count ?? (inclusionCount + exclusionCount || "-")} 条已医学审阅</strong>
          <span>{selected?.subject_id || "选择受试者"} · 原始文件 {selected?.file_count ?? "-"} 份</span>
        </div>
        <div>
          <strong>IN {reviewedInclusionCount}/{inclusionCount || "-"} · EX {reviewedExclusionCount}/{exclusionCount || "-"}</strong>
          <span>IN 与 EX 使用独立判断语义和状态</span>
        </div>
        <div>
          <strong>{reviewLoading ? "正在同步审阅包" : "逐条审阅状态"}</strong>
          <span>{(reviewPackage?.aggregate?.statuses || []).map((status) => aggregateStatusLabels[status] || status).join("；") || "等待选择受试者"}</span>
        </div>
        <div className={sourceAdmissionReady ? "" : "source-context-unconfigured"}>
          <strong>{sourceAdmissionLoading ? "来源准入检查中" : sourceAdmissionReady ? "来源准入已就绪" : "来源准入未就绪"}</strong>
          <span>{sourceAdmissionError ? sourceAdmissionError : sourceAdmission?.missing_source_kinds?.length ? `缺 ${sourceAdmission.missing_source_kinds.join("、")}` : "可保存审阅动作"}</span>
        </div>
      </section>
      <p className="eligibility-boundary-line">
        仅提供逐条标准审阅支持，不作出正式资格审核结论或随机化放行。AI 内容与医学判断分层记录，医学判断必须由用户主动确认。
      </p>
      {(error || rawError || reviewError || sourceAdmissionError) && (
        <section className={`panel gate-error ${reviewConflict ? "eligibility-conflict-banner" : ""}`}>
          <span>{error || rawError || reviewError || sourceAdmissionError}</span>
          <div className="gate-error-actions">
            <button className="secondary-button eligibility-review-retry" onClick={() => reloadReviewPackage(true)}>
              <RefreshCw size={15} /> {reviewConflict ? "刷新审阅状态" : "重新载入审阅包"}
            </button>
            {sourceAdmissionError && (
              <button className="secondary-button" onClick={refreshSourceAdmission} disabled={sourceAdmissionLoading} title="刷新来源准入状态">
                <RefreshCw size={15} /> 刷新来源准入
              </button>
            )}
          </div>
        </section>
      )}

      <div className="eligibility-workbench">
        <section className="panel eligibility-subjects-panel">
          <SectionTitle
            title="候选受试者池"
            action={<Tag tone={rawLoading ? "warning" : "info"}>{rawLoading ? "读取中" : `${rawIntake?.subject_pool?.unique_subject_count ?? 0} 名`}</Tag>}
          />
          <div className="eligibility-subject-summary">
            <span>原始文件 <strong>{rawIntake?.subject_pool?.total_files ?? "-"}</strong></span>
            <span>待 OCR/VLM <strong>{rawIntake?.subject_pool?.needs_ocr_vlm_count ?? "-"}</strong></span>
          </div>
          <div className="search-row eligibility-subject-search">
            <Search size={16} />
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索受试者或资料类型" />
          </div>
          <div className="eligibility-table-wrap">
            <table className="eligibility-subject-table">
              <thead>
                <tr>
                  <th>受试者</th>
                  <th>资料数</th>
                  <th>处理状态</th>
                </tr>
              </thead>
              <tbody>
                {filteredRows.map((row) => (
                  <tr key={row.subject_id} className={selectedRawSubjectId === row.subject_id ? "selected" : ""}>
                    <td>
                      <button
                        className="subject-link"
                        onClick={() => handleRawSubjectSelect(row.subject_id)}
                      >
                        {row.subject_id}
                      </button>
                    </td>
                    <td>{row.file_count}</td>
                    <td><Tag tone={selectedRawSubjectId === row.subject_id && reviewPackage ? "info" : "warning"}>{selectedRawSubjectId === row.subject_id && reviewPackage ? "审阅中" : "待处理"}</Tag></td>
                  </tr>
                ))}
                {!filteredRows.length && (
                  <tr>
                    <td colSpan={3}>
                      <div className="raw-pending-state">
                        {search ? "没有匹配的受试者原始资料。" : "候选受试者清单正在从当前项目原始资料生成；系统不会使用其他项目结果填充。"}
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="panel eligibility-criterion-ledger">
          <SectionTitle
            title={selected ? `${selected.subject_id} · 审阅账本` : "逐条标准审阅"}
            action={<Tag tone={reviewLoading ? "warning" : "info"}>{reviewLoading ? "同步中" : `${reviewPackage?.aggregate?.reviewed_count ?? 0} 条已审阅`}</Tag>}
          />
          {reviewPackage ? (
            <>
              <div className="eligibility-rule-tabs" role="tablist" aria-label="入排标准类型">
                <button className={selectedRuleType === "inclusion" ? "active" : ""} onClick={() => setSelectedRuleType("inclusion")}>
                  入选 IN <span>{reviewedInclusionCount}/{inclusionCount}</span>
                </button>
                <button className={selectedRuleType === "exclusion" ? "active" : ""} onClick={() => setSelectedRuleType("exclusion")}>
                  排除 EX <span>{reviewedExclusionCount}/{exclusionCount}</span>
                </button>
              </div>
              <div className="eligibility-aggregate-strip">
                {(reviewPackage.aggregate?.statuses || []).map((status) => (
                  <Tag key={status} tone={status === "blocked_by_incomplete_review" ? "warning" : "info"}>{aggregateStatusLabels[status] || status}</Tag>
                ))}
                <span>该状态用于组织审阅工作，不代表正式入排结论。</span>
              </div>
              <div className="eligibility-criterion-list">
                {criteriaForSelectedKind.map((criterion) => {
                  const state = criterion.state;
                  const rowStatus = state?.medical_decision
                    ? decisionOptions.find((item) => item.value === state.medical_decision)?.label || state.medical_decision
                    : state?.ai_draft_decision
                      ? "AI 草稿待医学确认"
                      : state?.latest_action === "request_evidence"
                        ? "待补充证据"
                        : state?.latest_action === "defer_review"
                          ? "已延期审阅"
                          : "待医学审阅";
                  return (
                    <button
                      key={criterion.criterion_uid}
                      className={`eligibility-criterion-row ${selectedCriterionUid === criterion.criterion_uid ? "selected" : ""}`}
                      onClick={() => setSelectedCriterionUid(criterion.criterion_uid)}
                    >
                      <span className="eligibility-criterion-id">{criterion.review_rule_id}</span>
                      <span className="eligibility-criterion-text">{criterion.text}</span>
                      <Tag tone={state?.medical_decision ? "success" : state?.ai_draft_decision ? "info" : "warning"}>{rowStatus}</Tag>
                    </button>
                  );
                })}
              </div>
            </>
          ) : (
            <div className="empty-state raw-pending-state">
              {reviewLoading ? "正在载入当前受试者的规则、证据和审阅状态。" : "请选择受试者进入逐条标准审阅。"}
            </div>
          )}
        </section>

        <aside className="panel eligibility-inspector">
          <SectionTitle
            title={selectedCriterion ? `${selectedCriterion.review_rule_id} · 标准审阅` : "标准审阅器"}
            action={(
              <button className="icon-button" title="刷新当前审阅包" onClick={() => reloadReviewPackage(true)} disabled={reviewLoading || reviewActionBusy}>
                <RefreshCw size={16} />
              </button>
            )}
          />
          {selectedCriterion ? (
            <div className="eligibility-inspector-scroll">
              <section className="eligibility-criterion-detail">
                <div className="eligibility-inspector-kicker">
                  <Tag tone={selectedCriterion.criterion_kind === "inclusion" ? "success" : "warning"}>{selectedCriterion.review_rule_id}</Tag>
                  <span>{selectedCriterion.source_rule_label || "系统审阅 ID"} · {selectedCriterion.numbering_status}</span>
                </div>
                <p>{selectedCriterion.text}</p>
                <span className="eligibility-source-locator">来源定位：{selectedCriterion.source_locator}</span>
                {!!selectedCriterion.children?.length && (
                  <div className="eligibility-child-criteria">
                    <strong>子条件（只读）</strong>
                    {selectedCriterion.children.map((child) => (
                      <div key={child.rule_id || child.review_rule_id || child.text}>
                        <span>{child.rule_id || child.review_rule_id}</span>
                        <p>{child.text}</p>
                      </div>
                    ))}
                  </div>
                )}
              </section>

              <section className="eligibility-evidence-section">
                <div className="eligibility-subsection-head">
                  <strong>当前版本证据</strong>
                  <span>{selectedEvidenceIds.length} 项已选</span>
                </div>
                {reviewEvidence.length ? reviewEvidence.map((evidence) => (
                  <label className={`eligibility-evidence-option ${selectedEvidenceIds.includes(evidence.evidence_id) ? "selected" : ""}`} key={evidence.evidence_id}>
                    <input
                      type="checkbox"
                      checked={selectedEvidenceIds.includes(evidence.evidence_id)}
                      onChange={(event) => setSelectedEvidenceIds((current) => (
                        event.target.checked
                          ? [...new Set([...current, evidence.evidence_id])]
                          : current.filter((item) => item !== evidence.evidence_id)
                      ))}
                    />
                    <span>
                      <strong>{evidence.source_id} · {eligibilitySourceTypeLabel(evidence.media_class)}</strong>
                      <small>{JSON.stringify(evidence.locator)} · {eligibilityEvidenceProcessingLabel(evidence.processing_state)} · {evidence.quality_state}</small>
                    </span>
                    <Tag tone={eligibilityEvidenceProcessingTone(evidence.processing_state)}>{eligibilityEvidenceProcessingLabel(evidence.processing_state)}</Tag>
                  </label>
                )) : (
                  <p className="quiet-text">当前尚无可绑定的版本化证据。可先发起补证请求或延期审阅，不能据此作决定性判断。</p>
                )}
              </section>

              <section className="eligibility-ai-draft-block">
                <div className="eligibility-subsection-head">
                  <strong>AI 草稿</strong>
                  <Tag tone={selectedCriterionState?.ai_draft_decision ? "info" : "neutral"}>{selectedCriterionState?.ai_draft_decision ? "待医学确认" : "尚未生成"}</Tag>
                </div>
                <p>{selectedCriterionState?.ai_draft_decision ? decisionLabel(selectedCriterionState.ai_draft_decision) : "独立 AI 仅生成逐条审阅草稿；不会自动写入医学判断。"}</p>
                {selectedCriterionState?.ai_draft_decision && (
                  <button
                    className="secondary-button"
                    disabled={!canAcceptAiDraft}
                    title={!sourceAdmissionReady ? "来源内容未就绪，需先完成来源内容核验" : !reviewReason.trim() ? "请先填写医学理由" : !selectedEvidenceCompleted ? "接受 AI 草稿前必须选择已完成证据" : "接受 AI 草稿"}
                    onClick={() => submitReviewAction("accept_ai_draft")}
                  >
                    <CheckCircle2 size={15} /> 接受为医学判断
                  </button>
                )}
              </section>

              <section className="eligibility-decision-block">
                <label>
                  <span>医学判断</span>
                  <select value={medicalDecisionDraft} onChange={(event) => setMedicalDecisionDraft(event.target.value)}>
                    <option value="">请选择逐条判断</option>
                    {decisionOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                  </select>
                </label>
                <label>
                  <span>医学理由（必填）</span>
                  <textarea
                    rows={4}
                    value={reviewReason}
                    onChange={(event) => setReviewReason(event.target.value)}
                    placeholder="说明本次判断、补证、延期或重置的依据；系统不会自动代填。"
                  />
                </label>
                {(decisiveDecision || insufficientDecision) && !selectedEvidenceCompleted && (
                  <p className="eligibility-inline-warning">该判断必须绑定至少一项处理完成的当前版本证据。</p>
                )}
                <div className="eligibility-action-grid">
                  <button
                    className="primary-button"
                    disabled={!canSaveMedicalDecision}
                    title={!sourceAdmissionReady ? "来源内容未就绪，需先完成来源内容核验" : !reviewReason.trim() ? "请填写医学理由" : !medicalDecisionEvidenceReady || !insufficientEvidenceReady ? "请选择处理完成的当前版本证据" : "保存医学判断"}
                    onClick={() => submitReviewAction("revise_decision", medicalDecisionDraft)}
                  >
                    <FileCheck2 size={15} /> 保存医学判断
                  </button>
                  <button className="secondary-button" disabled={!reviewReason.trim() || reviewActionBusy || !sourceAdmissionReady} title={!sourceAdmissionReady ? "来源内容未就绪，需先完成来源内容核验" : !reviewReason.trim() ? "请填写医学理由" : reviewActionBusy ? "审阅动作处理中" : "请求补充证据"} onClick={() => submitReviewAction("request_evidence")}>
                    <Search size={15} /> 请求补证
                  </button>
                  <button className="secondary-button" disabled={!reviewReason.trim() || reviewActionBusy || !sourceAdmissionReady} title={!sourceAdmissionReady ? "来源内容未就绪，需先完成来源内容核验" : !reviewReason.trim() ? "请填写医学理由" : reviewActionBusy ? "审阅动作处理中" : "延期审阅"} onClick={() => submitReviewAction("defer_review")}>
                    <Clock3 size={15} /> 延期审阅
                  </button>
                  {reviewStateHasDrift && (
                    <button className="secondary-button warning" disabled={!reviewReason.trim() || reviewActionBusy || !sourceAdmissionReady} title={!sourceAdmissionReady ? "来源内容未就绪，需先完成来源内容核验" : !reviewReason.trim() ? "请填写医学理由" : reviewActionBusy ? "审阅动作处理中" : "按当前来源版本重置"} onClick={() => submitReviewAction("reset_after_source_change")}>
                      <RotateCcw size={15} /> 来源变更后重置
                    </button>
                  )}
                </div>
              </section>

              <section className="eligibility-current-state">
                <strong>当前记录</strong>
                <span>医学判断：{decisionLabel(selectedCriterionState?.medical_decision)}</span>
                <span>证据处理：{eligibilityEvidenceProcessingLabel(selectedCriterionState?.evidence_processing_state)}</span>
                <span>状态版本：{selectedCriterionState?.state_revision || 0}</span>
                <span>最后更新：{selectedCriterionState?.updated_at || "尚无记录"}</span>
              </section>
            </div>
          ) : (
            <p className="quiet-text">从审阅账本选择一条 IN 或 EX 标准后，在此核对证据、AI 草稿并记录医学判断。</p>
          )}
        </aside>
      </div>

      <section className="panel eligibility-support-band">
        <div>
          <strong>原始资料链路</strong>
          <span>{rawSourceTypeLabel || "待读取"} · {rawIntake?.subject_pool?.total_files ?? "-"} 份文件 · {rawIntake?.protocol?.paragraph_count ?? "-"} 个方案段落</span>
        </div>
        <div>
          <strong>独立 AI 与证据任务</strong>
          <span>{rawAiBlocked ? "独立 AI 待配置" : rawEligibilityReviewReady ? "逐条审核任务已运行" : "等待证据任务与逐条 AI 草稿"}</span>
        </div>
        <div>
          <strong>旧产物边界</strong>
          <span>{rawForbiddenInputs.length} 类旧产物禁作输入；{legacyDataset ? "历史系统仅作迁移对照" : "当前未载入历史对照"}</span>
        </div>
        <div className="legacy-comparison">
          <strong>历史系统对照</strong>
          <span>不得用于当前 D001/MY009 原始资料审核输入。</span>
        </div>
      </section>
    </main>
  );
}

function sourceAdmissionStatusTone(status) {
  if (["ready", "parsed", "matched", "allowed", "confirmed_after_warning"].includes(status)) return "success";
  if (["warning", "mismatch"].includes(status)) return "warning";
  if (["failed", "error", "parse_error", "blocked_technical_failure"].includes(status)) return "danger";
  return "info";
}

function sourceAdmissionStatusLabel(status) {
  return {
    parsed: "已解析",
    ready: "技术可读",
    match: "匹配",
    matched: "匹配",
    allowed: "可使用",
    requires_confirmation: "待确认",
    warning: "需确认",
    mismatch: "不一致",
    not_assessed: "未评估",
    failed: "解析失败",
    error: "异常",
    confirmed_after_warning: "已确认沿用",
    blocked_technical_failure: "技术读取失败（阻断）",
  }[status] || status || "未评估";
}

function SourceAdmissionBand({
  sourceAdmission,
  loading,
  error,
  confirmationTarget,
  setConfirmationTarget,
  confirmationReason,
  setConfirmationReason,
  acknowledgedCodes,
  setAcknowledgedCodes,
  confirmedRecord,
  onConfirm,
  onRefresh,
}) {
  const sources = Array.isArray(sourceAdmission?.sources) ? sourceAdmission.sources : [];
  const protocolSource = sources.find((item) => item.entry?.source_kind === "protocol_docx");
  const bundleSource = sources.find((item) => item.entry?.source_kind === "raw_subject_bundle_inventory");
  const warningSources = sources.filter((item) => ["warning", "mismatch"].includes(item.content_validation?.content_status));
  const unresolvedSource = confirmationTarget ? warningSources.find((item) => item.entry.entry_id === confirmationTarget.entry.entry_id) : null;

  const startConfirmation = (source) => {
    setConfirmationTarget({
      entry: source.entry,
      expectedRevision: source.content_validation?.revision,
      idempotencyKey: requestKey("eligibility-source-admission-confirmation"),
      contentStatus: source.content_validation?.content_status || "warning",
      headlineLabel: source.content_validation?.content_status === "mismatch" ? "内容不一致" : "内容待确认",
      checks: Array.isArray(source.content_validation?.checks) ? source.content_validation.checks : [],
    });
    setConfirmationReason("");
    setAcknowledgedCodes([]);
  };

  const cancelConfirmation = () => {
    setConfirmationTarget(null);
    setConfirmationReason("");
    setAcknowledgedCodes([]);
  };

  const unresolvedChecks = (confirmationTarget?.checks || []).filter((check) => ["warning", "mismatch"].includes(check.outcome));
  const allAcknowledged = acknowledgedCodes.length === unresolvedChecks.length && unresolvedChecks.length > 0;
  const canSubmitConfirmation = allAcknowledged && confirmationReason.trim().length >= 10 && !loading;

  return (
    <section className="panel source-admission-band" aria-label="来源内容核验">
      <div className="source-admission-head">
        <ShieldAlert size={17} />
        <strong>来源内容核验</strong>
        <span>{sourceAdmission?.ready_for_use ? "全部来源已就绪，可进行审阅动作" : "存在未确认的来源内容警告或不一致"}</span>
        <button className="icon-button" onClick={onRefresh} disabled={loading} title={loading ? "刷新中" : "刷新来源准入状态"}>
          <RefreshCw size={15} />
        </button>
      </div>
      {error && <p className="gate-error">{error}</p>}
      <div className="source-admission-cards">
        {protocolSource && (
          <SourceAdmissionCard
            label="研究方案"
            source={protocolSource}
            onConfirm={() => startConfirmation(protocolSource)}
          />
        )}
        {bundleSource && (
          <SourceAdmissionCard
            label="受试者资料包"
            source={bundleSource}
            onConfirm={() => startConfirmation(bundleSource)}
            rawBundleNote="目录及文件构成核验，不代表已完成逐文件医学内容核验"
          />
        )}
        {!protocolSource && !bundleSource && !loading && (
          <p className="quiet-text">当前项目尚未返回来源内容核验信息。</p>
        )}
      </div>
      {confirmedRecord && !confirmationTarget && (
        <div className="content-confirmation-record">
          <Tag tone="info">已确认沿用</Tag>
          <p><strong>医学确认理由</strong>{confirmedRecord.reason}</p>
          <p>
            <small>
              操作者：{confirmedRecord.actor} · {confirmedRecord.at} · 内容状态：
              {confirmedRecord.contentStatus === "mismatch" ? "不一致" : confirmedRecord.contentStatus === "warning" ? "需确认" : "未评估"}
              · 使用状态：{sourceAdmissionStatusLabel(confirmedRecord.useStatus)}
            </small>
          </p>
        </div>
      )}
      {confirmationTarget && unresolvedSource && (
        <div className="content-confirmation">
          <div className="content-confirmation-head">
            <ShieldAlert size={15} />
            <strong>来源内容确认 · {sourceKindLabel(unresolvedSource.entry.source_kind)}</strong>
            <Tag tone={confirmationTarget.contentStatus === "mismatch" ? "danger" : "warning"}>{confirmationTarget.headlineLabel}</Tag>
          </div>
          <p>{unresolvedSource.content_validation?.summary || "该来源与已登记内容或预期内容存在差异，请逐项核对后确认是否继续沿用。"}</p>
          <div className="content-confirmation-checks">
            {confirmationTarget.checks.map((check) => (
              <div key={check.check_code}>
                <span>{check.label}</span>
                <b>{check.outcome === "match" ? "匹配" : check.outcome === "mismatch" ? "不一致" : check.outcome === "not_assessed" ? "未评估" : "需确认"}</b>
                <small title={check.observed_value}>{check.observed_value}</small>
              </div>
            ))}
          </div>
          {unresolvedChecks.length > 0 && (
            <div className="content-confirmation-override">
              <div className="content-confirmation-override-warning">
                <AlertTriangle size={15} />
                <span>以下信息尚未通过自动核验。请逐项对照原文；确认沿用不代表系统判定已转为匹配。</span>
              </div>
              <fieldset>
                <legend>逐项确认</legend>
                {unresolvedChecks.map((check) => (
                  <label className="content-confirmation-override-check" key={check.check_code}>
                    <input
                      type="checkbox"
                      checked={acknowledgedCodes.includes(check.check_code)}
                      onChange={(event) => setAcknowledgedCodes((current) => (
                        event.target.checked
                          ? [...new Set([...current, check.check_code])]
                          : current.filter((code) => code !== check.check_code)
                      ))}
                    />
                    <span>
                      <strong>我已核对：{check.label}</strong>
                      <small>{check.observed_value || "未识别到可核对内容"}</small>
                    </span>
                  </label>
                ))}
              </fieldset>
              <label>
                确认理由
                <textarea
                  value={confirmationReason}
                  onChange={(event) => setConfirmationReason(event.target.value)}
                  placeholder="说明为何确认该来源内容可继续沿用于本项目入排审核。"
                />
              </label>
              <div className="content-confirmation-actions">
                <button
                  className="primary-button"
                  title={loading ? "正在记录确认" : "需逐项确认所有未决内容，并填写至少10字的医学确认理由"}
                  onClick={onConfirm}
                  disabled={!canSubmitConfirmation}
                >
                  确认沿用
                </button>
                <button className="secondary-button" onClick={cancelConfirmation} disabled={loading} title={loading ? "确认记录正在保存" : "取消本次确认"}>
                  取消
                </button>
              </div>
              <small>确认后内容状态不会变为匹配，仅将使用状态改为已确认沿用；原提示、确认理由、操作者及版本信息将纳入审计记录。</small>
            </div>
          )}
        </div>
      )}
      {confirmationTarget && !unresolvedSource && (
        <p className="quiet-text">当前来源已无未解决的内容警告，即将刷新。</p>
      )}
    </section>
  );
}

function SourceAdmissionCard({ label, source, onConfirm, rawBundleNote }) {
  const entry = source.entry || {};
  const validation = source.content_validation || {};
  const status = validation.content_status || "not_assessed";
  const useStatus = validation.use_status || "unconfirmed";
  const technicalStatus = validation.technical_status || entry.parser_status || "not_assessed";
  const checks = Array.isArray(validation.checks) ? validation.checks : [];
  const needsConfirmation = ["warning", "mismatch"].includes(status) && useStatus === "requires_confirmation";
  const isConfirmed = useStatus === "confirmed_after_warning";
  return (
    <div className={`source-admission-card ${needsConfirmation ? "needs-confirmation" : ""}`}>
      <div className="source-admission-card-head">
        <strong>{label}</strong>
        <div className="source-admission-card-tags">
          <Tag tone={sourceAdmissionStatusTone(technicalStatus)}>{sourceAdmissionStatusLabel(technicalStatus)}</Tag>
          <Tag tone={sourceAdmissionStatusTone(status)}>{sourceAdmissionStatusLabel(status)}</Tag>
          <Tag tone={isConfirmed ? "success" : "info"}>{isConfirmed ? "已确认沿用" : useStatus === "allowed" ? "可使用" : "未确认"}</Tag>
        </div>
      </div>
      <div className="source-admission-card-body">
        <span>文件：{entry.public_title || entry.filename || "未命名"}</span>
        <span>大小：{entry.size_bytes !== undefined ? `${(entry.size_bytes / 1024).toFixed(1)} KB` : "-"}</span>
        <span>解析状态：{parserStatusLabel(entry.parser_status)}</span>
        {entry.metadata && Object.keys(entry.metadata).length > 0 && (
          <span>基本信息：{Object.entries(entry.metadata).filter(([, value]) => ["string", "number", "boolean"].includes(typeof value)).map(([key, value]) => `${key}: ${value}`).join(" · ")}</span>
        )}
      </div>
      {rawBundleNote && <p className="source-admission-raw-note">{rawBundleNote}</p>}
      <div className="source-admission-checks">
        {checks.map((check) => (
          <div key={check.check_code}>
            <span>{check.label}</span>
            <b>{check.outcome === "match" ? "匹配" : check.outcome === "mismatch" ? "不一致" : check.outcome === "not_assessed" ? "未评估" : "需确认"}</b>
            <small>{check.observed_value}</small>
          </div>
        ))}
        {!checks.length && <span className="quiet-text">暂无检查记录</span>}
      </div>
      <div className="source-admission-card-foot">
        {needsConfirmation ? (
          <button className="primary-button" onClick={onConfirm}>
            <ShieldAlert size={14} /> 确认该来源
          </button>
        ) : (
          <span className="quiet-text">{isConfirmed ? "已确认沿用" : "无需进一步确认"}</span>
        )}
      </div>
    </div>
  );
}

function ModuleSourceAdmissionBand({
  projectId,
  admission,
  loading,
  onRefresh,
  contextLabel,
}) {
  const sources = Array.isArray(admission?.sources) ? admission.sources : [];
  const [expanded, setExpanded] = useState(!admission?.ready_for_use);
  const [targetEntryId, setTargetEntryId] = useState("");
  const [reason, setReason] = useState("");
  const [acknowledgedCodes, setAcknowledgedCodes] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState("");
  const target = sources.find((source) => source.source_entry_id === targetEntryId);
  const unresolvedChecks = (target?.checks || []).filter((check) => ["warning", "mismatch"].includes(check.outcome));
  const allAcknowledged = unresolvedChecks.length > 0 && unresolvedChecks.every((check) => acknowledgedCodes.includes(check.check_code));
  const canConfirm = allAcknowledged && reason.trim().length >= 10 && !submitting;

  useEffect(() => {
    setTargetEntryId("");
    setReason("");
    setAcknowledgedCodes([]);
    setMessage("");
    setExpanded(!admission?.ready_for_use);
  }, [admission?.scope_id, projectId]);

  useEffect(() => {
    if (!admission?.ready_for_use) setExpanded(true);
    else if (!targetEntryId) setExpanded(false);
  }, [admission?.ready_for_use, targetEntryId]);

  const startConfirmation = (source) => {
    setTargetEntryId(source.source_entry_id);
    setReason("");
    setAcknowledgedCodes([]);
    setMessage("");
    setExpanded(true);
  };

  const cancelConfirmation = () => {
    setTargetEntryId("");
    setReason("");
    setAcknowledgedCodes([]);
  };

  const confirmSource = async () => {
    if (!target || !canConfirm) return;
    setSubmitting(true);
    setMessage("");
    try {
      const response = await fetch(`/api/projects/${projectId}/sources/${target.source_entry_id}/content-validation/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          reason: reason.trim(),
          acknowledged_check_codes: acknowledgedCodes,
          expected_revision: target.revision,
          idempotency_key: requestKey(`${admission?.module || "module"}-source-confirmation`),
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(apiDetailText(payload, `确认记录失败：${response.status}`));
      if (payload?.project_id !== projectId) {
        throw new Error("来源确认响应项目身份不匹配，未更新当前来源状态。");
      }
      setMessage("确认已记录；原内容警告或不一致状态继续保留，当前使用状态已更新为已确认沿用。");
      cancelConfirmation();
      await onRefresh();
    } catch (error) {
      setMessage(`确认失败：${apiErrorText(error)} 请刷新当前来源状态后重新核对。`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className={`module-source-admission ${admission?.ready_for_use ? "ready" : "attention"}`} aria-label={`${contextLabel}来源内容核验`}>
      <div className="module-source-admission-head">
        <ShieldAlert size={16} />
        <strong>来源内容核验</strong>
        <span>{admission?.ready_for_use ? `当前${contextLabel}来源已就绪` : `当前${contextLabel}存在待确认来源`}</span>
        <Tag tone={admission?.ready_for_use ? "success" : "warning"}>{admission?.ready_for_use ? "可进行医学审阅" : "暂不可晋级"}</Tag>
        <button className="icon-button" onClick={onRefresh} disabled={loading || submitting} title={loading ? "正在刷新来源状态" : "刷新来源状态"}>
          <RefreshCw size={14} />
        </button>
        <button className="module-source-admission-toggle" onClick={() => setExpanded((value) => !value)} title={expanded ? "收起核验详情" : "展开核验详情"}>
          <ChevronRight size={15} className={expanded ? "expanded" : ""} />
          {expanded ? "收起" : "详情"}
        </button>
      </div>
      {message && <div className="source-registry-message">{message}</div>}
      {expanded && (
        <div className="module-source-admission-body">
          {admission?.missing_source_roles?.length > 0 && (
            <p className="gate-error">缺少来源：{admission.missing_source_roles.join("、")}</p>
          )}
          <div className="module-source-admission-grid">
            {sources.map((source) => {
              const needsConfirmation = source.use_status === "requires_confirmation" && ["warning", "mismatch"].includes(source.content_status);
              return (
                <article className={`module-source-admission-source ${needsConfirmation ? "needs-confirmation" : ""}`} key={`${source.source_role_code}-${source.source_entry_id}`}>
                  <div className="module-source-admission-source-head">
                    <div>
                      <strong>{source.source_role}</strong>
                      <span>{source.public_title}</span>
                    </div>
                    <div>
                      <Tag tone={sourceAdmissionStatusTone(source.technical_status)}>{sourceAdmissionStatusLabel(source.technical_status)}</Tag>
                      <Tag tone={sourceAdmissionStatusTone(source.content_status)}>{sourceAdmissionStatusLabel(source.content_status)}</Tag>
                      <Tag tone={source.use_status === "confirmed_after_warning" ? "success" : source.use_status === "allowed" ? "success" : "warning"}>{sourceAdmissionStatusLabel(source.use_status)}</Tag>
                    </div>
                  </div>
                  <p>{source.summary}</p>
                  <div className="module-source-admission-checks">
                    {(source.checks || []).map((check) => (
                      <div key={check.check_code}>
                        <span>{check.label}</span>
                        <b>{sourceAdmissionStatusLabel(check.outcome)}</b>
                        <small title={check.observed_value || "未识别到可核对内容"}>{check.observed_value || "未识别到可核对内容"}</small>
                      </div>
                    ))}
                  </div>
                  {source.use_status === "confirmed_after_warning" && (
                    <div className="module-source-confirmed-record">
                      <Tag tone="success">已确认沿用</Tag>
                      <span>{source.confirmation_reason || "已记录医学确认理由"}</span>
                      <small>{source.confirmation_actor || "服务器核验身份"}{source.confirmed_at ? ` · ${new Date(source.confirmed_at).toLocaleString("zh-CN")}` : ""}</small>
                    </div>
                  )}
                  {needsConfirmation && (
                    <button className="secondary-button" onClick={() => startConfirmation(source)} disabled={submitting}>
                      <ShieldAlert size={14} /> 确认该来源
                    </button>
                  )}
                </article>
              );
            })}
            {!sources.length && !loading && <p className="quiet-text">当前包尚未返回来源内容核验信息。</p>}
          </div>
          {target && (
            <div className="module-source-confirmation">
              <div className="content-confirmation-head">
                <AlertTriangle size={15} />
                <strong>确认沿用 · {target.source_role}</strong>
                <Tag tone={target.content_status === "mismatch" ? "danger" : "warning"}>{sourceAdmissionStatusLabel(target.content_status)}</Tag>
              </div>
              <p>以下信息尚未通过自动核验。请逐项对照原始资料；确认沿用仅改变使用状态，不会将原内容状态改为“匹配”。</p>
              <fieldset>
                <legend>逐项确认</legend>
                {unresolvedChecks.map((check) => (
                  <label className="content-confirmation-override-check" key={check.check_code}>
                    <input
                      type="checkbox"
                      checked={acknowledgedCodes.includes(check.check_code)}
                      onChange={(event) => setAcknowledgedCodes((current) => (
                        event.target.checked
                          ? [...new Set([...current, check.check_code])]
                          : current.filter((code) => code !== check.check_code)
                      ))}
                    />
                    <span><strong>我已核对：{check.label}</strong><small>{check.observed_value || "未识别到可核对内容"}</small></span>
                  </label>
                ))}
              </fieldset>
              <label className="module-source-confirmation-reason">
                <span>医学确认理由</span>
                <textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={3} placeholder={`说明为何该来源可继续用于${contextLabel}，至少10个字。`} />
              </label>
              <div className="content-confirmation-actions">
                <button className="primary-button" onClick={confirmSource} disabled={!canConfirm} title={submitting ? "正在记录确认" : "需逐项确认全部未决检查并填写至少10字的医学确认理由"}>{submitting ? "记录中" : "确认沿用"}</button>
                <button className="secondary-button" onClick={cancelConfirmation} disabled={submitting} title={submitting ? "确认记录正在保存" : "取消本次确认"}>取消</button>
              </div>
              <small>确认只改变使用状态；原提示、确认理由、操作者和来源版本继续保留。</small>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

const writingSectionBackendIds = {
  synopsis: "sec_synopsis",
  endpoints: "sec_objectives_endpoints",
  eligibility: "sec_eligibility",
  soa: "sec_soa",
};

const revisionIntentOptions = [
  {
    value: "medical_writing_revision",
    label: "改写",
    defaultInstruction: "在不改变研究事实、数字、单位、阈值、时间点、终点层级和不确定性的前提下，优化选中文本的信息顺序、句法、医学术语和行文紧凑度，去除口语化、重复及机械的AI式表达，形成可直接用于中国临床试验方案正文的自然中文。",
  },
  {
    value: "regulatory_tone",
    label: "监管语气",
    defaultInstruction: "在不改变任何研究事实、义务强度和不确定性的前提下，将选中文本改为中国临床试验方案中的规范性、可执行性表述；准确区分应、须、不得、可、将、拟和建议，避免宣传性、过度承诺或结论强度升级，并保留全部数字、单位、阈值、时间窗和例外条件。",
  },
  {
    value: "consistency_check",
    label: "查一致性",
    defaultInstruction: "逐项核对选中文本与本次允许使用的来源在术语和缩略语、研究人群、治疗组、剂量与频次、时间点和访视窗、终点层级、分析集、入排条件及统计口径上的一致性；仅修正有直接依据的冲突。仅有当前选区一个来源时只做段内自洽核查，不声称已完成全方案一致性核查；来源之间无法判定时保留可确认内容并列明待医学决定项。",
  },
  {
    value: "evidence_gap",
    label: "补证据",
    defaultInstruction: "识别选中文本中需要方案、SAP、指导原则、临床研究或竞品方案支持的主张、阈值、时间点和设计理由；仅使用本次已选证据补充可直接支持的内容。不得虚构文献、指南、编号或结论；仍缺证据的部分保持审慎表述，并在修订理由中明确需要补充的证据类型和具体问题。",
  },
];

const revisionFollowupPlaceholders = {
  medical_writing_revision: "具体指出需要保留的事实和需要调整的表达，例如：保留全部数值与终点名称，合并重复句并将研究目的提前。",
  regulatory_tone: "具体指出义务强度或监管措辞问题，例如：保留原限制条件，将建议性表述改为可执行条款，但不得扩大禁止范围。",
  consistency_check: "具体指出待核对的冲突或口径，例如：仅修正访视窗与已选来源不一致之处，其余无直接依据的内容保持原文。",
  evidence_gap: "具体指出需要补强的主张和允许使用的证据，例如：仅用本轮已选证据补充阈值依据，未获支持的设计理由继续标记待确认。",
};

function writingBackendSectionId(sectionId) {
  return writingSectionBackendIds[sectionId] || null;
}

function revisionThreadStatusLabel(status) {
  return {
    candidate_ready: "AI候选，待选择",
    pending_medical_approval: "历史候选，待选择",
    accepted_pending_medical_approval: "历史候选，待迁移",
    author_selected: "医学作者已选用",
    medically_approved: "历史已选用",
    returned_for_revision: "已退回修订",
    superseded: "已终止",
    rejected: "已拒绝",
  }[status] || status || "待处理";
}

function isRevisionThreadSelectedByAuthor(status) {
  return ["author_selected", "medically_approved", "accepted_pending_medical_approval"].includes(status);
}

function revisionThreadTone(status) {
  if (status === "accepted_pending_medical_approval") return "warning";
  if (isRevisionThreadSelectedByAuthor(status)) return "success";
  if (["candidate_ready", "pending_medical_approval"].includes(status)) return "warning";
  if (["rejected", "superseded"].includes(status)) return "neutral";
  return "info";
}

function latestRevisionRoundSuggestions(thread) {
  const suggestions = thread?.suggestions || [];
  const latestTurn = Math.max(0, ...suggestions.map((item) => Number(item.turn_number || 0)));
  return suggestions.filter((item) => Number(item.turn_number || 0) === latestTurn);
}

function revisionSuggestionStatusLabel(status) {
  return {
    pending: "待处置",
    accepted: "已选用",
    rejected: "已拒绝",
    rewrite_requested: "已进入下一轮",
    not_selected: "本轮未选",
  }[status] || status || "待处置";
}

function revisionSuggestionTone(status) {
  if (status === "accepted") return "success";
  if (status === "pending") return "warning";
  return "neutral";
}

function revisionTurnTime(value) {
  if (!value) return "历史记录未保存时间";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("zh-CN", { hour12: false });
}

function cloneContentBlocks(blocks = []) {
  return JSON.parse(JSON.stringify(blocks));
}

function tiptapNodeText(node) {
  if (!node) return "";
  if (typeof node.text === "string") return node.text;
  if (node.type === "hardBreak") return "\n";
  const separator = ["doc", "sourceBlock", "tableCell", "tableHeader", "listItem"].includes(node.type)
    ? "\n"
    : "";
  return (node.content || []).map(tiptapNodeText).join(separator);
}

function tiptapInlineTextContent(value) {
  const lines = String(value || "").split("\n");
  const content = [];
  lines.forEach((line, index) => {
    if (index > 0) content.push({ type: "hardBreak" });
    if (line) content.push({ type: "text", text: line });
  });
  return content.length ? content : undefined;
}

function stableJsonStringify(value) {
  if (Array.isArray(value)) return `[${value.map(stableJsonStringify).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJsonStringify(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function stableRequestToken(value) {
  const input = stableJsonStringify(value);
  let hash = 2166136261;
  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function greenfieldApprovalBlockerCount(decisions = [], moduleResolutions = []) {
  const decisionCount = decisions.filter(
    (item) => item.approval_blocking && item.status !== "resolved",
  ).length;
  const hasUnresolvedModules = moduleResolutions.some(
    (item) => ["unknown", "deferred"].includes(item.status),
  );
  return decisionCount + (hasUnresolvedModules ? 1 : 0);
}

const medicalWritingFactLabels = {
  "framing.indication": "适应症",
  "framing.investigational_product": "试验药物",
  "framing.population_intent": "目标研究人群",
  "framing.intrinsic_objectives": "研究目的",
  "framing.product_profile": "产品特征",
  "framing.target_mechanism": "靶点与作用机制",
  "framing.structured_design": "结构化研究设计",
  "picos.population_summary": "研究人群概要",
  "picos.inclusion_modules": "入选标准",
  "picos.exclusion_modules": "排除标准",
  "picos.intervention_summary": "研究干预概要",
  "picos.intervention_dose_regimen": "给药剂量与方案",
  "picos.primary_objectives": "主要研究目的",
  "picos.primary_endpoint": "主要终点",
  "picos.secondary_objectives": "次要研究目的",
  "picos.key_secondary_endpoints": "关键次要终点",
  "picos.other_secondary_endpoints": "其他次要终点",
  "picos.exploratory_objectives": "探索性研究目的",
  "picos.exploratory_endpoints": "探索性终点",
  "picos.estimand_strategy": "估计目标策略",
  "picos.study_epochs": "研究阶段与周期",
  "picos.sample_size_strategy": "样本量策略",
  "picos.allowed_concomitant_rules": "允许的合并治疗规则",
  "picos.required_background_rules": "必须使用的背景治疗规则",
  "picos.prohibited_concomitant_rules": "禁止的合并治疗规则",
  "picos.statistical_strategy": "统计分析策略",
  "picos.aesi_definitions": "特别关注不良事件定义",
  "picos.safety_endpoints": "安全性终点",
};

function medicalWritingFactLabel(value) {
  return medicalWritingFactLabels[value] || value;
}

function contentBlockText(block) {
  if (!block) return "";
  if (block.block_type !== "table") return String(block.text || "").trim();
  return (block.rows || [])
    .flatMap((row) => (row || []).map((cell) => String(cell.text || "").trim()))
    .filter(Boolean)
    .join("；");
}

function isBlankGreenfieldBodyBlock(block) {
  return block?.block_type === "paragraph"
    && ["greenfield_scaffold", "greenfield_project_decision"].includes(
      block?.source_kind,
    )
    && !String(block?.text || "").trim()
    && /^greenfield:[^:]+:section:[^:]+:body:\d+$/.test(
      String(block?.source_locator || ""),
    );
}

function visibleTableTitle(block, fallback = "未命名表格") {
  return String(
    block?.structured_table?.title
      || block?.table_caption?.text
      || block?.title
      || block?.title_hint
      || fallback,
  ).trim();
}

function sourceTableCaptionText(block) {
  return String(
    block?.table_caption?.text
      || block?.structured_table?.source_caption?.text
      || "",
  ).trim();
}

function normalizedVisibleText(value) {
  return String(value || "").replace(/\s+/g, "").toLocaleLowerCase("zh-CN");
}

function visibleTableNotes(block) {
  return Array.isArray(block?.structured_table?.notes)
    ? block.structured_table.notes.filter((note) => String(note?.text || "").trim())
    : [];
}

function visibleTableColumnCount(block) {
  return Math.max(
    Number(block?.column_count || 0),
    Number(block?.structured_table?.columns?.length || 0),
    ...(block?.rows || []).map((row) => (row || []).reduce(
      (count, cell) => count + Math.max(1, Number(cell?.column_span || 1)),
      0,
    )),
  );
}

function tiptapCellNode(cell, header = false) {
  const text = String(cell?.text || "");
  const normalizedRichText = normalizeCitationMarkAttributes(cell?.rich_text);
  const richContent = normalizedRichText?.type === "doc" && Array.isArray(normalizedRichText.content)
    ? normalizedRichText.content
    : normalizedRichText?.type
      ? [normalizedRichText]
      : null;
  return {
    type: header ? "tableHeader" : "tableCell",
    attrs: {
      colspan: Math.max(1, Number(cell?.column_span || 1)),
      rowspan: Math.max(1, Number(cell?.row_span || 1)),
      colwidth: null,
      cellId: cell?.cell_id || null,
      sourceLocator: cell?.source_locator || null,
      gridColumnIndex: Number.isInteger(cell?.grid_column_index)
        ? cell.grid_column_index
        : null,
      styleRole: cell?.style_role || (header ? "header" : "body"),
    },
    content: richContent || [{
      type: "paragraph",
      content: tiptapInlineTextContent(text),
    }],
  };
}

function tiptapNodeFromContentBlock(block) {
  if (block.block_type === "figure" && block.figure_kind === "source_docx_image") {
    return {
      type: "sourceDocxImage",
      attrs: {
        sourceBlockId: block.block_id || null,
        imageId: block.image_id || block.figure_id || null,
        title: block.title || "",
        sourceLocator: block.source_locator || "",
        semanticRole: block.semantic_role || "figure",
        src: block.image_base64 && block.media_type
          ? `data:${block.media_type};base64,${block.image_base64}`
          : "",
        alt: block.alt_text || block.title || "",
      },
    };
  }
  if (block.block_type === "table") {
    return {
      type: "table",
      attrs: {
        sourceBlockId: block.block_id || null,
        sourceTableId: block.table_id || null,
      },
      content: (block.rows || []).map((row, rowIndex) => ({
        type: "tableRow",
        attrs: {
          rowId: `${block.table_id || block.block_id || "table"}_row_${rowIndex}`,
        },
        content: (row || []).filter((cell) => !cell?.hidden).map((cell) => tiptapCellNode(
          cell,
          cell?.style_role === "header" || (rowIndex === 0 && block.header_row_count !== 0),
        )),
      })),
    };
  }
  const type = block.block_type === "heading" ? "heading" : "paragraph";
  const content = tiptapInlineTextContent(block.text);
  const headingLevel = Number.isInteger(block.outline_level)
    ? Math.min(6, Math.max(1, block.outline_level + 1))
    : 1;
  const richText = normalizeCitationMarkAttributes(block.rich_text) || {
    type,
    ...(type === "heading" ? { attrs: { level: headingLevel } } : {}),
    ...(content ? { content } : {}),
  };
  return {
    type: "sourceBlock",
    attrs: { sourceBlockId: block.block_id || null },
    content: richText.type === "doc" && Array.isArray(richText.content)
      ? richText.content
      : [richText],
  };
}

/**
 * Backend working-copy validation rejects TipTap marks that include empty attrs
 * on simple marks (e.g. `{type:"bold", attrs:{}}`) and textStyle attrs with nulls.
 * Sanitize before mapping editor JSON into content_blocks so imported RUX/greenfield
 * edits can save without 4xx mark validation failures.
 * Authority: services/api/app/medical_writing_repository.py `_validate_rich_text_mark`.
 */
function sanitizeRichTextMark(mark) {
  if (!mark || typeof mark !== "object") return null;
  const type = mark.type;
  if (!type) return null;
  if (["bold", "italic", "underline", "superscript", "subscript"].includes(type)) {
    return { type };
  }
  if (type === "highlight") {
    const color = mark.attrs?.color;
    if (typeof color === "string" && /^#[0-9A-Fa-f]{6}$/.test(color)) {
      return { type, attrs: { color } };
    }
    return null;
  }
  if (type === "citation") {
    const attrs = mark.attrs || {};
    if (typeof attrs.referenceId === "string" && attrs.referenceId) {
      return { type, attrs: { referenceId: attrs.referenceId } };
    }
    if (Array.isArray(attrs.referenceIds) && attrs.referenceIds.length) {
      return { type, attrs: { referenceIds: attrs.referenceIds.filter(Boolean) } };
    }
    return null;
  }
  if (type === "crossReference") {
    const attrs = mark.attrs || {};
    if (attrs.targetKind && attrs.targetId) {
      return { type, attrs: { targetKind: attrs.targetKind, targetId: attrs.targetId } };
    }
    return null;
  }
  if (type === "textStyle" || type === "link") {
    // textStyle is allowed as fontFamily/fontSize/color only; drop null/empty attrs.
    if (type === "link") return null; // not in backend allow-list
    const attrs = {};
    const fontFamily = mark.attrs?.fontFamily;
    const fontSize = mark.attrs?.fontSize;
    const color = mark.attrs?.color;
    if (typeof fontFamily === "string" && fontFamily.trim()) attrs.fontFamily = fontFamily.trim();
    if (typeof fontSize === "string" && /^\d+(\.\d+)?pt$/.test(fontSize.trim())) attrs.fontSize = fontSize.trim();
    if (typeof color === "string" && /^#[0-9A-Fa-f]{6}$/.test(color)) attrs.color = color;
    if (!Object.keys(attrs).length) return null;
    return { type: "textStyle", attrs };
  }
  return null;
}

function sanitizeRichTextNode(node, depth = 0) {
  if (depth > 12 || !node || typeof node !== "object") return null;
  if (node.type === "text") {
    const text = typeof node.text === "string" ? node.text : "";
    if (!text) return null;
    const marks = Array.isArray(node.marks)
      ? node.marks.map(sanitizeRichTextMark).filter(Boolean)
      : undefined;
    // Dedupe mark types (backend requires unique mark types per text node)
    const seen = new Set();
    const uniqueMarks = [];
    for (const mark of marks || []) {
      if (seen.has(mark.type)) continue;
      seen.add(mark.type);
      uniqueMarks.push(mark);
    }
    return uniqueMarks.length
      ? { type: "text", text, marks: uniqueMarks }
      : { type: "text", text };
  }
  if (node.type === "hardBreak") return { type: "hardBreak" };
  const next = { type: node.type };
  if (node.attrs && typeof node.attrs === "object") {
    // Keep paragraph/heading attrs; drop nulls
    const attrs = {};
    for (const [key, value] of Object.entries(node.attrs)) {
      if (value === null || value === undefined || value === "") continue;
      attrs[key] = value;
    }
    if (Object.keys(attrs).length) next.attrs = attrs;
  }
  if (Array.isArray(node.content)) {
    const content = node.content
      .map((child) => sanitizeRichTextNode(child, depth + 1))
      .filter(Boolean);
    if (content.length) next.content = content;
  }
  return next;
}

function sanitizeRichText(richText) {
  if (!richText || typeof richText !== "object") return richText || null;
  return sanitizeRichTextNode(richText) || richText;
}

function richTextFromSourceBlockNode(node) {
  if (!node) return null;
  if (node.type === "sourceBlock") {
    if (!Array.isArray(node.content) || !node.content.length) return null;
    const raw = node.content.length === 1
      ? node.content[0]
      : { type: "doc", content: node.content };
    return sanitizeRichText(raw);
  }
  // Greenfield authoring may leave bare paragraph/heading nodes at doc top-level
  // when Enter exits an isolating sourceBlock. Preserve them as real block rich text.
  if (node.type === "paragraph" || node.type === "heading") {
    return sanitizeRichText(node);
  }
  if (Array.isArray(node.content) && node.content.length) {
    const raw = node.content.length === 1
      ? node.content[0]
      : { type: "doc", content: node.content };
    return sanitizeRichText(raw);
  }
  return null;
}

function greenfieldBlockTypeFromEditorNode(node) {
  if (!node) return "paragraph";
  if (node.type === "sourceBlock") {
    return node.content?.some((child) => child.type === "heading") ? "heading" : "paragraph";
  }
  if (node.type === "heading") return "heading";
  return "paragraph";
}

/**
 * Backend working-copy validation only allows mutating text/rich_text on existing
 * source-linked blocks (and governed table/figure inserts). It rejects arbitrary
 * top-level greenfield_new blocks. When Enter creates additional top-level
 * paragraph/heading nodes, fold them into the last foldable source block as a
 * multi-paragraph rich_text document so paragraph semantics persist and save works.
 */
function plainTextFromRichTextNode(node, depth = 0) {
  if (depth > 12 || !node || typeof node !== "object") return "";
  if (node.type === "text") return String(node.text || "");
  if (node.type === "hardBreak") return "\n";
  const children = Array.isArray(node.content) ? node.content : [];
  const childText = children.map((child) => plainTextFromRichTextNode(child, depth + 1));
  return node.type === "doc" ? childText.join("\n") : childText.join("");
}

function richTextParagraphNodesFromEditorNode(node) {
  const rich = richTextFromSourceBlockNode(node);
  if (!rich) {
    const text = tiptapNodeText(node);
    return [{
      type: greenfieldBlockTypeFromEditorNode(node) === "heading" ? "heading" : "paragraph",
      ...(greenfieldBlockTypeFromEditorNode(node) === "heading" ? { attrs: { level: 2 } } : {}),
      ...(text ? { content: tiptapInlineTextContent(text) } : {}),
    }];
  }
  if (rich.type === "doc" && Array.isArray(rich.content)) return rich.content.filter(Boolean);
  return [rich];
}

function appendEditorNodesToRichText(baseRichText, editorNodes) {
  const paragraphs = baseRichText?.type === "doc" && Array.isArray(baseRichText.content)
    ? baseRichText.content.filter(Boolean)
    : baseRichText
      ? [baseRichText]
      : [];
  for (const node of editorNodes) {
    paragraphs.push(...richTextParagraphNodesFromEditorNode(node));
  }
  if (!paragraphs.length) return null;
  return paragraphs.length === 1
    ? paragraphs[0]
    : { type: "doc", content: paragraphs };
}

function insertProtocolCitation(editor, insertion) {
  const referenceId = String(insertion?.referenceId || "").trim();
  if (!editor || !referenceId) return false;
  const cursor = editor.state.selection.to;
  return editor.chain()
    .focus()
    .setTextSelection(cursor)
    .insertContent({
      type: "text",
      text: "[待编号]",
      marks: [{ type: "citation", attrs: { referenceIds: [referenceId] } }],
    })
    .unsetMark("citation")
    .run();
}

function bindSourceTableDomIdentity(editor, tableBlocks = []) {
  const tables = Array.from(editor?.view?.dom?.querySelectorAll?.("table") || []);
  for (const block of tableBlocks) {
    let table = tables.find((candidate) => (
      candidate.getAttribute("data-source-block-id") === block.block_id
    ));
    if (!table) {
      const firstVisibleCellId = (block.rows || [])
        .flatMap((row) => row || [])
        .find((cell) => !cell?.hidden && cell?.cell_id)?.cell_id;
      table = tables.find((candidate) => (
        firstVisibleCellId
        && Array.from(candidate.querySelectorAll("[data-cell-id]")).some((cell) => (
          cell.getAttribute("data-cell-id") === firstVisibleCellId
        ))
      ));
    }
    if (!table) continue;
    if (block.block_id) table.setAttribute("data-source-block-id", block.block_id);
    if (block.table_id) table.setAttribute("data-source-table-id", block.table_id);
  }
}

function tableRowsFromTiptapNode(block, node) {
  if (node?.type !== "table") return null;
  const sourceRows = block.rows || [];
  const editorRows = node.content || [];
  if (editorRows.length !== sourceRows.length) return null;
  const nextRows = [];
  for (let rowIndex = 0; rowIndex < editorRows.length; rowIndex += 1) {
    const sourceRow = sourceRows[rowIndex] || [];
    const visibleSourceRow = sourceRow.filter((cell) => !cell?.hidden);
    const editorCells = editorRows[rowIndex]?.content || [];
    const sourceCellsById = new Map(
      visibleSourceRow
        .filter((cell) => String(cell.cell_id || ""))
        .map((cell) => [String(cell.cell_id), cell]),
    );
    const editedCellsById = new Map();
    let anonymousSourceIndex = 0;
    for (let cellIndex = 0; cellIndex < editorCells.length; cellIndex += 1) {
      const cellNode = editorCells[cellIndex];
      const cellId = String(cellNode?.attrs?.cellId || "");
      let sourceCell = cellId ? sourceCellsById.get(cellId) : null;
      if (!sourceCell && !cellId) {
        while (
          anonymousSourceIndex < visibleSourceRow.length
          && String(visibleSourceRow[anonymousSourceIndex]?.cell_id || "")
        ) anonymousSourceIndex += 1;
        sourceCell = visibleSourceRow[anonymousSourceIndex] || null;
        if (sourceCell) anonymousSourceIndex += 1;
      }
      if (!sourceCell) {
        // ProseMirror normalizes irregular DOCX tables to a rectangular grid.
        // Anonymous empty filler cells do not represent source content and are ignored.
        if (!cellId && !tiptapNodeText(cellNode).trim()) continue;
        return null;
      }
      const sourceCellKey = String(
        sourceCell.cell_id || `anonymous-${visibleSourceRow.indexOf(sourceCell)}`,
      );
      editedCellsById.set(sourceCellKey, {
        ...sourceCell,
        text: tiptapNodeText(cellNode),
        rich_text: {
          type: "doc",
          content: Array.isArray(cellNode?.content) ? cellNode.content : [],
        },
      });
    }
    if (editedCellsById.size !== visibleSourceRow.length) return null;
    let visibleCellIndex = 0;
    nextRows.push(sourceRow.map((cell) => {
      if (cell?.hidden) return cell;
      const key = String(cell.cell_id || `anonymous-${visibleCellIndex}`);
      visibleCellIndex += 1;
      return editedCellsById.get(key);
    }));
  }
  return nextRows;
}

function synchronizeTableBlockRows(block, rows) {
  const nextBlock = { ...block, rows };
  const structuredRows = block?.structured_table?.rows;
  if (!Array.isArray(structuredRows)) return nextBlock;
  const cellContentById = new Map(
    rows.flatMap((row) => (row || [])
      .filter((cell) => String(cell?.cell_id || ""))
      .map((cell) => [String(cell.cell_id), {
        text: String(cell.text || ""),
        rich_text: cell.rich_text || null,
      }])),
  );
  return {
    ...nextBlock,
    structured_table: {
      ...block.structured_table,
      rows: structuredRows.map((row) => ({
        ...row,
        cells: Array.isArray(row?.cells)
          ? row.cells.map((cell) => {
            const cellId = String(cell?.cell_id || "");
            return cellContentById.has(cellId)
              ? { ...cell, ...cellContentById.get(cellId) }
              : cell;
          })
          : row?.cells,
      })),
    },
  };
}

const MEDICAL_WRITING_RECOVERY_DRAFT_PREFIX = "cms-medical-writing-recovery:v1";

function medicalWritingRecoveryDraftPrefix({ projectId, documentId, sectionId }) {
  return [
    MEDICAL_WRITING_RECOVERY_DRAFT_PREFIX,
    encodeURIComponent(String(projectId || "")),
    encodeURIComponent(String(documentId || "")),
    encodeURIComponent(String(sectionId || "")),
  ].join(":");
}

function medicalWritingRecoveryDraftKey(identity) {
  return `${medicalWritingRecoveryDraftPrefix(identity)}:${Number(identity.baseRevision || 0)}`;
}

function sanitizeMedicalWritingRecoveryValue(value, key = "") {
  if (
    /^(?:file_bytes|bytes|blob|binary|base64|data_url|file_path|root_path|raw_file|source_file|content_b64|image_data|secret|token|api_key|credential)$/i.test(key)
  ) return undefined;
  if (typeof value === "string" && /^data:[^;]+;base64,/i.test(value)) return undefined;
  if (Array.isArray(value)) {
    return value
      .map((item) => sanitizeMedicalWritingRecoveryValue(item))
      .filter((item) => item !== undefined);
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .map(([entryKey, entryValue]) => [
          entryKey,
          sanitizeMedicalWritingRecoveryValue(entryValue, entryKey),
        ])
        .filter(([, entryValue]) => entryValue !== undefined),
    );
  }
  return value;
}

function medicalWritingRecoveryContentHash(contentBlocks) {
  const serialized = JSON.stringify(sanitizeMedicalWritingRecoveryValue(contentBlocks || []));
  let hash = 0x811c9dc5;
  for (let index = 0; index < serialized.length; index += 1) {
    hash ^= serialized.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return `fnv1a32:${(hash >>> 0).toString(16).padStart(8, "0")}`;
}

function listMedicalWritingRecoveryDrafts(storage, identity) {
  if (!storage || !identity.projectId || !identity.documentId || !identity.sectionId) return [];
  const prefix = `${medicalWritingRecoveryDraftPrefix(identity)}:`;
  const drafts = [];
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index);
    if (!key?.startsWith(prefix)) continue;
    try {
      const draft = JSON.parse(storage.getItem(key) || "null");
      if (
        draft?.schemaVersion === 1
        && draft.projectId === identity.projectId
        && draft.documentId === identity.documentId
        && draft.sectionId === identity.sectionId
        && Array.isArray(draft.contentBlocks)
      ) drafts.push({ ...draft, storageKey: key });
    } catch {
      // Ignore an invalid session-only recovery entry; server content remains authoritative.
    }
  }
  return drafts.sort((left, right) => String(right.updatedAt || "").localeCompare(String(left.updatedAt || "")));
}

function persistMedicalWritingRecoveryDraft(storage, identity, contentBlocks, now = new Date()) {
  if (!storage || !identity.projectId || !identity.documentId || !identity.sectionId) return null;
  const sanitizedBlocks = sanitizeMedicalWritingRecoveryValue(contentBlocks || []);
  const draft = {
    schemaVersion: 1,
    projectId: identity.projectId,
    documentId: identity.documentId,
    sectionId: identity.sectionId,
    baseRevision: Number(identity.baseRevision || 0),
    updatedAt: now.toISOString(),
    contentHash: medicalWritingRecoveryContentHash(sanitizedBlocks),
    contentBlocks: sanitizedBlocks,
  };
  const storageKey = medicalWritingRecoveryDraftKey(identity);
  storage.setItem(storageKey, JSON.stringify(draft));
  return { ...draft, storageKey };
}

function clearMedicalWritingRecoveryDrafts(storage, identity) {
  if (!storage) return;
  listMedicalWritingRecoveryDrafts(storage, identity).forEach((draft) => storage.removeItem(draft.storageKey));
}

function medicalWritingRecoveryDraftState(serverRevision, draft) {
  if (!draft) return "none";
  return Number(draft.baseRevision || 0) === Number(serverRevision || 0) ? "matching" : "conflict";
}

function workingCopyFreezeLabel(workingCopy) {
  if (workingCopy?.content_authority_state === "historical_quarantined") return "历史版本已隔离";
  return {
    editable: "编辑中",
    frozen: "当前作者确认版本 / 已冻结",
    invalidated: "已变更，待重新确认",
  }[workingCopy?.freeze_status] || "状态待确认";
}

function workingCopyFreezeTone(workingCopy) {
  if (workingCopy?.content_authority_state === "historical_quarantined") return "warning";
  if (workingCopy?.freeze_status === "frozen") return "success";
  if (workingCopy?.freeze_status === "invalidated") return "warning";
  return "info";
}

function freezeGapLabel(reasonCode) {
  return {
    working_copy_not_saved: "尚未保存版本",
    working_copy_quarantined: "历史内容已隔离",
    section_not_frozen: "待作者确认",
    freeze_invalidated: "冻结已失效",
    freeze_snapshot_missing: "冻结快照缺失",
    freeze_snapshot_inconsistent: "冻结快照不一致",
    applicability_unresolved: "章节适用性待确认",
  }[reasonCode] || "待处置";
}

function contentDispositionLabel(status) {
  return {
    open: "待医学处置",
    confirmed_source_text: "已确认沿用",
    correction_required: "需要修正",
  }[status] || "待医学处置";
}

function contentDispositionTone(status) {
  if (status === "confirmed_source_text") return "success";
  if (status === "correction_required") return "danger";
  return "warning";
}

function ContentFindingSourceText({ finding }) {
  const text = String(finding?.source_text || "");
  const start = Number(finding?.match_start);
  const end = Number(finding?.match_end);
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start || end > text.length) {
    return <>{text || "未返回原始信息"}</>;
  }
  return (
    <>
      {text.slice(0, start)}
      <mark>{text.slice(start, end)}</mark>
      {text.slice(end)}
    </>
  );
}

const PROTOCOL_STYLE_PRESETS = [
  { id: "heading_1", label: "一级标题", node: "heading", level: 1, font: "黑体", size: "16pt", attrs: { lineHeight: 1, spacingBeforePt: 18, spacingAfterPt: 8, leftIndentChars: 0, rightIndentChars: 0, firstLineIndentChars: 0 } },
  { id: "heading_2", label: "二级标题", node: "heading", level: 2, font: "黑体", size: "14pt", attrs: { lineHeight: 1, spacingBeforePt: 14, spacingAfterPt: 6, leftIndentChars: 0, rightIndentChars: 0, firstLineIndentChars: 0 } },
  { id: "heading_3", label: "三级标题", node: "heading", level: 3, font: "黑体", size: "12pt", attrs: { lineHeight: 1, spacingBeforePt: 10, spacingAfterPt: 4, leftIndentChars: 0, rightIndentChars: 0, firstLineIndentChars: 0 } },
  { id: "heading_4", label: "四级标题", node: "heading", level: 4, font: "黑体", size: "10.5pt", attrs: { lineHeight: 1, spacingBeforePt: 8, spacingAfterPt: 3, leftIndentChars: 0, rightIndentChars: 0, firstLineIndentChars: 0 } },
  { id: "body", label: "正文", node: "paragraph", font: "宋体", size: "10.5pt", attrs: { lineHeight: 1.5, spacingBeforePt: 0, spacingAfterPt: 4, leftIndentChars: 0, rightIndentChars: 0, firstLineIndentChars: 2 } },
  { id: "note", label: "附注", node: "paragraph", font: "宋体", size: "9pt", attrs: { lineHeight: 1, spacingBeforePt: 2, spacingAfterPt: 2, leftIndentChars: 0, rightIndentChars: 0, firstLineIndentChars: 0 } },
];
const PROTOCOL_FONT_OPTIONS = ["宋体", "黑体", "仿宋", "楷体", "Arial", "Times New Roman"];
const PROTOCOL_FONT_SIZE_OPTIONS = ["8pt", "9pt", "10.5pt", "12pt", "14pt", "16pt", "18pt", "22pt"];
const PROTOCOL_HIGHLIGHT_OPTIONS = [
  { value: "", label: "无标黄", color: "transparent" },
  { value: "#FFFF00", label: "黄色", color: "#ffff00" },
  { value: "#00FF00", label: "绿色", color: "#00ff00" },
  { value: "#00FFFF", label: "青色", color: "#00ffff" },
  { value: "#FF00FF", label: "粉色", color: "#ff00ff" },
];

function selectedProtocolBlockType(editor) {
  return editor?.isActive("heading") ? "heading" : "paragraph";
}

function selectedProtocolBlockAttrs(editor) {
  if (!editor) return {};
  return editor.getAttributes(selectedProtocolBlockType(editor)) || {};
}

function updateSelectedProtocolBlock(editor, attrs) {
  if (!editor) return false;
  return editor.chain().focus().updateAttributes(selectedProtocolBlockType(editor), attrs).run();
}

function applyProtocolStylePreset(editor, presetId) {
  const preset = PROTOCOL_STYLE_PRESETS.find((item) => item.id === presetId);
  if (!editor || !preset) return;
  const chain = editor.chain().focus();
  if (preset.node === "heading") chain.setHeading({ level: preset.level });
  else chain.setParagraph();
  chain.updateAttributes(preset.node, {
    stylePreset: preset.id,
    ...preset.attrs,
  }).run();
}

function clearProtocolDirectFormatting(editor) {
  if (!editor) return;
  const attrs = selectedProtocolBlockAttrs(editor);
  editor.chain().focus().unsetAllMarks().updateAttributes(selectedProtocolBlockType(editor), {
    ...PROTOCOL_PARAGRAPH_ATTRIBUTE_DEFAULTS,
    stylePreset: attrs.stylePreset || null,
  }).run();
}

function RichProtocolEditor({
  section,
  approvedLocked,
  readOnly = false,
  selectedSection,
  contentBlocks = [],
  sourceBlocks = [],
  onSelectedTextChange,
  onSelectedAnchorChange,
  onSelectedBlockContextChange,
  onEditorTextChange,
  onContentBlocksChange,
  onStructureError,
  tableTemplates = [],
  tableDomainProfiles = [],
  suggestedTableDomain = "",
  tableInsertBusy = false,
  canInsertTableTemplate = false,
  onInsertTableTemplate,
  focusTableBlockId = "",
  onFocusTableHandled,
  revisionThreads = [],
  citationInsertion = null,
  onCitationInsertionHandled,
  documentIndex = null,
  isGreenfieldAuthoring = false,
  allowEmptyDocument = false,
  fullscreenSaveState = "",
  fullscreenSaveDisabled = true,
  fullscreenSaveBusy = false,
  onFullscreenSave,
  onFullscreenOpenTool,
}) {
  const [activeTableBlockId, setActiveTableBlockId] = useState("");
  const [designerOpen, setDesignerOpen] = useState(false);
  const [documentFullscreen, setDocumentFullscreen] = useState(false);
  const [templateMenuOpen, setTemplateMenuOpen] = useState(false);
  const [paragraphSettingsOpen, setParagraphSettingsOpen] = useState(false);
  const [customTableDialogOpen, setCustomTableDialogOpen] = useState(false);
  const [duplicateTableRequest, setDuplicateTableRequest] = useState(null);
  const [customTableConfig, setCustomTableConfig] = useState({
    title: "",
    rowCount: 5,
    columnCount: 3,
    headerRowCount: 1,
    orientation: "auto",
    notesArea: true,
  });
  const [tableHorizontalScroll, setTableHorizontalScroll] = useState({
    overflow: false,
    canLeft: false,
    canRight: false,
  });
  const tableSelectionGuardRef = useRef({ blockId: "", until: 0 });
  const editorBaselineJsonRef = useRef("");
  const contentBlocksRef = useRef(contentBlocks);
  const sourceBlocksRef = useRef(sourceBlocks);
  // Sync props → ref after paint only. Updating refs during render would clobber
  // synchronous onUpdate ref writes when parent re-renders for selection state
  // before draft contentBlocks flush (TipTap can emit multiple updates per keystroke).
  // See: https://tiptap.dev/docs/editor/getting-started/install/react
  useEffect(() => {
    contentBlocksRef.current = contentBlocks;
  }, [contentBlocks]);
  useEffect(() => {
    sourceBlocksRef.current = sourceBlocks;
  }, [sourceBlocks]);
  const editableBlocks = contentBlocks.filter((block) => block.block_type !== "table" && String(block.text || "").trim());
  const tableBlocks = contentBlocks.filter((block) => block.block_type === "table" && Array.isArray(block.rows));
  const realSourceContent = contentBlocks.length || allowEmptyDocument
    ? {
      type: "doc",
      content: contentBlocks.map(tiptapNodeFromContentBlock),
    }
    : null;
  const editor = useEditor({
    extensions: [
      StarterKit,
      TextStyle,
      FontFamily,
      FontSize,
      Color,
      Subscript,
      Superscript,
      CitationMark,
      CrossReferenceMark,
      Highlight.configure({ multicolor: true }),
      TextAlign.configure({ types: ["heading", "paragraph"] }),
      ProtocolParagraphFormatting,
      WordEditingShortcuts,
      SourceBlockEnter,
      SourceBlock,
      SourceDocxImage,
      SourceTable.configure({ resizable: true }),
      SourceTableRow,
      SourceTableHeader,
      SourceTableCell,
    ],
    editable: !approvedLocked && !readOnly,
    content: realSourceContent || `
      <h2>${selectedSection === "synopsis" ? "1.1 方案概要" : "3.2 研究目的与终点"}</h2>
      <p>主要疗效终点为治疗期预设关键评估时间点 rTNSS 总分较基线的变化，具体分析时间窗和缺失数据处理方法将在统计学章节及 SAP 中进一步规定。</p>
      <table>
        <tbody>
          <tr><th>终点类型</th><th>终点名称</th><th>时间窗</th><th>分析集</th><th>证据状态</th></tr>
          <tr><td>主要</td><td>rTNSS 较基线变化</td><td>治疗期关键时间窗</td><td>ITT</td><td>待补竞品依据</td></tr>
          <tr><td>次要</td><td>iTNSS 较基线变化</td><td>W1-W4</td><td>ITT</td><td>已有方案模板</td></tr>
        </tbody>
      </table>
    `,
    onCreate: ({ editor }) => {
      editorBaselineJsonRef.current = stableJsonStringify(editor.getJSON());
      onEditorTextChange?.(editor.getText().trim());
      const firstBodyBlock = contentBlocksRef.current.find((block) => (
        block.block_type !== "heading" && contentBlockText(block)
      ));
      const firstWorkingBlock = firstBodyBlock
        || contentBlocksRef.current.find(isBlankGreenfieldBodyBlock)
        || contentBlocksRef.current.find((block) => contentBlockText(block));
      onSelectedTextChange?.(contentBlockText(firstBodyBlock));
      onSelectedAnchorChange?.(firstWorkingBlock?.source_locator || "");
      onSelectedBlockContextChange?.({
        blockType: firstWorkingBlock?.block_type || "",
        sourceKind: firstWorkingBlock?.source_kind || "",
      });
    },
    onUpdate: ({ editor }) => {
      onEditorTextChange?.(editor.getText().trim());
      if (readOnly || !contentBlocksRef.current.length) return;
      const currentBlocks = contentBlocksRef.current;
      const rawEditorNodes = editor.getJSON().content || [];
      const isEffectivelyEmptyNode = (node) => {
        const text = tiptapNodeText(node).replace(/[\u200b\u200c\u200d\ufeff]/g, "").trim();
        return !text;
      };
      // Ignore only TipTap's unbound empty document tail. Bound nodes and
      // non-empty additions are reconciled by stable sourceBlockId below.
      let editorNodes = rawEditorNodes;
      while (
        editorNodes.length
        && !editorNodes[editorNodes.length - 1]?.attrs?.sourceBlockId
        && isEffectivelyEmptyNode(editorNodes[editorNodes.length - 1])
      ) {
        editorNodes = editorNodes.slice(0, -1);
      }
      const grouped = groupEditorNodesBySourceBlockId(
        currentBlocks,
        editorNodes,
        { isEffectivelyEmptyNode },
      );
      if (grouped.error) {
        onStructureError?.(grouped.error);
        return;
      }
      let invalidTableStructure = false;
      const mappedBlocks = currentBlocks.map((block, index) => {
        const editorGroup = grouped.groups[index];
        const editorNode = editorGroup.node;
        if (block.block_type === "figure") {
          if (
            editorNode?.type !== "sourceDocxImage"
            || editorNode?.attrs?.sourceBlockId !== block.block_id
            || editorNode?.attrs?.imageId !== (block.image_id || block.figure_id)
          ) invalidTableStructure = true;
          return block;
        }
        if (block.block_type === "table") {
          const rows = tableRowsFromTiptapNode(block, editorNode);
          if (
            !rows
            || editorNode?.attrs?.sourceBlockId !== block.block_id
            || editorNode?.attrs?.sourceTableId !== block.table_id
          ) {
            invalidTableStructure = true;
            return block;
          }
          return synchronizeTableBlockRows(block, rows);
        }
        const editorNodesForRichText = [
          ...editorGroup.leadingNodes,
          ...(
            editorGroup.leadingNodes.length && isEffectivelyEmptyNode(editorNode)
              ? []
              : [editorNode]
          ),
          ...editorGroup.trailingNodes,
        ];
        const richText = appendEditorNodesToRichText(null, editorNodesForRichText);
        if (!richText) {
          invalidTableStructure = true;
          return block;
        }
        // Keep text in lockstep with rich_text plain text (backend invariant).
        const plain = plainTextFromRichTextNode(richText);
        return {
          ...block,
          text: plain,
          rich_text: richText,
        };
      });
      if (invalidTableStructure) {
        onStructureError?.("表格、图片或来源块身份发生变化；系统已阻止保存。表格行列、合并单元格和结构化附注请在对应设计器中调整。");
        return;
      }
      onStructureError?.("");
      const normalizedEditorJson = stableJsonStringify({
        type: "doc",
        content: editorNodes,
      });
      if (!editorBaselineJsonRef.current) {
        editorBaselineJsonRef.current = normalizedEditorJson;
        return;
      }
      const contentChanged = normalizedEditorJson !== editorBaselineJsonRef.current;
      if (contentChanged) {
        // Keep ref in sync before React re-renders so successive TipTap onUpdate
        // bursts see the latest mapped blocks without identity churn.
        // https://tiptap.dev/docs/editor/getting-started/install/react
        contentBlocksRef.current = mappedBlocks;
        onContentBlocksChange?.(mappedBlocks);
      }
    },
    onSelectionUpdate: ({ editor }) => {
      const { from, to } = editor.state.selection;
      let selectedBlockIndex = 0;
      editor.state.doc.forEach((node, offset, index) => {
        if (from >= offset && from <= offset + node.nodeSize) selectedBlockIndex = index;
      });
      const workingBlock = contentBlocksRef.current[selectedBlockIndex];
      const explicitSelection = from !== to;
      const revisionWorkingBlock = workingBlock?.block_type === "heading" && !explicitSelection
        ? contentBlocksRef.current.find((block) => (
          block.block_type !== "heading" && contentBlockText(block)
        )) || contentBlocksRef.current.find(isBlankGreenfieldBodyBlock) || workingBlock
        : workingBlock;
      setActiveTableBlockId(
        workingBlock?.block_type === "table" ? workingBlock.block_id : "",
      );
      const editorSelection = explicitSelection
        ? editor.state.doc.textBetween(from, to, " ").trim()
        : "";
      const fullWorkingText = contentBlockText(revisionWorkingBlock);
      const workingSelection = editorSelection && fullWorkingText.includes(editorSelection)
        ? editorSelection
        : isBlankGreenfieldBodyBlock(revisionWorkingBlock)
          ? ""
          : fullWorkingText;
      onSelectedTextChange?.(workingSelection);
      onSelectedAnchorChange?.(revisionWorkingBlock?.source_locator || "");
      onSelectedBlockContextChange?.({
        blockType: revisionWorkingBlock?.block_type || "",
        sourceKind: revisionWorkingBlock?.source_kind || "",
      });
    },
  });

  useEffect(() => {
    if (
      !editor
      || !import.meta.env.DEV
      || !globalThis.location?.search?.includes("editorDebug=1")
    ) return undefined;
    const diagnostic = {
      getJSON: () => editor.getJSON(),
      getSelection: () => {
        const { $from, $to, from, to } = editor.state.selection;
        const parentChain = Array.from(
          { length: $from.depth + 1 },
          (_, depth) => ({
            depth,
            type: $from.node(depth).type.name,
            sourceBlockId: $from.node(depth).attrs?.sourceBlockId || "",
          }),
        );
        return { from, to, parentChain, sameParent: $from.sameParent($to) };
      },
    };
    globalThis.__MEDICAL_WRITING_EDITOR_DIAGNOSTIC__ = diagnostic;
    return () => {
      if (globalThis.__MEDICAL_WRITING_EDITOR_DIAGNOSTIC__ === diagnostic) {
        delete globalThis.__MEDICAL_WRITING_EDITOR_DIAGNOSTIC__;
      }
    };
  }, [editor]);

  useEffect(() => {
    editor?.setEditable(!approvedLocked && !readOnly);
  }, [editor, approvedLocked, readOnly]);

  useEffect(() => {
    if (!documentFullscreen) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === "Escape") setDocumentFullscreen(false);
    };
    globalThis.addEventListener?.("keydown", closeOnEscape);
    return () => globalThis.removeEventListener?.("keydown", closeOnEscape);
  }, [documentFullscreen]);

  useEffect(() => {
    if (!editor || !citationInsertion?.id) return;
    if (readOnly || approvedLocked) {
      onCitationInsertionHandled?.(
        citationInsertion.id,
        "当前章节为只读或已锁定状态，请先创建可编辑工作副本。",
      );
      return;
    }
    const inserted = insertProtocolCitation(editor, citationInsertion);
    onCitationInsertionHandled?.(
      citationInsertion.id,
      inserted
        ? `已在当前光标处插入《${citationInsertion.title || "所选文献"}》的待统一编号上标引文；保存工作副本后纳入版本记录。`
        : "未能在当前光标处插入引文，请重新点击正文定位后再试。",
    );
  }, [editor, citationInsertion?.id, readOnly, approvedLocked]);

  const selectedBlockAttrs = selectedProtocolBlockAttrs(editor);
  const selectedStylePreset = selectedBlockAttrs.stylePreset
    || (editor?.isActive("heading")
      ? `heading_${Math.min(Number(editor.getAttributes("heading")?.level || 1), 4)}`
      : "body");
  const selectedPreset = PROTOCOL_STYLE_PRESETS.find((item) => item.id === selectedStylePreset)
    || PROTOCOL_STYLE_PRESETS[4];
  const selectedTextStyle = editor?.getAttributes("textStyle") || {};
  const selectedHighlight = editor?.getAttributes("highlight")?.color || "";
  const formattingDisabled = approvedLocked || readOnly || !editor;
  const setNumericParagraphAttribute = (key, rawValue) => {
    const value = Number(rawValue);
    if (!Number.isFinite(value)) return;
    updateSelectedProtocolBlock(editor, { [key]: value });
  };
  const adjustLeftIndent = (delta) => {
    const current = Number(selectedProtocolBlockAttrs(editor).leftIndentChars || 0);
    updateSelectedProtocolBlock(editor, {
      leftIndentChars: Math.min(20, Math.max(0, current + delta)),
    });
  };
  const activeTableBlock = tableBlocks.find((block) => block.block_id === activeTableBlockId)
    || tableBlocks[0]
    || null;
  const crossReferenceTargets = [
    ...(documentIndex?.tables || []),
    ...(documentIndex?.figures || []),
  ];
  const activeTableNotes = visibleTableNotes(activeTableBlock);
  const activeTableTitle = visibleTableTitle(activeTableBlock, section.title);
  const activeSourceCaption = sourceTableCaptionText(activeTableBlock);
  const sourceCaptionDiffers = activeSourceCaption
    && normalizedVisibleText(activeSourceCaption) !== normalizedVisibleText(activeTableTitle);
  const activeTableProfile = tableDomainProfiles.find((profile) => (
    profile.domain === activeTableBlock?.structured_table?.domain
  ));
  const designerTableBlock = useMemo(() => (
    activeTableBlock
      ? {
        ...activeTableBlock,
        structured_table: {
          ...(activeTableBlock.structured_table || {}),
          title: activeTableBlock.structured_table?.title
            || activeTableBlock.title
            || (/(?:表|表格)$/.test(section.title) ? section.title : `${section.title}表格`),
          domain: activeTableBlock.structured_table?.domain
            || (/流程表|schedule of (?:activities|assessments)/i.test(section.title)
              ? "schedule_of_activities"
              : "generic"),
        },
      }
      : null
  ), [activeTableBlock, section.title]);

  useEffect(() => {
    bindSourceTableDomIdentity(editor, tableBlocks);
  }, [editor, selectedSection, tableBlocks.map((block) => block.block_id).join("|")]);

  useEffect(() => {
    const scroller = editor?.view?.dom;
    if (!scroller) return undefined;
    let frame = 0;
    const synchronizeHorizontalScroll = () => {
      globalThis.cancelAnimationFrame?.(frame);
      frame = globalThis.requestAnimationFrame?.(() => {
        const maxScrollLeft = Math.max(0, scroller.scrollWidth - scroller.clientWidth);
        setTableHorizontalScroll({
          overflow: maxScrollLeft > 2,
          canLeft: scroller.scrollLeft > 2,
          canRight: scroller.scrollLeft < maxScrollLeft - 2,
        });
      }) || 0;
    };
    synchronizeHorizontalScroll();
    scroller.addEventListener("scroll", synchronizeHorizontalScroll, { passive: true });
    const observer = globalThis.ResizeObserver
      ? new globalThis.ResizeObserver(synchronizeHorizontalScroll)
      : null;
    observer?.observe(scroller);
    return () => {
      globalThis.cancelAnimationFrame?.(frame);
      scroller.removeEventListener("scroll", synchronizeHorizontalScroll);
      observer?.disconnect();
    };
  }, [editor, selectedSection, activeTableBlock?.block_id, tableBlocks.length]);

  const selectActiveTable = (blockId) => {
    const selectedTable = tableBlocks.find((block) => block.block_id === blockId);
    if (!selectedTable) return;
    tableSelectionGuardRef.current = {
      blockId: selectedTable.block_id,
      until: Date.now() + 500,
    };
    setActiveTableBlockId(selectedTable.block_id);
    onSelectedTextChange?.(contentBlockText(selectedTable));
    onSelectedAnchorChange?.(selectedTable.source_locator || "");
    onSelectedBlockContextChange?.({
      blockType: "table",
      sourceKind: selectedTable.source_kind || "",
      tableCell: null,
    });
    globalThis.requestAnimationFrame?.(() => {
      bindSourceTableDomIdentity(editor, tableBlocks);
      editor?.view?.dom?.scrollTo?.({ left: 0, behavior: "auto" });
      const tableElement = Array.from(
        editor?.view?.dom?.querySelectorAll?.("table[data-source-block-id]") || [],
      ).find((element) => element.getAttribute("data-source-block-id") === selectedTable.block_id);
      tableElement?.scrollIntoView?.({ block: "center", inline: "nearest", behavior: "auto" });
    });
  };

  const requestTemplateInsert = (template) => {
    const matchingTables = tableBlocks.filter(
      (block) => block.template_id === template.template_id,
    );
    if (matchingTables.length) {
      setDuplicateTableRequest({ template, matchingTables });
      return;
    }
    onInsertTableTemplate?.(template.template_id);
  };

  const scrollActiveTableHorizontally = (direction) => {
    const scroller = editor?.view?.dom;
    if (!scroller) return;
    const distance = Math.max(320, Math.round(scroller.clientWidth * 0.72));
    scroller.scrollBy({ left: distance * direction, behavior: "smooth" });
  };

  useEffect(() => {
    const focusedTable = tableBlocks.find((block) => block.block_id === focusTableBlockId);
    if (!focusedTable) return;
    selectActiveTable(focusTableBlockId);
    setDesignerOpen(true);
    setTemplateMenuOpen(false);
    onFocusTableHandled?.();
  }, [focusTableBlockId, tableBlocks.length]);

  useEffect(() => {
    const scroller = editor?.view?.dom?.closest?.(".protocol-editor");
    if (!scroller) return undefined;
    bindSourceTableDomIdentity(editor, tableBlocks);
    let frame = 0;
    const synchronizeVisibleTable = () => {
      globalThis.cancelAnimationFrame?.(frame);
      frame = globalThis.requestAnimationFrame?.(() => {
        const guardedSelection = tableSelectionGuardRef.current;
        if (guardedSelection.blockId && Date.now() < guardedSelection.until) {
          setActiveTableBlockId(guardedSelection.blockId);
          return;
        }
        const scrollerRect = scroller.getBoundingClientRect();
        const tables = Array.from(
          editor.view.dom.querySelectorAll("table[data-source-block-id]"),
        ).filter((table) => {
          const rect = table.getBoundingClientRect();
          return rect.bottom >= scrollerRect.top && rect.top <= scrollerRect.bottom;
        });
        if (!tables.length) return;
        const nearest = tables.reduce((current, candidate) => (
          Math.abs(candidate.getBoundingClientRect().top - scrollerRect.top - 16)
            < Math.abs(current.getBoundingClientRect().top - scrollerRect.top - 16)
            ? candidate
            : current
        ));
        const blockId = nearest.getAttribute("data-source-block-id") || "";
        if (blockId) setActiveTableBlockId(blockId);
      }) || 0;
    };
    scroller.addEventListener("scroll", synchronizeVisibleTable, { passive: true });
    return () => {
      globalThis.cancelAnimationFrame?.(frame);
      scroller.removeEventListener("scroll", synchronizeVisibleTable);
    };
  }, [editor, selectedSection, tableBlocks.length]);

  const updateDesignerTable = (nextTableBlock) => {
    if (readOnly || !activeTableBlock) return;
    const nextBlocks = contentBlocksRef.current.map((block) => (
      block.block_id === activeTableBlock.block_id ? nextTableBlock : block
    ));
    contentBlocksRef.current = nextBlocks;
    onContentBlocksChange?.(nextBlocks);
    editor?.commands.setContent({
      type: "doc",
      content: nextBlocks.map(tiptapNodeFromContentBlock),
    }, { emitUpdate: false });
  };
  return (
    <div className={`rich-editor-shell ${documentFullscreen ? "document-fullscreen" : ""}`}>
      <div className="rich-editor-meta">
        <strong>{section.title}</strong>
        <span>{readOnly ? "来源只读" : "工作副本"}</span>
        {tableBlocks.length > 0 && <span>{tableBlocks.length} 个表格</span>}
        {documentFullscreen && (
          <div className="rich-editor-fullscreen-actions" aria-label="正文全屏关键操作">
            <span className={fullscreenSaveState === "有未保存修订" ? "is-dirty" : ""}>
              {fullscreenSaveState || (readOnly ? "只读" : "已保存")}
            </span>
            {!readOnly && (
              <button
                type="button"
                className="rich-editor-fullscreen-save"
                disabled={fullscreenSaveDisabled}
                title={fullscreenSaveDisabled ? fullscreenSaveState || "当前不可保存" : "保存当前工作副本"}
                onClick={onFullscreenSave}
              >
                <FileCheck2 size={14} /> {fullscreenSaveBusy ? "保存中" : "保存"}
              </button>
            )}
            {["AI", "证据", "文献"].map((tool) => (
              <button
                type="button"
                key={tool}
                title={`退出正文全屏并打开${tool === "AI" ? "AI候选与改写" : tool}`}
                onClick={() => {
                  setDocumentFullscreen(false);
                  onFullscreenOpenTool?.(tool);
                }}
              >
                {tool === "AI" ? <Sparkles size={14} /> : tool === "证据" ? <ScanSearch size={14} /> : <BookOpenText size={14} />}
                {tool === "AI" ? "AI候选/改写" : tool}
              </button>
            ))}
          </div>
        )}
        <button
          type="button"
          className="rich-editor-fullscreen-button"
          onClick={() => setDocumentFullscreen((value) => !value)}
          title={documentFullscreen ? "退出正文全屏" : "全屏编辑正文"}
          aria-label={documentFullscreen ? "退出正文全屏" : "全屏编辑正文"}
        >
          {documentFullscreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
        </button>
      </div>
      <div className="rich-toolbar" aria-label="医学写作格式工具栏">
        <div className="rich-toolbar-row rich-toolbar-text-row">
          <label className="rich-toolbar-select rich-style-select">
            <span>样式</span>
            <select
              aria-label="段落样式"
              value={selectedStylePreset}
              disabled={formattingDisabled}
              onChange={(event) => applyProtocolStylePreset(editor, event.target.value)}
            >
              {PROTOCOL_STYLE_PRESETS.map((preset) => (
                <option key={preset.id} value={preset.id}>{preset.label}</option>
              ))}
            </select>
          </label>
          <label className="rich-toolbar-select rich-font-select">
            <span>字体</span>
            <select
              aria-label="字体"
              value={selectedTextStyle.fontFamily || selectedPreset.font}
              disabled={formattingDisabled}
              onChange={(event) => editor?.chain().focus().setFontFamily(event.target.value).run()}
            >
              {PROTOCOL_FONT_OPTIONS.map((font) => <option key={font} value={font}>{font}</option>)}
            </select>
          </label>
          <label className="rich-toolbar-select rich-size-select">
            <span>字号</span>
            <select
              aria-label="字号"
              value={selectedTextStyle.fontSize || selectedPreset.size}
              disabled={formattingDisabled}
              onChange={(event) => editor?.chain().focus().setFontSize(event.target.value).run()}
            >
              {PROTOCOL_FONT_SIZE_OPTIONS.map((size) => <option key={size} value={size}>{size.replace("pt", "")}</option>)}
            </select>
          </label>
          <span className="rich-toolbar-separator" aria-hidden="true" />
          {[
            ["加粗", Bold, editor?.isActive("bold"), () => editor?.chain().focus().toggleBold().run()],
            ["斜体", Italic, editor?.isActive("italic"), () => editor?.chain().focus().toggleItalic().run()],
            ["下划线", UnderlineIcon, editor?.isActive("underline"), () => editor?.chain().focus().toggleUnderline().run()],
            ["上标", SuperscriptIcon, editor?.isActive("superscript"), () => editor?.chain().focus().toggleSuperscript().run()],
            ["下标", SubscriptIcon, editor?.isActive("subscript"), () => editor?.chain().focus().toggleSubscript().run()],
          ].map(([label, Icon, active, run]) => (
            <button
              type="button"
              key={label}
              className={active ? "active" : ""}
              disabled={formattingDisabled}
              onClick={run}
              title={label}
              aria-label={label}
            >
              <Icon size={15} />
            </button>
          ))}
          <span className="rich-toolbar-separator" aria-hidden="true" />
          <label className="rich-color-control" title="文字颜色">
            <Palette size={15} aria-hidden="true" />
            <span
              className="rich-color-swatch"
              style={{ backgroundColor: selectedTextStyle.color || "#222222" }}
              aria-hidden="true"
            />
            <input
              type="color"
              aria-label="文字颜色"
              value={/^#[0-9a-f]{6}$/i.test(selectedTextStyle.color || "") ? selectedTextStyle.color : "#222222"}
              disabled={formattingDisabled}
              onChange={(event) => editor?.chain().focus().setColor(event.target.value.toUpperCase()).run()}
            />
          </label>
          <label className="rich-highlight-control" title="文字标黄">
            <Highlighter size={15} aria-hidden="true" />
            <span
              className="rich-color-swatch"
              style={{ backgroundColor: selectedHighlight || "#ffff00" }}
              aria-hidden="true"
            />
            <select
              aria-label="文字标黄"
              value={selectedHighlight}
              disabled={formattingDisabled}
              onChange={(event) => {
                if (event.target.value) editor?.chain().focus().setHighlight({ color: event.target.value }).run();
                else editor?.chain().focus().unsetHighlight().run();
              }}
            >
              {PROTOCOL_HIGHLIGHT_OPTIONS.map((option) => (
                <option key={option.value || "none"} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={formattingDisabled}
            title={formattingDisabled ? "当前为只读状态，不能清除格式" : "清除直接格式，保留当前标准样式"}
            onClick={() => clearProtocolDirectFormatting(editor)}
            aria-label="清除直接格式"
          >
            <Eraser size={15} />
          </button>
        </div>
        <div className="rich-toolbar-row rich-toolbar-paragraph-row">
          {[
            ["项目符号", List, editor?.isActive("bulletList"), () => editor?.chain().focus().toggleBulletList().run()],
            ["编号", ListOrdered, editor?.isActive("orderedList"), () => editor?.chain().focus().toggleOrderedList().run()],
            ["左对齐", AlignLeft, editor?.isActive({ textAlign: "left" }), () => editor?.chain().focus().setTextAlign("left").run()],
            ["居中", AlignCenter, editor?.isActive({ textAlign: "center" }), () => editor?.chain().focus().setTextAlign("center").run()],
            ["右对齐", AlignRight, editor?.isActive({ textAlign: "right" }), () => editor?.chain().focus().setTextAlign("right").run()],
            ["两端对齐", AlignJustify, editor?.isActive({ textAlign: "justify" }), () => editor?.chain().focus().setTextAlign("justify").run()],
            ["减少左缩进", IndentDecrease, false, () => adjustLeftIndent(-1)],
            ["增加左缩进", IndentIncrease, false, () => adjustLeftIndent(1)],
          ].map(([label, Icon, active, run], index) => (
            <button
              type="button"
              key={label}
              className={active ? "active" : ""}
              disabled={formattingDisabled}
              onClick={run}
              title={label}
              aria-label={label}
            >
              <Icon size={15} />
            </button>
          ))}
          <span className="rich-toolbar-separator" aria-hidden="true" />
          <label className="rich-toolbar-select rich-line-height-select">
            <span>行距</span>
            <select
              aria-label="行距"
              value={selectedBlockAttrs.lineHeight ?? selectedPreset.attrs.lineHeight}
              disabled={formattingDisabled}
              onChange={(event) => setNumericParagraphAttribute("lineHeight", event.target.value)}
            >
              {[1, 1.15, 1.25, 1.5, 2].map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <div className="rich-paragraph-settings">
            <button
              type="button"
              className={paragraphSettingsOpen ? "active" : ""}
              disabled={formattingDisabled}
              aria-expanded={paragraphSettingsOpen}
              title={formattingDisabled ? "当前为只读状态，不能调整段落" : "段落设置"}
              onClick={() => setParagraphSettingsOpen((value) => !value)}
              aria-label="段落设置"
            >
              段落
            </button>
            {paragraphSettingsOpen && (
              <div className="rich-paragraph-popover" role="dialog" aria-label="段落设置">
                {[
                  ["首行缩进（字符）", "firstLineIndentChars", selectedBlockAttrs.firstLineIndentChars ?? selectedPreset.attrs.firstLineIndentChars, -10, 20, 0.5],
                  ["左缩进（字符）", "leftIndentChars", selectedBlockAttrs.leftIndentChars ?? 0, 0, 20, 0.5],
                  ["右缩进（字符）", "rightIndentChars", selectedBlockAttrs.rightIndentChars ?? 0, 0, 20, 0.5],
                  ["段前（磅）", "spacingBeforePt", selectedBlockAttrs.spacingBeforePt ?? selectedPreset.attrs.spacingBeforePt, 0, 72, 1],
                  ["段后（磅）", "spacingAfterPt", selectedBlockAttrs.spacingAfterPt ?? selectedPreset.attrs.spacingAfterPt, 0, 72, 1],
                ].map(([label, key, value, min, max, step]) => (
                  <label key={key}>
                    <span>{label}</span>
                    <input
                      type="number"
                      min={min}
                      max={max}
                      step={step}
                      value={value}
                      onChange={(event) => setNumericParagraphAttribute(key, event.target.value)}
                    />
                  </label>
                ))}
              </div>
            )}
          </div>
          <span className="rich-toolbar-separator" aria-hidden="true" />
          <button type="button" disabled={formattingDisabled || !editor?.can().undo()} title={formattingDisabled ? "当前为只读状态，不能撤销" : !editor?.can().undo() ? "当前没有可撤销的编辑" : "撤销"} onClick={() => editor?.chain().focus().undo().run()} aria-label="撤销"><Undo2 size={15} /></button>
          <button type="button" disabled={formattingDisabled || !editor?.can().redo()} title={formattingDisabled ? "当前为只读状态，不能重做" : !editor?.can().redo() ? "当前没有可重做的编辑" : "重做"} onClick={() => editor?.chain().focus().redo().run()} aria-label="重做"><Redo2 size={15} /></button>
          <span className="rich-toolbar-separator" aria-hidden="true" />
          <label className="rich-cross-reference-picker" title="插入表或图的交叉引用">
            <Link2 size={15} aria-hidden="true" />
            <select
              aria-label="插入交叉引用"
              value=""
              disabled={formattingDisabled || !crossReferenceTargets.length}
              onChange={(event) => {
                const [targetKind, targetId] = event.target.value.split(":", 2);
                const target = crossReferenceTargets.find((item) => (
                  item.kind === targetKind && item.object_id === targetId
                ));
                if (target) insertCrossReference(editor, target);
                event.target.value = "";
              }}
            >
              <option value="">交叉引用</option>
              {(documentIndex?.tables || []).length > 0 && (
                <optgroup label="表">
                  {documentIndex.tables.map((item) => (
                    <option key={`table:${item.object_id}`} value={`table:${item.object_id}`}>
                      {item.display_label}
                    </option>
                  ))}
                </optgroup>
              )}
              {(documentIndex?.figures || []).length > 0 && (
                <optgroup label="图">
                  {documentIndex.figures.map((item) => (
                    <option key={`figure:${item.object_id}`} value={`figure:${item.object_id}`}>
                      {item.display_label}
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
          </label>
          <span className="rich-toolbar-separator" aria-hidden="true" />
          {tableBlocks.length > 0 && (
            <label className="rich-table-picker">
              <Table2 size={15} aria-hidden="true" />
              <select
                aria-label="选择当前表格"
                value={activeTableBlock?.block_id || ""}
                onChange={(event) => selectActiveTable(event.target.value)}
                title="选择要查看或编辑的表格"
              >
                {tableBlocks.map((block, index) => (
                  <option key={block.block_id} value={block.block_id}>
                    {`表格 ${index + 1}｜${block.structured_table?.title || block.title || block.title_hint || section.title}`}
                  </option>
                ))}
              </select>
            </label>
          )}
          {activeTableBlock && (
            <button
              type="button"
              className="rich-table-designer-button"
              disabled={!editor}
              title={readOnly ? "全屏查看当前表格" : "全屏编辑当前表格结构与附注"}
              aria-label={readOnly ? "全屏查看当前表格" : "全屏编辑当前表格结构与附注"}
              onClick={() => setDesignerOpen(true)}
            >
              <Maximize2 size={15} />
            </button>
          )}
          {!readOnly && (
            <div className="rich-table-template-menu">
              <button
                type="button"
                className={templateMenuOpen ? "rich-table-template-button active" : "rich-table-template-button"}
                disabled={!canInsertTableTemplate || tableInsertBusy || !tableTemplates.length}
                title={!canInsertTableTemplate
                  ? "请先保存当前工作副本，并确保没有未保存修订"
                  : "从跨项目结构化模板插入表格"}
                aria-label="插入结构化表格"
                aria-expanded={templateMenuOpen}
                onClick={() => setTemplateMenuOpen((value) => !value)}
              >
                <Table2 size={15} />
                <span>{tableInsertBusy ? "插入中" : "插入表格"}</span>
              </button>
              {templateMenuOpen && (
                <div className="rich-table-template-popover" role="menu" aria-label="结构化表格模板">
                  {tableTemplates.map((template) => (
                    <button
                      type="button"
                      role="menuitem"
                      key={template.template_id}
                      onClick={() => {
                        setTemplateMenuOpen(false);
                        if (template.supports_custom_dimensions) {
                          setCustomTableConfig((current) => ({
                            ...current,
                            title: current.title || `${section.title}表格`,
                          }));
                          setCustomTableDialogOpen(true);
                        } else {
                          requestTemplateInsert(template);
                        }
                      }}
                    >
                      <strong>{template.label}</strong>
                      <span>{template.purpose}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
      {duplicateTableRequest && (
        <div className="rich-table-insert-overlay" role="presentation">
          <section className="rich-table-insert-dialog" role="dialog" aria-modal="true" aria-label="确认重复插入结构化表格">
            <header>
              <div>
                <span>结构化表格</span>
                <strong>当前章节已有“{duplicateTableRequest.template.label}”</strong>
              </div>
              <button type="button" onClick={() => setDuplicateTableRequest(null)} title="关闭" aria-label="关闭重复表格确认"><XCircle size={17} /></button>
            </header>
            <div className="rich-table-duplicate-summary">
              <p>已找到 {duplicateTableRequest.matchingTables.length} 张同模板表格。通常应继续编辑现有表格；仅在同一章节确需分别呈现不同分析、阶段或估计目标时再插入第二张。</p>
              {duplicateTableRequest.matchingTables.map((block, index) => (
                <button
                  type="button"
                  key={block.block_id}
                  onClick={() => {
                    selectActiveTable(block.block_id);
                    setDesignerOpen(true);
                    setDuplicateTableRequest(null);
                  }}
                >
                  <Table2 size={15} />
                  <span>打开现有表格 {index + 1}</span>
                  <strong>{visibleTableTitle(block, section.title)}</strong>
                </button>
              ))}
            </div>
            <footer>
              <span>明确重复插入会生成新的表格实例，并记录其与现有表格的关联。</span>
              <div>
                <button type="button" onClick={() => setDuplicateTableRequest(null)}>取消</button>
                <button
                  type="button"
                  className="primary-button"
                  disabled={tableInsertBusy}
                  title={tableInsertBusy ? "正在插入表格，请稍候" : "确认重复插入一张独立表格"}
                  onClick={() => {
                    onInsertTableTemplate?.(
                      duplicateTableRequest.template.template_id,
                      null,
                      {
                        allowDuplicate: true,
                        duplicateReason: "医学写作用户确认同一章节需要独立的同模板表格实例",
                      },
                    );
                    setDuplicateTableRequest(null);
                  }}
                >
                  <Plus size={15} /> 仍插入一张
                </button>
              </div>
            </footer>
          </section>
        </div>
      )}
      {customTableDialogOpen && (
        <div className="rich-table-insert-overlay" role="presentation">
          <section className="rich-table-insert-dialog" role="dialog" aria-modal="true" aria-label="插入自定义结构化表格">
            <header>
              <div>
                <span>结构化表格</span>
                <strong>插入自定义表格</strong>
              </div>
              <button type="button" onClick={() => setCustomTableDialogOpen(false)} title="关闭" aria-label="关闭自定义表格对话框"><XCircle size={17} /></button>
            </header>
            <div className="rich-table-insert-form">
              <label className="rich-table-title-field">
                <span>表题</span>
                <input
                  type="text"
                  value={customTableConfig.title}
                  maxLength={160}
                  onChange={(event) => setCustomTableConfig((current) => ({ ...current, title: event.target.value }))}
                />
              </label>
              {[
                ["总行数", "rowCount", 2, 50],
                ["列数", "columnCount", 2, 20],
                ["表头行", "headerRowCount", 0, Math.min(5, customTableConfig.rowCount - 1)],
              ].map(([label, key, min, max]) => (
                <label key={key}>
                  <span>{label}</span>
                  <input
                    type="number"
                    min={min}
                    max={max}
                    value={customTableConfig[key]}
                    onChange={(event) => {
                      const value = Math.min(max, Math.max(min, Number(event.target.value) || min));
                      setCustomTableConfig((current) => {
                        const next = { ...current, [key]: value };
                        if (key === "rowCount") next.headerRowCount = Math.min(next.headerRowCount, Math.min(5, value - 1));
                        return next;
                      });
                    }}
                  />
                </label>
              ))}
              <label>
                <span>页面方向</span>
                <select
                  value={customTableConfig.orientation}
                  onChange={(event) => setCustomTableConfig((current) => ({ ...current, orientation: event.target.value }))}
                >
                  <option value="auto">按列数自动</option>
                  <option value="portrait">纵向</option>
                  <option value="landscape">横向</option>
                </select>
              </label>
              <label className="rich-table-notes-option">
                <input
                  type="checkbox"
                  checked={customTableConfig.notesArea}
                  onChange={(event) => setCustomTableConfig((current) => ({ ...current, notesArea: event.target.checked }))}
                />
                <span>启用表下附注区</span>
              </label>
            </div>
            <footer>
              <span>插入后将直接打开统一表格设计器，可继续增删行列、合并单元格和编辑附注。</span>
              <div>
                <button type="button" onClick={() => setCustomTableDialogOpen(false)}>取消</button>
                <button
                  type="button"
                  className="primary-button"
                  disabled={tableInsertBusy || !customTableConfig.title.trim()}
                  title={tableInsertBusy
                    ? "表格正在插入或工作副本正在保存，请稍候"
                    : !customTableConfig.title.trim()
                      ? "请先填写表题"
                      : "插入结构化表格并打开全屏设计器"}
                  onClick={() => {
                    onInsertTableTemplate?.("generic_table", customTableConfig);
                    setCustomTableDialogOpen(false);
                  }}
                >
                  <Table2 size={15} /> 插入并打开设计器
                </button>
              </div>
            </footer>
          </section>
        </div>
      )}
      {activeTableBlock && (
        <section className="rich-table-sync-band" aria-label="当前表格同步内容">
          <div className="rich-table-sync-heading">
            <div>
              <span>正文同步表格</span>
              <strong>{activeTableTitle}</strong>
            </div>
            <div className="rich-table-sync-metrics">
              <span>{activeTableProfile?.label || "通用结构化表格"}</span>
              <span>{activeTableBlock.rows.length} 行 × {visibleTableColumnCount(activeTableBlock)} 列</span>
              <span>{activeTableNotes.length} 条附注</span>
              {tableHorizontalScroll.overflow && (
                <div className="rich-table-scroll-controls" aria-label="宽表横向浏览">
                  <button
                    type="button"
                    aria-label="向左浏览表格"
                    title="向左浏览表格"
                    disabled={!tableHorizontalScroll.canLeft}
                    onClick={() => scrollActiveTableHorizontally(-1)}
                  >
                    <ChevronLeft size={14} />
                  </button>
                  <button
                    type="button"
                    aria-label="向右浏览表格"
                    title="向右浏览表格"
                    disabled={!tableHorizontalScroll.canRight}
                    onClick={() => scrollActiveTableHorizontally(1)}
                  >
                    <ChevronRight size={14} />
                  </button>
                </div>
              )}
            </div>
          </div>
          {sourceCaptionDiffers && (
            <p className="rich-table-source-caption">
              <span>来源表题</span>
              <strong>{activeSourceCaption}</strong>
            </p>
          )}
          {activeTableNotes.length > 0 && (
            <div className="rich-table-sync-notes" aria-label="当前表格完整附注">
              {activeTableNotes.map((note, index) => (
                <p key={note.note_id || `${activeTableBlock.block_id}-note-${index}`}>
                  <b>{note.marker || index + 1}</b>
                  <span>{note.text}</span>
                </p>
              ))}
            </div>
          )}
        </section>
      )}
      <EditorContent
        editor={editor}
        className={activeTableBlock ? "protocol-editor has-table-sync-band" : "protocol-editor"}
      />
      {designerOpen && designerTableBlock && (
        <StructuredTableDesigner
          tableBlock={designerTableBlock}
          readOnly={readOnly || approvedLocked}
          onChange={updateDesignerTable}
          onSelectedCellChange={(cell) => {
            if (!cell) {
              onSelectedBlockContextChange?.({
                blockType: "table",
                sourceKind: activeTableBlock.source_kind || "",
                tableCell: null,
              });
              return;
            }
            const tableCell = {
              blockId: activeTableBlock.block_id,
              tableId: activeTableBlock.table_id,
              tableVersion: Number(activeTableBlock.structured_table?.version || 0),
              sourceKind: activeTableBlock.source_kind || "",
              ...cell,
            };
            onSelectedTextChange?.(cell.text);
            onSelectedAnchorChange?.("");
            onSelectedBlockContextChange?.({
              blockType: "table",
              sourceKind: activeTableBlock.source_kind || "",
              tableCell,
            });
          }}
          cellRevisionThreads={revisionThreads.filter((thread) => (
            thread?.table_cell_anchor?.block_id === activeTableBlock.block_id
          ))}
          documentIndex={documentIndex}
          domainProfiles={tableDomainProfiles}
          suggestedDomain={suggestedTableDomain}
          onClose={() => setDesignerOpen(false)}
        />
      )}
    </div>
  );
}

function MedicalWritingManifestPanel({
  manifest,
  loading,
  message,
  onRefresh,
  selectedPackageId,
  onSelectPackage,
  tflCitations,
  tflCitationLoading,
  tflCitationMessage,
  onRefreshTflCitations,
}) {
  const packages = manifest?.packages || [];
  const selectedPackage = packages.find((item) => item.package_id === selectedPackageId) || packages[0];
  const documents = selectedPackage?.documents || [];
  const sections = selectedPackage ? selectedPackage.sections.slice(0, 12) : [];
  const tables = selectedPackage ? selectedPackage.tables.slice(0, 12) : [];
  const gates = selectedPackage?.quality_gates || [];
  const citationCandidates = tflCitations?.candidates || [];
  const citationGates = tflCitations?.quality_gates || [];
  const warnings = selectedPackage?.parser_warnings?.slice(0, 5) || [];
  const blockedCount = gates.filter((gate) => ["blocked", "blocker"].includes(gate.status)).length;
  const warningCount = gates.filter((gate) => gate.status === "warning").length;
  const greenfieldPackage = documents.some((document) => document.file_format === "structured_project_decisions");

  return (
    <section className="panel tfl-manifest-panel writing-manifest-panel">
      <SectionTitle
        title="研究方案写作资料包"
        action={<button onClick={onRefresh} disabled={loading} title={loading ? "资料包正在生成" : "刷新研究方案写作资料包"}>{loading ? "生成中" : "刷新资料包"}</button>}
      />
      <div className="writing-boundary">
        {greenfieldPackage
          ? "当前展示结构化项目决策、章节骨架、未决事项和质量门；AI修订只生成待作者选择候选，不得自行补齐未决项目事实。"
          : "当前展示真实DOCX来源、章节/表格候选、来源定位和质量门；AI修订建议均为待作者选择的正式内容候选，不替代作者核对、版本冻结或正式导出检查。"}
      </div>
      <div className="writing-manifest-stats">
        <div><strong>{formatMaybeNumber(manifest?.package_count)}</strong><span>写作资料包</span></div>
        <div><strong>{formatMaybeNumber(manifest?.total_documents)}</strong><span>源文档</span></div>
        <div><strong>{formatMaybeNumber(manifest?.total_sections)}</strong><span>章节候选</span></div>
        <div><strong>{formatMaybeNumber(manifest?.total_tables)}</strong><span>表格候选</span></div>
        <div><strong>{formatMaybeNumber(manifest?.total_source_spans)}</strong><span>source spans</span></div>
        <div className={blockedCount ? "warning" : ""}><strong>{blockedCount}</strong><span>阻断质量门</span></div>
      </div>
      {message && <div className="source-registry-message">{message}</div>}
      <div className="tfl-package-tabs">
        {packages.map((item) => (
          <button
            key={item.package_id}
            className={item.package_id === selectedPackage?.package_id ? "active" : ""}
            onClick={() => onSelectPackage(item.package_id)}
          >
            {item.package_label}
          </button>
        ))}
      </div>
      {selectedPackage ? (
        <>
          <div className="tfl-package-summary writing-package-summary">
            <div><span>项目</span><strong>{selectedPackage.project_code}</strong></div>
            <div><span>适应症</span><strong>{selectedPackage.indication}</strong></div>
            <div><span>资料底座</span><strong>{selectedPackage.source_root_label}</strong></div>
            <div><span>证据覆盖</span><strong>{selectedPackage.evidence_coverage_percent}%：覆盖率不代表内容已确认</strong></div>
            <div><span>导出准备</span><strong>{selectedPackage.can_generate_review_docx ? "可生成审阅版 DOCX" : "不可生成审阅版 DOCX"} / {selectedPackage.formal_export_status}</strong></div>
          </div>
          <div className="tfl-quality-gates writing-quality-tags">
            <Tag tone="warning">待作者选择内容候选</Tag>
            <Tag tone={documents.length ? "success" : "danger"}>{documents.length ? "正文已解析" : "仅文件级登记"}</Tag>
            <Tag tone={blockedCount ? "danger" : "success"}>阻断 {blockedCount}</Tag>
            <Tag tone={warningCount ? "warning" : "success"}>待确认 {warningCount}</Tag>
            <Tag tone="neutral">独立AI边界</Tag>
          </div>
          {warnings.length ? (
            <div className="tfl-warning-list">
              {warnings.map((warning) => <span key={warning}>{warning}</span>)}
            </div>
          ) : null}
          <div className="tfl-note-list">
            <span>{selectedPackage.ai_revision_boundary}</span>
            {(manifest.parser_notes || []).slice(0, 3).map((note) => <span key={note}>{note}</span>)}
          </div>

          <div className="writing-citation-panel">
            <SectionTitle
              title="TFL写作引用候选"
              action={<button onClick={onRefreshTflCitations} disabled={tflCitationLoading} title={tflCitationLoading ? "引用候选正在读取" : "刷新TFL写作引用候选"}>{tflCitationLoading ? "读取中" : "刷新引用候选"}</button>}
            />
            <div className="writing-citation-boundary">
              来自数据分析与TFL的审阅处置记录。{tflCitations?.formal_output_boundary || "当前仅汇总TFL写作引用候选，不自动生成或改写正式医学写作正文。"}
            </div>
            {tflCitationMessage && <div className="source-registry-message">{tflCitationMessage}</div>}
            <div className="writing-citation-stats">
              <div><strong>{tflCitations?.total_candidates || 0}</strong><span>引用候选</span></div>
              <div><strong>{citationGates.filter((gate) => gate.status === "passed").length}</strong><span>通过质量门</span></div>
              <div><strong>{citationGates.filter((gate) => gate.status !== "passed").length}</strong><span>待确认质量门</span></div>
            </div>
            <div className="writing-citation-gates">
              {citationGates.map((gate) => (
                <div key={gate.gate_id}>
                  <Tag tone={safetyGateTone(gate.status)}>{gateStatusLabel(gate.status)}</Tag>
                  <strong>{gate.gate_label}</strong>
                  <span>{gate.detail}</span>
                </div>
              ))}
            </div>
            <div className="writing-citation-list">
              {citationCandidates.length ? citationCandidates.slice(0, 8).map((candidate) => (
                <article key={candidate.candidate_id}>
                  <div className="writing-citation-head">
                    <div>
                      <strong>{candidate.output_display_id}</strong>
                      <span>{tflOutputTypeLabel(candidate.output_type)} / {candidate.domain_hint || "领域待确认"} · {candidate.package_label}</span>
                    </div>
                    <Tag tone="warning">待医学确认</Tag>
                  </div>
                  <div className="writing-citation-meta">
                    <div><span>配对数据集</span><strong>{candidate.paired_dataset_name || "未配对"} {candidate.paired_dataset_row_count !== null && candidate.paired_dataset_row_count !== undefined ? `(${formatMaybeNumber(candidate.paired_dataset_row_count)}行)` : ""}</strong></div>
                    <div><span>建议章节</span><strong>{candidate.recommended_writing_sections.slice(0, 3).join(" / ")}</strong></div>
                    <div><span>审阅人</span><strong>{candidate.reviewer}</strong></div>
                  </div>
                  <p>{candidate.review_comment}</p>
                  <span className="writing-citation-boundary-line">{candidate.citation_boundary}</span>
                </article>
              )) : <div className="empty-state">暂无来自数据分析与TFL的写作引用候选。请先在TFL审阅工作台标记写作引用候选。</div>}
            </div>
          </div>

          <div className="tfl-manifest-grid writing-doc-grid">
            <div className="tfl-table-block">
              <h3>源文档</h3>
              <div className="tfl-table-scroll writing-doc-table">
                <table>
                  <thead>
                    <tr>
                      <th>文档</th>
                      <th>方案号/版本</th>
                      <th>解析</th>
                      <th>段落/表格/span</th>
                      <th>Word特征</th>
                    </tr>
                  </thead>
                  <tbody>
                    {documents.map((document, index) => (
                      <tr key={`${document.document_id}:${document.relative_path}:${index}`}>
                        <td><strong>{document.public_title}</strong><span>{document.relative_path}</span></td>
                        <td>{document.protocol_identifier}<span>{document.protocol_version} / {document.protocol_date}</span></td>
                        <td><Tag tone={document.parser_status === "正文已解析" ? "success" : "warning"}>{document.parser_status}</Tag></td>
                        <td>{document.paragraph_count} / {document.table_count} / {document.span_count}</td>
                        <td>{document.image_count} 图像；{document.has_revision_marks ? "有修订痕迹" : "无修订痕迹"}；{document.has_fields ? "有字段" : "无字段"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="tfl-table-block">
              <h3>写作质量门</h3>
              <div className="tfl-table-scroll writing-gate-table">
                <table>
                  <thead>
                    <tr>
                      <th>质量门</th>
                      <th>状态</th>
                      <th>负责角色</th>
                      <th>说明</th>
                      <th>来源</th>
                    </tr>
                  </thead>
                  <tbody>
                    {gates.map((gate) => (
                      <tr key={gate.gate_id}>
                        <td><strong>{gate.gate_label}</strong></td>
                        <td><Tag tone={safetyGateTone(gate.status)}>{gateStatusLabel(gate.status)}</Tag></td>
                        <td>{gate.owner}</td>
                        <td>{gate.detail}</td>
                        <td>{gate.source_refs.slice(0, 3).join("；") || "待补来源定位"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <div className="tfl-table-block writing-wide-block">
            <h3>方案章节候选</h3>
            <div className="tfl-table-scroll writing-section-table">
              <table>
                <thead>
                  <tr>
                    <th>章节</th>
                    <th>ICH M11锚点</th>
                    <th>状态</th>
                    <th>来源定位</th>
                    <th>段落/表格</th>
                    <th>证据覆盖</th>
                    <th>映射置信度</th>
                    <th>AI任务</th>
                  </tr>
                </thead>
                <tbody>
                  {sections.map((section) => (
                    <tr key={section.section_id}>
                      <td><strong>{section.section_number ? `${section.section_number} ${section.heading}` : section.heading}</strong><span>{section.anchor_path}</span></td>
                      <td>{section.ich_m11_area || "待人工映射"}</td>
                      <td>{section.writing_status}<span>{section.medical_approval_status}</span></td>
                      <td>{section.source_locator}</td>
                      <td>{section.paragraph_count} / {section.table_count}</td>
                      <td>{section.evidence_coverage_percent}%<span>{section.evidence_status}</span></td>
                      <td>{Math.round(section.extraction_confidence * 100)}%<span>{section.requires_human_mapping ? "需人工确认" : "已确认"}</span></td>
                      <td>{section.ai_task_ready ? "可准备AI任务" : "待确认后准备"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="tfl-table-block writing-wide-block">
            <h3>表格与来源定位</h3>
            <div className="tfl-table-scroll writing-table-inventory">
              <table>
                <thead>
                  <tr>
                    <th>表格</th>
                    <th>角色候选</th>
                    <th>行/列/非空单元</th>
                    <th>表头线索</th>
                    <th>来源定位</th>
                    <th>结构风险</th>
                    <th>解析状态</th>
                  </tr>
                </thead>
                <tbody>
                  {tables.map((table) => (
                    <tr key={table.table_id}>
                      <td><strong>Table {table.table_index}</strong><span>{table.title_hint}</span></td>
                      <td>{table.role_hint}</td>
                      <td>{table.row_count} / {table.column_count} / {table.nonempty_cell_count}</td>
                      <td>{table.headers.slice(0, 4).join("；") || "待抽取"}</td>
                      <td>{table.source_locator}</td>
                      <td>{table.quality_notes.slice(0, 2).join("；") || "无开放提示"}</td>
                      <td>{parserStatusDisplay(table.parser_status)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      ) : (
        <div className="empty-state">尚未生成研究方案写作资料包。</div>
      )}
    </section>
  );
}

function GreenfieldDecisionReviewPanel({ state, busyDecisionId, message, onResolve }) {
  const decisions = state?.decisions || [];
  const [drafts, setDrafts] = useState({});
  const [editingIds, setEditingIds] = useState(() => new Set());

  useEffect(() => {
    setDrafts(Object.fromEntries(decisions.map((item) => [item.decision_id, {
      value: item.value || "",
      rationale: item.rationale || "",
      sourceRefs: (item.source_refs || []).join("\n"),
    }])));
    setEditingIds(new Set(
      decisions.filter((item) => item.status !== "resolved").map((item) => item.decision_id),
    ));
  }, [state?.baseline_revision]);

  const unresolvedCount = decisions.filter((item) => item.status !== "resolved").length;
  const updateDraft = (decisionId, field, value) => {
    setDrafts((current) => ({
      ...current,
      [decisionId]: { ...current[decisionId], [field]: value },
    }));
  };
  const submitDecision = (item) => {
    const draft = drafts[item.decision_id] || {};
    const sourceRefs = String(draft.sourceRefs || "")
      .split(/[\n；;]/)
      .map((value) => value.trim())
      .filter(Boolean);
    if (!draft.value?.trim() || !draft.rationale?.trim() || !sourceRefs.length) return;
    onResolve(item.decision_id, {
      value: draft.value.trim(),
      rationale: draft.rationale.trim(),
      sourceRefs,
    });
  };

  return (
    <div className="greenfield-decision-review">
      <header>
        <div>
          <span>项目决策基线</span>
          <strong>版本 {state?.baseline_revision || "-"}</strong>
        </div>
        <Tag tone={unresolvedCount ? "warning" : "success"}>
          {unresolvedCount ? `${unresolvedCount} 项未决` : "已全部形成决策"}
        </Tag>
      </header>
      <p className="greenfield-decision-boundary">
        决策值、医学理由和确认记录同时写入版本化基线；未决阻断项不会由AI自行补齐。
      </p>
      <div className="greenfield-decision-review-list">
        {decisions.map((item, index) => {
          const editing = editingIds.has(item.decision_id);
          const draft = drafts[item.decision_id] || {};
          const canSubmit = Boolean(
            draft.value?.trim()
            && draft.rationale?.trim()
            && String(draft.sourceRefs || "").split(/[\n；;]/).some((value) => value.trim()),
          );
          const busy = busyDecisionId === item.decision_id;
          return (
            <section key={item.decision_id} className={item.status === "resolved" ? "resolved" : "unresolved"}>
              <div className="greenfield-decision-review-head">
                <span>{String(index + 1).padStart(2, "0")}</span>
                <strong>{item.label}</strong>
                <Tag tone={item.status === "resolved" ? "success" : "warning"}>
                  {item.status === "resolved" ? "已形成决策" : "阻断批准"}
                </Tag>
              </div>
              {editing ? (
                <div className="greenfield-decision-review-form">
                  <label>
                    <span>确认的项目决策</span>
                    <textarea value={draft.value || ""} onChange={(event) => updateDraft(item.decision_id, "value", event.target.value)} placeholder="填写已确认的剂量、终点、样本量或其他项目决策" />
                  </label>
                  <label>
                    <span>医学/统计理由</span>
                    <textarea value={draft.rationale || ""} onChange={(event) => updateDraft(item.decision_id, "rationale", event.target.value)} placeholder="说明形成该决策的依据及适用边界" />
                  </label>
                  <label>
                    <span>来源或确认记录</span>
                    <textarea value={draft.sourceRefs || ""} onChange={(event) => updateDraft(item.decision_id, "sourceRefs", event.target.value)} placeholder="每行一条，如：项目决策会纪要 2026-07-14；统计确认邮件 v1" />
                  </label>
                  <div className="greenfield-decision-review-actions">
                    {item.status === "resolved" && (
                      <button type="button" onClick={() => setEditingIds((current) => {
                        const next = new Set(current);
                        next.delete(item.decision_id);
                        return next;
                      })} disabled={busy}>取消</button>
                    )}
                    <button className="primary-button" type="button" onClick={() => submitDecision(item)} disabled={!canSubmit || Boolean(busyDecisionId)}>
                      {busy ? "保存中" : item.status === "resolved" ? "更新决策" : "确认并解除阻断"}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="greenfield-decision-review-summary">
                  <p><span>决策</span>{item.value}</p>
                  <p><span>理由</span>{item.rationale}</p>
                  <p><span>记录</span>{(item.source_refs || []).join("；")}</p>
                  <button type="button" onClick={() => setEditingIds((current) => new Set([...current, item.decision_id]))}>更新决策</button>
                </div>
              )}
            </section>
          );
        })}
      </div>
      {!decisions.length && <div className="empty-state">当前文档未登记阻断性项目决策。</div>}
      {message && <p className={`greenfield-decision-message ${message.startsWith("保存失败") ? "danger" : ""}`}>{message}</p>}
    </div>
  );
}

function medicalWritingStructuredTarget(section) {
  const interactions = new Set(section?.interactionTypes || []);
  const sectionNumber = section?.sectionNumber || "";
  const startsWith = (prefix) => sectionNumber === prefix || sectionNumber.startsWith(`${prefix}.`);
  if (interactions.has("dose_modification_rule_builder") || startsWith("6.4")) {
    return { stage: "picos", group: "intervention", panel: "ip_actions", label: "试验用药品调整与处置", buttonLabel: "试验用药品调整与处置" };
  }
  if (interactions.has("non_investigational_intervention_builder") || startsWith("6.9")) {
    return { stage: "picos", group: "intervention", panel: "non_ip", label: "非试验用药与补救治疗", buttonLabel: "非试验用药与补救治疗" };
  }
  if (interactions.has("concomitant_therapy_rule_builder") || startsWith("6.10")) {
    return { stage: "picos", group: "intervention", panel: "cm", label: "合并用药规则", buttonLabel: "合并用药规则" };
  }
  if (interactions.has("eligibility_rule_builder")) {
    return { stage: "picos", group: "population", label: "入排与洗脱规则", buttonLabel: "结构化入排" };
  }
  if (["assessment_instrument_builder", "aesi_rule_builder"].some((item) => interactions.has(item))) {
    return { stage: "picos", group: "outcomes", label: "结局、安全性与量表", buttonLabel: "终点与量表" };
  }
  if (interactions.has("schedule_of_activities_editor")) {
    return { kind: "table", templateId: "schedule_of_activities", label: "研究流程表", buttonLabel: "研究流程表" };
  }
  if (["analysis_set_builder", "sample_size_builder"].some((item) => interactions.has(item))) {
    return { stage: "picos", group: "execution", label: "研究执行与统计设计", buttonLabel: "执行与统计" };
  }
  if (interactions.has("objective_estimand_builder")) {
    return { stage: "picos", group: section?.sectionNumber?.startsWith("3.") ? "outcomes" : "execution", label: "研究目的、终点与估计目标", buttonLabel: "目的与终点" };
  }
  if (interactions.has("front_matter_editor")) {
    return { kind: "document_object", role: "layout", label: "方案首页排版对象", buttonLabel: "方案首页" };
  }
  if (interactions.has("synopsis_editor")) {
    return { kind: "document_object", role: "protocol_synopsis", label: "方案摘要结构化对象", buttonLabel: "方案摘要" };
  }
  return null;
}

function useSoaModalFocusA11y(open, containerRef, onClose) {
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  useEffect(() => {
    if (!open) return undefined;
    const restoreFocus = document.activeElement;
    const container = containerRef.current;
    const focusableSelector = "button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])";
    const focusables = () => Array.from(container?.querySelectorAll?.(focusableSelector) || [])
      .filter((element) => !element.disabled);
    globalThis.requestAnimationFrame?.(() => container?.focus?.());
    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onCloseRef.current?.();
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusables();
      if (!items.length) {
        event.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !items.includes(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !items.includes(active))) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown, true);
    return () => {
      document.removeEventListener("keydown", handleKeyDown, true);
      restoreFocus?.focus?.();
    };
  }, [open, containerRef]);
}

function WritingPage({
  projectId,
  projectHeader,
  projectSourceMode,
  aiGatewayStatus,
  refreshDashboard,
  onNavigationGuardChange,
}) {
  const [selectedSection, setSelectedSection] = useState("");
  const [documentSession, setDocumentSession] = useState(null);
  const [documentSessionLoading, setDocumentSessionLoading] = useState(false);
  const [documentSessionMessage, setDocumentSessionMessage] = useState("");
  const [greenfieldState, setGreenfieldState] = useState(null);
  const [greenfieldDecisionBusy, setGreenfieldDecisionBusy] = useState("");
  const [greenfieldDecisionMessage, setGreenfieldDecisionMessage] = useState("");
  const [sectionContent, setSectionContent] = useState(null);
  const [writingManifest, setWritingManifest] = useState(null);
  const [manifestLoading, setManifestLoading] = useState(false);
  const [manifestMessage, setManifestMessage] = useState("");
  const [selectedPackageId, setSelectedPackageId] = useState("");
  const [tflCitations, setTflCitations] = useState(null);
  const [tflCitationLoading, setTflCitationLoading] = useState(false);
  const [tflCitationMessage, setTflCitationMessage] = useState("");
  const [workingCopy, setWorkingCopy] = useState(null);
  const [workingCopyDraftBlocks, setWorkingCopyDraftBlocks] = useState([]);
  const [workingCopyLoading, setWorkingCopyLoading] = useState(false);
  const [workingCopyActionBusy, setWorkingCopyActionBusy] = useState(false);
  const [workingCopyMessage, setWorkingCopyMessage] = useState("");
  const [workingCopyEditing, setWorkingCopyEditing] = useState(false);
  const [workingCopyDirty, setWorkingCopyDirty] = useState(false);
  const [workingCopySaveKey, setWorkingCopySaveKey] = useState("");
  const [workingCopyReloadNonce, setWorkingCopyReloadNonce] = useState(0);
  const [workingCopyHydrationEpoch, setWorkingCopyHydrationEpoch] = useState(0);
  const [workingCopyLoadError, setWorkingCopyLoadError] = useState("");
  const [loadedEditorIdentity, setLoadedEditorIdentity] = useState("");
  const [recoveryDraftPrompt, setRecoveryDraftPrompt] = useState(null);
  const [currentRecoveryDraft, setCurrentRecoveryDraft] = useState(null);
  const [pendingEditorNavigation, setPendingEditorNavigation] = useState(null);
  const [contentQuality, setContentQuality] = useState(null);
  const [contentQualityLoading, setContentQualityLoading] = useState(false);
  const [contentQualityMessage, setContentQualityMessage] = useState("");
  const [contentQualityDockOpen, setContentQualityDockOpen] = useState(false);
  const [selectedContentFindingId, setSelectedContentFindingId] = useState("");
  const [contentDispositionReason, setContentDispositionReason] = useState("");
  const [contentDispositionAcknowledged, setContentDispositionAcknowledged] = useState(false);
  const [contentDispositionBusy, setContentDispositionBusy] = useState(false);
  const [tableTemplates, setTableTemplates] = useState([]);
  const [tableDomainProfiles, setTableDomainProfiles] = useState([]);
  const [tableTemplateLoading, setTableTemplateLoading] = useState(false);
  const [insertedTableBlockId, setInsertedTableBlockId] = useState("");
  const [soaCandidatePicker, setSoaCandidatePicker] = useState(null);
  const [documentObjectPicker, setDocumentObjectPicker] = useState(null);
  const [soaCreateConfirmOpen, setSoaCreateConfirmOpen] = useState(false);
  const [documentExportBusy, setDocumentExportBusy] = useState("");
  const [documentExportProgress, setDocumentExportProgress] = useState(null);
  const [fullDraftJob, setFullDraftJob] = useState(null);
  const [fullDraftArtifact, setFullDraftArtifact] = useState(null);
  const [fullDraftBusy, setFullDraftBusy] = useState(false);
  const [fullDraftMessage, setFullDraftMessage] = useState("");
  const documentExportRunRef = useRef(0);
  const fullDraftRunRef = useRef(0);
  const [documentPreview, setDocumentPreview] = useState(null);
  const [documentPreviewBusy, setDocumentPreviewBusy] = useState(false);
  const [documentPreviewMessage, setDocumentPreviewMessage] = useState("");
  const documentPreviewRequestRef = useRef(0);
  const [editorStructureError, setEditorStructureError] = useState("");
  const [revisionThreads, setRevisionThreads] = useState([]);
  const [revisionLoading, setRevisionLoading] = useState(false);
  const [revisionMessage, setRevisionMessage] = useState("");
  const [revisionJobs, setRevisionJobs] = useState(() => emptyRevisionJobMap());
  const revisionJobState = pickFocusedRevisionJob(revisionJobs);
  const revisionJobProgress = revisionJobState?.progress || null;
  const revisionJobPercent = Math.max(
    0,
    Math.min(100, Math.round(Number(revisionJobProgress?.percent || 0) * 100)),
  );
  const revisionScreenGenRef = useRef(createScreenGeneration("", ""));
  const [revisionInstruction, setRevisionInstruction] = useState(revisionIntentOptions[0].defaultInstruction);
  const [revisionIntent, setRevisionIntent] = useState(revisionIntentOptions[0].value);
  const [selectedEditorText, setSelectedEditorText] = useState("");
  const [selectedEditorAnchor, setSelectedEditorAnchor] = useState("");
  const [selectedEditorBlockContext, setSelectedEditorBlockContext] = useState({
    blockType: "",
    sourceKind: "",
    tableCell: null,
  });
  const [editorPlainText, setEditorPlainText] = useState("");
  const [activeRevisionThreadId, setActiveRevisionThreadId] = useState("");
  const [selectedRevisionSuggestionId, setSelectedRevisionSuggestionId] = useState("");
  const [revisionActionComment, setRevisionActionComment] = useState("");
  const [revisionRewriteInstruction, setRevisionRewriteInstruction] = useState("");
  const [activeWritingRailTab, setActiveWritingRailTab] = useState("AI");
  const [selectedReferenceBriefIds, setSelectedReferenceBriefIds] = useState([]);
  const [documentMapOpen, setDocumentMapOpen] = useState(false);
  const [documentMapSearch, setDocumentMapSearch] = useState("");
  const [authoringJourneyAvailable, setAuthoringJourneyAvailable] = useState(false);
  const [authoringJourneySnapshot, setAuthoringJourneySnapshot] = useState(null);
  const [studyDesignOpen, setStudyDesignOpen] = useState(false);
  const [studyDesignTarget, setStudyDesignTarget] = useState({ stage: "", group: "", panel: "", label: "", requestId: 0 });
  const [protocolTemplate, setProtocolTemplate] = useState(null);
  const [moduleResolutionBusy, setModuleResolutionBusy] = useState("");
  const [moduleResolutionMessage, setModuleResolutionMessage] = useState("");
  const [moduleResolutionResult, setModuleResolutionResult] = useState(null);
  const [citationInsertion, setCitationInsertion] = useState(null);
  const [citationInsertionMessage, setCitationInsertionMessage] = useState("");
  const [documentIndex, setDocumentIndex] = useState(null);
  const [templateUpgradePreview, setTemplateUpgradePreview] = useState(null);
  const [templateUpgradeOpen, setTemplateUpgradeOpen] = useState(false);
  const [templateUpgradeLoading, setTemplateUpgradeLoading] = useState(false);
  const [templateUpgradeBusy, setTemplateUpgradeBusy] = useState(false);
  const [templateUpgradeMessage, setTemplateUpgradeMessage] = useState("");
  const [templateUpgradeConsolidationAccepted, setTemplateUpgradeConsolidationAccepted] = useState(false);
  const [templateUpgradeApprovalResetAccepted, setTemplateUpgradeApprovalResetAccepted] = useState(false);
  const [templateUpgradeAppliedResult, setTemplateUpgradeAppliedResult] = useState(null);
  const [studyConsistency, setStudyConsistency] = useState(null);
  const [studyRebindPreview, setStudyRebindPreview] = useState(null);
  const [studyRebindOpen, setStudyRebindOpen] = useState(false);
  const [studyRebindBusy, setStudyRebindBusy] = useState(false);
  const [studyRebindMessage, setStudyRebindMessage] = useState("");
  const [studyRebindReason, setStudyRebindReason] = useState("");
  const [studyRebindContentAccepted, setStudyRebindContentAccepted] = useState(false);
  const [studyRebindApprovalAccepted, setStudyRebindApprovalAccepted] = useState(false);
  const [studyReconciliationReason, setStudyReconciliationReason] = useState("");
  const [studyReconciliationAccepted, setStudyReconciliationAccepted] = useState(false);
  const [interventionProjectionBusy, setInterventionProjectionBusy] = useState(false);
  const [interventionProjectionConflict, setInterventionProjectionConflict] = useState(null);
  const [freezeReadiness, setFreezeReadiness] = useState(null);
  const [freezeReadinessError, setFreezeReadinessError] = useState("");
  const [freezeHistory, setFreezeHistory] = useState([]);
  const [quarantinedWorkingCopy, setQuarantinedWorkingCopy] = useState(null);
  const [versionHistoryLoading, setVersionHistoryLoading] = useState(false);
  const [versionHistoryMessage, setVersionHistoryMessage] = useState("");
  const [bindingRecoveryReason, setBindingRecoveryReason] = useState("");
  const [bindingRecoveryAcknowledged, setBindingRecoveryAcknowledged] = useState(false);
  const workingCopyRequestRef = useRef(0);
  const documentSessionRequestRef = useRef(0);
  const workingCopyDraftBlocksRef = useRef(workingCopyDraftBlocks);
  const workingCopyDirtyRef = useRef(workingCopyDirty);
  workingCopyDraftBlocksRef.current = workingCopyDraftBlocks;
  workingCopyDirtyRef.current = workingCopyDirty;
  const activePackage = (writingManifest?.packages || []).find((item) => item.package_id === selectedPackageId) || writingManifest?.packages?.[0];
  const isDemoWritingSession = projectId === "proj_mgk10_sar_demo";
  const editorSessionAvailable = isDemoWritingSession || documentSession?.project_id === projectId;
  const greenfieldSetupAvailable = !isDemoWritingSession
    && !documentSessionLoading
    && !editorSessionAvailable
    && !documentSessionMessage;
  const isGreenfieldSession = ["greenfield_candidate", "template_upgrade_candidate"].includes(documentSession?.status)
    || greenfieldState?.source_mode === "greenfield_project_decision";
  const isLegacyGreenfieldTemplate = isGreenfieldSession
    && !documentSession?.template_id
    && documentSession?.template_version === "greenfield_protocol_v0_1";
  const protocolModuleResolutions = greenfieldState?.module_resolutions
    || documentSession?.module_resolutions
    || [];
  useEffect(() => {
    let cancelled = false;
    setAuthoringJourneyAvailable(false);
    setAuthoringJourneySnapshot(null);
    setStudyDesignOpen(false);
    setStudyDesignTarget({ stage: "", group: "", panel: "", label: "", requestId: 0 });
    setInterventionProjectionConflict(null);
    if (isDemoWritingSession) return () => { cancelled = true; };
    fetch(`/api/projects/${projectId}/medical-writing/authoring-journey?allow_missing=true`)
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status));
        return response.json();
      })
      .then((payload) => {
        if (cancelled) return;
        if (payload.available === false) {
          setAuthoringJourneySnapshot(null);
          setAuthoringJourneyAvailable(false);
          return;
        }
        setAuthoringJourneySnapshot(payload);
        setAuthoringJourneyAvailable(true);
      })
      .catch(() => {
        if (cancelled) return;
        setAuthoringJourneySnapshot(null);
        setAuthoringJourneyAvailable(false);
      });
    return () => { cancelled = true; };
  }, [projectId, isDemoWritingSession]);
  useEffect(() => {
    if (!documentSession?.template_id || !documentSession?.template_version) {
      setProtocolTemplate(null);
      return undefined;
    }
    const controller = new AbortController();
    fetch(
      `/api/medical-writing/protocol-templates/${encodeURIComponent(documentSession.template_id)}/${encodeURIComponent(documentSession.template_version)}`,
      { signal: controller.signal },
    )
      .then(readJsonOrThrow)
      .then((payload) => {
        if (!controller.signal.aborted) setProtocolTemplate(payload);
      })
      .catch((error) => {
        if (error?.name !== "AbortError" && !controller.signal.aborted) setProtocolTemplate(null);
      });
    return () => controller.abort();
  }, [documentSession?.template_id, documentSession?.template_version]);
  const documentSectionDepths = useMemo(() => {
    const sourceSections = documentSession?.sections || [];
    const sectionById = new Map(sourceSections.map((item) => [item.section_id, item]));
    const depthById = new Map();
    const resolveDepth = (item, ancestry = new Set()) => {
      if (!item || !item.parent_id || !sectionById.has(item.parent_id)) return 0;
      if (depthById.has(item.section_id)) return depthById.get(item.section_id);
      if (ancestry.has(item.section_id)) return 0;
      const nextAncestry = new Set(ancestry);
      nextAncestry.add(item.section_id);
      const depth = Math.min(resolveDepth(sectionById.get(item.parent_id), nextAncestry) + 1, 4);
      depthById.set(item.section_id, depth);
      return depth;
    };
    sourceSections.forEach((item) => depthById.set(item.section_id, resolveDepth(item)));
    return depthById;
  }, [documentSession?.document_id, documentSession?.template_version, documentSession?.sections]);
  const documentSections = isDemoWritingSession
    ? writingSections
    : (documentSession?.sections || []).map((item) => {
      const freezeGap = (freezeReadiness?.gaps || []).find(
        (gap) => gap.section_id === item.section_id,
      );
      const omitted = item.applicability_status === "not_applicable"
        && item.applicability_render_action === "omit";
      const status = omitted
        ? "不适用"
        : !freezeReadiness
          ? "状态读取中"
          : !freezeGap
            ? "已冻结"
            : freezeGap.reason_code === "freeze_invalidated"
              ? "待重新确认"
              : freezeGap.reason_code === "working_copy_quarantined"
                ? "历史版本已隔离"
                : freezeGap.reason_code === "working_copy_not_saved"
                  ? "尚未保存"
                  : freezeGap.reason_code === "applicability_unresolved"
                    ? "适用性待确认"
                    : ["freeze_snapshot_missing", "freeze_snapshot_inconsistent"].includes(freezeGap.reason_code)
                      ? "冻结异常"
                      : "编辑中";
      return {
        id: item.section_id,
        title: item.heading,
        parentId: item.parent_id,
        depth: documentSectionDepths.get(item.section_id) || 0,
        status,
        coverage: null,
        revisions: revisionThreads.filter((thread) => thread.section_id === item.section_id).length,
        templateNodeId: item.template_node_id || "",
        sectionNumber: item.section_number || "",
        nodeKind: item.node_kind || "section",
        applicabilityMode: item.applicability_mode || "required",
        applicabilityStatus: item.applicability_status || "unknown",
        applicabilityRenderAction: item.applicability_render_action || "include",
        repeatable: Boolean(item.repeatable),
        titleLocked: Boolean(item.title_locked),
        interactionTypes: item.interaction_types || ["rich_text"],
        draftingStatus: item.drafting_status || "unclassified",
        draftingBlockerCode: item.drafting_blocker_code || "",
        draftingBlockerReason: item.drafting_blocker_reason || "",
        draftingMissingInputs: item.drafting_missing_inputs || [],
        draftingResolutionActions: item.drafting_resolution_actions || [],
      };
    });
  const section = documentSections.find((item) => item.id === selectedSection) || documentSections[0] || {
    id: "unavailable",
    title: "尚未建立可编辑章节",
    status: "待建立",
    coverage: 0,
    revisions: 0,
  };
  const isStudySchemaSection = section.nodeKind === "study_schema"
    || section.interactionTypes?.includes("study_schema_editor");
  const structuredDesignTarget = medicalWritingStructuredTarget(section);
  const structuredDesignTriggerAvailable = Boolean(structuredDesignTarget)
    && !isStudySchemaSection
    && (["table", "document_object"].includes(structuredDesignTarget.kind) || authoringJourneyAvailable);
  const openStudyDesign = (target = null) => {
    setStudyDesignTarget((current) => ({
      stage: target?.stage || "",
      group: target?.group || "",
      panel: target?.panel || "",
      label: target?.label || "",
      requestId: current.requestId + 1,
    }));
    setStudyDesignOpen(true);
  };
  const selectedSectionNeedsReconciliation = studyConsistency?.status === "reconciliation_required"
    && (studyConsistency.affected_sections || []).some((item) => item.section_id === selectedSection);
  const studyConsistencyBlocksFinal = Boolean(studyConsistency?.blocks_approved_export);
  const selectedSectionConsistencyBlocked = Boolean(studyConsistency?.blocks_new_approval)
    && (!(studyConsistency?.affected_sections || []).length
      || (studyConsistency?.affected_sections || []).some((item) => item.section_id === selectedSection));
  const visibleDocumentSections = documentMapSearch.trim()
    ? documentSections.filter((item) => item.title.toLowerCase().includes(documentMapSearch.trim().toLowerCase()))
    : documentSections;
  const backendSectionId = isDemoWritingSession ? writingBackendSectionId(selectedSection) : selectedSection;
  const sectionHasBackendBinding = Boolean(backendSectionId);
  const expectedEditorIdentity = [projectId, documentSession?.document_id || "", selectedSection].join(":");
  const sectionContentAvailable = isDemoWritingSession || Boolean(
    loadedEditorIdentity === expectedEditorIdentity
    && Array.isArray(sectionContent?.content_blocks),
  );
  const structuredInterventionRules = authoringJourneySnapshot?.picos?.intervention_rules;
  const interventionRulePanelHasContent = (() => {
    if (structuredInterventionRules?.authority !== "structured") return false;
    const rules = structuredInterventionRules.non_ip_treatment_rules || [];
    if (structuredDesignTarget?.panel === "ip_actions") {
      return structuredInterventionRules.ip_adjustment_policy === "no_planned_adjustment"
        || Boolean(structuredInterventionRules.ip_action_rules?.length);
    }
    if (structuredDesignTarget?.panel === "non_ip") {
      return rules.some((item) => ["background", "rescue", "other_non_investigational"].includes(item.rule_class));
    }
    if (structuredDesignTarget?.panel === "cm") {
      return rules.some((item) => ["allowed_cm", "prohibited_cm"].includes(item.rule_class));
    }
    return false;
  })();
  const interventionProjectionAvailable = Boolean(
    authoringJourneyAvailable
    && ["ip_actions", "non_ip", "cm"].includes(structuredDesignTarget?.panel)
    && interventionRulePanelHasContent
    && editorSessionAvailable
    && sectionContentAvailable
  );
  const workingCopyRevision = workingCopy?.revision ?? 0;
  const recoveryIdentity = {
    projectId,
    documentId: documentSession?.document_id || "",
    sectionId: selectedSection,
    baseRevision: workingCopyRevision,
  };
  const recoveryDraftPromptRef = useRef(recoveryDraftPrompt);
  const currentRecoveryDraftRef = useRef(currentRecoveryDraft);
  recoveryDraftPromptRef.current = recoveryDraftPrompt;
  currentRecoveryDraftRef.current = currentRecoveryDraft;
  const persistCurrentRecoveryDraft = useCallback(() => {
    if (!workingCopyDirtyRef.current) return null;
    try {
      const draft = persistMedicalWritingRecoveryDraft(
        globalThis.sessionStorage,
        {
          projectId,
          documentId: documentSession?.document_id || "",
          sectionId: selectedSection,
          baseRevision: workingCopyRevision,
        },
        workingCopyDraftBlocksRef.current,
      );
      if (draft) {
        currentRecoveryDraftRef.current = draft;
        setCurrentRecoveryDraft(draft);
      }
      return draft;
    } catch {
      return null;
    }
  }, [projectId, documentSession?.document_id, selectedSection, workingCopyRevision]);
  const clearCurrentRecoveryDraft = useCallback(() => {
    try {
      clearMedicalWritingRecoveryDrafts(globalThis.sessionStorage, {
        projectId,
        documentId: documentSession?.document_id || "",
        sectionId: selectedSection,
      });
    } catch {
      // Session storage can be unavailable in hardened browser modes.
    }
    recoveryDraftPromptRef.current = null;
    currentRecoveryDraftRef.current = null;
    setRecoveryDraftPrompt(null);
    setCurrentRecoveryDraft(null);
  }, [projectId, documentSession?.document_id, selectedSection]);
  const restoreLatestRecoveryDraft = useCallback(() => {
    const draft = recoveryDraftPromptRef.current || currentRecoveryDraftRef.current;
    if (!draft?.contentBlocks) return false;
    setWorkingCopyDraftBlocks(cloneContentBlocks(draft.contentBlocks));
    setWorkingCopyEditing(true);
    setWorkingCopyDirty(true);
    setWorkingCopySaveKey(`wc-${projectId}-${selectedSection}-${Date.now()}`);
    setRecoveryDraftPrompt(null);
    setCurrentRecoveryDraft(draft);
    setWorkingCopyMessage(
      draft.recoveryState === "conflict"
        ? `已恢复基于版本 ${draft.baseRevision} 的会话稿；当前服务器为版本 ${workingCopyRevision}，请人工核对冲突后保存。`
        : `已恢复 ${new Date(draft.updatedAt).toLocaleString("zh-CN", { hour12: false })} 的会话稿，请核对后保存。`,
    );
    return true;
  }, [projectId, selectedSection, workingCopyRevision]);
  const discardUnsavedWorkingCopy = useCallback(() => {
    clearCurrentRecoveryDraft();
    setWorkingCopyDirty(false);
    setEditorStructureError("");
  }, [clearCurrentRecoveryDraft]);
  const requestEditorNavigation = useCallback((request) => {
    if (!request?.run) return;
    if (!workingCopyDirtyRef.current) {
      request.run();
      return;
    }
    persistCurrentRecoveryDraft();
    setPendingEditorNavigation(request);
  }, [persistCurrentRecoveryDraft]);
  const requestSectionChange = useCallback((nextSectionId, afterChange) => {
    if (!nextSectionId || nextSectionId === selectedSection) {
      afterChange?.();
      return;
    }
    requestEditorNavigation({
      kind: "section",
      label: `切换至“${documentSections.find((item) => item.id === nextSectionId)?.title || nextSectionId}”`,
      run: () => {
        setSectionContent(null);
        setLoadedEditorIdentity("");
        setSelectedSection(nextSectionId);
        afterChange?.();
      },
    });
  }, [selectedSection, documentSections, requestEditorNavigation]);
  const requestWorkingCopyReload = useCallback(() => {
    requestEditorNavigation({
      kind: "reload",
      label: "重新加载服务器版本",
      run: () => setWorkingCopyReloadNonce((value) => value + 1),
    });
  }, [requestEditorNavigation]);
  useEffect(() => {
    if (!workingCopyDirty || !recoveryIdentity.documentId || !recoveryIdentity.sectionId) return undefined;
    const timer = globalThis.setTimeout?.(() => persistCurrentRecoveryDraft(), 450);
    return () => globalThis.clearTimeout?.(timer);
  }, [
    workingCopyDirty,
    workingCopyDraftBlocks,
    recoveryIdentity.documentId,
    recoveryIdentity.sectionId,
    recoveryIdentity.baseRevision,
    persistCurrentRecoveryDraft,
  ]);
  useEffect(() => {
    if (!workingCopyDirty) return undefined;
    const handleBeforeUnload = (event) => {
      persistCurrentRecoveryDraft();
      event.preventDefault();
      event.returnValue = "";
    };
    globalThis.addEventListener?.("beforeunload", handleBeforeUnload);
    return () => globalThis.removeEventListener?.("beforeunload", handleBeforeUnload);
  }, [workingCopyDirty, persistCurrentRecoveryDraft]);
  useEffect(() => {
    if (!onNavigationGuardChange) return undefined;
    if (!workingCopyDirty) {
      onNavigationGuardChange(null);
      return undefined;
    }
    onNavigationGuardChange({
      dirty: true,
      sectionTitle: section.title,
      hasRecoveryDraft: Boolean(currentRecoveryDraftRef.current || recoveryDraftPromptRef.current),
      persistDraft: persistCurrentRecoveryDraft,
      restoreDraft: restoreLatestRecoveryDraft,
      discardDraft: discardUnsavedWorkingCopy,
    });
    return () => onNavigationGuardChange(null);
  }, [
    onNavigationGuardChange,
    workingCopyDirty,
    section.title,
    Boolean(currentRecoveryDraft),
    persistCurrentRecoveryDraft,
    restoreLatestRecoveryDraft,
    discardUnsavedWorkingCopy,
  ]);
  const editorFrozen = workingCopy?.freeze_status === "frozen";
  const workingCopyAuthoritative = workingCopy?.content_authority_state === "active_authoritative";
  const realWorkingCopyEditable = !isDemoWritingSession
    && (workingCopyRevision >= 1 || workingCopyEditing)
    && workingCopyAuthoritative
    && !editorFrozen;
  const workingCopyDisplayBlocks = realWorkingCopyEditable || workingCopyRevision >= 1
    ? workingCopyDraftBlocks
    : sectionContent?.content_blocks || [];
  const sectionHasReviewableBody = workingCopyDisplayBlocks.some((block) => (
    block.block_type !== "heading"
    && !String(block.style_id || "").startsWith("greenfield_heading")
    && Boolean(contentBlockText(block))
  ));
  const showDraftingReadiness = (
    section.draftingStatus === "actionable_blocker"
    && !sectionHasReviewableBody
  );
  const isSoaSection = Boolean(section.interactionTypes?.includes("schedule_of_activities_editor"));
  const sectionSoaTableCandidates = isSoaSection
    ? workingCopyDisplayBlocks
      .filter((block) => block.block_type === "table" && Array.isArray(block.rows))
      .map((block) => ({
        blockId: String(block.block_id || ""),
        title: block.structured_table?.title || block.title || "",
        structured: block.template_id === "schedule_of_activities"
          || block.structured_table?.domain === "schedule_of_activities",
      }))
    : [];
  const sectionDocumentObjectCandidates = structuredDesignTarget?.kind === "document_object"
    ? workingCopyDisplayBlocks
      .filter((block) => (
        block.block_type === "table"
        && Array.isArray(block.rows)
        && block.structured_table?.role === structuredDesignTarget.role
      ))
      .map((block, index) => ({
        blockId: String(block.block_id || ""),
        title: block.structured_table?.title || block.title || `${structuredDesignTarget.label} ${index + 1}`,
        role: block.structured_table?.role || "unclassified",
        rows: block.rows.length,
        columns: Number(block.column_count || 0),
      }))
    : [];
  const soaCreateGateReason = isDemoWritingSession
    ? "演示项目会话不支持创建研究流程表"
    : workingCopyRevision < 1
      ? "请先创建并保存工作副本"
      : workingCopyDirty
        ? "存在未保存修订，请先保存工作副本"
        : !workingCopyAuthoritative
          ? "当前历史工作版本已隔离，请先在版本面板确认绑定或恢复权威基线"
          : editorFrozen
            ? "当前作者确认版本已冻结，请先解除冻结再编辑"
          : workingCopyActionBusy
            ? "正在处理工作副本操作，请稍候"
            : selectedSectionConsistencyBlocked
              ? (studyConsistency?.message || "当前章节尚未完成研究设计一致性闭环")
              : "";
  const openSectionSoaEntry = () => {
    if (sectionSoaTableCandidates.length === 1) {
      const [onlyCandidate] = sectionSoaTableCandidates;
      setInsertedTableBlockId(onlyCandidate.blockId);
      return;
    }
    if (sectionSoaTableCandidates.length > 1) {
      setSoaCandidatePicker(sectionSoaTableCandidates);
      return;
    }
    setSoaCreateConfirmOpen(true);
  };
  const openSectionDocumentObjectEntry = () => {
    if (sectionDocumentObjectCandidates.length === 1) {
      setInsertedTableBlockId(sectionDocumentObjectCandidates[0].blockId);
      return;
    }
    if (sectionDocumentObjectCandidates.length > 1) {
      setDocumentObjectPicker({
        label: structuredDesignTarget.label,
        role: structuredDesignTarget.role,
        candidates: sectionDocumentObjectCandidates,
      });
      return;
    }
    setWorkingCopyMessage(`当前“${section.title}”未找到${structuredDesignTarget.label}；正文保持不变。`);
  };
  const soaCandidateDialogRef = useRef(null);
  const soaCreateDialogRef = useRef(null);
  const documentObjectDialogRef = useRef(null);
  useSoaModalFocusA11y(Boolean(soaCandidatePicker), soaCandidateDialogRef, () => setSoaCandidatePicker(null));
  useSoaModalFocusA11y(soaCreateConfirmOpen, soaCreateDialogRef, () => setSoaCreateConfirmOpen(false));
  useSoaModalFocusA11y(Boolean(documentObjectPicker), documentObjectDialogRef, () => setDocumentObjectPicker(null));
  const allRequiredSectionsFrozen = !isDemoWritingSession && freezeReadiness?.ready === true;
  const remainingFreezeSectionCount = freezeReadiness
    ? Math.max(
      0,
      Number(freezeReadiness.required_section_count || 0)
        - Number(freezeReadiness.current_frozen_section_count || 0),
    )
    : null;
  const aiRevisionUnavailableReason = !aiGatewayStatus?.configured
    ? "独立AI尚未配置。"
    : editorFrozen
      ? "当前作者确认版本已冻结，请先解除冻结。"
      : !workingCopyAuthoritative
        ? "当前历史工作版本已隔离，请先完成版本恢复。"
        : !sectionHasBackendBinding
          ? "当前章节尚未建立后端章节映射。"
          : !editorSessionAvailable
            ? (documentSessionMessage || "真实方案文档会话尚未就绪。")
            : !sectionContentAvailable
              ? (documentSessionMessage || "当前章节正文尚未完成段落级加载，加载完成后可使用AI修订。")
              : selectedEditorBlockContext.blockType === "table"
                && (!selectedEditorBlockContext.tableCell || workingCopyDirty)
                ? (!selectedEditorBlockContext.tableCell
                  ? "请先在全屏表格设计器中选择一个单元格。"
                  : "请先保存当前表格修订。")
                : "";
  const aiRevisionDisabled = Boolean(aiRevisionUnavailableReason);
  const paragraphLoadPending = !isStudySchemaSection
    && sectionHasBackendBinding
    && editorSessionAvailable
    && !sectionContentAvailable;
  const contentFindings = contentQuality?.findings || [];
  const selectedContentFinding = contentFindings.find(
    (item) => item.finding_id === selectedContentFindingId,
  ) || contentFindings[0] || null;
  const contentQualityBlockingCount = contentQuality?.approval_blocking_count || 0;
  const contentQualityConfirmedCount = contentQuality?.confirmed_count || 0;
  const refreshWritingManifest = () => {
    setManifestLoading(true);
    setManifestMessage("");
    fetch(`/api/projects/${projectId}/medical-writing/manifest?allow_missing=true`)
      .then((response) => (response.ok ? response.json() : Promise.reject(response)))
      .then((payload) => {
        if (payload.available === false) {
          setWritingManifest(null);
          setSelectedPackageId("");
          return;
        }
        setWritingManifest(payload);
        const packageIds = (payload.packages || []).map((item) => item.package_id);
        if (!packageIds.includes(selectedPackageId)) setSelectedPackageId(packageIds[0] || "");
      })
      .catch((error) => {
        if (error?.status === 404) {
          setWritingManifest(null);
          setSelectedPackageId("");
          return;
        }
        setManifestMessage(`研究方案写作资料包生成失败：${error.status || error.message || "network"}`);
      })
      .finally(() => setManifestLoading(false));
  };
  const refreshDocumentSession = (signal) => {
    if (isDemoWritingSession) {
      setDocumentSession(null);
      setDocumentSessionMessage("");
      return;
    }
    const requestId = documentSessionRequestRef.current + 1;
    documentSessionRequestRef.current = requestId;
    setDocumentSessionLoading(true);
    setDocumentSessionMessage("");
    fetch(`/api/projects/${projectId}/medical-writing/document-session?allow_missing=true`, { signal })
      .then(readJsonOrThrow)
      .then((payload) => {
        if (!signal?.aborted && documentSessionRequestRef.current === requestId) {
          if (payload.available === false) {
            setDocumentSession(null);
            setGreenfieldState(null);
            setDocumentSessionMessage("");
            return;
          }
          setDocumentSession(payload);
        }
      })
      .catch((error) => {
        if (
          error?.name === "AbortError"
          || signal?.aborted
          || documentSessionRequestRef.current !== requestId
        ) return;
        if (error?.status === 404) {
          setDocumentSession(null);
          setGreenfieldState(null);
          setDocumentSessionMessage("");
          return;
        }
        setDocumentSessionMessage(`真实方案文档会话读取失败：${apiErrorText(error)}`);
      })
      .finally(() => {
        if (!signal?.aborted && documentSessionRequestRef.current === requestId) {
          setDocumentSessionLoading(false);
        }
      });
  };
  const refreshGreenfieldState = (signal) => {
    if (isDemoWritingSession) {
      setGreenfieldState(null);
      return Promise.resolve();
    }
    return fetch(`/api/projects/${projectId}/medical-writing/greenfield-document`, { signal })
      .then((response) => {
        if (response.status === 404) return null;
        return readJsonOrThrow(response);
      })
      .then((payload) => {
        if (!signal?.aborted) setGreenfieldState(payload);
      })
      .catch((error) => {
        if (error?.name === "AbortError" || signal?.aborted) return;
        setGreenfieldState(null);
      });
  };
  const refreshStudyConsistency = (signal) => {
    if (isDemoWritingSession || !editorSessionAvailable) {
      setStudyConsistency(null);
      return Promise.resolve(null);
    }
    fetch(`/api/projects/${projectId}/medical-writing/authoring-journey?allow_missing=true`, { signal })
      .then(readJsonOrThrow)
      .then((payload) => {
        if (signal?.aborted) return;
        if (payload.available === false) {
          setAuthoringJourneySnapshot(null);
          setAuthoringJourneyAvailable(false);
          return;
        }
        setAuthoringJourneySnapshot(payload);
        setAuthoringJourneyAvailable(true);
      })
      .catch((error) => {
        if (error?.name === "AbortError" || signal?.aborted) return;
        setAuthoringJourneySnapshot(null);
        setAuthoringJourneyAvailable(false);
      });
    return fetch(`/api/projects/${projectId}/medical-writing/study-consistency`, { signal })
      .then(readJsonOrThrow)
      .then((payload) => {
        if (!signal?.aborted) setStudyConsistency(payload);
        return payload;
      })
      .catch((error) => {
        if (error?.name === "AbortError" || signal?.aborted) return null;
        setStudyConsistency(null);
        return null;
      });
  };
  const openStudyRebind = () => {
    if (studyRebindBusy) return;
    setStudyRebindOpen(true);
    setStudyRebindMessage("");
    setStudyRebindReason("");
    setStudyRebindContentAccepted(false);
    setStudyRebindApprovalAccepted(false);
    if (studyConsistency?.status === "reconciliation_required") {
      setStudyRebindPreview(null);
      return;
    }
    setStudyRebindBusy(true);
    fetch(`/api/projects/${projectId}/medical-writing/study-consistency/rebind-preview`)
      .then(readJsonOrThrow)
      .then(setStudyRebindPreview)
      .catch((error) => {
        setStudyRebindPreview(null);
        setStudyRebindMessage(`设计变更预检失败：${apiErrorText(error)}`);
      })
      .finally(() => setStudyRebindBusy(false));
  };
  const applyStudyRebind = () => {
    const preview = studyRebindPreview;
    if (
      !preview?.can_apply
      || studyRebindBusy
      || studyRebindReason.trim().length < 10
      || !studyRebindContentAccepted
      || !studyRebindApprovalAccepted
    ) return;
    setStudyRebindBusy(true);
    setStudyRebindMessage("");
    fetch(`/api/projects/${projectId}/medical-writing/study-consistency/rebind`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        preview_id: preview.preview_id,
        expected_document_id: preview.document_id,
        expected_baseline_revision: preview.baseline_revision,
        expected_baseline_sha256: preview.baseline_sha256,
        confirm_content_preserved: studyRebindContentAccepted,
        confirm_affected_approvals_reset: studyRebindApprovalAccepted,
        reason: studyRebindReason.trim(),
        actor: "medical_manager",
        idempotency_key: `study-rebind-${projectId}-${preview.preview_id}`.slice(0, 200),
      }),
    })
      .then(readJsonOrThrow)
      .then((payload) => {
        setStudyConsistency(payload.consistency);
        setStudyRebindOpen(false);
        setStudyRebindPreview(null);
        setWorkingCopyMessage(
          payload.reset_approval_count
            ? `研究设计已重绑定；${payload.reset_approval_count}个受影响章节的当前冻结已失效，正文保留并待逐章调和。`
            : "研究设计已重绑定；受影响正文已保留，需逐章完成调和确认。",
        );
        setWorkingCopyReloadNonce((value) => value + 1);
        refreshDocumentSession();
      })
      .catch((error) => setStudyRebindMessage(
        error?.status === 409
          ? `重绑定未执行：依据已变化，请重新预检。${apiErrorText(error)}`
          : `重绑定未执行：${apiErrorText(error)}`,
      ))
      .finally(() => setStudyRebindBusy(false));
  };
  const confirmStudyReconciliation = () => {
    if (
      studyRebindBusy
      || !selectedSectionNeedsReconciliation
      || workingCopyDirty
      || workingCopyRevision < 1
      || studyReconciliationReason.trim().length < 10
      || !studyReconciliationAccepted
    ) return;
    setStudyRebindBusy(true);
    setStudyRebindMessage("");
    fetch(
      `/api/projects/${projectId}/medical-writing/study-consistency/sections/${selectedSection}/confirm`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_id: documentSession?.document_id,
          expected_working_copy_revision: workingCopyRevision,
          reason: studyReconciliationReason.trim(),
          acknowledge_content_reconciled: studyReconciliationAccepted,
          actor: "medical_manager",
          idempotency_key: `study-reconcile-${projectId}-${selectedSection}-r${workingCopyRevision}`,
        }),
      },
    )
      .then(readJsonOrThrow)
      .then((payload) => {
        setWorkingCopy(payload.working_copy);
        setWorkingCopyDraftBlocks(cloneContentBlocks(payload.working_copy.content_blocks));
        setStudyConsistency(payload.consistency);
        setStudyReconciliationReason("");
        setStudyReconciliationAccepted(false);
        setWorkingCopyMessage("当前章节已按最新研究设计完成调和确认，可重新确认并冻结当前版本。");
        refreshFreezeReadiness();
      })
      .catch((error) => setStudyRebindMessage(`章节调和确认失败：${apiErrorText(error)}`))
      .finally(() => setStudyRebindBusy(false));
  };
  const refreshContentQuality = (signal) => {
    if (isDemoWritingSession || !selectedSection) {
      setContentQuality(null);
      setContentQualityMessage("");
      return Promise.resolve();
    }
    setContentQualityLoading(true);
    setContentQualityMessage("");
    return fetch(
      `/api/projects/${projectId}/medical-writing/content-quality?section_id=${encodeURIComponent(selectedSection)}`,
      { signal },
    )
      .then(readJsonOrThrow)
      .then((payload) => {
        if (signal?.aborted) return;
        setContentQuality(payload);
        const findingIds = (payload.findings || []).map((item) => item.finding_id);
        setSelectedContentFindingId((current) => (
          findingIds.includes(current) ? current : findingIds[0] || ""
        ));
      })
      .catch((error) => {
        if (error?.name === "AbortError" || signal?.aborted) return;
        setContentQuality(null);
        setContentQualityMessage(`源内容核查读取失败：${apiErrorText(error)}`);
      })
      .finally(() => {
        if (!signal?.aborted) setContentQualityLoading(false);
      });
  };
  const refreshFreezeReadiness = (signal) => {
    if (isDemoWritingSession || !editorSessionAvailable) {
      setFreezeReadiness(null);
      setFreezeReadinessError("");
      return Promise.resolve(null);
    }
    setFreezeReadinessError("");
    return fetch(`/api/projects/${projectId}/medical-writing/freeze-readiness`, { signal })
      .then(readJsonOrThrow)
      .then((payload) => {
        if (!signal?.aborted) setFreezeReadiness(payload);
        return payload;
      })
      .catch((error) => {
        if (error?.name === "AbortError" || signal?.aborted) return null;
        setFreezeReadiness(null);
        setFreezeReadinessError(`冻结准备状态读取失败：${apiErrorText(error)}`);
        return null;
      });
  };
  const refreshVersionHistory = (signal) => {
    if (isDemoWritingSession || !editorSessionAvailable || !selectedSection) {
      setFreezeHistory([]);
      setQuarantinedWorkingCopy(null);
      setVersionHistoryMessage("");
      return Promise.resolve();
    }
    setVersionHistoryLoading(true);
    setVersionHistoryMessage("");
    return Promise.all([
      fetch(
        `/api/projects/${projectId}/medical-writing/working-copies/${selectedSection}/freeze-history`,
        { signal },
      ).then(readJsonOrThrow),
      fetch(
        `/api/projects/${projectId}/medical-writing/working-copies/${selectedSection}/quarantined-history`,
        { signal },
      ).then((response) => (response.status === 404 ? null : readJsonOrThrow(response))),
    ])
      .then(([freezeRecords, quarantined]) => {
        if (signal?.aborted) return;
        setFreezeHistory(Array.isArray(freezeRecords) ? freezeRecords : []);
        setQuarantinedWorkingCopy(quarantined);
      })
      .catch((error) => {
        if (error?.name === "AbortError" || signal?.aborted) return;
        setFreezeHistory([]);
        setQuarantinedWorkingCopy(null);
        setVersionHistoryMessage(`版本历史读取失败：${apiErrorText(error)}`);
      })
      .finally(() => {
        if (!signal?.aborted) setVersionHistoryLoading(false);
      });
  };
  useEffect(() => {
    // Reset section selection immediately on project switch so section-content
    // effects never fetch a stale section_id against a newly loaded document session.
    setSelectedSection("");
    setSectionContent(null);
    setWorkingCopy(null);
    setWorkingCopyDraftBlocks([]);
    setWorkingCopyEditing(false);
    setWorkingCopyDirty(false);
    setEditorStructureError("");
    setFreezeReadiness(null);
    setFreezeReadinessError("");
    setFreezeHistory([]);
    setQuarantinedWorkingCopy(null);
    setBindingRecoveryReason("");
    setBindingRecoveryAcknowledged(false);
    setDocumentPreview(null);
    setDocumentPreviewMessage("");
    setDocumentPreviewBusy(false);
    setFullDraftJob(null);
    setFullDraftArtifact(null);
    setFullDraftBusy(false);
    setFullDraftMessage("");
    fullDraftRunRef.current += 1;
    documentPreviewRequestRef.current += 1;
    const controller = new AbortController();
    refreshWritingManifest();
    refreshDocumentSession(controller.signal);
    return () => controller.abort();
  }, [projectId]);
  useEffect(() => {
    const controller = new AbortController();
    refreshFreezeReadiness(controller.signal);
    return () => controller.abort();
  }, [projectId, editorSessionAvailable, documentSession?.document_id, workingCopyReloadNonce]);
  useEffect(() => {
    setFreezeHistory([]);
    setQuarantinedWorkingCopy(null);
    setVersionHistoryMessage("");
    setBindingRecoveryReason("");
    setBindingRecoveryAcknowledged(false);
    if (activeWritingRailTab !== "版本") return undefined;
    const controller = new AbortController();
    refreshVersionHistory(controller.signal);
    return () => controller.abort();
  }, [activeWritingRailTab, projectId, editorSessionAvailable, selectedSection, workingCopyReloadNonce]);
  useEffect(() => {
    if (isDemoWritingSession || !editorSessionAvailable || !workingCopy?.revision) {
      setDocumentIndex(null);
      return undefined;
    }
    const controller = new AbortController();
    fetch(`/api/projects/${projectId}/medical-writing/document-index`, {
      signal: controller.signal,
    })
      .then((response) => {
        // A greenfield baseline can exist before its first working-copy index.
        // Treat that short-lived state as an empty index, not a failed request.
        if (response.status === 404) return null;
        return readJsonOrThrow(response);
      })
      .then((payload) => {
        if (!controller.signal.aborted) setDocumentIndex(payload);
      })
      .catch((error) => {
        if (error?.name !== "AbortError" && !controller.signal.aborted) {
          setDocumentIndex(null);
        }
      });
    return () => controller.abort();
  }, [projectId, isDemoWritingSession, editorSessionAvailable, documentSession?.document_id, workingCopy?.revision]);
  useEffect(() => {
    const controller = new AbortController();
    refreshStudyConsistency(controller.signal);
    return () => controller.abort();
  }, [
    projectId,
    isDemoWritingSession,
    editorSessionAvailable,
    documentSession?.document_id,
    workingCopy?.revision,
  ]);
  useEffect(() => {
    setTemplateUpgradePreview(null);
    setTemplateUpgradeMessage("");
    setTemplateUpgradeConsolidationAccepted(false);
    setTemplateUpgradeApprovalResetAccepted(false);
    if (!isLegacyGreenfieldTemplate) return undefined;
    const controller = new AbortController();
    setTemplateUpgradeLoading(true);
    fetch(
      `/api/projects/${projectId}/medical-writing/greenfield-document/template-upgrade/preview`,
      { signal: controller.signal },
    )
      .then(readJsonOrThrow)
      .then((payload) => {
        if (!controller.signal.aborted) setTemplateUpgradePreview(payload);
      })
      .catch((error) => {
        if (error?.name !== "AbortError" && !controller.signal.aborted) {
          setTemplateUpgradeMessage(`模板升级预检失败：${apiErrorText(error)}`);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setTemplateUpgradeLoading(false);
      });
    return () => controller.abort();
  }, [projectId, documentSession?.document_id, documentSession?.template_version, isLegacyGreenfieldTemplate]);
  useEffect(() => {
    if (!["greenfield_candidate", "template_upgrade_candidate"].includes(documentSession?.status)) {
      setGreenfieldState(null);
      return undefined;
    }
    const controller = new AbortController();
    refreshGreenfieldState(controller.signal);
    return () => controller.abort();
  }, [projectId, documentSession?.document_id, documentSession?.status]);
  const applyTemplateUpgrade = () => {
    const preview = templateUpgradePreview;
    if (!preview?.can_apply || templateUpgradeBusy) return;
    setTemplateUpgradeBusy(true);
    setTemplateUpgradeMessage("");
    fetch(
      `/api/projects/${projectId}/medical-writing/greenfield-document/template-upgrade/apply`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_baseline_revision: preview.current_baseline_revision,
          expected_baseline_sha256: preview.current_baseline_sha256,
          expected_preview_sha256: preview.preview_sha256,
          target_template_id: preview.target_template_id,
          target_template_version: preview.target_template_version,
          target_template_definition_sha256: preview.target_template_definition_sha256,
          acknowledge_consolidation: templateUpgradeConsolidationAccepted,
          acknowledge_approval_reset: templateUpgradeApprovalResetAccepted,
          actor: "medical_manager",
          idempotency_key: `template-upgrade-${projectId}-${preview.preview_sha256.slice(0, 16)}`,
        }),
      },
    )
      .then(readJsonOrThrow)
      .then((payload) => {
        setTemplateUpgradeAppliedResult(payload);
        setTemplateUpgradeOpen(false);
        setTemplateUpgradePreview(null);
        setSelectedSection(payload.document?.sections?.[0]?.section_id || "");
        setWorkingCopyMessage(`已切换至当前中文M11模板（${payload.target_section_count}个结构节点）；旧工作副本和历史快照均已保留，当前章节需重新确认并冻结。`);
        refreshDocumentSession();
        refreshGreenfieldState();
      })
      .catch((error) => setTemplateUpgradeMessage(
        error?.status === 409
          ? `升级未执行：预检依据已变化，请关闭后重新打开。${apiErrorText(error)}`
          : `升级未执行：${apiErrorText(error)}`,
      ))
      .finally(() => setTemplateUpgradeBusy(false));
  };
  const rollbackTemplateUpgrade = () => {
    const applied = templateUpgradeAppliedResult;
    if (!applied || templateUpgradeBusy) return;
    setTemplateUpgradeBusy(true);
    setTemplateUpgradeMessage("");
    fetch(
      `/api/projects/${projectId}/medical-writing/greenfield-document/template-upgrade/rollback`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          migration_event_id: applied.migration_event_id,
          expected_baseline_revision: applied.baseline_revision,
          expected_baseline_sha256: applied.baseline_sha256,
          actor: "medical_manager",
          idempotency_key: `template-upgrade-rollback-${projectId}-${applied.migration_event_id}`,
        }),
      },
    )
      .then(readJsonOrThrow)
      .then((payload) => {
        setTemplateUpgradeAppliedResult(null);
        setSelectedSection(payload.restored_document?.sections?.[0]?.section_id || "");
        setWorkingCopyMessage("已恢复升级前的旧版工作副本；原有工作副本和保存快照重新成为当前文档历史。 ");
        refreshDocumentSession();
        refreshGreenfieldState();
      })
      .catch((error) => setWorkingCopyMessage(`无法恢复升级前版本：${apiErrorText(error)}`))
      .finally(() => setTemplateUpgradeBusy(false));
  };
  const handleGreenfieldCreated = (payload) => {
    const document = payload?.document;
    if (!document) return;
    setAuthoringJourneyAvailable(true);
    setDocumentSession(document);
    setDocumentSessionMessage("");
    setGreenfieldState({
      project_id: projectId,
      document_id: document.document_id,
      protocol_id: document.protocol_id,
      version: document.version,
      baseline_revision: payload.baseline_revision,
      baseline_sha256: payload.baseline_sha256,
      source_mode: "greenfield_project_decision",
      decisions: payload.decisions || [],
      module_resolutions: document.module_resolutions || payload.module_resolutions || [],
      approval_blocker_count: greenfieldApprovalBlockerCount(
        payload.decisions || [],
        document.module_resolutions || payload.module_resolutions || [],
      ),
    });
    setSelectedSection(document.sections?.[0]?.section_id || "");
    setWorkingCopyMessage("研究方案工作稿已建立；可直接审阅、选用AI候选并继续编辑。");
    refreshWritingManifest();
  };
  const resolveGreenfieldDecision = (decisionId, values) => {
    if (!isGreenfieldSession || greenfieldDecisionBusy || !greenfieldState?.baseline_revision) return;
    setGreenfieldDecisionBusy(decisionId);
    setGreenfieldDecisionMessage("");
    fetch(
      `/api/projects/${projectId}/medical-writing/greenfield-document/decisions/${encodeURIComponent(decisionId)}/resolve`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_baseline_revision: greenfieldState.baseline_revision,
          value: values.value,
          rationale: values.rationale,
          source_refs: values.sourceRefs,
          actor: "medical_manager",
          idempotency_key: `greenfield-decision-${projectId}-${decisionId}-${Date.now()}`,
        }),
      },
    )
      .then(readJsonOrThrow)
      .then((payload) => {
        setGreenfieldState((current) => {
          if (!current) return current;
          const decisions = (current.decisions || []).map((item) => (
            item.decision_id === decisionId ? payload.decision : item
          ));
          return {
            ...current,
            baseline_revision: payload.baseline_revision,
            baseline_sha256: payload.baseline_sha256,
            decisions,
            approval_blocker_count: greenfieldApprovalBlockerCount(
              decisions,
              current.module_resolutions,
            ),
          };
        });
        setGreenfieldDecisionMessage(`“${payload.decision.label}”已写入项目决策基线版本 ${payload.baseline_revision}；相关旧AI线程将按新基线重新核验。`);
        refreshWritingManifest();
        refreshRevisionThreads();
      })
      .catch((error) => setGreenfieldDecisionMessage(
        error.status === 409
          ? `保存失败：项目决策基线已更新，请刷新后重新核对。${apiErrorText(error)}`
          : `保存失败：${apiErrorText(error)}`,
      ))
      .finally(() => setGreenfieldDecisionBusy(""));
  };
  const applyProtocolModuleResolution = (resolution, draft) => {
    if (
      !resolution?.semantic_node_id
      || !greenfieldState?.baseline_revision
      || !greenfieldState?.baseline_sha256
      || moduleResolutionBusy
    ) return;
    setModuleResolutionBusy(resolution.semantic_node_id);
    setModuleResolutionMessage("");
    setModuleResolutionResult(null);
    const moduleResolutionRequestIdentity = {
      projectId,
      baselineRevision: greenfieldState.baseline_revision,
      baselineSha256: greenfieldState.baseline_sha256,
      semanticNodeId: resolution.semantic_node_id,
      status: draft.status,
      renderAction: draft.renderAction,
      rationale: draft.rationale.trim(),
      sourceRefs: [...(draft.sourceRefs || [])].sort(),
    };
    fetch(
      `/api/projects/${projectId}/medical-writing/greenfield-document/module-resolutions/${encodeURIComponent(resolution.semantic_node_id)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_baseline_revision: greenfieldState.baseline_revision,
          expected_baseline_sha256: greenfieldState.baseline_sha256,
          semantic_node_id: resolution.semantic_node_id,
          status: draft.status,
          render_action: draft.renderAction,
          rationale: draft.rationale.trim(),
          source_refs: draft.sourceRefs,
          actor: "medical_manager",
          idempotency_key: (
            `module-resolution-${projectId}-${resolution.semantic_node_id}-`
            + stableRequestToken(moduleResolutionRequestIdentity)
          ).slice(0, 200),
        }),
      },
    )
      .then(readJsonOrThrow)
      .then((payload) => {
        setModuleResolutionResult(payload);
        const mergeAppliedResolution = (items = []) => {
          const next = (items || []).filter(
            (item) => item.semantic_node_id !== payload.resolution.semantic_node_id,
          );
          next.push(payload.resolution);
          return next;
        };
        setGreenfieldState((current) => {
          if (!current) return current;
          const moduleResolutions = mergeAppliedResolution(
            current.module_resolutions,
          );
          return {
            ...current,
            baseline_revision: payload.baseline_revision,
            baseline_sha256: payload.baseline_sha256,
            module_resolutions: moduleResolutions,
            approval_blocker_count: greenfieldApprovalBlockerCount(
              current.decisions,
              moduleResolutions,
            ),
          };
        });
        setDocumentSession((current) => current ? {
          ...current,
          module_resolutions: mergeAppliedResolution(current.module_resolutions),
        } : current);
        setModuleResolutionMessage(
          payload.reset_approval_count
            ? `设计选择已应用；${payload.reset_approval_count}条旧冻结记录已保留为历史，相关正文需重新确认。`
            : "设计选择已应用到方案摘要、正文及关联模块。",
        );
        if ((payload.removed_section_ids || []).includes(selectedSection)) setSelectedSection("");
        refreshDocumentSession();
        refreshGreenfieldState();
        refreshStudyConsistency();
        refreshWritingManifest();
      })
      .catch((error) => setModuleResolutionMessage(
        error?.status === 409
          ? `应用失败：方案基线已变化，请刷新后重试。${apiErrorText(error)}`
          : `应用失败：${apiErrorText(error)}`,
      ))
      .finally(() => setModuleResolutionBusy(""));
  };
  useEffect(() => {
    const controller = new AbortController();
    setTableTemplateLoading(true);
    fetch("/api/medical-writing/table-templates", { signal: controller.signal })
      .then(readJsonOrThrow)
      .then((payload) => {
        if (!controller.signal.aborted) setTableTemplates(Array.isArray(payload) ? payload : []);
      })
      .catch((error) => {
        if (error?.name !== "AbortError" && !controller.signal.aborted) {
          setTableTemplates([]);
          setWorkingCopyMessage(`结构化表格模板读取失败：${apiErrorText(error)}`);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setTableTemplateLoading(false);
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/medical-writing/table-domain-profiles", { signal: controller.signal })
      .then(readJsonOrThrow)
      .then((payload) => {
        if (!controller.signal.aborted) setTableDomainProfiles(Array.isArray(payload) ? payload : []);
      })
      .catch((error) => {
        if (error?.name !== "AbortError" && !controller.signal.aborted) {
          setTableDomainProfiles([]);
          setWorkingCopyMessage(`领域表格配置读取失败：${apiErrorText(error)}`);
        }
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (documentSections.length && !documentSections.some((item) => item.id === selectedSection)) {
      requestSectionChange(documentSections[0].id);
    }
  }, [documentSession?.document_id, documentSections.length, selectedSection, requestSectionChange]);
  useEffect(() => {
    if (isDemoWritingSession || !documentSession || !selectedSection) {
      workingCopyRequestRef.current += 1;
      setSectionContent(null);
      setWorkingCopy(null);
      setWorkingCopyDraftBlocks([]);
      setWorkingCopyEditing(false);
      setWorkingCopyDirty(false);
      setWorkingCopyLoadError("");
      setLoadedEditorIdentity("");
      setRecoveryDraftPrompt(null);
      setCurrentRecoveryDraft(null);
      return undefined;
    }
    const controller = new AbortController();
    const requestId = workingCopyRequestRef.current + 1;
    workingCopyRequestRef.current = requestId;
    const requestIdentity = [projectId, documentSession.document_id, selectedSection].join(":");
    setWorkingCopyLoading(true);
    setWorkingCopyLoadError("");
    Promise.all([
      fetch(`/api/projects/${projectId}/medical-writing/document-session/sections/${selectedSection}`, { signal: controller.signal }).then(readJsonOrThrow),
      fetch(`/api/projects/${projectId}/medical-writing/working-copies/${selectedSection}`, { signal: controller.signal }).then(readJsonOrThrow),
    ])
      .then(([sectionPayload, workingCopyPayload]) => {
        if (
          controller.signal.aborted
          || workingCopyRequestRef.current !== requestId
        ) return;
        setSectionContent(sectionPayload);
        setWorkingCopy(workingCopyPayload);
        setWorkingCopyDraftBlocks(cloneContentBlocks(
          workingCopyPayload.revision >= 1
            ? workingCopyPayload.content_blocks
            : sectionPayload.content_blocks,
        ));
        setWorkingCopyEditing(workingCopyPayload.revision >= 1);
        setWorkingCopyDirty(false);
        setEditorStructureError("");
        setWorkingCopyHydrationEpoch((value) => value + 1);
        setLoadedEditorIdentity(requestIdentity);
        setCurrentRecoveryDraft(null);
        try {
          const [latestDraft] = listMedicalWritingRecoveryDrafts(globalThis.sessionStorage, {
            projectId,
            documentId: documentSession.document_id,
            sectionId: selectedSection,
          });
          setRecoveryDraftPrompt(latestDraft ? {
            ...latestDraft,
            recoveryState: medicalWritingRecoveryDraftState(workingCopyPayload.revision, latestDraft),
          } : null);
        } catch {
          setRecoveryDraftPrompt(null);
        }
        setWorkingCopySaveKey(`wc-${projectId}-${selectedSection}-${Date.now()}`);
      })
      .catch((error) => {
        if (
          error?.name === "AbortError"
          || controller.signal.aborted
          || workingCopyRequestRef.current !== requestId
        ) return;
        setWorkingCopyLoadError(`章节正文或工作副本读取失败：${apiErrorText(error)}`);
      })
      .finally(() => {
        if (!controller.signal.aborted && workingCopyRequestRef.current === requestId) {
          setWorkingCopyLoading(false);
        }
      });
    return () => controller.abort();
  }, [projectId, isDemoWritingSession, documentSession?.document_id, selectedSection, workingCopyReloadNonce]);
  useEffect(() => {
    const controller = new AbortController();
    setContentDispositionReason("");
    setContentDispositionAcknowledged(false);
    refreshContentQuality(controller.signal);
    return () => controller.abort();
  }, [projectId, isDemoWritingSession, selectedSection, workingCopyReloadNonce]);
  const refreshRevisionThreads = () => {
    if (!editorSessionAvailable) {
      setRevisionLoading(false);
      setRevisionMessage("");
      setRevisionThreads([]);
      setActiveRevisionThreadId("");
      return;
    }
    setRevisionLoading(true);
    setRevisionMessage("");
    setRevisionThreads([]);
    fetch(`/api/projects/${projectId}/revision-threads`)
      .then(readJsonOrThrow)
      .then((payload) => {
        const threads = Array.isArray(payload) ? payload : [];
        setRevisionThreads(threads);
        if (!threads.some((thread) => thread.thread_id === activeRevisionThreadId)) {
          setActiveRevisionThreadId(threads[threads.length - 1]?.thread_id || "");
        }
      })
      .catch((error) => setRevisionMessage(`AI修订线程读取失败：${apiErrorText(error)}`))
      .finally(() => setRevisionLoading(false));
  };
  useEffect(() => {
    refreshRevisionThreads();
  }, [projectId, editorSessionAvailable]);

  // Screen generation: project/section switch invalidates in-flight side effects.
  useEffect(() => {
    revisionScreenGenRef.current = createScreenGeneration(projectId, selectedSection || "");
    setRevisionJobs(emptyRevisionJobMap());
  }, [projectId, selectedSection]);

  // Resume initial + rewrite concurrently; each op has independent map state.
  useEffect(() => {
    let cancelled = false;
    const screenAtStart = revisionScreenGenRef.current;
    const storageKeys = [
      { key: `mw_revision_job_${projectId}`, operation: "initial" },
      { key: `mw_rewrite_job_${projectId}`, operation: "rewrite" },
    ];
    const stillCurrent = () =>
      !cancelled
      && isScreenGenerationCurrent(screenAtStart, projectId, selectedSection || "");

    const resumeOne = async ({ key, operation }) => {
      let stored;
      try {
        stored = JSON.parse(localStorage.getItem(key) || "null");
      } catch {
        return;
      }
      if (!stored || !stored.job_id || stored.project_id !== projectId) return;
      if (isStaleCompletion(stored, projectId, operation === "initial" ? (selectedSection || "") : "")) {
        return;
      }
      if (!stillCurrent()) return;
      setRevisionJobs((map) => setOperationJob(map, operation, {
        job_id: stored.job_id,
        status: "resuming",
        operation,
        ...stored,
      }));
      setRevisionMessage(operation === "rewrite" ? "AI重写正在恢复…" : "AI修订正在恢复…");
      const { status, result, error, transportResultOk } = await pollDurableMwJob(
        projectId,
        stored.job_id,
        {
          intervalMs: 2000,
          maxLoops: 150,
          onUpdate: (st) => {
            if (!stillCurrent()) return;
            setRevisionJobs((map) => {
              const prev = map?.[operation];
              if (!prev || prev.job_id !== stored.job_id) return map;
              return setOperationJob(map, operation, {
                ...prev,
                status: st.status,
                progress: st.progress,
              });
            });
            if (st.progress?.phase) {
              setRevisionMessage(
                `${st.progress.message || "正在生成AI候选"}（${Math.round((st.progress?.percent || 0) * 100)}%）`,
              );
            }
          },
        },
      );
      if (!stillCurrent()) return;

      let domainThread = null;
      if (status === "completed" && transportResultOk && result) {
        try {
          const threads = await fetch(`/api/projects/${projectId}/revision-threads`).then(readJsonOrThrow);
          if (!stillCurrent()) return;
          const exact = extractArtifactThreadId(result);
          domainThread = exact ? threads.find((t) => t.thread_id === exact) || null : null;
        } catch {
          domainThread = null;
        }
      }
      if (!stillCurrent()) return;

      const ack = acknowledgeRevisionDomain({
        status,
        resultBody: transportResultOk ? result : null,
        locator: stored,
        domainThread,
        currentProjectId: projectId,
        currentSectionId: selectedSection || "",
        screenGeneration: screenAtStart,
      });
      if (ack.outcome === "stale_screen") return;

      if (ack.outcome === "success" && domainThread) {
        setRevisionThreads((previous) => [
          ...previous.filter((t) => t.thread_id !== domainThread.thread_id),
          domainThread,
        ]);
        setActiveRevisionThreadId(domainThread.thread_id);
        setRevisionMessage("AI修订建议已生成。请选择一个候选。");
        if (ack.shouldClear) {
          try { localStorage.removeItem(key); } catch { /* ignore */ }
          setRevisionJobs((map) => clearOperationJob(map, operation));
        }
        return;
      }
      if (ack.outcome === "terminal_failure") {
        setRevisionMessage(`AI修订${status === "cancelled" ? "已取消" : "失败"}：${error || "请稍后重试。"}`);
        if (ack.shouldClear) {
          try { localStorage.removeItem(key); } catch { /* ignore */ }
          setRevisionJobs((map) => clearOperationJob(map, operation));
        } else {
          setRevisionJobs((map) => setOperationJob(map, operation, {
            ...stored,
            operation,
            status,
            domainReconciled: false,
          }));
        }
        return;
      }
      setRevisionMessage(
        ack.outcome === "reconcile_failed"
          ? "AI修订已结束，但结果核对失败。定位器已保留，请重试核对。"
          : "AI修订仍在后台进行，请稍后查看或刷新页面恢复。",
      );
      setRevisionJobs((map) => setOperationJob(map, operation, {
        ...stored,
        operation,
        status,
        domainReconciled: false,
      }));
    };

    // Concurrent recovery — neither op blocks the other.
    Promise.all(storageKeys.map((entry) => resumeOne(entry)));
    return () => {
      cancelled = true;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, selectedSection]);
  useEffect(() => {
    setSelectedEditorText("");
    setSelectedEditorAnchor("");
    setSelectedEditorBlockContext({ blockType: "", sourceKind: "" });
    setEditorPlainText("");
    setEditorStructureError("");
    setSelectedReferenceBriefIds([]);
    setSoaCandidatePicker(null);
    setSoaCreateConfirmOpen(false);
  }, [selectedSection]);
  useEffect(() => {
    setActiveWritingRailTab("AI");
    setSelectedReferenceBriefIds([]);
  }, [projectId]);
  const defaultRevisionWorkingBlock = workingCopyDisplayBlocks.find((block) => (
    block.block_type !== "heading" && String(block.text || "").trim()
  )) || workingCopyDisplayBlocks.find(isBlankGreenfieldBodyBlock)
    || workingCopyDisplayBlocks.find((block) => String(block.text || "").trim());
  const submitRevisionRequest = () => {
    const tableCell = selectedEditorBlockContext.tableCell;
    const defaultRevisionText = isDemoWritingSession
      ? editorPlainText
      : defaultRevisionWorkingBlock?.text;
    const blankSectionDraft = Boolean(
      !tableCell
      && !selectedEditorText
      && !String(defaultRevisionText || "").trim()
      && isBlankGreenfieldBodyBlock(defaultRevisionWorkingBlock),
    );
    const selected_text = (
      tableCell?.text
      || selectedEditorText
      || defaultRevisionText
      || ""
    ).trim();
    const intentProfile = revisionIntentOptions.find((item) => item.value === revisionIntent);
    const normalizedInstruction = revisionInstruction.trim();
    const hasCustomBlankDraftInstruction = Boolean(
      normalizedInstruction
      && normalizedInstruction !== String(intentProfile?.defaultInstruction || "").trim(),
    );
    const requestInstruction = blankSectionDraft
      ? [
        (
          `当前“${section.title}”章节正文为空。请依据当前项目StudyDefinition、PICOS、章节语义、`
          + "已准入语料及本次已选证据，生成3-5个可直接审阅的中国临床试验方案实质正文候选；"
          + "不得改写或重复章节标题，不得补造证据不支持的项目事实。"
        ),
        "写作意图：章节起草。",
        hasCustomBlankDraftInstruction ? `用户补充要求：${normalizedInstruction}` : "",
      ].filter(Boolean).join(" ")
      : normalizedInstruction;
    const anchor_path = tableCell
      ? ""
      : isDemoWritingSession
        ? `sections.${backendSectionId}.editor.${selectedEditorText ? "selection" : "body"}`
        : (
          blankSectionDraft
            ? defaultRevisionWorkingBlock?.source_locator
            : selectedEditorAnchor || defaultRevisionWorkingBlock?.source_locator || ""
        );
    if (!sectionHasBackendBinding) {
      setRevisionMessage("当前章节暂无后端章节绑定，不能提交AI修订，避免错误写入其他章节。");
      return;
    }
    if (!requestInstruction || editorFrozen || !workingCopyAuthoritative || (!selected_text && !blankSectionDraft)) return;
    if (shouldBlockStartForOperation(revisionJobs, "initial")) {
      setRevisionMessage("AI修订正在进行中，请等待完成或取消后再试。");
      return;
    }
    setRevisionLoading(true);
    setRevisionMessage("AI修订已提交，正在后台生成候选...");
    fetch(`/api/projects/${projectId}/revision-threads`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_id: isDemoWritingSession ? undefined : documentSession?.document_id,
        section_id: backendSectionId,
        anchor_type: tableCell ? "table_cell" : selectedEditorText ? "selection" : "section",
        anchor_path,
        selected_text,
        table_cell_anchor: tableCell ? {
          working_copy_id: workingCopy?.working_copy_id || "",
          working_copy_revision: workingCopyRevision,
          table_version: tableCell.tableVersion,
          block_hash: "",
          block_id: tableCell.blockId,
          table_id: tableCell.tableId,
          row_id: tableCell.rowId,
          column_id: tableCell.columnId,
          cell_id: tableCell.cellId,
          captured_text: tableCell.text,
          source_kind: tableCell.sourceKind || "source_linked",
        } : undefined,
        user_instruction: requestInstruction,
        intent: revisionIntent,
        evidence_brief_ids: selectedReferenceBriefIds,
        requested_by: "medical_manager",
      }),
    })
      .then(readJsonOrThrow)
      .then(async (payload) => {
        const screenAtStart = revisionScreenGenRef.current;
        const stillCurrent = () =>
          isScreenGenerationCurrent(screenAtStart, projectId, selectedSection || "");
        // Durable path: payload is {job_id, status} or {job_id, status:"completed", result}.
        if (payload.job_id && payload.status !== "completed") {
          const storageKey = `mw_revision_job_${projectId}`;
          const operation = "initial";
          const locator = buildLocator({
            projectId,
            jobId: payload.job_id,
            operation,
            sectionId: backendSectionId,
            jobType: "section_ai_candidate",
          });
          try { localStorage.setItem(storageKey, JSON.stringify(locator)); } catch { /* ignore */ }
          if (!stillCurrent()) return;
          setRevisionJobs((map) => setOperationJob(map, operation, { ...locator, status: payload.status || "queued" }));
          const { status: jobStatus, result: jobResult, error: jobError, transportResultOk } = await pollDurableMwJob(
            projectId, payload.job_id,
            { intervalMs: 1500, maxLoops: 200, onUpdate: (st) => {
              if (!stillCurrent()) return;
              setRevisionJobs((map) => {
                const prev = map?.[operation];
                if (!prev || prev.job_id !== payload.job_id) return map;
                return setOperationJob(map, operation, { ...prev, status: st.status, progress: st.progress });
              });
              if (st.progress?.phase) {
                setRevisionMessage(
                  `${st.progress.message || "正在生成AI候选"}（${Math.round((st.progress?.percent || 0) * 100)}%）`,
                );
              }
            }},
          );
          if (!stillCurrent()) return;
          let domainThread = null;
          if (jobStatus === "completed" && transportResultOk && jobResult) {
            try {
              const threadsResp = await fetch(`/api/projects/${projectId}/revision-threads`).then(readJsonOrThrow);
              if (!stillCurrent()) return;
              const exactId = extractArtifactThreadId(jobResult);
              domainThread = exactId ? threadsResp.find((t) => t.thread_id === exactId) || null : null;
            } catch {
              domainThread = null;
            }
          }
          if (!stillCurrent()) return;
          const ack = acknowledgeRevisionDomain({
            status: jobStatus,
            resultBody: transportResultOk ? jobResult : null,
            locator,
            domainThread,
            currentProjectId: projectId,
            currentSectionId: selectedSection || "",
            screenGeneration: screenAtStart,
          });
          if (ack.outcome === "stale_screen") return;
          if (ack.outcome === "success" && domainThread) {
            setRevisionThreads((previous) => [...previous.filter((thread) => thread.thread_id !== domainThread.thread_id), domainThread]);
            setActiveRevisionThreadId(domainThread.thread_id);
            setRevisionActionComment("");
            setRevisionMessage("AI修订建议已生成。请选择一个候选；系统将原子记录作者选择并写入当前版本化工作副本。");
            if (ack.shouldClear) {
              try { localStorage.removeItem(storageKey); } catch { /* ignore */ }
              setRevisionJobs((map) => clearOperationJob(map, operation));
            }
            return;
          }
          if (ack.outcome === "terminal_failure") {
            setRevisionMessage(`AI修订${jobStatus === "cancelled" ? "已取消" : "失败"}：${jobError || "请稍后重试。"}`);
          } else {
            setRevisionMessage(
              ack.outcome === "reconcile_failed"
                ? "AI修订已结束，但结果核对失败。定位器已保留，请重试核对。"
                : "AI修订仍在后台进行，请稍后查看或刷新页面恢复。",
            );
          }
          if (ack.shouldClear) {
            try { localStorage.removeItem(storageKey); } catch { /* ignore */ }
            setRevisionJobs((map) => clearOperationJob(map, operation));
          } else {
            setRevisionJobs((map) => setOperationJob(map, operation, {
              ...locator,
              status: jobStatus,
              domainReconciled: false,
            }));
          }
          return;
        }
        if (!stillCurrent()) return;
        // Cached completed result from durable reuse, or legacy sync path.
        const threadData = payload.result?.thread || payload.thread;
        if (!threadData) {
          setRevisionMessage("AI修订作业已提交，但未返回有效结果。");
          return;
        }
        setRevisionThreads((previous) => [...previous.filter((thread) => thread.thread_id !== threadData.thread_id), threadData]);
        setActiveRevisionThreadId(threadData.thread_id);
        setRevisionActionComment("");
        setRevisionMessage("AI修订建议已生成。请选择一个候选；系统将原子记录作者选择并写入当前版本化工作副本。");
      })
      .catch((error) => setRevisionMessage(`AI修订提交失败：${apiErrorText(error)}`))
      .finally(() => setRevisionLoading(false));
  };
  const cancelRevisionJob = async (operation) => {
    const op = operation || revisionJobState?.operation || "initial";
    const job = revisionJobs?.[op] || revisionJobState;
    if (!job?.job_id) return;
    const screenAtStart = revisionScreenGenRef.current;
    const stillCurrent = () =>
      isScreenGenerationCurrent(screenAtStart, projectId, selectedSection || "");
    try {
      await fetch(`/api/projects/${projectId}/medical-writing/jobs/${job.job_id}/cancel`, { method: "POST" });
      if (!stillCurrent()) return;
      setRevisionMessage("AI修订取消请求已发送，正在确认…");
      const storageKey = op === "rewrite"
        ? `mw_rewrite_job_${projectId}`
        : `mw_revision_job_${projectId}`;
      const { status, error, transportResultOk, result } = await pollDurableMwJob(
        projectId,
        job.job_id,
        { intervalMs: 1000, maxLoops: 30 },
      );
      if (!stillCurrent()) return;
      // Never clear on cancelled without domain recon (no status===cancelled override).
      const ack = acknowledgeRevisionDomain({
        status,
        resultBody: transportResultOk ? result : null,
        locator: job,
        domainThread: null,
        currentProjectId: projectId,
        currentSectionId: selectedSection || "",
        screenGeneration: screenAtStart,
      });
      if (ack.outcome === "stale_screen") return;
      if (status === "cancelled" || status === "failed") {
        setRevisionMessage(
          ack.domainReconciled
            ? `AI修订已${status === "cancelled" ? "取消" : "失败"}${error ? `：${error}` : "。"}`
            : "取消请求已发送，结果核对未完成。定位器已保留，请重试核对。",
        );
      } else {
        setRevisionMessage("取消请求已发送，作业状态仍在确认中。定位器已保留。");
      }
      if (ack.shouldClear) {
        try { localStorage.removeItem(storageKey); } catch { /* ignore */ }
        setRevisionJobs((map) => clearOperationJob(map, op));
      } else {
        setRevisionJobs((map) => setOperationJob(map, op, {
          ...job,
          operation: op,
          status,
          domainReconciled: false,
        }));
      }
    } catch { /* best-effort */ }
  };
  const retryRevisionJob = async (operation) => {
    const op = operation || revisionJobState?.operation || "initial";
    const job = revisionJobs?.[op] || revisionJobState;
    if (!job?.job_id) return;
    const screenAtStart = revisionScreenGenRef.current;
    const stillCurrent = () =>
      isScreenGenerationCurrent(screenAtStart, projectId, selectedSection || "");
    try {
      const resp = await fetch(`/api/projects/${projectId}/medical-writing/jobs/${job.job_id}/retry`, { method: "POST" });
      if (!resp.ok) return;
      const body = await resp.json();
      const nextJobId = resolveRetryJobId(job.job_id, body);
      const storageKey = op === "rewrite"
        ? `mw_rewrite_job_${projectId}`
        : `mw_revision_job_${projectId}`;
      const locator = mergeRetryLocator(
        { ...job, operation: op, section_id: job.section_id || backendSectionId, job_type: "section_ai_candidate" },
        nextJobId,
        projectId,
      );
      try { localStorage.setItem(storageKey, JSON.stringify(locator)); } catch { /* ignore */ }
      if (!stillCurrent()) return;
      setRevisionJobs((map) => setOperationJob(map, op, { ...locator, status: "queued" }));
      setRevisionMessage("AI修订已重新提交。");
      const { status, result, error, transportResultOk } = await pollDurableMwJob(
        projectId,
        nextJobId,
        {
          intervalMs: 1500,
          maxLoops: 200,
          onUpdate: (st) => {
            if (!stillCurrent()) return;
            setRevisionJobs((map) => {
              const prev = map?.[op];
              if (!prev || prev.job_id !== nextJobId) return map;
              return setOperationJob(map, op, {
                ...prev,
                status: st.status,
                progress: st.progress,
              });
            });
            if (st.progress?.phase) {
              setRevisionMessage(
                `${st.progress.message || "正在生成AI候选"}（${Math.round((st.progress?.percent || 0) * 100)}%）`,
              );
            }
          },
        },
      );
      if (!stillCurrent()) return;
      let domainThread = null;
      if (status === "completed" && transportResultOk && result) {
        try {
          const threads = await fetch(`/api/projects/${projectId}/revision-threads`).then(readJsonOrThrow);
          if (!stillCurrent()) return;
          const exactId = extractArtifactThreadId(result);
          domainThread = exactId ? threads.find((t) => t.thread_id === exactId) || null : null;
        } catch {
          domainThread = null;
        }
      }
      if (!stillCurrent()) return;
      const ack = acknowledgeRevisionDomain({
        status,
        resultBody: transportResultOk ? result : null,
        locator,
        domainThread,
        currentProjectId: projectId,
        currentSectionId: selectedSection || "",
        screenGeneration: screenAtStart,
      });
      if (ack.outcome === "stale_screen") return;
      if (ack.outcome === "success" && domainThread) {
        setRevisionThreads((prev) => [...prev.filter((t) => t.thread_id !== domainThread.thread_id), domainThread]);
        setActiveRevisionThreadId(domainThread.thread_id);
        setRevisionMessage("AI修订建议已生成。");
      } else if (ack.outcome === "terminal_failure") {
        setRevisionMessage(`AI修订${status === "cancelled" ? "已取消" : "失败"}：${error || ""}`);
      } else {
        setRevisionMessage(
          ack.outcome === "reconcile_failed"
            ? "AI修订已结束，但结果核对失败。定位器已保留，请重试核对。"
            : "AI修订仍在后台进行，请稍后查看或刷新页面恢复。",
        );
      }
      if (ack.shouldClear) {
        try { localStorage.removeItem(storageKey); } catch { /* ignore */ }
        setRevisionJobs((map) => clearOperationJob(map, op));
      } else {
        setRevisionJobs((map) => setOperationJob(map, op, {
          ...locator,
          status,
          domainReconciled: false,
        }));
      }
    } catch { /* best-effort */ }
  };
  const submitRevisionAction = async (thread, suggestion, action) => {
    if (!thread || !suggestion || revisionLoading) return;
    if (action === "accept" && protectedTokenAdoptionBlocked(suggestion)) {
      setRevisionMessage("候选改变了源文本受保护医学标识，已阻止选用；请让AI重写并保留原始数字、单位、术语和引用。");
      return;
    }
    if (action === "request_rewrite" && shouldBlockStartForOperation(revisionJobs, "rewrite")) {
      setRevisionMessage("AI重写正在进行中，请等待完成或取消后再试。");
      return;
    }
    setRevisionLoading(true);
    setRevisionMessage("");
    try {
      // For "accept", use the single atomic accept-and-apply endpoint.
      // If the working copy is frozen, dirty, quarantined, or non-authoritative,
      // block with a clear actionable message — never fall through to the
      // legacy two-step accept→apply chain for production sessions.
      if (action === "accept" && !isDemoWritingSession) {
        if (editorFrozen) {
          setRevisionMessage("当前作者确认版本已冻结，请先解除冻结后再选用候选。");
          return;
        }
        if (workingCopyDirty) {
          setRevisionMessage("存在未保存修订，请先保存或重新加载后再选用候选。");
          return;
        }
        if (!workingCopyAuthoritative) {
          setRevisionMessage("当前历史内容已隔离，请先确认绑定或恢复权威源基线后再选用候选。");
          return;
        }
        // Proceed with the atomic endpoint.
        const response = await fetch(`/api/projects/${projectId}/revision-threads/${thread.thread_id}/accept-and-apply`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            suggestion_id: suggestion.suggestion_id,
            expected_working_copy_revision: workingCopyRevision,
            actor: "medical_manager",
            idempotency_key: `apply-${projectId}-${thread.thread_id}-wc${workingCopyRevision}`,
          }),
        });
        const payload = await readJsonOrThrow(response);
        // Atomic result returns thread_id (not thread object).  Reconcile
        // by fetching the exact thread after the atomic write succeeds.
        if (payload.thread_id) {
          const threadResp = await fetch(`/api/projects/${projectId}/revision-threads`).then(readJsonOrThrow);
          const updatedThread = threadResp.find((t) => t.thread_id === payload.thread_id);
          if (updatedThread) {
            setRevisionThreads((previous) => previous.map((item) => (item.thread_id === updatedThread.thread_id ? updatedThread : item)));
            setActiveRevisionThreadId(updatedThread.thread_id);
          }
        }
        if (payload.working_copy) {
          const nextWorkingCopy = payload.working_copy;
          setWorkingCopy(nextWorkingCopy);
          setWorkingCopyDraftBlocks(cloneContentBlocks(nextWorkingCopy.content_blocks));
          setWorkingCopyEditing(true);
          setWorkingCopyDirty(false);
          setWorkingCopySaveKey(`wc-${projectId}-${selectedSection}-${Date.now()}`);
          setSelectedEditorText("");
          setSelectedEditorAnchor("");
          setRevisionMessage(`已选用并写入工作副本版本 ${nextWorkingCopy.revision}。`);
          refreshContentQuality();
          refreshFreezeReadiness();
        }
        return;
      }
      // request_rewrite goes through the durable path.
      const response = await fetch(`/api/projects/${projectId}/revision-threads/${thread.thread_id}/actions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action,
          suggestion_id: suggestion.suggestion_id,
          actor: "medical_manager",
          comment: revisionActionComment,
          rewrite_instruction: action === "request_rewrite" ? revisionRewriteInstruction : "",
        }),
      });
      const payload = await readJsonOrThrow(response);
      // Durable rewrite: payload is {job_id, status}; poll then fetch thread.
      if (payload.job_id && payload.status !== "completed") {
        const screenAtStart = revisionScreenGenRef.current;
        const stillCurrent = () =>
          isScreenGenerationCurrent(screenAtStart, projectId, selectedSection || "");
        setRevisionMessage("AI按反馈生成新一轮候选中...");
        const storageKey = `mw_rewrite_job_${projectId}`;
        const operation = "rewrite";
        const locator = buildLocator({
          projectId,
          jobId: payload.job_id,
          operation,
          sectionId: thread.section_id || backendSectionId,
          jobType: "section_ai_candidate",
          threadId: thread.thread_id,
        });
        try { localStorage.setItem(storageKey, JSON.stringify(locator)); } catch { /* ignore */ }
        if (!stillCurrent()) return;
        setRevisionJobs((map) => setOperationJob(map, operation, { ...locator, status: payload.status || "queued" }));
        const { status: rwStatus, result: rwResult, error: rwError, transportResultOk } = await pollDurableMwJob(
          projectId, payload.job_id,
          {
            intervalMs: 1500,
            maxLoops: 200,
            onUpdate: (st) => {
              if (!stillCurrent()) return;
              setRevisionJobs((map) => {
                const prev = map?.[operation];
                if (!prev || prev.job_id !== payload.job_id) return map;
                return setOperationJob(map, operation, { ...prev, status: st.status, progress: st.progress });
              });
            },
          },
        );
        if (!stillCurrent()) return;
        let domainThread = null;
        if (rwStatus === "completed" && transportResultOk && rwResult) {
          try {
            const threadsResp = await fetch(`/api/projects/${projectId}/revision-threads`).then(readJsonOrThrow);
            if (!stillCurrent()) return;
            // v2: exact thread id only — no fallback to request thread_id.
            const exactId = extractArtifactThreadId(rwResult);
            domainThread = exactId ? threadsResp.find((t) => t.thread_id === exactId) || null : null;
          } catch {
            domainThread = null;
          }
        }
        if (!stillCurrent()) return;
        const ack = acknowledgeRevisionDomain({
          status: rwStatus,
          resultBody: transportResultOk ? rwResult : null,
          locator,
          domainThread,
          currentProjectId: projectId,
          currentSectionId: selectedSection || "",
          screenGeneration: screenAtStart,
        });
        if (ack.outcome === "stale_screen") return;
        if (ack.outcome === "success" && domainThread) {
          setRevisionThreads((previous) => previous.map((item) => (item.thread_id === domainThread.thread_id ? domainThread : item)));
          setRevisionMessage("已要求AI按医学反馈生成新一轮候选。");
        } else if (ack.outcome === "terminal_failure") {
          setRevisionMessage(`AI重写${rwStatus === "cancelled" ? "已取消" : "失败"}：${rwError || "请稍后重试。"}`);
        } else {
          setRevisionMessage(
            ack.outcome === "reconcile_failed"
              ? "AI重写已结束，但结果核对失败。定位器已保留，请重试核对。"
              : "AI重写仍在后台进行，请稍后查看或刷新页面恢复。",
          );
        }
        if (ack.shouldClear) {
          try { localStorage.removeItem(storageKey); } catch { /* ignore */ }
          setRevisionJobs((map) => clearOperationJob(map, operation));
        } else {
          setRevisionJobs((map) => setOperationJob(map, operation, {
            ...locator,
            status: rwStatus,
            domainReconciled: false,
          }));
        }
        return;
      }
      // Legacy sync path (demo / non-durable reject, etc.).
      if (!payload.thread) {
        setRevisionMessage("修订处置已提交，但未返回有效线程。");
        return;
      }
      setRevisionThreads((previous) => previous.map((item) => (item.thread_id === payload.thread.thread_id ? payload.thread : item)));
      setActiveRevisionThreadId(payload.thread.thread_id);
      if (action === "accept") {
        // Real-project path never reaches here; demo may still use legacy apply.
        if (isDemoWritingSession) {
          await applyApprovedRevision(payload.thread, { fromSelection: true });
        } else {
          setRevisionMessage("生产路径必须使用原子选用并写入；请重新选用候选。");
        }
      } else {
        setRevisionMessage(action === "reject"
          ? "已拒绝该建议并写入审计。"
          : "已要求AI按医学反馈生成新一轮候选。");
      }
    } catch (error) {
      setRevisionMessage(`修订处置失败：${apiErrorText(error)}`);
    } finally {
      setRevisionLoading(false);
    }
  };
  const applyApprovedRevision = async (thread, { fromSelection = false } = {}) => {
    // Production real-project path is atomic accept-and-apply only.
    // This legacy helper is retained solely for demo sessions.
    if (!isDemoWritingSession) {
      setRevisionMessage("生产路径已禁用分步写入；请使用“选用并写入”原子操作。");
      return false;
    }
    if (
      !thread
      || !isRevisionThreadSelectedByAuthor(thread.status)
      || workingCopyActionBusy
      || workingCopyDirty
      || editorFrozen
      || !workingCopyAuthoritative
      || (workingCopy?.applied_revision_thread_ids || []).includes(thread.thread_id)
    ) {
      if (isRevisionThreadSelectedByAuthor(thread?.status)) {
        const reason = workingCopyDirty
          ? "存在未保存修订，请先保存或重新加载后重试写入。"
          : editorFrozen
            ? "当前作者确认版本已冻结，请先解除冻结后重试写入。"
            : !workingCopyAuthoritative
              ? "当前历史内容已隔离，请先确认绑定或恢复权威源基线。"
              : "当前工作副本暂不可写入，请刷新章节后重试。";
        setRevisionMessage(`候选处置已记录，但尚未写入正文：${reason}`);
      }
      return false;
    }
    setWorkingCopyActionBusy(true);
    setWorkingCopyMessage("");
    if (!fromSelection) setRevisionMessage("");
    try {
      const response = await fetch(`/api/projects/${projectId}/medical-writing/working-copies/${selectedSection}/revision-threads/${thread.thread_id}/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_working_copy_revision: workingCopyRevision,
          actor: "medical_manager",
          idempotency_key: `apply-${projectId}-${thread.thread_id}-wc${workingCopyRevision}`,
        }),
      });
      const payload = await readJsonOrThrow(response);
      const nextWorkingCopy = payload.working_copy;
      setWorkingCopy(nextWorkingCopy);
      setWorkingCopyDraftBlocks(cloneContentBlocks(nextWorkingCopy.content_blocks));
      setWorkingCopyEditing(true);
      setWorkingCopyDirty(false);
      setWorkingCopySaveKey(`wc-${projectId}-${selectedSection}-${Date.now()}`);
      setSelectedEditorText("");
      setSelectedEditorAnchor("");
      setWorkingCopyMessage(`AI候选已由医学作者选用并写入工作副本版本 ${nextWorkingCopy.revision}；原始 DOCX 未被修改。`);
      setRevisionMessage(`已选用并写入工作副本版本 ${nextWorkingCopy.revision}。`);
      refreshContentQuality();
      refreshFreezeReadiness();
      return true;
    } catch (error) {
      setRevisionMessage(error?.status === 409
        ? `候选处置已记录，但写入失败：${apiErrorText(error)}。请重新加载当前章节后使用“重试写入”。`
        : `候选处置已记录，但写入工作副本失败：${apiErrorText(error)}。请处理当前提示后使用“重试写入”。`);
      return false;
    } finally {
      setWorkingCopyActionBusy(false);
    }
  };
  const createWorkingCopy = () => {
    if (isDemoWritingSession || !sectionContentAvailable || editorFrozen || !workingCopyAuthoritative) return;
    setWorkingCopyDraftBlocks(cloneContentBlocks(sectionContent?.content_blocks || []));
    setWorkingCopyEditing(true);
    setWorkingCopyDirty(false);
    setWorkingCopySaveKey(`wc-${projectId}-${selectedSection}-${Date.now()}`);
    setWorkingCopyMessage("可编辑工作副本已就绪；首次实际修订后再保存为版本 1。");
  };
  const updateWorkingCopyDraft = (nextBlocks) => {
    if (!realWorkingCopyEditable || editorFrozen) return;
    setWorkingCopyDraftBlocks(nextBlocks);
    setWorkingCopyDirty(true);
    setWorkingCopySaveKey(`wc-${projectId}-${selectedSection}-${Date.now()}`);
  };
  const saveWorkingCopy = () => {
    if (
      isDemoWritingSession
      || workingCopyActionBusy
      || editorFrozen
      || !workingCopyAuthoritative
      || !workingCopyDirty
      || !workingCopyDraftBlocks.length
      || editorStructureError
    ) return;
    setWorkingCopyActionBusy(true);
    setWorkingCopyMessage("");
    fetch(`/api/projects/${projectId}/medical-writing/working-copies/${selectedSection}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_id: documentSession?.document_id,
        expected_revision: workingCopyRevision,
        content_blocks: workingCopyDraftBlocks,
        actor: "medical_manager",
        idempotency_key: workingCopySaveKey || `wc-${projectId}-${selectedSection}-${Date.now()}`,
      }),
    })
      .then(async (response) => {
        if (response.ok) return response.json();
        const payload = await response.json().catch(() => ({}));
        const error = new Error(payload.detail || `HTTP ${response.status}`);
        error.status = response.status;
        error.detail = payload.detail;
        throw error;
      })
      .then((payload) => {
        setWorkingCopy(payload);
        setWorkingCopyDraftBlocks(cloneContentBlocks(payload.content_blocks));
        setWorkingCopyEditing(true);
        setWorkingCopyDirty(false);
        clearCurrentRecoveryDraft();
        setWorkingCopySaveKey(`wc-${projectId}-${selectedSection}-${Date.now()}`);
        setWorkingCopyMessage(`工作副本版本 ${payload.revision} 已保存；原始 DOCX 未被修改。`);
        refreshContentQuality();
        refreshFreezeReadiness();
      })
      .catch((error) => {
        persistCurrentRecoveryDraft();
        setWorkingCopyMessage(error.status === 409
          ? `保存被拒绝：${apiErrorText(error)}。工作副本未被覆盖；请重新加载当前版本后再修订。`
          : `工作副本保存失败：${apiErrorText(error)}`);
      })
      .finally(() => setWorkingCopyActionBusy(false));
  };
  const applyInterventionRulesToSection = (overwriteMedicalEdits = false) => {
    if (
      !interventionProjectionAvailable
      || interventionProjectionBusy
      || workingCopyActionBusy
      || workingCopyLoading
      || workingCopyDirty
      || editorFrozen
      || !workingCopyAuthoritative
      || !workingCopy
    ) return;
    setInterventionProjectionBusy(true);
    setWorkingCopyMessage("");
    if (!overwriteMedicalEdits) setInterventionProjectionConflict(null);
    let journeySnapshot;
    fetch(`/api/projects/${projectId}/medical-writing/authoring-journey`)
      .then(readJsonOrThrow)
      .then((payload) => {
        journeySnapshot = payload;
        setAuthoringJourneySnapshot(payload);
        if (!payload.intervention_rules_sha256) {
          throw new Error("请先在结构化设计中保存本章干预规则");
        }
        const idempotencyKey = [
          "intervention-projection",
          projectId,
          selectedSection,
          `j${payload.revision}`,
          `w${workingCopyRevision}`,
          payload.intervention_rules_sha256.slice(0, 16),
          overwriteMedicalEdits ? "overwrite" : "preserve",
        ].join("-").slice(0, 200);
        return fetch(
          `/api/projects/${projectId}/medical-writing/working-copies/${selectedSection}/intervention-rules-projection`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              expected_journey_revision: payload.revision,
              expected_intervention_rules_sha256: payload.intervention_rules_sha256,
              expected_working_copy_revision: workingCopyRevision,
              overwrite_medical_edits: overwriteMedicalEdits,
              actor: "medical_manager",
              reason: overwriteMedicalEdits
                ? "医学经理确认以最新结构化规则覆盖本章既有人工修订。"
                : "医学经理确认将最新结构化规则应用到当前方案章节。",
              idempotency_key: idempotencyKey,
            }),
          },
        ).then(readJsonOrThrow);
      })
      .then((payload) => {
        const nextWorkingCopy = payload.working_copy;
        setWorkingCopy(nextWorkingCopy);
        setWorkingCopyDraftBlocks(cloneContentBlocks(nextWorkingCopy.content_blocks));
        setWorkingCopyEditing(true);
        setWorkingCopyDirty(false);
        setWorkingCopySaveKey(`wc-${projectId}-${selectedSection}-${Date.now()}`);
        setInterventionProjectionConflict(null);
        setWorkingCopyMessage(
          `结构化规则已应用到本章正文，工作副本更新至版本 ${nextWorkingCopy.revision}。`,
        );
        refreshContentQuality();
        refreshFreezeReadiness();
        refreshStudyConsistency();
      })
      .catch((error) => {
        if (error?.status === 409 && /medical edits|医学修订|人工修订/i.test(apiErrorText(error))) {
          setInterventionProjectionConflict({
            message: "本章规则正文已有人工作文修订。继续会以最新结构化规则覆盖这些修订。",
            journeyRevision: journeySnapshot?.revision || null,
          });
          return;
        }
        setWorkingCopyMessage(
          error?.status === 409
            ? `规则未应用：版本或依据已变化，请重新加载后再试。${apiErrorText(error)}`
            : `规则应用失败：${apiErrorText(error)}`,
        );
      })
      .finally(() => setInterventionProjectionBusy(false));
  };
  const applyContentDisposition = (status) => {
    if (
      !selectedContentFinding
      || contentDispositionBusy
      || workingCopyDirty
      || contentDispositionReason.trim().length < 10
      || (status === "confirmed_source_text" && !contentDispositionAcknowledged)
    ) return;
    setContentDispositionBusy(true);
    setContentQualityMessage("");
    fetch(
      `/api/projects/${projectId}/medical-writing/content-quality/findings/${encodeURIComponent(selectedContentFinding.finding_id)}/disposition?section_id=${encodeURIComponent(selectedSection)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          status,
          reason: contentDispositionReason.trim(),
          actor: "medical_manager",
          expected_content_fingerprint: selectedContentFinding.content_fingerprint,
          expected_content_revision: selectedContentFinding.content_revision,
          expected_disposition_revision: selectedContentFinding.disposition_revision,
          idempotency_key: `content-quality-${projectId}-${selectedContentFinding.finding_id}-${Date.now()}`,
        }),
      },
    )
      .then(readJsonOrThrow)
      .then((payload) => {
        setSelectedContentFindingId(payload.finding_id);
        setContentDispositionReason("");
        setContentDispositionAcknowledged(false);
        const nextMessage = (
          status === "confirmed_source_text"
            ? "已记录医学确认并保留原警示；当前内容指纹下不再阻断正式 Word。"
            : status === "correction_required"
              ? "已标记为需要修正；在工作副本中消除该异常前继续阻断正式 Word。"
              : "已撤销当前处置；该项恢复为开放核查。"
        );
        return refreshContentQuality().then(() => setContentQualityMessage(nextMessage));
      })
      .catch((error) => setContentQualityMessage(
        error.status === 409
          ? `处置被拒绝：${apiErrorText(error)}。请刷新后重新核对当前原文。`
          : `源内容处置失败：${apiErrorText(error)}`,
      ))
      .finally(() => setContentDispositionBusy(false));
  };
  const insertTableTemplate = (templateId, options = null, duplicateIntent = null) => {
    if (
      isDemoWritingSession
      || workingCopyActionBusy
      || workingCopyDirty
      || workingCopyRevision < 1
      || editorFrozen
      || !workingCopyAuthoritative
      || !templateId
    ) return;
    setWorkingCopyActionBusy(true);
    setWorkingCopyMessage("");
    const query = new URLSearchParams({ actor: "medical_manager" });
    query.set(
      "idempotency_key",
      `table-insert-${projectId}-${selectedSection}-r${workingCopyRevision}-${templateId}`,
    );
    if (options) {
      query.set("title", String(options.title || "").trim());
      query.set("row_count", String(options.rowCount));
      query.set("column_count", String(options.columnCount));
      query.set("header_row_count", String(options.headerRowCount));
      query.set("orientation", String(options.orientation || "auto"));
      query.set("notes_area", String(Boolean(options.notesArea)));
    }
    if (duplicateIntent?.allowDuplicate) {
      query.set("allow_duplicate", "true");
      query.set("duplicate_reason", String(duplicateIntent.duplicateReason || "").trim());
    }
    fetch(
      `/api/projects/${projectId}/medical-writing/working-copies/${selectedSection}/table-templates/${encodeURIComponent(templateId)}/instantiate?${query.toString()}`,
      { method: "POST" },
    )
      .then(readJsonOrThrow)
      .then((payload) => {
        const nextWorkingCopy = payload.working_copy;
        setWorkingCopy(nextWorkingCopy);
        setWorkingCopyDraftBlocks(cloneContentBlocks(nextWorkingCopy.content_blocks));
        setWorkingCopyEditing(true);
        setWorkingCopyDirty(false);
        setWorkingCopySaveKey(`wc-${projectId}-${selectedSection}-${Date.now()}`);
        setInsertedTableBlockId(payload.table_block?.block_id || "");
        setWorkingCopyMessage(
          `${payload.table_block?.title || "结构化表格"}已插入工作副本版本 ${nextWorkingCopy.revision}，并保留模板来源。`,
        );
        refreshContentQuality();
        refreshFreezeReadiness();
      })
      .catch((error) => setWorkingCopyMessage(`表格插入失败：${apiErrorText(error)}`))
      .finally(() => setWorkingCopyActionBusy(false));
  };
  const updateDocumentExportProgress = (payload) => {
    const progress = payload?.progress || payload || {};
    const rawPercent = Number(progress.percent || 0);
    const percent = Math.max(
      0,
      Math.min(100, Math.round(rawPercent <= 1 ? rawPercent * 100 : rawPercent)),
    );
    setDocumentExportProgress({
      status: payload?.status || "running",
      phase: progress.phase || "queued",
      percent,
      step: Number(progress.step || 0),
      stepTotal: Number(progress.step_total || 5),
      message: progress.message || "正在准备 Word 导出",
    });
  };
  const documentExportStorageKey = `mw-document-export:${projectId}`;
  const clearStoredDocumentExport = (jobId) => {
    try {
      const stored = JSON.parse(localStorage.getItem(documentExportStorageKey) || "null");
      if (!jobId || stored?.job_id === jobId) {
        localStorage.removeItem(documentExportStorageKey);
      }
    } catch {
      localStorage.removeItem(documentExportStorageKey);
    }
  };
  const downloadDocumentExportArtifact = async (jobId, mode) => {
    const response = await fetch(
      `/api/projects/${projectId}/medical-writing/document-exports/${encodeURIComponent(jobId)}/download`,
    );
    const sourceReferenceStatus = response.headers.get("X-Medical-Writing-Source-Reference-Status");
    const userActionRequired = response.headers.get("X-Medical-Writing-User-Action-Required") === "true";
    const warningMessage = response.headers.get("X-Medical-Writing-Warning-Message");
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      const error = new Error(payload.detail || `HTTP ${response.status}`);
      error.status = response.status;
      throw error;
    }
    const blob = await response.blob();
    const filename = mode === "approved_final"
      ? `${documentSession?.protocol_id || "研究方案"}_${documentSession?.version || "当前版本"}_方案终稿.docx`
      : `${documentSession?.protocol_id || "研究方案"}_${documentSession?.version || "当前版本"}_草稿预览.docx`;
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(objectUrl);
    if (mode === "draft_preview" && userActionRequired && sourceReferenceStatus === "blocked") {
      setWorkingCopyMessage(
        `草稿已生成；${warningMessage || "请先处理原方案中的文献引用，再生成正式 Word。"}`,
      );
    } else {
      setWorkingCopyMessage(
        mode === "approved_final"
          ? "方案终稿 Word 已从各章节已确认快照生成。"
          : "草稿预览 Word 已按当前已保存工作副本与未编辑原文完整组装。",
      );
    }
  };
  const monitorDocumentExport = async (jobId, mode, runToken) => {
    const { status, error } = await pollDurableMwJob(
      projectId,
      jobId,
      {
        intervalMs: 750,
        maxLoops: 800,
        onUpdate: (payload) => {
          if (documentExportRunRef.current === runToken) {
            updateDocumentExportProgress(payload);
          }
        },
      },
    );
    if (documentExportRunRef.current !== runToken) return;
    if (status !== "completed") {
      throw new Error(error || `Word 导出任务未完成：${status}`);
    }
    await downloadDocumentExportArtifact(jobId, mode);
    clearStoredDocumentExport(jobId);
    setDocumentExportProgress(null);
  };
  const fullDraftStorageKey = `mw-full-draft:${projectId}`;
  const monitorFullDraft = async (jobId, runToken) => {
    const { status, error } = await pollDurableMwJob(
      projectId,
      jobId,
      {
        intervalMs: 900,
        maxLoops: 1200,
        onUpdate: (payload) => {
          if (fullDraftRunRef.current === runToken) setFullDraftJob(payload);
        },
      },
    );
    if (fullDraftRunRef.current !== runToken) return;
    if (status !== "completed") {
      throw new Error(error || `全文初稿任务未完成：${status}`);
    }
    const response = await fetch(
      `/api/projects/${projectId}/medical-writing/full-drafts/${encodeURIComponent(jobId)}/result`,
    );
    const payload = await readJsonOrThrow(response);
    if (fullDraftRunRef.current !== runToken) return;
    setFullDraftJob((current) => ({ ...(current || {}), job_id: jobId, status: "completed" }));
    setFullDraftArtifact(payload.artifact || null);
    setFullDraftMessage(
      `全文初稿已生成 ${payload.artifact?.coverage?.generated_count || 0}/${payload.artifact?.coverage?.target_count || 0} 个章节候选，请整体审核后采纳。`,
    );
    localStorage.removeItem(fullDraftStorageKey);
  };
  const startFullDraft = () => {
    if (
      isDemoWritingSession
      || !editorSessionAvailable
      || fullDraftBusy
      || workingCopyDirty
      || editorFrozen
      || !workingCopyAuthoritative
    ) return;
    const runToken = fullDraftRunRef.current + 1;
    fullDraftRunRef.current = runToken;
    setFullDraftBusy(true);
    setFullDraftArtifact(null);
    setFullDraftMessage("正在创建全文初稿任务；AI会先生成候选，不会自动改写正文。");
    fetch(`/api/projects/${projectId}/medical-writing/full-drafts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ actor: "medical_manager" }),
    })
      .then(readJsonOrThrow)
      .then((payload) => {
        if (fullDraftRunRef.current !== runToken) return null;
        setFullDraftJob(payload);
        localStorage.setItem(
          fullDraftStorageKey,
          JSON.stringify({ project_id: projectId, job_id: payload.job_id }),
        );
        return monitorFullDraft(payload.job_id, runToken);
      })
      .catch((error) => {
        if (fullDraftRunRef.current !== runToken) return;
        setFullDraftMessage(`全文初稿生成失败：${apiErrorText(error)}`);
        localStorage.removeItem(fullDraftStorageKey);
      })
      .finally(() => {
        if (fullDraftRunRef.current === runToken) setFullDraftBusy(false);
      });
  };
  const adoptFullDraft = () => {
    const jobId = fullDraftJob?.job_id;
    if (!jobId || !fullDraftArtifact || fullDraftBusy || workingCopyDirty || editorFrozen) return;
    setFullDraftBusy(true);
    setFullDraftMessage("正在按章节版本逐项写入全文初稿；任一版本冲突都会停止并保留已审计结果。");
    fetch(`/api/projects/${projectId}/medical-writing/full-drafts/${encodeURIComponent(jobId)}/adopt`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ actor: "medical_manager" }),
    })
      .then(readJsonOrThrow)
      .then(async (payload) => {
        setFullDraftMessage(
          `全文初稿已写入 ${payload.adopted_count || 0} 个章节（重放 ${payload.replayed_count || 0} 个），请继续逐章审阅后再冻结。`,
        );
        setWorkingCopyReloadNonce((value) => value + 1);
        await refreshDocumentSession();
        await refreshGreenfieldState();
        await refreshFreezeReadiness();
        await refreshContentQuality();
      })
      .catch((error) => setFullDraftMessage(`全文初稿采纳失败：${apiErrorText(error)}`))
      .finally(() => setFullDraftBusy(false));
  };
  useEffect(() => {
    if (!projectId || isDemoWritingSession) return undefined;
    let stored = null;
    try {
      stored = JSON.parse(localStorage.getItem(fullDraftStorageKey) || "null");
    } catch {
      localStorage.removeItem(fullDraftStorageKey);
    }
    if (!stored?.job_id || stored.project_id !== projectId) return undefined;
    const runToken = fullDraftRunRef.current + 1;
    fullDraftRunRef.current = runToken;
    setFullDraftBusy(true);
    setFullDraftMessage("正在恢复全文初稿任务状态。");
    monitorFullDraft(stored.job_id, runToken)
      .catch((error) => {
        if (fullDraftRunRef.current === runToken) {
          setFullDraftMessage(`全文初稿恢复失败：${apiErrorText(error)}`);
          localStorage.removeItem(fullDraftStorageKey);
        }
      })
      .finally(() => {
        if (fullDraftRunRef.current === runToken) setFullDraftBusy(false);
      });
    return () => {
      if (fullDraftRunRef.current === runToken) fullDraftRunRef.current += 1;
    };
  }, [projectId, isDemoWritingSession]);
  useEffect(() => {
    if (!projectId || isDemoWritingSession) return undefined;
    let stored = null;
    try {
      stored = JSON.parse(localStorage.getItem(documentExportStorageKey) || "null");
    } catch {
      localStorage.removeItem(documentExportStorageKey);
    }
    if (!stored?.job_id || stored.project_id !== projectId) return undefined;
    const runToken = documentExportRunRef.current + 1;
    documentExportRunRef.current = runToken;
    const mode = stored.mode || "draft_preview";
    setDocumentExportBusy(mode);
    updateDocumentExportProgress({
      status: "queued",
      progress: {
        phase: "resuming",
        percent: 0,
        step: 0,
        step_total: 5,
        message: "正在恢复 Word 导出任务",
      },
    });
    monitorDocumentExport(stored.job_id, mode, runToken)
      .catch((error) => {
        if (documentExportRunRef.current !== runToken) return;
        setWorkingCopyMessage(`Word 导出失败：${medicalWritingExportErrorText(error)}`);
        clearStoredDocumentExport(stored.job_id);
        setDocumentExportProgress(null);
      })
      .finally(() => {
        if (documentExportRunRef.current === runToken) {
          setDocumentExportBusy("");
        }
      });
    return () => {
      if (documentExportRunRef.current === runToken) {
        documentExportRunRef.current += 1;
      }
    };
  }, [projectId, isDemoWritingSession]);
  const exportMedicalWritingDocument = (mode) => {
    if (
      isDemoWritingSession
      || documentExportBusy
      || workingCopyDirty
      || (mode === "approved_final" && (!allRequiredSectionsFrozen || studyConsistencyBlocksFinal))
    ) return;
    setDocumentExportBusy(mode);
    setWorkingCopyMessage("");
    updateDocumentExportProgress({
      status: "queued",
      progress: {
        phase: "queued",
        percent: 0,
        step: 0,
        step_total: 5,
        message: "正在创建 Word 导出任务",
      },
    });
    const runToken = documentExportRunRef.current + 1;
    documentExportRunRef.current = runToken;
    fetch(
      `/api/projects/${projectId}/medical-writing/document-exports`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode,
          actor: "medical_manager",
          idempotency_key: `document-export-${projectId}-${mode}-${Date.now()}`,
        }),
      },
    )
      .then(readJsonOrThrow)
      .then((payload) => {
        if (documentExportRunRef.current !== runToken) return null;
        localStorage.setItem(
          documentExportStorageKey,
          JSON.stringify({
            project_id: projectId,
            job_id: payload.job_id,
            mode,
            started_at: new Date().toISOString(),
          }),
        );
        return monitorDocumentExport(payload.job_id, mode, runToken);
      })
      .catch((error) => {
        if (documentExportRunRef.current !== runToken) return;
        clearStoredDocumentExport();
        setDocumentExportProgress(null);
        setWorkingCopyMessage(`Word 导出失败：${medicalWritingExportErrorText(error)}`);
      })
      .finally(() => {
        if (documentExportRunRef.current === runToken) {
          setDocumentExportBusy("");
      }
    });
  };
  const loadDocumentPreview = () => {
    if (
      isDemoWritingSession
      || !editorSessionAvailable
      || documentPreviewBusy
      || workingCopyDirty
    ) return;
    const requestId = documentPreviewRequestRef.current + 1;
    documentPreviewRequestRef.current = requestId;
    setDocumentPreviewBusy(true);
    setDocumentPreviewMessage("");
    fetch(`/api/projects/${projectId}/medical-writing/document-preview?mode=draft_preview`)
      .then(readJsonOrThrow)
      .then((payload) => {
        if (documentPreviewRequestRef.current !== requestId) return;
        setDocumentPreview(payload);
      })
      .catch((error) => {
        if (documentPreviewRequestRef.current !== requestId) return;
        setDocumentPreviewMessage(`版式状态读取失败：${apiErrorText(error)}`);
      })
      .finally(() => {
        if (documentPreviewRequestRef.current === requestId) setDocumentPreviewBusy(false);
      });
  };
  const selectedFreezeGap = (freezeReadiness?.gaps || []).find(
    (gap) => gap.section_id === selectedSection,
  );
  const freezeHardBlocked = Boolean(
    selectedFreezeGap
    && !["section_not_frozen", "freeze_invalidated"].includes(selectedFreezeGap.reason_code),
  );
  const freezeBlockedReason = isDemoWritingSession
    ? "演示项目不写入作者冻结记录"
    : !editorSessionAvailable
      ? "真实方案文档会话未就绪"
      : workingCopyRevision < 1
        ? "请先创建并保存当前工作副本"
        : workingCopyDirty
          ? "存在未保存修订，请先保存"
          : !workingCopyAuthoritative
            ? workingCopy?.quarantine_reason || "当前历史版本已隔离，请先确认绑定或恢复权威基线"
            : section.applicabilityStatus === "not_applicable" && section.applicabilityRenderAction === "omit"
              ? "当前章节已确认为不适用并从终稿集合省略，无需冻结"
            : workingCopy?.study_definition_reconciliation_required || selectedSectionConsistencyBlocked
              ? workingCopy?.study_definition_reconciliation_reason || studyConsistency?.message || "请先完成当前章节的研究设计调和"
              : freezeReadinessError
                ? freezeReadinessError
                : !freezeReadiness
                  ? "冻结准备状态尚未读取"
                  : freezeHardBlocked
                    ? selectedFreezeGap.message || freezeGapLabel(selectedFreezeGap.reason_code)
                    : workingCopyActionBusy
                      ? "正在处理当前版本，请稍候"
                      : "";
  const canFreezeCurrentVersion = !editorFrozen && !freezeBlockedReason;
  const canUnfreezeCurrentVersion = editorFrozen
    && !workingCopyDirty
    && workingCopyAuthoritative
    && !workingCopyActionBusy;
  const submitWorkingCopyFreeze = (operation) => {
    if (
      isDemoWritingSession
      || workingCopyActionBusy
      || workingCopyRevision < 1
      || workingCopyDirty
      || !workingCopyAuthoritative
      || (operation === "freeze" ? !canFreezeCurrentVersion : !canUnfreezeCurrentVersion)
    ) return;
    setWorkingCopyActionBusy(true);
    setWorkingCopyMessage("");
    const endpoint = operation === "freeze" ? "freeze-current-version" : "unfreeze";
    const reason = operation === "freeze"
      ? "医学作者确认当前章节的当前保存版本已定稿。"
      : "医学作者解除当前章节冻结以继续编辑。";
    fetch(`/api/projects/${projectId}/medical-writing/working-copies/${selectedSection}/${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_id: documentSession?.document_id,
        expected_working_copy_revision: workingCopyRevision,
        expected_study_definition_id: workingCopy?.source_study_definition_id || "",
        expected_study_definition_revision: workingCopy?.source_study_definition_revision || null,
        expected_study_definition_sha256: workingCopy?.source_study_definition_sha256 || "",
        reason,
        actor: "medical_manager",
        idempotency_key: `${operation}-${projectId}-${selectedSection}-r${workingCopyRevision}-${Date.now()}`.slice(0, 200),
      }),
    })
      .then(readJsonOrThrow)
      .then(async (payload) => {
        const nextWorkingCopy = payload.working_copy;
        setWorkingCopy(nextWorkingCopy);
        setWorkingCopyDraftBlocks(cloneContentBlocks(nextWorkingCopy.content_blocks));
        setWorkingCopyEditing(nextWorkingCopy.revision >= 1);
        setWorkingCopyDirty(false);
        clearCurrentRecoveryDraft();
        setWorkingCopySaveKey(`wc-${projectId}-${selectedSection}-${Date.now()}`);
        await refreshFreezeReadiness();
        if (activeWritingRailTab === "版本") await refreshVersionHistory();
        await refreshDashboard?.();
        setWorkingCopyMessage(operation === "freeze"
          ? `当前作者确认版本 ${nextWorkingCopy.revision} 已冻结；需继续编辑时可先解除冻结。`
          : `版本 ${nextWorkingCopy.revision} 已解除冻结，可继续编辑；原冻结记录已保留。`);
      })
      .catch((error) => setWorkingCopyMessage(
        `${operation === "freeze" ? "冻结" : "解除冻结"}失败：${apiErrorText(error)}`,
      ))
      .finally(() => setWorkingCopyActionBusy(false));
  };
  const recoverWorkingCopyBinding = (operation) => {
    if (
      workingCopyActionBusy
      || workingCopyAuthoritative
      || !quarantinedWorkingCopy
      || bindingRecoveryReason.trim().length < 10
      || !bindingRecoveryAcknowledged
    ) return;
    setWorkingCopyActionBusy(true);
    setVersionHistoryMessage("");
    const endpoint = operation === "accept" ? "accept-and-bind" : "revert-authoritative-baseline";
    fetch(`/api/projects/${projectId}/medical-writing/working-copies/${selectedSection}/${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_id: documentSession?.document_id,
        expected_working_copy_revision: workingCopyRevision,
        reason: bindingRecoveryReason.trim(),
        acknowledge_binding: true,
        actor: "medical_manager",
        idempotency_key: `${operation}-binding-${projectId}-${selectedSection}-r${workingCopyRevision}-${Date.now()}`.slice(0, 200),
      }),
    })
      .then(readJsonOrThrow)
      .then(async (payload) => {
        const nextWorkingCopy = payload.working_copy;
        setWorkingCopy(nextWorkingCopy);
        setWorkingCopyDraftBlocks(cloneContentBlocks(nextWorkingCopy.content_blocks));
        setWorkingCopyEditing(nextWorkingCopy.revision >= 1);
        setWorkingCopyDirty(false);
        clearCurrentRecoveryDraft();
        setBindingRecoveryReason("");
        setBindingRecoveryAcknowledged(false);
        setWorkingCopySaveKey(`wc-${projectId}-${selectedSection}-${Date.now()}`);
        await refreshFreezeReadiness();
        await refreshVersionHistory();
        setWorkingCopyMessage(operation === "accept"
          ? `已由医学作者确认隔离内容并绑定当前研究定义，工作副本更新至版本 ${nextWorkingCopy.revision}。`
          : `已恢复权威源基线，工作副本更新至版本 ${nextWorkingCopy.revision}；隔离内容仍保留在历史中。`);
      })
      .catch((error) => setVersionHistoryMessage(`版本恢复失败：${apiErrorText(error)}`))
      .finally(() => setWorkingCopyActionBusy(false));
  };
  const sectionThreads = sectionHasBackendBinding ? revisionThreads.filter((thread) => thread.section_id === backendSectionId) : [];
  const activeThread = sectionHasBackendBinding
    ? sectionThreads.find((thread) => thread.thread_id === activeRevisionThreadId)
      || [...sectionThreads].reverse().find((thread) => ["candidate_ready", "pending_medical_approval", "author_selected", "accepted_pending_medical_approval"].includes(thread.status))
      || sectionThreads[sectionThreads.length - 1]
    : null;
  const sectionCandidateVersions = latestRevisionRoundSuggestions(activeThread)
    .filter((suggestion) => String(suggestion.proposal_text || "").trim());
  const activeSuggestion = sectionCandidateVersions.find((item) => item.suggestion_id === selectedRevisionSuggestionId)
    || sectionCandidateVersions.find((item) => item.user_decision === "accepted")
    || sectionCandidateVersions[0]
    || null;
  const activeRevisionIntent = activeThread?.intent || revisionIntent;
  const revisionRewritePlaceholder = revisionFollowupPlaceholders[activeRevisionIntent]
    || "具体说明需要保留、删除或改正的内容；不要只写“优化一下”。";
  useEffect(() => {
    const firstCurrentSuggestionId = sectionCandidateVersions[0]?.suggestion_id || "";
    if (!firstCurrentSuggestionId) {
      if (selectedRevisionSuggestionId) setSelectedRevisionSuggestionId("");
      return;
    }
    if (!sectionCandidateVersions.some((item) => item.suggestion_id === selectedRevisionSuggestionId)) {
      setSelectedRevisionSuggestionId(firstCurrentSuggestionId);
    }
  }, [
    activeThread?.thread_id,
    sectionCandidateVersions.map((item) => item.suggestion_id).join("|"),
  ]);
  useEffect(() => {
    setRevisionActionComment("");
    setRevisionRewriteInstruction("");
  }, [activeThread?.thread_id, activeSuggestion?.suggestion_id]);
  const activeRevisionApplied = Boolean(activeThread && (workingCopy?.applied_revision_thread_ids || []).includes(activeThread.thread_id));
  const unresolvedAiCandidateCount = revisionThreads.filter((thread) => (
    ["candidate_ready", "pending_medical_approval", "author_selected", "accepted_pending_medical_approval"].includes(thread.status)
    && !(workingCopy?.applied_revision_thread_ids || []).includes(thread.thread_id)
  )).length;
  const canApplyApprovedRevision = !isDemoWritingSession
    && isRevisionThreadSelectedByAuthor(activeThread?.status)
    && activeSuggestion?.user_decision === "accepted"
    && !activeRevisionApplied
    && !workingCopyDirty
    && !editorFrozen
    && workingCopyAuthoritative
    && !workingCopyActionBusy;
  const canSelectAndApplyRevision = !isDemoWritingSession
    && Boolean(workingCopy?.working_copy_id)
    && !workingCopyDirty
    && !editorFrozen
    && workingCopyAuthoritative
    && !workingCopyActionBusy;
  const protectedTokenAdoptionBlocked = (candidate) => candidate?.protected_token_status === "violated";
  const canSelectAndApplyActiveRevision = canSelectAndApplyRevision
    && !protectedTokenAdoptionBlocked(activeSuggestion);
  const revisionBoundary = "AI输出为可追溯候选。医学作者点击“选用并写入”即形成医学决定，不再重复设置同角色批准步骤；原子写入若因受保护标识、版本或绑定核验失败，选用与写入均不生效，候选保持待处置并显示错误。定稿时再确认并冻结当前版本。";
  const handleRevisionIntentChange = (intent) => {
    const nextIntent = revisionIntentOptions.find((item) => item.value === intent);
    if (!nextIntent) return;
    setRevisionIntent(nextIntent.value);
    setRevisionInstruction(nextIntent.defaultInstruction);
  };
  const queueCitationInsertion = (reference) => {
    if (!realWorkingCopyEditable || editorFrozen) {
      const message = workingCopyAuthoritative
        ? "请先创建可编辑工作副本，并确保当前作者版本未冻结。"
        : "当前历史内容已隔离，请先确认绑定或恢复权威基线。";
      setCitationInsertionMessage(message);
      return message;
    }
    const insertion = {
      id: globalThis.crypto?.randomUUID?.() || `citation-${Date.now()}`,
      referenceId: reference.reference_id,
      title: reference.title,
    };
    setCitationInsertion(insertion);
    const message = "正在插入当前光标位置；引文编号将按正文首次出现顺序更新。";
    setCitationInsertionMessage(message);
    return message;
  };
  const writingRailTabs = ["AI", "证据", "文献", "风险", "审阅", "版本"];
  const enabledWritingRailTabs = isGreenfieldSession
    ? ["AI", "证据", "文献", "审阅", "版本"]
    : ["AI", "证据", "文献", "版本"];
  const studyConsistencyNeedsAction = !isStudySchemaSection
    && Boolean(studyConsistency?.status)
    && !["current", "unbound_legacy"].includes(studyConsistency.status);
  const freezeReadinessNeedsAction = !isStudySchemaSection
    && authoringJourneyAvailable
    && editorSessionAvailable
    && !workingCopyLoading
    && !editorFrozen
    && Boolean(freezeBlockedReason);
  const editorBlocker = studyConsistencyNeedsAction
    ? {
        message: studyConsistency.status === "reconciliation_required" && selectedSectionNeedsReconciliation
          ? "研究设计已更新，当前章节需完成调和后再冻结或正式导出。"
          : "研究设计已更新，当前文档需重绑定后再冻结或正式导出。",
        actionLabel: studyConsistency.status === "reconciliation_required" && selectedSectionNeedsReconciliation
          ? "完成本章调和"
          : studyConsistency.status === "reconciliation_required"
            ? "查看待调和章节"
            : "查看影响并重绑定",
        onAction: openStudyRebind,
      }
    : freezeReadinessNeedsAction
      ? {
          message: conciseEditorBlockerReason(freezeBlockedReason),
          actionLabel: !workingCopyAuthoritative
            ? "查看版本恢复"
            : (!freezeReadiness || freezeReadinessError)
              ? "重试准备检查"
              : "查看版本状态",
          onAction: () => {
            if (!workingCopyAuthoritative || (freezeReadiness && !freezeReadinessError)) {
              setActiveWritingRailTab("版本");
              return;
            }
            refreshFreezeReadiness();
          },
        }
      : null;
  const editorBlockerDetails = [...new Set([
    freezeBlockedReason,
    studyConsistency?.message,
    workingCopy?.quarantine_reason,
  ].filter(Boolean))];
  return (
    <main className="page writing-page">
      <SectionTitle
        eyebrow="医学写作"
        title={greenfieldSetupAvailable ? "研究方案智能设计与写作" : "研究方案文档编辑与AI修订"}
        action={greenfieldSetupAvailable ? null : (
          <div className="writing-title-actions">
            {authoringJourneyAvailable && <button type="button" onClick={() => openStudyDesign()} title="查看当前文档所依据的研究框架、PICOS与语料状态"><ListChecks size={15} /> 研究设计</button>}
            {structuredDesignTriggerAvailable && (
              <button
                type="button"
                className="writing-structured-design-trigger"
                disabled={workingCopyLoading || !sectionContentAvailable}
                title={workingCopyLoading || !sectionContentAvailable
                  ? "正在读取当前章节与工作副本"
                  : `直接打开与“${section.title}”关联的${structuredDesignTarget.label}编辑器`}
                onClick={() => (
                  structuredDesignTarget.kind === "table"
                    ? openSectionSoaEntry()
                    : structuredDesignTarget.kind === "document_object"
                      ? openSectionDocumentObjectEntry()
                      : openStudyDesign(structuredDesignTarget)
                )}
              >
                <PencilLine size={15} /> {structuredDesignTarget.buttonLabel}
              </button>
            )}
            {interventionProjectionAvailable && (
              <button
                type="button"
                className="writing-intervention-project-trigger"
                onClick={() => applyInterventionRulesToSection(false)}
                disabled={interventionProjectionBusy || workingCopyActionBusy || workingCopyLoading || workingCopyDirty || editorFrozen || !workingCopyAuthoritative}
                title={workingCopyDirty
                  ? "存在未保存的正文修订，请先保存后再应用结构化规则"
                  : !workingCopyAuthoritative
                    ? "当前历史工作版本已隔离"
                  : editorFrozen
                    ? "当前作者确认版本已冻结，请先解除冻结"
                    : "将已提交的结构化干预规则生成可继续编辑的本章正文"}
              >
                <FileCheck2 size={15} /> {interventionProjectionBusy ? "应用中" : "应用规则到正文"}
              </button>
            )}
            {isLegacyGreenfieldTemplate && (
              <button
                type="button"
                onClick={() => setTemplateUpgradeOpen(true)}
                disabled={templateUpgradeLoading || !templateUpgradePreview?.can_apply}
                title={templateUpgradeLoading ? "正在核对旧章节与当前模板" : templateUpgradePreview?.can_apply ? "预览旧章节到当前中文M11模板的映射，不会立即修改文档" : templateUpgradeMessage || "当前模板升级不可用"}
              >
                <RefreshCw size={15} /> {templateUpgradeLoading ? "核对模板" : "升级模板"}
              </button>
            )}
            <button
              type="button"
              onClick={() => setActiveWritingRailTab("AI")}
              disabled={aiRevisionDisabled}
              title={aiRevisionUnavailableReason || "打开AI修订面板"}
              aria-describedby={paragraphLoadPending ? "writing-ai-unavailable-reason" : undefined}
            >
              <Sparkles size={15} /> AI修订
            </button>
            {isGreenfieldSession && (
              <button
                type="button"
                className="primary-button"
                onClick={() => {
                  setActiveWritingRailTab("AI");
                  startFullDraft();
                }}
                disabled={
                  fullDraftBusy
                  || workingCopyDirty
                  || editorFrozen
                  || !workingCopyAuthoritative
                  || !editorSessionAvailable
                }
                title={workingCopyDirty
                  ? "请先保存当前手工修订"
                  : editorFrozen
                    ? "当前版本已冻结，请先解除冻结"
                    : "由独立AI按章节生成完整研究方案正文候选，待整体审核后写入"}
              >
                <Sparkles size={15} /> {fullDraftBusy ? "全文生成中" : "生成全文初稿"}
              </button>
            )}
            <button type="button" onClick={() => setDocumentMapOpen(true)} title="打开研究方案目录">
              <BookOpenText size={16} /> 目录
            </button>
            <button
              className={editorFrozen ? "writing-complete-button" : "primary-button"}
              title={editorFrozen
                ? (canUnfreezeCurrentVersion ? "解除当前版本冻结并保留历史记录" : "当前版本暂不可解除冻结")
                : freezeBlockedReason || "由当前医学作者确认并冻结已保存版本"}
              aria-label={editorFrozen
                ? (canUnfreezeCurrentVersion ? "解除当前版本冻结" : "解除冻结暂不可用：当前版本尚未满足解除条件")
                : (canFreezeCurrentVersion ? "确认并冻结当前版本" : `确认并冻结暂不可用：${freezeBlockedReason || "当前版本尚未满足冻结条件"}`)}
              disabled={editorFrozen ? !canUnfreezeCurrentVersion : !canFreezeCurrentVersion}
              onClick={() => submitWorkingCopyFreeze(editorFrozen ? "unfreeze" : "freeze")}
            >
              <FileCheck2 size={15} /> {workingCopyActionBusy ? "处理中" : editorFrozen ? "解除冻结" : "确认并冻结"}
            </button>
          </div>
        )}
      />
      {!isDemoWritingSession && editorSessionAvailable && !authoringJourneyAvailable && (
        <LegacyAuthoringBootstrapPanel
          projectId={projectId}
          expectedIndication={projectHeader?.indication || ""}
          onConfirmed={() => refreshStudyConsistency()}
          onOpenBinding={openStudyRebind}
        />
      )}
      {templateUpgradeAppliedResult && (
        <div className="writing-template-upgrade-result" role="status">
          <span>已升级至当前中文M11模板，旧文档历史仍完整保留。开始保存新工作副本后将不再允许直接恢复。</span>
          <button type="button" onClick={rollbackTemplateUpgrade} disabled={templateUpgradeBusy} title="仅在升级后尚未保存任何新工作副本时可恢复">
            <RotateCcw size={14} /> {templateUpgradeBusy ? "处理中" : "恢复升级前版本"}
          </button>
        </div>
      )}
      <div className={`writing-layout writing-editor-first-layout ${greenfieldSetupAvailable ? "writing-pre-document-layout" : ""} ${isStudySchemaSection ? "writing-study-schema-layout" : ""}`}>
        <section className={`panel editor-panel writing-editor-core ${greenfieldSetupAvailable ? "writing-pre-document-core" : ""}`}>
          {!isStudySchemaSection && !isDemoWritingSession && editorSessionAvailable && (
            <div className="working-copy-status-bar">
              <div className="working-copy-status-main">
                <div className="working-copy-identity">
                  <span>文档工作副本</span>
                  <strong className="working-copy-revision">
                    {workingCopyLoading ? "版本读取中" : workingCopyRevision >= 1 ? `版本 ${workingCopyRevision}` : "尚未保存版本"}
                  </strong>
                </div>
                <Tag tone={workingCopyFreezeTone(workingCopy)}>{workingCopyFreezeLabel(workingCopy)}</Tag>
                <strong className="working-copy-save-state">{workingCopyDirty ? "有未保存修订" : workingCopyRevision >= 1 ? "已保存" : isGreenfieldSession ? "绿地候选基线" : "原始方案只读来源"}</strong>
                <time title={workingCopy?.updated_at ? `最近更新：${new Date(workingCopy.updated_at).toLocaleString("zh-CN", { hour12: false })}` : "未生成工作副本"}>
                  {workingCopy?.updated_at ? new Date(workingCopy.updated_at).toLocaleDateString("zh-CN") : "未生成"}
                </time>
              </div>
              <div className="working-copy-actions">
                {isGreenfieldSession && (
                  <button onClick={() => setActiveWritingRailTab("审阅")} title="打开项目决策与动态章节审阅">
                    <ListChecks size={14} /> 待审核 {greenfieldState?.approval_blocker_count || 0} 项
                  </button>
                )}
                {workingCopyRevision < 1 && !workingCopyEditing && (
                  <button
                    onClick={createWorkingCopy}
                    disabled={workingCopyLoading || !sectionContentAvailable || !workingCopyAuthoritative || editorFrozen}
                    title={!workingCopyAuthoritative
                      ? "当前历史内容已隔离，请先在版本面板处置"
                      : isGreenfieldSession
                        ? "从当前绿地候选章节创建版本化工作副本"
                        : "从当前原始方案章节创建本地工作副本"}
                  >
                    <PencilLine size={14} /> 创建工作副本
                  </button>
                )}
                {(workingCopyEditing || workingCopyRevision >= 1) && (
                  <button
                    className="primary-button"
                    onClick={saveWorkingCopy}
                    disabled={workingCopyActionBusy || !workingCopyDirty || editorFrozen || !workingCopyAuthoritative || Boolean(editorStructureError)}
                    title={editorStructureError
                      ? "段落结构发生变化，必须重新加载后再保存"
                      : !workingCopyAuthoritative
                        ? "当前历史工作版本已隔离"
                      : editorFrozen
                        ? "请先解除当前作者确认版本的冻结"
                      : !workingCopyDirty
                        ? "当前没有未保存修订"
                        : "保存完整来源关联工作副本"}
                  >
                    <FileCheck2 size={14} /> {workingCopyActionBusy ? "保存中" : "保存工作副本"}
                  </button>
                )}
                <button
                  onClick={requestWorkingCopyReload}
                  disabled={workingCopyLoading || workingCopyActionBusy}
                  title={workingCopyDirty ? "将先确认如何处理未保存修订" : "重新加载服务器版本"}
                >
                  <History size={14} /> 重新加载
                </button>
                <button
                  type="button"
                  onClick={() => setActiveWritingRailTab("版本")}
                  title="查看冻结历史、隔离历史与版本恢复"
                >
                  <History size={14} /> 版本与恢复
                </button>
                <button
                  type="button"
                  className={`content-quality-trigger ${contentQualityBlockingCount ? "has-blocking" : "is-clear"}`}
                  onClick={() => setContentQualityDockOpen(true)}
                  disabled={contentQualityLoading || !selectedSection}
                  title={contentQualityLoading
                    ? "正在读取当前章节源内容核查"
                    : contentQualityBlockingCount
                      ? `当前章节有 ${contentQualityBlockingCount} 项待医学处置或需要修正`
                      : contentQualityConfirmedCount
                        ? `当前章节 ${contentQualityConfirmedCount} 项警示已由医学确认沿用`
                        : "查看当前章节源内容核查"}
                >
                  {contentQualityBlockingCount ? <ShieldAlert size={14} /> : <CheckCircle2 size={14} />}
                  内容核查 {contentQualityLoading ? "…" : contentQuality?.finding_count ?? 0}
                </button>
                <button
                  type="button"
                  onClick={() => exportMedicalWritingDocument("draft_preview")}
                  disabled={Boolean(documentExportBusy) || workingCopyDirty}
                  title={workingCopyDirty ? "存在未保存修订，请先保存后再生成草稿预览" : "生成含全部正文与真实表格的草稿预览 Word"}
                >
                  <Download size={14} /> {documentExportBusy === "draft_preview" ? "生成中" : "预览 Word"}
                </button>
                <button
                  type="button"
                  className={documentPreview?.page_count_basis === "microsoft_word_receipt" ? "content-quality-trigger is-clear" : ""}
                  onClick={loadDocumentPreview}
                  disabled={documentPreviewBusy || workingCopyDirty}
                  title={workingCopyDirty ? "存在未保存修订，请先保存后读取当前快照版式" : "读取当前快照的快速分页估算；它不等同于Word最终页数"}
                >
                  <BookOpenText size={14} /> {documentPreviewBusy ? "读取中" : documentPreview ? "刷新版式" : "版式估算"}
                </button>
                <button
                  type="button"
                  onClick={() => exportMedicalWritingDocument("approved_final")}
                  disabled={Boolean(documentExportBusy) || workingCopyDirty || !allRequiredSectionsFrozen || studyConsistencyBlocksFinal}
                  title={studyConsistencyBlocksFinal
                    ? studyConsistency?.message || "研究设计与正文尚未完成一致性闭环"
                    : freezeReadinessError
                      ? freezeReadinessError
                    : !allRequiredSectionsFrozen
                      ? `仍有 ${remainingFreezeSectionCount ?? "-"} 个章节未形成当前作者确认冻结版本`
                    : "从各章节不可变作者冻结快照生成正式 Word"}
                >
                  <FileCheck2 size={14} /> {documentExportBusy === "approved_final" ? "生成中" : "正式 Word"}
                </button>
              </div>
              {documentExportProgress && (
                <div className="document-export-progress" role="status" aria-live="polite">
                  <div
                    className="document-export-progress-track"
                    role="progressbar"
                    aria-label="Word 导出进度"
                    aria-valuemin="0"
                    aria-valuemax="100"
                    aria-valuenow={documentExportProgress.percent}
                  >
                    <span style={{ width: `${documentExportProgress.percent}%` }} />
                  </div>
                  <strong>{documentExportProgress.message}</strong>
                  <span>
                    {documentExportProgress.step}/{documentExportProgress.stepTotal}
                    {" · "}
                    {documentExportProgress.percent}%
                  </span>
                </div>
              )}
            </div>
          )}
          {documentPreview && (
            <MedicalWritingPreviewPanel
              preview={documentPreview}
              busy={documentPreviewBusy}
              message={documentPreviewMessage}
              onRefresh={loadDocumentPreview}
              onClose={() => {
                setDocumentPreview(null);
                setDocumentPreviewMessage("");
              }}
            />
          )}
          {editorBlocker && (
            <div className="writing-editor-blocker" role="status">
              <ShieldAlert size={15} />
              <strong>{editorBlocker.message}</strong>
              {editorBlockerDetails.length > 0 && (
                <details>
                  <summary>详情</summary>
                  {editorBlockerDetails.map((detail) => <p key={detail}>{detail}</p>)}
                </details>
              )}
              <button type="button" onClick={editorBlocker.onAction}>{editorBlocker.actionLabel}</button>
            </div>
          )}
          {!isStudySchemaSection && showDraftingReadiness && (
            <div className="writing-drafting-readiness" role="status">
              <Sparkles size={16} />
              <div>
                <strong>本章尚无可审阅正文，系统应先生成候选</strong>
                <span>{section.draftingBlockerReason}</span>
                {section.draftingMissingInputs.length > 0 && (
                  <details>
                    <summary>查看仍缺少的依据</summary>
                    <ul>
                      {section.draftingMissingInputs.map((item) => (
                        <li key={item}>{medicalWritingFactLabel(item)}</li>
                      ))}
                    </ul>
                  </details>
                )}
                {section.draftingResolutionActions.length > 0 && (
                  <details>
                    <summary>系统将如何处理</summary>
                    <ul>
                      {section.draftingResolutionActions.map((item) => <li key={item}>{item}</li>)}
                    </ul>
                  </details>
                )}
              </div>
              <button
                type="button"
                onClick={() => {
                  setActiveWritingRailTab("AI");
                  submitRevisionRequest();
                }}
                disabled={aiRevisionDisabled}
                title={aiRevisionUnavailableReason || "由AI基于已绑定资料和已确认研究事实先生成本章候选"}
              >
                AI 先起草
              </button>
            </div>
          )}
          {!isStudySchemaSection && interventionProjectionConflict && (
            <div className="writing-intervention-projection-conflict" role="alert">
              <div>
                <ShieldAlert size={16} />
                <span><strong>检测到人工修订</strong><small>{interventionProjectionConflict.message}</small></span>
              </div>
              <div className="writing-intervention-projection-conflict-actions">
                <button type="button" onClick={() => setInterventionProjectionConflict(null)} disabled={interventionProjectionBusy}>保留人工修订</button>
                <button type="button" className="danger-quiet" onClick={() => applyInterventionRulesToSection(true)} disabled={interventionProjectionBusy}>确认覆盖</button>
              </div>
            </div>
          )}
          {!isStudySchemaSection && workingCopyMessage && /^草稿已生成；/.test(workingCopyMessage) && (
            <div className="working-copy-message">{workingCopyMessage}</div>
          )}
          {!isStudySchemaSection && workingCopyMessage && /失败|拒绝|冲突|未完成|错误/.test(workingCopyMessage) && (
            <div className="working-copy-message danger">{workingCopyMessage}</div>
          )}
          {!isStudySchemaSection && workingCopyLoadError && (
            <div className="working-copy-load-error" role="alert">
              <span>{workingCopyLoadError} 当前内存中的编辑内容未被清空。</span>
              <button type="button" onClick={requestWorkingCopyReload} disabled={workingCopyLoading} title="重新读取当前章节与工作副本">
                <RefreshCw size={14} /> {workingCopyLoading ? "重试中" : "重试读取"}
              </button>
            </div>
          )}
          {!isStudySchemaSection && recoveryDraftPrompt && (
            <div className={`working-copy-recovery-prompt ${recoveryDraftPrompt.recoveryState === "conflict" ? "is-conflict" : ""}`} role="alert">
              <div>
                <strong>{recoveryDraftPrompt.recoveryState === "conflict" ? "发现版本冲突的会话恢复稿" : "发现未保存的会话恢复稿"}</strong>
                <span>
                  {new Date(recoveryDraftPrompt.updatedAt).toLocaleString("zh-CN", { hour12: false })}
                  {` · 基于版本 ${recoveryDraftPrompt.baseRevision} · ${recoveryDraftPrompt.contentHash}`}
                </span>
                {recoveryDraftPrompt.recoveryState === "conflict" && <small>当前服务器版本为 {workingCopyRevision}；系统不会自动套用，请恢复后逐项核对。</small>}
              </div>
              <div>
                <button type="button" onClick={() => { clearCurrentRecoveryDraft(); }} title="删除当前章节的会话恢复稿">放弃恢复稿</button>
                <button type="button" className="primary-button" onClick={restoreLatestRecoveryDraft} title={recoveryDraftPrompt.recoveryState === "conflict" ? "恢复为冲突稿并由医学作者人工核对" : "恢复会话稿到当前编辑器"}>恢复会话稿</button>
              </div>
            </div>
          )}
          {!isStudySchemaSection && editorStructureError && <div className="working-copy-message danger">{editorStructureError}</div>}
          {!isStudySchemaSection && editorFrozen && (
            <div className="approval-lock">
              <CheckCircle2 size={16} />
              当前作者确认版本已冻结；如需继续修订，请先解除冻结，原冻结记录会继续保留。
            </div>
          )}
          {!isStudySchemaSection && authoringJourneyAvailable && workingCopy && !workingCopyAuthoritative && !editorBlocker && (
            <div className="approval-lock warning">
              <AlertTriangle size={16} />
              <span>{conciseEditorBlockerReason(workingCopy.quarantine_reason || "历史工作版本与当前研究定义不一致，已隔离且不作为当前编辑内容。")}</span>
              <button type="button" onClick={() => setActiveWritingRailTab("版本")}>查看与恢复</button>
            </div>
          )}
          {!isStudySchemaSection && (!sectionHasBackendBinding || !editorSessionAvailable)
            && !(greenfieldSetupAvailable && !editorSessionAvailable) && (
            <div className="approval-lock warning">
              <AlertTriangle size={16} />
              {!editorSessionAvailable
                ? (documentSessionMessage || "真实方案文档会话未就绪；系统不会回退到其他项目正文。")
                : "当前章节暂无后端章节绑定，AI修订已关闭；请先完成章节映射，避免写入其他章节线程。"}
            </div>
          )}
          {isStudySchemaSection && editorSessionAvailable ? (
            <StudySchemaEditor
              projectId={projectId}
              sectionId={backendSectionId}
              readOnly={editorFrozen || !workingCopyAuthoritative}
            />
          ) : editorSessionAvailable && sectionContentAvailable ? (
            <RichProtocolEditor
              key={`${selectedSection}:${workingCopyRevision}:${workingCopy?.content_sha256 || "no-hash"}:${workingCopyEditing ? "edit" : "source"}:h${workingCopyHydrationEpoch}`}
              section={section}
              approvedLocked={editorFrozen}
              readOnly={!isDemoWritingSession && !realWorkingCopyEditable}
              selectedSection={selectedSection}
              contentBlocks={isDemoWritingSession ? [] : workingCopyDisplayBlocks}
              sourceBlocks={isDemoWritingSession ? [] : sectionContent?.content_blocks || []}
              isGreenfieldAuthoring={isGreenfieldSession}
              onSelectedTextChange={setSelectedEditorText}
              onSelectedAnchorChange={setSelectedEditorAnchor}
              onSelectedBlockContextChange={setSelectedEditorBlockContext}
              onEditorTextChange={setEditorPlainText}
              onContentBlocksChange={updateWorkingCopyDraft}
              onStructureError={setEditorStructureError}
              tableTemplates={tableTemplates}
              tableDomainProfiles={tableDomainProfiles}
              suggestedTableDomain={isSoaSection ? "schedule_of_activities" : ""}
              tableInsertBusy={tableTemplateLoading || workingCopyActionBusy}
              canInsertTableTemplate={
                !isDemoWritingSession
                && workingCopyRevision >= 1
                && !workingCopyDirty
                && workingCopyAuthoritative
                && !editorFrozen
              }
              onInsertTableTemplate={insertTableTemplate}
              focusTableBlockId={insertedTableBlockId}
              onFocusTableHandled={() => setInsertedTableBlockId("")}
              revisionThreads={sectionThreads}
              citationInsertion={citationInsertion}
              onCitationInsertionHandled={(_insertionId, message) => {
                setCitationInsertion(null);
                setCitationInsertionMessage(message || "引文插入处置完成。");
              }}
              documentIndex={documentIndex}
              allowEmptyDocument={!isDemoWritingSession}
              fullscreenSaveState={workingCopyActionBusy ? "保存中" : workingCopyDirty ? "有未保存修订" : workingCopyRevision >= 1 ? `版本 ${workingCopyRevision} 已保存` : "尚无保存版本"}
              fullscreenSaveDisabled={workingCopyActionBusy || !workingCopyDirty || editorFrozen || !workingCopyAuthoritative || Boolean(editorStructureError)}
              fullscreenSaveBusy={workingCopyActionBusy}
              onFullscreenSave={saveWorkingCopy}
              onFullscreenOpenTool={(tool) => {
                setActiveWritingRailTab(tool);
                globalThis.requestAnimationFrame?.(() => document.querySelector(".writing-ai-core")?.scrollIntoView?.({ block: "start" }));
              }}
            />
          ) : greenfieldSetupAvailable ? (
            <MedicalWritingAuthoringJourneySetup
              key={projectId}
              projectId={projectId}
              projectHeader={projectHeader}
              projectSourceMode={projectSourceMode}
              onCreated={handleGreenfieldCreated}
            />
          ) : (
            <div className="rich-editor-shell real-document-session-blocked">
              <div className="rich-editor-meta">
                <span>当前章节：{section.title}</span>
                <span>证据覆盖 {Number.isFinite(section.coverage) ? `${section.coverage}%` : "待核验"}</span>
                <span>编辑会话未就绪</span>
              </div>
              <div className="protocol-editor blocked-editor-canvas">
                <h2>{section.title}</h2>
                <p>{documentSessionLoading ? "正在加载研究方案文档会话。" : (documentSessionMessage || "当前文档会话暂不可用。")}</p>
              </div>
            </div>
          )}
        </section>
        {!greenfieldSetupAvailable && <aside className="panel ai-rail writing-ai-core" hidden={isStudySchemaSection}>
          <div className="rail-tabs">
            {writingRailTabs.map((tab) => (
              <button
                className={tab === activeWritingRailTab ? "active" : ""}
                key={tab}
                disabled={!enabledWritingRailTabs.includes(tab)}
                title={tab === "AI" ? "AI修订线程" : tab === "证据" ? "竞品方案参照与本次AI证据包" : tab === "文献" ? "项目文献库与正文引文" : tab === "版本" ? "作者冻结、隔离历史与版本恢复" : tab === "审阅" && isGreenfieldSession ? "项目决策审阅与版本化回写" : `${tab}面板尚未开放`}
                onClick={() => enabledWritingRailTabs.includes(tab) && setActiveWritingRailTab(tab)}
              >
                {tab}
              </button>
            ))}
          </div>
          {activeWritingRailTab === "AI" ? (
          <>
            {isGreenfieldSession && (
              <section className="full-draft-panel" aria-label="研究方案全文初稿">
                <div className="full-draft-panel-head">
                  <div>
                    <Tag tone="success">AI主导</Tag>
                    <h3>研究方案全文初稿</h3>
                  </div>
                  <span>{fullDraftArtifact?.coverage ? `${fullDraftArtifact.coverage.generated_count}/${fullDraftArtifact.coverage.target_count} 章` : "待生成"}</span>
                </div>
                <p>独立AI会按当前研究设计和已绑定语料生成完整章节正文；你只需整体审核，确认后才会写入工作副本。</p>
                {fullDraftJob?.progress && !["completed", "failed", "cancelled"].includes(fullDraftJob.status) && (
                  <div className="revision-progress" role="status" aria-live="polite">
                    <strong>{fullDraftJob.progress.message || "正在生成全文初稿"}</strong>
                    <span>{Math.round(Number(fullDraftJob.progress.percent || 0) * 100)}%</span>
                  </div>
                )}
                {fullDraftMessage && <p className="revision-message">{fullDraftMessage}</p>}
                {fullDraftArtifact && (
                  <>
                    <div className="full-draft-review-list" aria-label="全文初稿候选正文">
                      {(fullDraftArtifact.sections || []).map((section) => (
                        <article className="full-draft-review-item" key={section.section_id}>
                          <div className="full-draft-review-item-head">
                            <strong>{section.section_number ? `${section.section_number} ` : ""}{section.heading || section.section_id}</strong>
                            <span>{(section.evidence_span_ids || []).length} 条证据绑定</span>
                          </div>
                          <p>{section.proposal_text}</p>
                          <small>{section.rationale}</small>
                        </article>
                      ))}
                    </div>
                    <button
                      type="button"
                      className="primary-button"
                      onClick={adoptFullDraft}
                      disabled={fullDraftBusy || workingCopyDirty || editorFrozen || !workingCopyAuthoritative}
                      title="按章节版本与幂等键整体采纳全文候选，发生冲突时停止写入"
                    >
                      <FileCheck2 size={14} /> {fullDraftBusy ? "采纳中" : "整体审核后采纳并写入"}
                    </button>
                  </>
                )}
                {!fullDraftArtifact && !fullDraftBusy && (
                  <button
                    type="button"
                    className="primary-button"
                    onClick={startFullDraft}
                    disabled={workingCopyDirty || editorFrozen || !workingCopyAuthoritative || !editorSessionAvailable}
                    title="生成完整研究方案正文候选"
                  >
                    <Sparkles size={14} /> 生成全文初稿
                  </button>
                )}
              </section>
            )}
            <div className="revision-form">
              <Tag tone="info">AI候选，待选择</Tag>
              <h3>AI修订指令</h3>
              <p>{revisionBoundary}</p>
              {selectedEditorBlockContext.blockType === "table" && (
                <p className="revision-message">
                  {selectedEditorBlockContext.tableCell
                    ? `当前目标：第 ${selectedEditorBlockContext.tableCell.rowIndex + 1} 行 / 第 ${selectedEditorBlockContext.tableCell.columnIndex + 1} 列。AI只生成该单元格的完整替换候选。`
                    : "当前选中表格。请在全屏表格设计器中选择一个单元格后提交AI修订。"}
                </p>
              )}
            <label>
              修订意图
              <select
                value={revisionIntent}
                onChange={(event) => handleRevisionIntentChange(event.target.value)}
                disabled={aiRevisionDisabled || revisionLoading}
                title={aiRevisionUnavailableReason || (revisionLoading ? "修订任务正在处理" : "选择AI修订意图")}
                aria-describedby={paragraphLoadPending ? "writing-ai-unavailable-reason" : undefined}
              >
                {revisionIntentOptions.map((item) => <option value={item.value} key={item.value}>{item.label}</option>)}
              </select>
            </label>
            <label>
              用户指令
              <textarea
                value={revisionInstruction}
                onChange={(event) => setRevisionInstruction(event.target.value)}
                disabled={aiRevisionDisabled || revisionLoading}
                title={aiRevisionUnavailableReason || (revisionLoading ? "修订任务正在处理" : "补充本次AI修订要求")}
                aria-describedby={paragraphLoadPending ? "writing-ai-unavailable-reason" : undefined}
              />
            </label>
            <div className="selected-text">
              <strong>本次提交文本</strong>
              <span>{greenfieldSetupAvailable
                ? "建立工作稿后，可选择章节正文或表格单元格与AI逐轮修订。"
                : sectionHasBackendBinding
                ? (
                  selectedEditorBlockContext.tableCell?.text
                  || selectedEditorText
                  || (isDemoWritingSession ? editorPlainText : defaultRevisionWorkingBlock?.text)
                  || (
                    isBlankGreenfieldBodyBlock(defaultRevisionWorkingBlock)
                      ? "当前章节正文为空：AI将依据研究定义、PICOS、章节语义及已选证据生成 3-5 个实质正文候选。"
                      : "请选择当前工作副本段落或表格单元格后提交。"
                  )
                )
                : "当前章节暂无后端章节绑定，不能提交AI修订。"}</span>
            </div>
            <div className="revision-evidence-package">
              <strong>本次AI允许来源</strong>
              <span>{selectedReferenceBriefIds.length ? `${selectedReferenceBriefIds.length} 条已选外部证据 + 当前目标原文` : "仅当前目标原文；未加入外部证据"}</span>
              <button onClick={() => setActiveWritingRailTab("证据")} title="打开竞品方案参照并选择医学已批准证据">选择证据</button>
            </div>
            <button
              className="primary-button"
              onClick={submitRevisionRequest}
              disabled={aiRevisionDisabled || revisionLoading || !revisionInstruction.trim()}
              title={aiRevisionUnavailableReason || (!revisionInstruction.trim() ? "请先填写AI修订指令" : revisionLoading ? "修订任务正在处理" : "提交AI修订任务")}
              aria-describedby={paragraphLoadPending ? "writing-ai-unavailable-reason" : undefined}
            >
              {revisionLoading ? "处理中" : "提交AI修订"}
            </button>
            {revisionJobProgress && !["completed", "failed", "cancelled"].includes(revisionJobState?.status) && (
              <div className="revision-progress" role="status" aria-live="polite">
                <div>
                  <strong>{revisionJobProgress.message || "正在生成AI候选"}</strong>
                  <span>{revisionJobPercent}%</span>
                </div>
                <div
                  className="revision-progress-track"
                  role="progressbar"
                  aria-label="AI候选生成进度"
                  aria-valuemin="0"
                  aria-valuemax="100"
                  aria-valuenow={revisionJobPercent}
                >
                  <span style={{ width: `${revisionJobPercent}%` }} />
                </div>
                {revisionJobProgress.step_total > 0 && (
                  <small>
                    步骤 {revisionJobProgress.step}/{revisionJobProgress.step_total}
                  </small>
                )}
              </div>
            )}
            {revisionMessage && <p className="revision-message">{revisionMessage}</p>}
          </div>
          <section className="writing-ai-candidates" aria-label="当前章节AI候选版本">
            <header><div><span>独立AI</span><strong>可直接采用的版本</strong></div><em>{sectionCandidateVersions.length} 个</em></header>
            {sectionCandidateVersions.map((candidate, index) => (
              <article key={candidate.suggestion_id} className={candidate.suggestion_id === activeSuggestion?.suggestion_id ? "selected" : ""}>
                <div><strong>{index === 0 ? "推荐版本" : `备选 ${index}`}</strong><Tag tone={revisionSuggestionTone(candidate.user_decision)}>{revisionSuggestionStatusLabel(candidate.user_decision)}</Tag></div>
                <p>{candidate.proposal_text}</p>
                <p className="quiet-text">{candidate.rationale}</p>
                <button
                  type="button"
                  onClick={() => setSelectedRevisionSuggestionId(candidate.suggestion_id)}
                  className={candidate.suggestion_id === activeSuggestion?.suggestion_id ? "active" : ""}
                  disabled={revisionLoading}
                  title="在下方查看该候选的依据、不确定性和处置记录"
                >
                  {candidate.suggestion_id === activeSuggestion?.suggestion_id ? "当前查看" : "查看详情"}
                </button>
                <button
                  type="button"
                  className="primary-button"
                  onClick={() => {
                    setSelectedRevisionSuggestionId(candidate.suggestion_id);
                    submitRevisionAction(activeThread, candidate, "accept");
                  }}
                  disabled={
                    revisionLoading
                    || candidate.user_decision !== "pending"
                    || !canSelectAndApplyRevision
                    || protectedTokenAdoptionBlocked(candidate)
                  }
                  title={protectedTokenAdoptionBlocked(candidate)
                    ? "候选改变了源文本受保护医学标识，请让AI重写后再选用"
                    : workingCopyDirty
                    ? "存在未保存的手工修订，请先保存或重新加载"
                    : !workingCopyAuthoritative
                      ? "当前历史工作版本已隔离"
                    : editorFrozen
                      ? "当前作者确认版本已冻结"
                      : !workingCopy?.working_copy_id
                        ? "当前章节尚未建立版本化工作副本"
                        : candidate.user_decision === "accepted"
                          ? "该候选已经由医学作者选用"
                          : "记录医学作者选择并写入版本化工作副本"}
                >
                  <FileCheck2 size={14} /> {candidate.user_decision === "accepted" ? "已选用" : "选用并写入"}
                </button>
              </article>
            ))}
            {!sectionCandidateVersions.length && (
              <div className="empty-state">
                <span>尚未生成本章候选。独立AI将基于已确认研究事实、准入语料和本次所选证据提供 3-5 个版本。</span>
                <button
                  type="button"
                  className="primary-button"
                  onClick={submitRevisionRequest}
                  disabled={aiRevisionDisabled || revisionLoading || !revisionInstruction.trim()}
                  title={aiRevisionUnavailableReason
                    ? aiRevisionUnavailableReason
                    : !revisionInstruction.trim()
                      ? "请先填写AI修订指令"
                      : revisionLoading
                        ? "修订任务正在处理"
                        : "生成3-5个本章首稿候选"}
                  aria-describedby={paragraphLoadPending ? "writing-ai-unavailable-reason" : undefined}
                >
                  <Sparkles size={14} /> 生成本章首稿候选
                </button>
              </div>
            )}
          </section>
          <div className="revision-thread-list">
            <div className="revision-thread-head">
              <h3>修订线程</h3>
              <button onClick={refreshRevisionThreads} disabled={revisionLoading || !editorSessionAvailable} title={!editorSessionAvailable ? "真实方案文档会话未就绪" : revisionLoading ? "修订线程正在读取" : "刷新修订线程"}>{revisionLoading ? "读取中" : "刷新"}</button>
            </div>
            {sectionThreads.length ? sectionThreads.map((thread) => (
              <button
                key={thread.thread_id}
                className={thread.thread_id === activeThread?.thread_id ? "active" : ""}
                onClick={() => {
                  setActiveRevisionThreadId(thread.thread_id);
                  setSelectedRevisionSuggestionId("");
                }}
              >
                <span>{thread.thread_id.replace("thread_", "线程 ")}</span>
                <Tag tone={revisionThreadTone(thread.status)}>{revisionThreadStatusLabel(thread.status)}</Tag>
              </button>
            )) : <p className="quiet-text">当前章节暂无修订线程。</p>}
          </div>
          <div className="revision-thread">
            {activeThread ? (
              <>
                <Tag tone={revisionThreadTone(activeThread.status)}>{revisionThreadStatusLabel(activeThread.status)}</Tag>
                <div className="revision-ledger-head">
                  <div>
                    <h3>修订审阅记录</h3>
                    <p>{activeThread.anchor_type === "table_cell" ? "同一表格单元格的医学反馈、AI候选和处置历史" : "同一原始段落的医学反馈、AI候选和处置历史"}</p>
                  </div>
                  <span>{activeThread.suggestions?.length || 0} 轮</span>
                </div>
                <div className="revision-turn-ledger" data-testid="revision-turn-ledger">
                  {(activeThread.suggestions || []).map((suggestion, index) => {
                    const isCurrentTurn = suggestion.suggestion_id === activeSuggestion?.suggestion_id;
                    const turnNumber = suggestion.turn_number || index + 1;
                    return (
                      <section className={`revision-turn ${isCurrentTurn ? "current" : "historical"}`} data-turn-number={turnNumber} key={suggestion.suggestion_id}>
                        <header>
                          <div>
                            <strong>第 {turnNumber} 轮</strong>
                            <span>{revisionTurnTime(suggestion.created_at)}</span>
                          </div>
                          <Tag tone={revisionSuggestionTone(suggestion.user_decision)}>{revisionSuggestionStatusLabel(suggestion.user_decision)}</Tag>
                        </header>
                        <div className="revision-turn-grid">
                          <div className="revision-turn-request">
                            <span>本轮要求</span>
                            <p>{suggestion.user_instruction || (index === 0 ? activeThread.user_instruction : "历史记录未保存本轮指令")}</p>
                            <span>医学反馈</span>
                            <p>{suggestion.user_comment || (index === 0 ? "首次生成，无上一轮反馈。" : "本轮未补充处置意见。")}</p>
                          </div>
                          <div className="revision-turn-candidate">
                            <span>AI候选</span>
                            {activeThread.anchor_type === "table_cell" ? (
                              <div className="table-cell-revision-diff" aria-label="表格单元格AI修订前后对照">
                                <div>
                                  <span>提交时单元格快照</span>
                                  <p>{activeThread.selected_text || "空白单元格"}</p>
                                </div>
                                <div>
                                  <span>AI候选</span>
                                  <p>{suggestion.proposal_text || "暂无建议正文"}</p>
                                </div>
                              </div>
                            ) : <p>{suggestion.proposal_text || "暂无建议正文"}</p>}
                            {suggestion.diff_segments?.length > 0 && (
                              <div className="revision-local-diff" aria-label="局部文字差异">
                                <span>局部差异</span>
                                <div className="revision-local-diff-text">
                                  {suggestion.diff_segments.map((segment, segmentIndex) => (
                                    <mark
                                      key={`${suggestion.suggestion_id}-diff-${segmentIndex}`}
                                      className={`revision-diff-${segment.operation}`}
                                      title={segment.operation === "delete" ? "原文删除" : segment.operation === "insert" ? "候选新增" : "保持不变"}
                                    >
                                      {segment.operation === "delete" ? "−" : segment.operation === "insert" ? "+" : ""}{segment.text}
                                    </mark>
                                  ))}
                                </div>
                                {suggestion.diff_source_hash && <small>差异绑定选区版本：{suggestion.diff_source_hash.slice(0, 12)}…</small>}
                              </div>
                            )}
                            <span>理由与不确定性</span>
                            <p>{suggestion.rationale || "待生成修订理由。"}</p>
                            <p className="quiet-text">{suggestion.uncertainty || "需医学经理确认医学合理性、证据依据和版本影响。"}</p>
                            {suggestion.impact_status && suggestion.impact_status !== "legacy_unavailable" && (
                              <div className={`revision-impact-panel ${suggestion.impact_status}`} aria-label="局部下游影响">
                                <span>下游影响</span>
                                <p>{suggestion.impact_status === "known" ? "仅展示当前语义索引可证明的影响；未列出的对象不代表已证明无影响。" : "部分传播关系未建立，采用前必须对未解析影响做医学核验。"}</p>
                                <ul>
                                  {(suggestion.impact_refs || []).map((ref, refIndex) => (
                                    <li key={`${suggestion.suggestion_id}-impact-${refIndex}`} className={`revision-impact-${ref.scope}`}>
                                      <strong>{ref.scope === "local" ? "当前选区" : ref.scope === "downstream" ? "需重新核验" : "未解析"}</strong>
                                      <span>{ref.message || ref.reason_code}</span>
                                      {ref.section_id && <small>{ref.section_id}{ref.block_id ? ` · ${ref.block_id}` : ""}</small>}
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            )}
                            {suggestion.protected_token_status && suggestion.protected_token_status !== "legacy_unavailable" && (
                              <div className={`revision-protected-token-panel ${suggestion.protected_token_status}`} aria-label="受保护医学标识核验">
                                <span>受保护标识</span>
                                <p>{suggestion.protected_token_status === "verified"
                                  ? "源文本数字、单位、受控术语和引用顺序已核验。"
                                  : suggestion.protected_token_status === "unresolved"
                                    ? "候选新增数字、术语或引用，需要医学经理核验来源。"
                                    : "候选改变了源文本受保护标识，系统将阻止写入。"}</p>
                                {(suggestion.protected_token_issues || []).length > 0 && (
                                  <ul>
                                    {(suggestion.protected_token_issues || []).map((issue, issueIndex) => (
                                      <li key={`${suggestion.suggestion_id}-protected-${issueIndex}`}>
                                        <strong>{issue.reason_code}</strong>
                                        <span>{issue.message || issue.proposal_text || issue.source_text}</span>
                                      </li>
                                    ))}
                                  </ul>
                                )}
                              </div>
                            )}
                          </div>
                        </div>
                        <footer>
                          <span title={suggestion.ai_run_id || activeThread.ai_run_id}>AI运行 {suggestion.ai_run_id || activeThread.ai_run_id || "历史记录未保存"}</span>
                          <span>{suggestion.evidence_span_ids?.length || 0} 条证据定位</span>
                          {suggestion.parent_suggestion_id && <span title={suggestion.parent_suggestion_id}>承接上一轮候选</span>}
                        </footer>
                      </section>
                    );
                  })}
                </div>
                <p className="revision-boundary-line">{revisionBoundary}</p>
                {activeSuggestion?.user_decision === "pending" && (
                  <div className="revision-current-action">
                    <strong>处置第 {activeSuggestion.turn_number || activeThread.suggestions?.length || 1} 轮</strong>
                    <label>
                      医学反馈
                      <textarea value={revisionActionComment} onChange={(event) => setRevisionActionComment(event.target.value)} disabled={revisionLoading} placeholder="记录医学判断、事实问题或需要保留的表述" />
                    </label>
                    <label>
                      下一轮重写要求
                      <textarea value={revisionRewriteInstruction} onChange={(event) => setRevisionRewriteInstruction(event.target.value)} disabled={revisionLoading} placeholder={revisionRewritePlaceholder} />
                    </label>
                    <div className="button-row">
                      <button
                        className="primary-button"
                        disabled={revisionLoading || !canSelectAndApplyActiveRevision}
                        title={protectedTokenAdoptionBlocked(activeSuggestion)
                          ? "候选改变了源文本受保护医学标识，请让AI重写后再选用"
                          : workingCopyDirty
                          ? "存在未保存的手工修订，请先保存或重新加载"
                          : !workingCopyAuthoritative
                            ? "当前历史工作版本已隔离"
                          : editorFrozen
                            ? "当前作者确认版本已冻结"
                            : !workingCopy?.working_copy_id
                              ? "请先创建工作副本"
                              : "选用当前候选并写入版本化工作副本"}
                        onClick={() => submitRevisionAction(activeThread, activeSuggestion, "accept")}
                      >选用并写入</button>
                      <button disabled={revisionLoading} title="拒绝当前AI建议" onClick={() => submitRevisionAction(activeThread, activeSuggestion, "reject")}>拒绝建议</button>
                      <button disabled={revisionLoading || !revisionRewriteInstruction.trim()} title={!revisionRewriteInstruction.trim() ? "请先填写下一轮重写要求" : "基于上一轮候选和医学反馈生成下一轮"} onClick={() => submitRevisionAction(activeThread, activeSuggestion, "request_rewrite")}>生成下一轮</button>
                    </div>
                  </div>
                )}
                {isRevisionThreadSelectedByAuthor(activeThread.status) && activeRevisionApplied && (
                  <div className="revision-application-band applied">
                    <div>
                      <strong>已选用并写入工作副本</strong>
                      <span>该修订线程已写入当前工作副本历史，不会重复应用。</span>
                    </div>
                    <Tag tone="success">已应用</Tag>
                  </div>
                )}
                {isRevisionThreadSelectedByAuthor(activeThread.status) && !activeRevisionApplied && isDemoWritingSession && (
                  <div className="revision-application-band ready">
                    <div>
                      <strong>{activeThread.status === "accepted_pending_medical_approval" ? "历史候选已选用，待写入" : "医学作者已选用，待写入"}</strong>
                      <span>演示会话仍可使用分步写入；生产会话仅支持原子选用并写入。</span>
                    </div>
                    <div className="revision-application-actions">
                      {activeThread.status === "accepted_pending_medical_approval" && <Tag tone="warning">历史状态</Tag>}
                      <button
                        className="primary-button"
                        onClick={() => applyApprovedRevision(activeThread)}
                        disabled={!canApplyApprovedRevision}
                        title="演示：重试将医学作者已选用的AI候选写入当前工作副本"
                      >
                        <FileCheck2 size={14} /> {workingCopyActionBusy ? "写入中" : "演示写入"}
                      </button>
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="empty-state">暂无AI修订线程。请在上方提交修订指令。</div>
            )}
          </div>
          <div className="export-gate">
            <h3>导出质量门</h3>
            {[`AI候选待处置 ${unresolvedAiCandidateCount} 项`, `源内容待处置 ${contentQualityBlockingCount} 项`, `资料包阻断质量门 ${activePackage?.blocking_gate_count ?? 0} 项`, `当前章节修订线程 ${sectionThreads.length} 条`, `证据索引覆盖 ${Number.isFinite(section.coverage) ? `${section.coverage}%` : "待核验"}`].map((item, index) => (
              <p key={item} className={index < 3 ? "blocking" : "info"}>{item}</p>
            ))}
          </div>
          </>
          ) : activeWritingRailTab === "版本" ? (
            <section className="writing-version-panel" aria-label="作者确认与版本恢复">
              <header>
                <div>
                  <span>当前章节</span>
                  <strong>作者确认与冻结</strong>
                </div>
                <button type="button" onClick={() => refreshVersionHistory()} disabled={versionHistoryLoading} title="重新读取冻结与隔离历史">
                  <RefreshCw size={14} /> {versionHistoryLoading ? "读取中" : "刷新"}
                </button>
              </header>
              <div className="writing-version-summary">
                <div><span>当前工作版本</span><strong>{workingCopyRevision >= 1 ? `版本 ${workingCopyRevision}` : "尚未保存"}</strong></div>
                <div><span>状态</span><Tag tone={workingCopyFreezeTone(workingCopy)}>{workingCopyFreezeLabel(workingCopy)}</Tag></div>
                <div><span>全文冻结进度</span><strong>{freezeReadiness ? `${freezeReadiness.current_frozen_section_count}/${freezeReadiness.required_section_count}` : "待读取"}</strong></div>
              </div>
              {(freezeReadinessError || versionHistoryMessage) && (
                <p className="writing-version-message danger">{freezeReadinessError || versionHistoryMessage}</p>
              )}
              {selectedFreezeGap && (
                <div className="writing-version-readiness">
                  <Tag tone={["section_not_frozen", "freeze_invalidated"].includes(selectedFreezeGap.reason_code) ? "warning" : "danger"}>
                    {freezeGapLabel(selectedFreezeGap.reason_code)}
                  </Tag>
                  <p>{selectedFreezeGap.message}</p>
                </div>
              )}
              <details className="writing-version-disclosure" open={workingCopy?.content_authority_state === "historical_quarantined"}>
                <summary>
                  <span>隔离历史</span>
                  <Tag tone={quarantinedWorkingCopy ? "warning" : "neutral"}>{quarantinedWorkingCopy ? "1 个可查版本" : "无"}</Tag>
                </summary>
                {quarantinedWorkingCopy ? (
                  <div className="writing-quarantine-entry">
                    <div>
                      <strong>隔离工作版本 {quarantinedWorkingCopy.quarantined_revision ?? quarantinedWorkingCopy.revision}</strong>
                      <span>{quarantinedWorkingCopy.updated_at ? new Date(quarantinedWorkingCopy.updated_at).toLocaleString("zh-CN", { hour12: false }) : "时间待核对"}</span>
                    </div>
                    <p>{quarantinedWorkingCopy.quarantine_reason || "该历史内容与当前研究定义绑定不一致，已从主编辑器隔离。"}</p>
                    <span>{quarantinedWorkingCopy.content_blocks?.length || 0} 个内容块，仅用于核对与受控恢复。</span>
                    {!workingCopyAuthoritative && (
                      <div className="writing-binding-recovery-form">
                        <label>
                          恢复理由
                          <textarea
                            value={bindingRecoveryReason}
                            onChange={(event) => setBindingRecoveryReason(event.target.value)}
                            placeholder="至少10字，说明为何确认绑定该版本，或为何恢复权威源基线"
                            disabled={workingCopyActionBusy}
                          />
                        </label>
                        <label className="writing-binding-recovery-check">
                          <input
                            type="checkbox"
                            checked={bindingRecoveryAcknowledged}
                            onChange={(event) => setBindingRecoveryAcknowledged(event.target.checked)}
                            disabled={workingCopyActionBusy}
                          />
                          <span>我已核对所选隔离版本与当前研究定义，并理解两种恢复操作都会生成新工作副本版本。</span>
                        </label>
                        <div className="writing-binding-recovery-actions">
                          <button
                            type="button"
                            className="primary-button"
                            onClick={() => recoverWorkingCopyBinding("accept")}
                            disabled={workingCopyActionBusy || bindingRecoveryReason.trim().length < 10 || !bindingRecoveryAcknowledged}
                            title="由当前医学作者确认所选隔离内容，并绑定至当前研究定义"
                          >确认绑定此版本</button>
                          <button
                            type="button"
                            onClick={() => recoverWorkingCopyBinding("revert")}
                            disabled={workingCopyActionBusy || bindingRecoveryReason.trim().length < 10 || !bindingRecoveryAcknowledged}
                            title="不使用隔离内容，从权威源章节基线建立新工作副本"
                          ><RotateCcw size={14} /> 恢复权威源基线</button>
                        </div>
                      </div>
                    )}
                  </div>
                ) : <p className="quiet-text">{versionHistoryLoading ? "正在读取隔离历史。" : "当前章节没有可查的隔离工作版本。"}</p>}
              </details>
              <details className="writing-version-disclosure">
                <summary>
                  <span>冻结历史</span>
                  <Tag tone="neutral">{freezeHistory.length} 条</Tag>
                </summary>
                {freezeHistory.length ? (
                  <div className="writing-freeze-history-list">
                    {freezeHistory.map((record) => (
                      <div key={record.snapshot_id} className={record.is_current ? "is-current" : ""}>
                        <div><strong>工作副本版本 {record.working_copy_revision}</strong>{record.is_current && <Tag tone="success">当前冻结</Tag>}</div>
                        <span>{record.frozen_at ? new Date(record.frozen_at).toLocaleString("zh-CN", { hour12: false }) : "时间待核对"} · {record.source === "legacy_medical_approval" ? "历史记录迁移" : "作者冻结"}</span>
                      </div>
                    ))}
                  </div>
                ) : <p className="quiet-text">{versionHistoryLoading ? "正在读取冻结历史。" : "当前章节尚无冻结记录。"}</p>}
              </details>
            </section>
          ) : activeWritingRailTab === "审阅" && isGreenfieldSession ? (
            <GreenfieldDecisionReviewPanel
              state={greenfieldState}
              busyDecisionId={greenfieldDecisionBusy}
              message={greenfieldDecisionMessage}
              onResolve={resolveGreenfieldDecision}
            />
          ) : activeWritingRailTab === "文献" ? (
            <>
              {citationInsertionMessage && <p className="medical-literature-insertion-message">{citationInsertionMessage}</p>}
              <MedicalWritingLiteraturePanel
                projectId={projectId}
                onInsertReference={queueCitationInsertion}
              />
            </>
          ) : (
            <WritingReferencePanel
              projectId={projectId}
              selectedBriefIds={selectedReferenceBriefIds}
              onSelectedBriefIdsChange={setSelectedReferenceBriefIds}
              onUseEvidence={() => setActiveWritingRailTab("AI")}
            />
          )}
        </aside>}
      </div>
      {paragraphLoadPending && (
        <p id="writing-ai-unavailable-reason" className="writing-editor-availability-note" role="status">
          当前章节正文仍在加载；完成后可使用AI修订。
        </p>
      )}
      {pendingEditorNavigation && (
        <div className="writing-unsaved-navigation-backdrop" role="presentation">
          <section className="writing-unsaved-navigation-dialog" role="dialog" aria-modal="true" aria-label="未保存修订处理">
            <header>
              <ShieldAlert size={18} />
              <div>
                <strong>当前章节有未保存修订</strong>
                <span>准备{pendingEditorNavigation.label}。请选择保留当前编辑，或明确丢弃后继续。</span>
              </div>
            </header>
            <div className="writing-unsaved-navigation-actions">
              <button type="button" onClick={() => setPendingEditorNavigation(null)}>继续编辑</button>
              {(currentRecoveryDraft || recoveryDraftPrompt) && (
                <button type="button" onClick={() => { restoreLatestRecoveryDraft(); setPendingEditorNavigation(null); }}>恢复会话稿</button>
              )}
              <button
                type="button"
                className="danger-quiet"
                onClick={() => {
                  const pending = pendingEditorNavigation;
                  setPendingEditorNavigation(null);
                  discardUnsavedWorkingCopy();
                  pending.run();
                }}
              >
                {pendingEditorNavigation.kind === "reload" ? "丢弃并重新加载" : "丢弃并切换"}
              </button>
            </div>
          </section>
        </div>
      )}
      {!greenfieldSetupAvailable && documentMapOpen && (
        <div className="writing-document-map-backdrop" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setDocumentMapOpen(false);
        }}>
          <aside className="panel section-tree writing-document-map-drawer" role="dialog" aria-modal="false" aria-label="研究方案目录">
            <header>
              <div><span>研究方案目录</span><strong>{documentSections.length} 个结构节点</strong></div>
              <button className="icon-button" onClick={() => setDocumentMapOpen(false)} title="关闭目录"><XCircle size={18} /></button>
            </header>
            <label className="writing-document-map-search">
              <Search size={15} />
              <input value={documentMapSearch} onChange={(event) => setDocumentMapSearch(event.target.value)} placeholder="搜索章节标题" autoFocus />
            </label>
            <div className="writing-section-buttons">
              {visibleDocumentSections.map((item) => (
                <button
                  key={item.id}
                  className={`${selectedSection === item.id ? "active" : ""} ${item.depth ? "nested-section" : "root-section"}`}
                  style={{ "--writing-section-depth": Math.min(item.depth || 0, 4) }}
                  onClick={() => {
                    requestSectionChange(item.id, () => setDocumentMapOpen(false));
                  }}
                  title={item.title}
                >
                  <span>{item.title}</span>
                  <Tag tone={["已冻结", "不适用"].includes(item.status) ? "success" : "warning"}>{item.status}</Tag>
                </button>
              ))}
              {!visibleDocumentSections.length && <p className="quiet-text">未找到匹配章节。</p>}
            </div>
          </aside>
        </div>
      )}
      {!greenfieldSetupAvailable && studyDesignOpen && authoringJourneyAvailable && (
        <div className="writing-document-map-backdrop" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setStudyDesignOpen(false);
        }}>
          <aside className="panel writing-study-design-drawer" role="dialog" aria-modal="false" aria-label="研究设计基线">
            <header>
              <div><span>{studyDesignTarget.label ? "当前章节的结构化设计" : "研究设计基线"}</span><strong>{studyDesignTarget.label || "研究框架、PICOS与动态章节"}</strong><small>医学经理的设计选择立即应用；已有正文不会丢失，受影响内容会进入调和与重新审阅。</small></div>
              <button className="icon-button" onClick={() => setStudyDesignOpen(false)} title="关闭研究设计"><XCircle size={18} /></button>
            </header>
            <div className="writing-study-design-body">
              {!studyDesignTarget.label
                && protocolModuleResolutions.length > 0
                && (protocolTemplate?.nodes || []).length > 0
                && (
                <ProtocolModuleResolutionPanel
                  resolutions={protocolModuleResolutions}
                  templateNodes={protocolTemplate?.nodes || []}
                  busyId={moduleResolutionBusy}
                  baselineReady={Boolean(greenfieldState?.baseline_revision && greenfieldState?.baseline_sha256)}
                  message={moduleResolutionMessage}
                  lastResult={moduleResolutionResult}
                  onApply={applyProtocolModuleResolution}
                />
              )}
              <MedicalWritingAuthoringJourneySetup
                key={`${projectId}:${studyDesignTarget.requestId}`}
                projectId={projectId}
                projectHeader={projectHeader}
                projectSourceMode={projectSourceMode}
                existingDocument
                initialStage={studyDesignTarget.stage}
                initialGroup={studyDesignTarget.group}
                initialInterventionPanel={studyDesignTarget.panel}
                focusLabel={studyDesignTarget.label ? `${section.sectionNumber || "首页"} ${section.title} · ${studyDesignTarget.label}` : ""}
                onJourneyChanged={() => refreshStudyConsistency()}
              />
            </div>
          </aside>
        </div>
      )}
      {!greenfieldSetupAvailable && studyRebindOpen && studyConsistency && (
        <div className="writing-document-map-backdrop" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget && !studyRebindBusy) setStudyRebindOpen(false);
        }}>
          <aside className="panel writing-study-rebind-drawer" role="dialog" aria-modal="true" aria-label="研究设计与正文一致性">
            <header>
              <div>
                <span>研究设计与正文一致性</span>
                <strong>{studyConsistency.status === "reconciliation_required" ? "逐章完成正文调和" : "核对设计变更影响并重绑定"}</strong>
                <small>{studyConsistency.message}</small>
              </div>
              <button className="icon-button" onClick={() => setStudyRebindOpen(false)} disabled={studyRebindBusy} title="关闭"><XCircle size={18} /></button>
            </header>
            {studyConsistency.status === "reconciliation_required" ? (
              <>
                <div className="writing-study-rebind-section-list">
                  {(studyConsistency.affected_sections || []).map((item) => (
                    <button
                      type="button"
                      key={item.section_id}
                      className={item.section_id === selectedSection ? "active" : ""}
                      onClick={() => requestSectionChange(item.section_id)}
                    >
                      <span>{item.section_number || "首页"}</span>
                      <strong>{item.heading}</strong>
                      <Tag tone={item.section_id === selectedSection ? "warning" : "neutral"}>{item.section_id === selectedSection ? "当前" : "待调和"}</Tag>
                    </button>
                  ))}
                </div>
                {selectedSectionNeedsReconciliation ? (
                  <div className="writing-study-reconciliation-form">
                    <p>先在正文编辑器中完成本章修订并保存，再确认本章已逐项反映当前研究框架/PICOS。完成调和后，仍需由作者确认并冻结当前版本。</p>
                    <label>
                      调和说明
                      <textarea value={studyReconciliationReason} onChange={(event) => setStudyReconciliationReason(event.target.value)} placeholder="说明已核对和修订的具体内容，例如年龄范围、疾病活动度阈值及筛选期要求。" />
                    </label>
                    <label className="writing-study-rebind-check"><input type="checkbox" checked={studyReconciliationAccepted} onChange={(event) => setStudyReconciliationAccepted(event.target.checked)} /><span>我已核对当前已保存工作副本，确认本章正文已反映当前StudyDefinition。</span></label>
                    {workingCopyDirty && <p className="danger">当前章节仍有未保存修订，请先保存工作副本。</p>}
                  </div>
                ) : <p className="quiet-text">请选择一个待调和章节。</p>}
              </>
            ) : (
              <>
                <div className="writing-study-rebind-summary">
                  <div><span>受影响章节</span><strong>{studyRebindPreview?.affected_sections?.length ?? studyConsistency.affected_sections?.length ?? 0}</strong></div>
                  <div><span>已有工作副本</span><strong>{studyRebindPreview?.affected_working_copy_count ?? "-"}</strong></div>
                  <div><span>需失效冻结</span><strong>{studyRebindPreview?.approval_reset_count ?? "-"}</strong></div>
                </div>
                {studyConsistency.status === "binding_required" && (
                  <p className="writing-study-rebind-scope-note">
                    首次绑定覆盖完整文档，但不会改写原始来源或正文；完成后仅需核对上方显示的已有工作副本。
                  </p>
                )}
                <details
                  className="writing-study-rebind-details"
                  open={(studyRebindPreview?.affected_sections?.length ?? studyConsistency.affected_sections?.length ?? 0) <= 12}
                >
                  <summary>
                    查看章节明细
                    <span>{studyRebindPreview?.affected_sections?.length ?? studyConsistency.affected_sections?.length ?? 0} 项</span>
                  </summary>
                  <div className="writing-study-rebind-section-list">
                    {(studyRebindPreview?.affected_sections || studyConsistency.affected_sections || []).map((item) => (
                      <div key={item.section_id}>
                        <span>{item.section_number || "首页"}</span>
                        <strong>{item.heading}</strong>
                        <small>{(item.affected_dependents || []).join(" · ") || "文档绑定需补齐"}</small>
                      </div>
                    ))}
                  </div>
                </details>
                <div className="writing-study-reconciliation-form">
                  <label>
                    变更原因
                    <textarea value={studyRebindReason} onChange={(event) => setStudyRebindReason(event.target.value)} placeholder="说明本次研究设计变更及为什么需要重新核对上述章节。" />
                  </label>
                  <label className="writing-study-rebind-check"><input type="checkbox" checked={studyRebindContentAccepted} onChange={(event) => setStudyRebindContentAccepted(event.target.checked)} /><span>我理解当前正文不会被系统静默改写，重绑定后仍须逐章修订和确认。</span></label>
                  <label className="writing-study-rebind-check"><input type="checkbox" checked={studyRebindApprovalAccepted} onChange={(event) => setStudyRebindApprovalAccepted(event.target.checked)} /><span>我确认受影响章节的当前冻结将失效，历史冻结快照仍保留。</span></label>
                </div>
              </>
            )}
            {studyRebindMessage && <p className="working-copy-message danger">{studyRebindMessage}</p>}
            <footer>
              <button type="button" onClick={() => setStudyRebindOpen(false)} disabled={studyRebindBusy}>关闭</button>
              {studyConsistency.status === "reconciliation_required" ? (
                <button
                  type="button"
                  className="primary-button"
                  onClick={confirmStudyReconciliation}
                  disabled={studyRebindBusy || !selectedSectionNeedsReconciliation || workingCopyDirty || workingCopyRevision < 1 || studyReconciliationReason.trim().length < 10 || !studyReconciliationAccepted}
                  title={studyRebindBusy
                    ? "正在保存调和确认"
                    : !selectedSectionNeedsReconciliation
                      ? "请先选择一个待调和章节"
                      : workingCopyDirty
                        ? "请先保存当前正文修订"
                        : workingCopyRevision < 1
                          ? "请先创建并保存工作副本"
                          : studyReconciliationReason.trim().length < 10
                            ? "请填写至少10字的调和说明"
                            : !studyReconciliationAccepted
                              ? "请确认当前正文已反映StudyDefinition"
                              : "确认本章已完成StudyDefinition调和"}
                ><CheckCircle2 size={15} /> {studyRebindBusy ? "确认中" : "确认本章已调和"}</button>
              ) : (
                <button
                  type="button"
                  className="primary-button"
                  onClick={applyStudyRebind}
                  disabled={studyRebindBusy || !studyRebindPreview?.can_apply || studyRebindReason.trim().length < 10 || !studyRebindContentAccepted || !studyRebindApprovalAccepted}
                  title={studyRebindBusy
                    ? "正在重绑定研究定义"
                    : !studyRebindPreview?.can_apply
                      ? "当前重绑定预检尚未通过"
                      : studyRebindReason.trim().length < 10
                        ? "请填写至少10字的研究设计变更原因"
                        : !studyRebindContentAccepted
                          ? "请确认正文不会被系统静默改写"
                          : !studyRebindApprovalAccepted
                            ? "请确认受影响章节的当前冻结将失效"
                            : "确认按当前预检结果重绑定"}
                ><RefreshCw size={15} /> {studyRebindBusy ? "处理中" : "确认重绑定"}</button>
              )}
            </footer>
          </aside>
        </div>
      )}
      {!greenfieldSetupAvailable && templateUpgradeOpen && templateUpgradePreview && (
        <div className="writing-document-map-backdrop" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget && !templateUpgradeBusy) setTemplateUpgradeOpen(false);
        }}>
          <aside className="panel writing-template-upgrade-drawer" role="dialog" aria-modal="true" aria-label="研究方案模板升级预检">
            <header>
              <div>
                <span>模板升级预检</span>
                <strong>{templateUpgradePreview.source_section_count} 个旧节点 → {templateUpgradePreview.target_section_count} 个当前M11节点</strong>
                <small>确认后创建新的文档身份并复制当前有效内容；旧工作副本、保存快照和审计历史不删除。</small>
              </div>
              <button className="icon-button" onClick={() => setTemplateUpgradeOpen(false)} disabled={templateUpgradeBusy} title="关闭模板升级预检"><XCircle size={18} /></button>
            </header>
            <div className="writing-template-upgrade-summary">
              <div><span>映射覆盖</span><strong>{templateUpgradePreview.mapped_source_section_count}/{templateUpgradePreview.source_section_count}</strong></div>
              <div><span>已保存工作副本</span><strong>{templateUpgradePreview.working_copy_count}</strong></div>
              <div><span>合并目标</span><strong>{templateUpgradePreview.consolidation_target_node_ids?.length || 0}</strong></div>
              <div><span>需重新确认</span><strong>{templateUpgradePreview.approval_reset_count}</strong></div>
            </div>
            <div className="writing-template-upgrade-table-wrap">
              <table className="writing-template-upgrade-table">
                <thead><tr><th>旧章节</th><th>内容版本</th><th>当前M11目标</th><th>处理</th></tr></thead>
                <tbody>
                  {(templateUpgradePreview.mappings || []).map((mapping) => (
                    <tr key={mapping.source_section_id}>
                      <td><strong>{mapping.source_heading}</strong><small>{mapping.source_section_key}</small></td>
                      <td>{mapping.source_content_origin === "working_copy" ? `工作副本 v${mapping.source_content_revision}` : "旧基线"}</td>
                      <td><strong>{mapping.target_section_number || "首页"} {mapping.target_heading}</strong><small>{mapping.target_template_node_id}</small></td>
                      <td><Tag tone={mapping.mapping_kind === "consolidated" ? "warning" : "success"}>{mapping.mapping_kind === "consolidated" ? "合并保留" : "直接保留"}</Tag></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="writing-template-upgrade-confirmations">
              {(templateUpgradePreview.consolidation_target_node_ids || []).length > 0 && (
                <label><input type="checkbox" checked={templateUpgradeConsolidationAccepted} onChange={(event) => setTemplateUpgradeConsolidationAccepted(event.target.checked)} /><span>我已核对合并项：旧“研究背景与依据”和“疾病背景”将共同保留在M11“引言”节点中。</span></label>
              )}
              <label><input type="checkbox" checked={templateUpgradeApprovalResetAccepted} onChange={(event) => setTemplateUpgradeApprovalResetAccepted(event.target.checked)} /><span>我理解升级后的全部章节需按新结构重新确认并冻结，旧冻结记录不会自动继承。</span></label>
            </div>
            {templateUpgradeMessage && <p className="working-copy-message danger">{templateUpgradeMessage}</p>}
            <footer>
              <button type="button" onClick={() => setTemplateUpgradeOpen(false)} disabled={templateUpgradeBusy}>取消</button>
              <button
                type="button"
                className="primary-button"
                onClick={applyTemplateUpgrade}
                disabled={templateUpgradeBusy || !templateUpgradeConsolidationAccepted || !templateUpgradeApprovalResetAccepted}
                title={!templateUpgradeConsolidationAccepted || !templateUpgradeApprovalResetAccepted ? "请先逐项确认迁移边界" : "创建当前M11模板文档并保留旧历史"}
              >
                <RefreshCw size={15} /> {templateUpgradeBusy ? "升级中" : "确认升级"}
              </button>
            </footer>
          </aside>
        </div>
      )}
      {contentQualityDockOpen && (
        <section className="writing-content-quality-dock" role="dialog" aria-modal="false" aria-label="源内容核查">
          <header className="writing-content-quality-head">
            <div>
              <ShieldAlert size={18} />
              <strong>源内容核查</strong>
              <span>{section.title}</span>
            </div>
            <div>
              <Tag tone={contentQualityBlockingCount ? "danger" : "success"}>
                {contentQualityBlockingCount ? `${contentQualityBlockingCount} 项阻断正式 Word` : "当前无开放阻断"}
              </Tag>
              <button
                className="icon-button"
                onClick={() => setContentQualityDockOpen(false)}
                title="关闭源内容核查"
                aria-label="关闭源内容核查"
              >
                <XCircle size={18} />
              </button>
            </div>
          </header>
          <div className="writing-content-quality-summary">
            <span><strong>{contentQuality?.finding_count ?? 0}</strong> 本章异常</span>
            <span><strong>{contentQuality?.open_count ?? 0}</strong> 待医学处置</span>
            <span><strong>{contentQuality?.correction_required_count ?? 0}</strong> 需要修正</span>
            <span><strong>{contentQualityConfirmedCount}</strong> 已确认沿用</span>
            <button onClick={() => refreshContentQuality()} disabled={contentQualityLoading} title="重新读取当前章节的已保存内容">
              <RefreshCw size={14} /> {contentQualityLoading ? "读取中" : "刷新"}
            </button>
          </div>
          {contentQualityMessage && (
            <p className={`writing-content-quality-message ${contentQualityMessage.includes("失败") || contentQualityMessage.includes("拒绝") ? "danger" : ""}`}>
              {contentQualityMessage}
            </p>
          )}
          {workingCopyDirty && (
            <p className="writing-content-quality-unsaved">
              当前核查基于最近一次已保存版本；请先保存未提交修订，再处置对应异常。
            </p>
          )}
          {selectedContentFinding ? (
            <div className="writing-content-quality-body">
              <nav className="writing-content-quality-list" aria-label="当前章节源内容异常列表">
                {contentFindings.map((finding) => (
                  <button
                    key={finding.finding_id}
                    className={finding.finding_id === selectedContentFinding.finding_id ? "active" : ""}
                    onClick={() => {
                      setSelectedContentFindingId(finding.finding_id);
                      setContentDispositionReason("");
                      setContentDispositionAcknowledged(false);
                    }}
                    title={finding.source_text}
                  >
                    <span>{finding.rule_label}</span>
                    <strong>{finding.source_text}</strong>
                    <Tag tone={contentDispositionTone(finding.disposition_status)}>
                      {contentDispositionLabel(finding.disposition_status)}
                    </Tag>
                  </button>
                ))}
              </nav>
              <article className="writing-content-quality-detail">
                <section className="writing-content-primary-evidence">
                  <div>
                    <span>当前原文（完整）</span>
                    <Tag tone={contentDispositionTone(selectedContentFinding.disposition_status)}>
                      {contentDispositionLabel(selectedContentFinding.disposition_status)}
                    </Tag>
                  </div>
                  <blockquote>
                    <ContentFindingSourceText finding={selectedContentFinding} />
                  </blockquote>
                  <p><strong>为什么提示：</strong>{selectedContentFinding.finding_reason}</p>
                </section>
                <details className="writing-content-traceability">
                  <summary>溯源信息</summary>
                  <dl>
                    <div><dt>章节</dt><dd>{selectedContentFinding.section_heading}</dd></div>
                    <div><dt>位置类型</dt><dd>{selectedContentFinding.location_kind === "table_cell" ? "表格单元格" : "正文段落"}</dd></div>
                    {selectedContentFinding.table_id && <div><dt>表格 / 单元格</dt><dd>{selectedContentFinding.table_id} / {selectedContentFinding.cell_id || "未返回"}</dd></div>}
                    {Number.isInteger(selectedContentFinding.row_index) && <div><dt>行 / 列</dt><dd>{selectedContentFinding.row_index + 1} / {(selectedContentFinding.cell_index ?? 0) + 1}</dd></div>}
                    <div><dt>来源定位</dt><dd>{selectedContentFinding.source_locator || "当前工作副本稳定标识"}</dd></div>
                    <div><dt>规则</dt><dd>{selectedContentFinding.rule_code} · {selectedContentFinding.detector_version}</dd></div>
                  </dl>
                </details>
                {selectedContentFinding.disposition_revision > 0 && selectedContentFinding.disposition_reason && (
                  <section className="writing-content-prior-disposition">
                    <span>当前医学处置记录</span>
                    <p>{selectedContentFinding.disposition_reason}</p>
                    <small>{selectedContentFinding.disposition_actor || "医学经理"} · {selectedContentFinding.disposition_at ? new Date(selectedContentFinding.disposition_at).toLocaleString("zh-CN", { hour12: false }) : "时间未返回"}</small>
                  </section>
                )}
                <section className="writing-content-disposition-form">
                  <label>
                    本次医学判断理由
                    <textarea
                      value={contentDispositionReason}
                      onChange={(event) => setContentDispositionReason(event.target.value)}
                      placeholder="说明核对了什么、为什么确认沿用或为什么需要修正（至少10个字符）"
                      disabled={contentDispositionBusy || workingCopyDirty}
                    />
                  </label>
                  <label className="writing-content-acknowledgement">
                    <input
                      type="checkbox"
                      checked={contentDispositionAcknowledged}
                      onChange={(event) => setContentDispositionAcknowledged(event.target.checked)}
                      disabled={contentDispositionBusy || workingCopyDirty}
                    />
                    我已阅读完整原文和提示理由；确认沿用只解除当前内容指纹对正式 Word 的阻断，原警示与审计记录继续保留。
                  </label>
                  <div className="writing-content-disposition-actions">
                    <button
                      onClick={() => applyContentDisposition("correction_required")}
                      disabled={contentDispositionBusy || workingCopyDirty || contentDispositionReason.trim().length < 10}
                      title={workingCopyDirty ? "请先保存当前修订" : "标记该原文需要在工作副本中修正"}
                    >
                      <PencilLine size={14} /> 需要修正
                    </button>
                    <button
                      className="primary-button"
                      onClick={() => applyContentDisposition("confirmed_source_text")}
                      disabled={contentDispositionBusy || workingCopyDirty || contentDispositionReason.trim().length < 10 || !contentDispositionAcknowledged}
                      title={!contentDispositionAcknowledged ? "请先确认已阅读完整原文和提示理由" : "在保留警示和审计的前提下确认沿用"}
                    >
                      <CheckCircle2 size={14} /> 确认沿用
                    </button>
                    {selectedContentFinding.disposition_status !== "open" && (
                      <button
                        onClick={() => applyContentDisposition("open")}
                        disabled={contentDispositionBusy || workingCopyDirty || contentDispositionReason.trim().length < 10}
                        title="撤销当前处置并恢复为开放核查"
                      >
                        <RotateCcw size={14} /> 撤销处置
                      </button>
                    )}
                  </div>
                </section>
              </article>
            </div>
          ) : (
            <div className="writing-content-quality-clear">
              <CheckCircle2 size={24} />
              <strong>当前章节未发现已启用规则命中的源内容异常</strong>
              <p>这不代表已完成医学、科学性或跨文件一致性审阅；当前仅报告确定性内容质量规则。</p>
            </div>
          )}
          <footer>
            草稿编辑和草稿预览不受本核查阻断；待医学处置或需要修正的项目会阻断正式 Word。
          </footer>
        </section>
      )}
      {soaCandidatePicker && (
        <div className="rich-table-insert-overlay" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setSoaCandidatePicker(null);
        }}>
          <section
            className="rich-table-insert-dialog"
            role="dialog"
            aria-modal="true"
            aria-label="选择要打开的研究流程表"
            tabIndex={-1}
            ref={soaCandidateDialogRef}
          >
            <header>
              <div>
                <span>研究流程表</span>
                <strong>当前章节有 {soaCandidatePicker.length} 张候选表格</strong>
              </div>
              <button type="button" onClick={() => setSoaCandidatePicker(null)} title="关闭" aria-label="关闭研究流程表选择"><XCircle size={17} /></button>
            </header>
            <div className="rich-table-duplicate-summary">
              <p>请显式选择要打开的一张；系统不会默认打开第一张，也不会改动工作副本。</p>
              {soaCandidatePicker.map((candidate, index) => (
                <button
                  type="button"
                  key={candidate.blockId || index}
                  data-soa-candidate-block-id={candidate.blockId}
                  onClick={() => {
                    setInsertedTableBlockId(candidate.blockId);
                    setSoaCandidatePicker(null);
                  }}
                >
                  <Table2 size={15} />
                  <strong>表格 {index + 1} · {candidate.title || "未命名表格"}</strong>
                  <span>{candidate.structured ? "结构化研究流程表" : "待人工确认映射"}</span>
                </button>
              ))}
              <span>取消、按 Escape 或点击空白处都不会打开任何表格，工作副本保持不变。</span>
              <div>
                <button type="button" onClick={() => setSoaCandidatePicker(null)}>取消</button>
              </div>
            </div>
          </section>
        </div>
      )}
      {documentObjectPicker && (
        <div className="rich-table-insert-overlay" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setDocumentObjectPicker(null);
        }}>
          <section
            className="rich-table-insert-dialog"
            role="dialog"
            aria-modal="true"
            aria-label={`选择要打开的${documentObjectPicker.label}`}
            tabIndex={-1}
            ref={documentObjectDialogRef}
          >
            <header>
              <div>
                <span>{documentObjectPicker.role === "layout" ? "方案首页" : "方案摘要"}</span>
                <strong>请选择要编辑的{documentObjectPicker.label}</strong>
              </div>
              <button type="button" onClick={() => setDocumentObjectPicker(null)} title="关闭" aria-label="关闭对象选择"><XCircle size={17} /></button>
            </header>
            <div className="rich-table-duplicate-summary">
              <p>这些对象共用当前章节工作副本和 Word 导出链，但不会进入正文表格编号或表目录。</p>
              {documentObjectPicker.candidates.map((candidate, index) => (
                <button
                  type="button"
                  key={candidate.blockId || index}
                  data-document-object-block-id={candidate.blockId}
                  onClick={() => {
                    setInsertedTableBlockId(candidate.blockId);
                    setDocumentObjectPicker(null);
                  }}
                >
                  <Table2 size={15} />
                  <strong>{candidate.title}</strong>
                  <span>{candidate.rows} 行 × {candidate.columns || "?"} 列</span>
                </button>
              ))}
              <span>取消、按 Escape 或点击空白处均不会修改工作副本。</span>
              <div><button type="button" onClick={() => setDocumentObjectPicker(null)}>取消</button></div>
            </div>
          </section>
        </div>
      )}
      {soaCreateConfirmOpen && (
        <div className="rich-table-insert-overlay" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setSoaCreateConfirmOpen(false);
        }}>
          <section
            className="rich-table-insert-dialog"
            role="dialog"
            aria-modal="true"
            aria-label="创建研究流程表"
            tabIndex={-1}
            ref={soaCreateDialogRef}
          >
            <header>
              <div>
                <span>研究流程表</span>
                <strong>当前章节还没有研究流程表</strong>
              </div>
              <button type="button" onClick={() => setSoaCreateConfirmOpen(false)} title="关闭" aria-label="关闭创建研究流程表"><XCircle size={17} /></button>
            </header>
            <div className="rich-table-duplicate-summary">
              <p>确认后将在当前已保存工作副本中插入研究流程表模板并自动打开表格设计器；插入会生成新的工作副本版本，原始 DOCX 保持只读。</p>
              {soaCreateGateReason ? <p>{soaCreateGateReason}</p> : null}
              <span>取消或按 Escape 不创建任何表格；只有“创建并打开”会在重新核对全部前置条件后执行插入。</span>
              <div>
                <button type="button" onClick={() => setSoaCreateConfirmOpen(false)}>取消</button>
                <button
                  type="button"
                  className="primary-button"
                  disabled={Boolean(soaCreateGateReason)}
                  data-gate-reason={soaCreateGateReason}
                  title={soaCreateGateReason || "在当前已保存工作副本中创建研究流程表并打开编辑器"}
                  onClick={() => {
                    if (soaCreateGateReason) return;
                    insertTableTemplate("schedule_of_activities");
                    setSoaCreateConfirmOpen(false);
                  }}
                >
                  <Plus size={15} /> 创建并打开
                </button>
              </div>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}

function approvalTypeLabel(targetType, fallback = "") {
  if (targetType === "evidence_picos_snapshot") return "证据调研与方案设计";
  if (targetType?.startsWith("medical_writing")) return "医学写作";
  if (targetType?.startsWith("medical_monitoring")) return "医学监查";
  if (targetType?.startsWith("eligibility_review")) return "入排审核";
  return fallback || "审批事项";
}

function approvalTitle(item, projectLabel = "") {
  const knownTitles = {
    approval_protocol_sec_objectives: "研究目的与终点章节",
    approval_medical_monitoring_batch003: "Batch 003 风险冻结包",
  };
  if (item.target_type === "medical_monitoring_risk_disposition") {
    if (String(item.display_title || "").trim()) return item.display_title.trim();
    const comments = item.review_comments || "";
    const risk = comments.match(/风险：([^；。]+)/)?.[1]?.trim();
    const subject = comments.match(/受试者：([^；。]+)/)?.[1]?.trim();
    const riskText = risk
      ? subject && !risk.includes(subject) ? `${subject} ${risk}` : risk
      : subject;
    const prefix = String(projectLabel || item.project_id || "").trim();
    const title = riskText ? `内部Query草稿审批：${riskText}` : "内部Query草稿审批：医学监查风险处置建议";
    return prefix ? `${prefix} · ${title}` : title;
  }
  if (item.target_type === "medical_writing_revision_thread") return `医学写作修订建议：${item.target_id}`;
  if (item.target_type === "evidence_picos_snapshot") {
    return `PICOS方案设计医学批准${item.target_revision ? `（版本 ${item.target_revision}）` : ""}`;
  }
  return item.display_title || knownTitles[item.approval_id] || item.title || item.target_id || "待医学批准内容";
}

function approvalStateLabel(state) {
  return {
    ai_draft: "待医学批准",
    in_medical_review: "医学审阅中",
    returned_for_revision: "退回修订",
    medically_approved: "已批准",
    locked_for_submission: "已锁定",
    superseded: "已作废",
    archived: "已归档",
  }[state] || state;
}

function normalizeApprovalItem(item, projectLabel = "") {
  if (item.approval_id) {
    const isMonitoringDisposition = item.target_type === "medical_monitoring_risk_disposition";
    const isPicosApproval = item.target_type === "evidence_picos_snapshot";
    return {
      id: item.approval_id,
      title: approvalTitle(item, projectLabel),
      detail: item.display_detail || approvalTypeLabel(item.target_type),
      type: approvalTypeLabel(item.target_type),
      state: approvalStateLabel(item.state),
      rawState: item.state,
      ai: isMonitoringDisposition || item.requested_by === "system" ? "规则运行" : isPicosApproval ? "PICOS用户决策" : "AI 修订",
      risk: isMonitoringDisposition ? "内部审批候选" : isPicosApproval ? "当前快照待医学批准" : item.state === "ai_draft" ? "待查看质量门" : "需质量门确认",
      owner: item.reviewed_by || item.approved_by || "医学经理",
      blockers: [],
      comments: item.review_comments || "",
      internalApprovalBoundary: isMonitoringDisposition
        ? "仅批准内部Query草稿/处置建议，不代表对外Query已执行、风险关闭或归档。"
        : isPicosApproval
          ? "仅批准当前证据资料包与PICOS版本快照；证据或PICOS版本变化后必须重新提交医学批准。"
          : "",
      isMonitoringDisposition,
      isPicosApproval,
    };
  }
  return {
    ...item,
    rawState: item.state,
  };
}

const plannedModuleContent = {
  evidenceDesign: {
    module: "evidence_design",
    eyebrow: "证据与设计",
    title: "证据调研与方案设计",
    status: "原始资料登记与证据索引 P0",
    summary: "面向适应症背景、监管指导原则、竞品目录、竞品方案和临床结果，形成可更新的证据平台，并将待医学确认的 PICOS 设计建议流转到医学写作。",
    inputs: ["CDE/FDA/EMA 指导原则", "ClinicalTrials.gov / CDE 登记", "PubMed / 期刊全文", "竞品 protocol / SAP / medical review", "本地 CRSwNP 竞品调研原文"],
    aiTasks: ["disease_background_research", "competitive_intelligence", "protocol_design_synthesis", "picos_design_coach"],
    next: ["建立证据资料台账", "接入公开检索与本地竞品原文", "形成 PICOS 问答式设计工作流", "与医学写作章节树联动"],
  },
  tfl: {
    module: "data_analysis_tfl",
    eyebrow: "数据分析",
    title: "数据分析与TFL",
    status: "资料登记与数据清单 P0",
    summary: "面向 SDTM/ADaM、define.xml、SAP 和 TFL shells，提供医学经理可读的数据查看、表图清单生成、监管交付和写作引用能力。",
    inputs: ["SDTM XPT/SAS7BDAT", "ADaM XPT/SAS7BDAT", "define.xml", "SAP", "TFL shells / RTF / CSV"],
    aiTasks: ["tfl_generation_assist", "analysis_result_explanation"],
    next: ["盘点 Ruxolitinib-AD 与 MY008 的数据集样本", "建立数据集清单（dataset manifest）", "生成TFL查看页最小版", "将结果摘要供医学写作引用"],
  },
  safety: {
    module: "safety_pv",
    eyebrow: "安全性协同",
    title: "安全信号与PV协同",
    status: "协同复核 P0",
    summary: "本页输出为安全性医学/PV协同候选，不替代PV系统或正式药物警戒流程；以下内容均为待医学/PV确认。",
    inputs: ["安全性listing", "PV提供的个案叙述资料", "DSUR/IB安全更新素材", "安全计划参考资料", "医学监查风险账本"],
    aiTasks: ["safety_case_medical_review", "signal_narrative_synthesis"],
    next: ["确定与医学监查风险账本的边界", "接入安全性资料台账", "建立 SAE/AESI 医学审阅质量门", "联动医学写作 DSUR/IB 模块"],
  },
};

const sourceRegistryCandidates = {
  evidenceDesign: [
    {
      id: "ev-crs-trial-design",
      title: "CRSwNP 竞品试验设计索引",
      kind: "local-file",
      module: "evidence_design",
      projectIds: ["proj_mgk10_crswnp"],
      sourceType: "CSV",
      purpose: "竞品方案设计、终点、样本量和入排标准结构化索引。",
    },
    {
      id: "ev-crs-efficacy",
      title: "CRSwNP 疗效结果索引",
      kind: "local-file",
      module: "evidence_design",
      projectIds: ["proj_mgk10_crswnp"],
      sourceType: "CSV",
      purpose: "PICOS 决策和医学写作主要/次要终点证据。",
    },
    {
      id: "ev-crs-safety",
      title: "CRSwNP 安全性结果索引",
      kind: "local-file",
      module: "evidence_design",
      projectIds: ["proj_mgk10_crswnp"],
      sourceType: "CSV",
      purpose: "竞品安全性结局、AESI 和安全章节证据。",
    },
    {
      id: "ev-crs-document-index",
      title: "CRSwNP 原文索引",
      kind: "local-file",
      module: "evidence_design",
      projectIds: ["proj_mgk10_crswnp"],
      sourceType: "CSV",
      purpose: "追踪 protocol、SAP、publication 和监管原文路径。",
    },
  ],
  tfl: [
    {
      id: "tfl-rux-listing",
      title: "RUX-03-002 项目级 listing",
      kind: "local-file",
      module: "data_analysis_tfl",
      projectIds: ["proj_rux_03_002"],
      sourceType: "XLSX",
      purpose: "跨项目字段识别、数据集查看和医学解释样本。",
    },
    {
      id: "tfl-rux-sdtm-package",
      title: "RUX-03-002 SDTM 数据包",
      kind: "local-directory",
      module: "data_analysis_tfl",
      projectIds: ["proj_rux_03_002"],
      sourceKind: "tfl_dataset_package_inventory",
      sourceType: "Directory",
      purpose: "XPT、define、aCRF 和 reviewer guide 的 dataset manifest 起点。",
    },
    {
      id: "tfl-rux-final-tfl",
      title: "RUX-03-002 SAR 与 TFL 包",
      kind: "local-directory",
      module: "data_analysis_tfl",
      projectIds: ["proj_rux_03_002"],
      sourceKind: "tfl_output_package_inventory",
      sourceType: "Directory",
      purpose: "最终 TFL、adhoc TLF 和写作引用链路。",
    },
  ],
  safety: [
    {
      id: "pv-my009-mm-listing",
      title: "MY009 UC 医学复核 listing",
      kind: "local-file",
      module: "safety_pv",
      projectIds: ["proj_my009_uc"],
      sourceType: "XLSX",
      purpose: "AE、实验室、合并用药和医学复核安全样本。",
    },
    {
      id: "pv-my009-safety-package",
      title: "MY009 UC S1 安全评估包",
      kind: "local-directory",
      module: "safety_pv",
      projectIds: ["proj_my009_uc"],
      sourceKind: "safety_signal_package_inventory",
      sourceType: "Directory",
      purpose: "安全评估报告、AE TFL、比较表和演示材料登记。",
    },
    {
      id: "pv-my009-dsur",
      title: "MY009 DSUR 医学资料收集表",
      kind: "local-file",
      module: "safety_pv",
      projectIds: ["proj_my009_uc"],
      sourceType: "DOCX",
      purpose: "DSUR/IB 安全更新和医学-PV 协同字段样本。",
    },
    {
      id: "pv-rux-pv-plan",
      title: "RUX-03-002 PV计划包",
      kind: "local-directory",
      module: "safety_pv",
      projectIds: ["proj_rux_03_002"],
      sourceKind: "pv_safety_package_inventory",
      sourceType: "Directory",
      purpose: "安全管理计划、PV 协同边界和质量门依据。",
    },
    {
      id: "pv-rux-274",
      title: "RUX-03-002 2.7.4安全总结",
      kind: "local-directory",
      module: "safety_pv",
      projectIds: ["proj_rux_03_002"],
      sourceKind: "clinical_safety_summary_inventory",
      sourceType: "Directory",
      purpose: "安全性总结、实验室和 AE 风险解释的监管交付依据。",
    },
  ],
};

function TflManifestPanel({
  projectId,
  manifest,
  loading,
  message,
  onRefresh,
  selectedPackageId,
  onSelectPackage,
  reviewWorkbench,
  reviewLoading,
  reviewMessage,
  selectedOutputId,
  onSelectOutput,
  onRefreshReview,
  onApplyReviewAction,
  applyingReviewAction,
}) {
  const packages = manifest?.packages || [];
  const selectedPackage = packages.find((item) => item.package_id === selectedPackageId) || packages[0];
  const [reviewComment, setReviewComment] = useState("");
  const qualityGaps = packages.reduce((count, item) => count + (item.define_itemgroup_count ? 0 : 1), 0);
  const datasetPreview = selectedPackage
    ? [...selectedPackage.datasets]
        .sort((left, right) => {
          const parsedDelta = Number(right.parser_status === "parsed") - Number(left.parser_status === "parsed");
          if (parsedDelta) return parsedDelta;
          return `${left.standard}${left.dataset_name}`.localeCompare(`${right.standard}${right.dataset_name}`);
        })
        .slice(0, 12)
    : [];
  const outputPreview = selectedPackage ? selectedPackage.outputs.slice(0, 12) : [];
  const warnings = selectedPackage?.parser_warnings?.slice(0, 5) || [];
  const selectedTflCounts = selectedPackage?.tfl_count_by_type || {};
  const tflCountText = `表${selectedTflCounts.table || 0} / 图${selectedTflCounts.figure || 0} / Listing${selectedTflCounts.listing || 0}`;
  const reviewOutput = reviewWorkbench?.selected_output;
  const reviewDataset = reviewWorkbench?.paired_dataset;
  const reviewCandidates = reviewWorkbench?.candidate_outputs || [];
  const reviewGates = reviewWorkbench?.quality_gates || [];
  const reviewRecords = reviewWorkbench?.review_records || [];
  const datasetContext = reviewWorkbench?.dataset_context || [];
  const reviewStatus = reviewWorkbench?.current_status || "待医学审阅";
  const sourceAdmission = reviewWorkbench?.source_admission;
  const sourceAdmissionReady = Boolean(sourceAdmission?.ready_for_use);
  const writingCandidateAllowed = Boolean(reviewDataset) && reviewStatus === "医学已审阅" && sourceAdmissionReady;
  const actionOrder = [
    "mark_reviewed",
    "request_statistical_review",
    "create_writing_candidate",
    "return_for_dataset_check",
    "reset_review",
  ];

  useEffect(() => {
    setReviewComment("");
  }, [reviewWorkbench?.selected_output_id]);

  const submitReviewAction = (action) => {
    onApplyReviewAction(action, reviewComment).then((ok) => {
      if (ok) setReviewComment("");
    });
  };

  return (
    <section className="panel tfl-manifest-panel">
      <SectionTitle
        title="数据集清单与TFL交付清单"
        action={<button onClick={onRefresh} disabled={loading} title={loading ? "TFL清单正在生成" : "刷新数据集与TFL交付清单"}>{loading ? "生成中" : "刷新清单"}</button>}
      />
      <div className="tfl-manifest-stats">
        <div><strong>{manifest?.package_count || 0}</strong><span>真实交付包</span></div>
        <div><strong>{formatMaybeNumber(manifest?.total_datasets)}</strong><span>数据文件</span></div>
        <div><strong>{formatMaybeNumber(manifest?.total_outputs)}</strong><span>TFL RTF输出</span></div>
        <div className={qualityGaps ? "warning" : ""}><strong>{qualityGaps}</strong><span>define缺口包</span></div>
      </div>
      {message && <div className="source-registry-message">{message}</div>}
      <div className="tfl-package-tabs">
        {packages.map((item) => (
          <button
            key={item.package_id}
            className={item.package_id === selectedPackage?.package_id ? "active" : ""}
            onClick={() => onSelectPackage(item.package_id)}
          >
            {item.package_label}
          </button>
        ))}
      </div>
      {selectedPackage ? (
        <>
          <div className="tfl-package-summary">
            <div><span>数据目录</span><strong>{selectedPackage.dataset_root_label}</strong></div>
            <div><span>TFL目录</span><strong>{selectedPackage.tfl_root_label}</strong></div>
            <div><span>define.xml</span><strong>{selectedPackage.define_xml_count} 个文件 / {selectedPackage.define_itemgroup_count} 个数据集定义</strong></div>
            <div><span>TFL输出</span><strong>{tflCountText}</strong></div>
            <div><span>目录角色</span><strong>{Object.entries(selectedPackage.dataset_count_by_role).map(([key, value]) => `${key}:${value}`).join("；") || "未识别"}</strong></div>
          </div>
          <div className="tfl-quality-gates">
            <Tag tone={selectedPackage.define_itemgroup_count ? "success" : "warning"}>
              {selectedPackage.define_itemgroup_count ? "define已关联" : "define缺失/未提供"}
            </Tag>
            <Tag tone={Object.values(selectedPackage.tfl_count_by_type).length ? "success" : "warning"}>TFL输出已登记</Tag>
            <Tag tone="warning">不生成正式TFL</Tag>
            <Tag tone="neutral">待医学确认</Tag>
          </div>
          {warnings.length ? (
            <div className="tfl-warning-list">
              {warnings.map((warning) => <span key={warning}>{warning}</span>)}
            </div>
          ) : null}
          <ModuleSourceAdmissionBand
            projectId={projectId}
            admission={sourceAdmission}
            loading={reviewLoading}
            onRefresh={onRefreshReview}
            contextLabel="TFL审阅"
          />
          <div className="tfl-review-workbench">
            <SectionTitle
              title="TFL审阅工作台"
              action={<button onClick={onRefreshReview} disabled={reviewLoading || !selectedPackage} title={!selectedPackage ? "请先选择真实TFL资料包" : reviewLoading ? "审阅工作台正在读取" : "刷新TFL审阅状态"}>{reviewLoading ? "读取中" : "刷新审阅状态"}</button>}
            />
            <div className="tfl-review-boundary">
              {reviewWorkbench?.formal_output_boundary || "当前仅形成待医学确认的数据审阅和写作引用候选，不生成正式监管TFL。"}
            </div>
            {reviewMessage && <div className="source-registry-message">{reviewMessage}</div>}
            <div className="tfl-review-focus">
              <div><span>当前审阅状态</span><strong>{reviewStatus}</strong></div>
              <div><span>当前TFL对象</span><strong>{reviewOutput?.display_id || "未选择"}</strong></div>
              <div><span>类型/领域</span><strong>{reviewOutput ? `${tflOutputTypeLabel(reviewOutput.output_type)} / ${reviewOutput.domain_hint || "领域待识别"}` : "未选择"}</strong></div>
              <div><span>配对数据集</span><strong>{reviewDataset ? `${reviewDataset.dataset_name}（${reviewDataset.row_count ?? "未读"}行）` : "未识别，需复核"}</strong></div>
            </div>
            <div className="tfl-review-grid">
              <div className="tfl-review-selector">
                <h3>候选TFL输出</h3>
                <div className="tfl-review-candidate-list">
                  {reviewCandidates.length ? reviewCandidates.map((output) => (
                    <button
                      key={output.output_id}
                      className={output.output_id === (selectedOutputId || reviewWorkbench?.selected_output_id) ? "active" : ""}
                      onClick={() => onSelectOutput(output.output_id)}
                    >
                      <strong>{output.display_id}</strong>
                      <span>{tflOutputTypeLabel(output.output_type)} · {output.domain_hint || "领域待识别"} · {output.paired_file_id ? "已配对" : "未配对"}</span>
                    </button>
                  )) : <div className="empty-state">当前包尚未识别可审阅TFL输出。</div>}
                </div>
              </div>
              <div className="tfl-review-detail">
                <h3>质量门与处置意见</h3>
                <div className="tfl-review-gates">
                  {reviewGates.map((gate) => (
                    <div key={gate.gate_id}>
                      <Tag tone={safetyGateTone(gate.status)}>{gateStatusLabel(gate.status)}</Tag>
                      <strong>{gate.gate_label}</strong>
                      <span>{gate.detail}</span>
                    </div>
                  ))}
                </div>
                <label className="tfl-review-comment">
                  <span>本次医学/统计处理意见</span>
                  <textarea
                    value={reviewComment}
                    onChange={(event) => setReviewComment(event.target.value)}
                    placeholder="填写审阅依据、需统计复核的问题或允许进入写作引用候选的边界。"
                    rows={4}
                  />
                </label>
                <div className="tfl-review-actions">
                  {actionOrder.map((action) => {
                    const needsComment = action !== "reset_review";
                    const requiresSourceAdmission = ["mark_reviewed", "create_writing_candidate"].includes(action);
                    const disabled = reviewLoading ||
                      Boolean(applyingReviewAction) ||
                      !reviewOutput ||
                      (needsComment && !reviewComment.trim()) ||
                      (requiresSourceAdmission && !sourceAdmissionReady) ||
                      (action === "create_writing_candidate" && !writingCandidateAllowed);
                    return (
                      <button
                        key={action}
                        className={action === "mark_reviewed" ? "primary-button" : ""}
                        onClick={() => submitReviewAction(action)}
                        disabled={disabled}
                        title={!sourceAdmissionReady && requiresSourceAdmission ? "需先完成当前来源的内容核验或确认沿用" : tflReviewActionLabel(action)}
                      >
                        {applyingReviewAction === action ? "处理中" : tflReviewActionLabel(action)}
                      </button>
                    );
                  })}
                </div>
                {!writingCandidateAllowed && (
                  <p className="tfl-review-hint">标记写作引用候选须同时满足：来源已准入、已配对数据集，并基于当前来源版本完成医学审阅。</p>
                )}
              </div>
            </div>
            <div className="tfl-review-support-grid">
              <div className="tfl-table-block">
                <h3>配套数据集上下文</h3>
                <div className="tfl-table-scroll tfl-review-dataset-table">
                  <table>
                    <thead>
                      <tr>
                        <th>数据集</th>
                        <th>标准/角色</th>
                        <th>域</th>
                        <th>行/变量</th>
                        <th>关键变量</th>
                        <th>define</th>
                      </tr>
                    </thead>
                    <tbody>
                      {datasetContext.map((dataset) => (
                        <tr key={dataset.dataset_id}>
                          <td><strong>{dataset.dataset_name}</strong><span>{dataset.relative_path}</span></td>
                          <td>{dataset.standard} / {dataset.package_role}</td>
                          <td>{dataset.domain || dataset.class_name || "未识别"}</td>
                          <td>{formatMaybeNumber(dataset.row_count)} / {formatMaybeNumber(dataset.column_count)}</td>
                          <td>{dataset.key_variables.slice(0, 6).join(", ") || "待解析"}</td>
                          <td>{dataset.define_linked ? "已关联" : "未关联"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
              <div className="tfl-review-audit">
                <h3>审阅轨迹</h3>
                {reviewRecords.length ? reviewRecords.map((record) => (
                  <div key={record.record_id}>
                    <Tag tone={record.new_status === "写作引用候选" || record.new_status === "医学已审阅" ? "success" : "warning"}>
                      {record.new_status}
                    </Tag>
                    <strong>{tflReviewActionLabel(record.action)}</strong>
                    <span>{record.actor} · {new Date(record.created_at).toLocaleString("zh-CN")}</span>
                    <p>{record.comment || "未填写意见"}</p>
                  </div>
                )) : <div className="empty-state">尚无审阅动作记录。</div>}
              </div>
            </div>
          </div>
          <div className="tfl-manifest-grid">
            <div className="tfl-table-block">
              <h3>数据集清单（dataset manifest）</h3>
              <div className="tfl-table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>数据集</th>
                      <th>标准</th>
                      <th>角色</th>
                      <th>域/类别</th>
                      <th>行数</th>
                      <th>变量数</th>
                      <th>关键变量</th>
                      <th>define</th>
                      <th>解析状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {datasetPreview.map((dataset) => (
                      <tr key={dataset.dataset_id}>
                        <td><strong>{dataset.dataset_name}</strong><span>{dataset.relative_path}</span></td>
                        <td>{dataset.standard}</td>
                        <td>{dataset.package_role}</td>
                        <td>{dataset.domain || dataset.class_name || "未识别"}</td>
                        <td>{formatMaybeNumber(dataset.row_count)}</td>
                        <td>{formatMaybeNumber(dataset.column_count)}</td>
                        <td>{dataset.key_variables.slice(0, 5).join(", ") || "待解析"}</td>
                        <td>{dataset.define_linked ? "已关联" : "未关联"}</td>
                        <td>{parserStatusDisplay(dataset.parser_status)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="tfl-table-block">
              <h3>TFL清单</h3>
              <div className="tfl-table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>编号</th>
                      <th>类型</th>
                      <th>领域</th>
                      <th>标题线索</th>
                      <th>配对数据</th>
                      <th>文件</th>
                      <th>状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {outputPreview.map((output) => (
                      <tr key={output.output_id}>
                        <td><strong>{output.display_id}</strong></td>
                        <td>{tflOutputTypeLabel(output.output_type)}</td>
                        <td>{output.domain_hint || "未识别"}</td>
                        <td>{output.title_hint || "待抽取"}</td>
                        <td>{output.paired_file_id ? "已配对" : "未配对"}</td>
                        <td><span>{output.relative_path}</span></td>
                        <td>{parserStatusDisplay(output.parser_status)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
          <div className="tfl-note-list">
            {selectedPackage.traceability_notes.map((note) => <span key={note}>{note}</span>)}
          </div>
        </>
      ) : (
        <div className="empty-state">尚未生成数据集与TFL清单。</div>
      )}
    </section>
  );
}

function SafetyRiskProjection({ riskIndex, loading, error, onOpenMonitoringRisk }) {
  const actionRows = monitoringRiskRowsFromInbox({ items: riskIndex?.work_items || [] }, "");
  const rows = riskIndexRowsFromApi(riskIndex, actionRows);
  const severityCounts = rows.reduce((counts, risk) => ({ ...counts, [risk.severity]: (counts[risk.severity] || 0) + 1 }), {});
  const subjects = new Set(rows.map((risk) => risk.subject).filter((value) => value && value !== "-"));
  const sites = new Set(rows.map((risk) => risk.site).filter((value) => value && value !== "-"));
  return (
    <section className="panel safety-risk-projection">
      <div className="safety-risk-projection-head">
        <div>
          <strong>安全性医学风险只读投影</strong>
          <span>复用医学监查中的同一风险编号、来源、状态和审计；风险处置仍在医学监查完成。</span>
        </div>
        <Tag tone="info">只读投影</Tag>
      </div>
      <div className="safety-risk-summary">
        <div><strong>{rows.length}</strong><span>Safety/PV关注风险</span></div>
        <div className="danger"><strong>{severityCounts.critical || 0}</strong><span>紧急</span></div>
        <div className="warning"><strong>{severityCounts.high || 0}</strong><span>高</span></div>
        <div><strong>{sites.size}</strong><span>涉及中心</span></div>
        <div><strong>{subjects.size}</strong><span>涉及受试者</span></div>
      </div>
      {error && <p className="gate-error">{error}</p>}
      {loading ? <div className="empty-state">正在读取当前项目安全性医学风险。</div> : (
        rows.length || error ? (
          <MedicalMonitoringRiskChecklist
            rows={rows}
            selectedRiskId=""
            onSelect={onOpenMonitoringRisk}
            taxonomy={riskIndex?.taxonomy}
            total={rows.length}
          />
        ) : <div className="empty-state">当前项目没有带Safety/PV关注标签的开放医学风险；这不等同于项目不存在安全性风险。</div>
      )}
    </section>
  );
}

function SafetyPvManifestPanel({
  projectId,
  manifest,
  loading,
  message,
  onRefresh,
  selectedPackageId,
  onSelectPackage,
  selectedSignalId,
  onSelectSignal,
  reviewWorkbench,
  reviewLoading,
  reviewMessage,
  reviewComment,
  setReviewComment,
  onRefreshReview,
  onReviewAction,
  applyingReviewAction,
  handoffManifest,
  onRefreshHandoff,
  selectionLocked,
}) {
  const packages = manifest?.packages || [];
  const selectedPackage = packages.find((item) => item.package_id === selectedPackageId) || packages[0];
  const domains = selectedPackage ? selectedPackage.listing_domains.slice(0, 14) : [];
  const documents = selectedPackage ? selectedPackage.documents.slice(0, 10) : [];
  const candidates = (reviewWorkbench?.candidate_signals?.length ? reviewWorkbench.candidate_signals : selectedPackage?.signal_candidates || []).slice(0, 24);
  const selectedSignal = reviewWorkbench?.selected_signal || candidates.find((item) => item.signal_id === selectedSignalId) || candidates[0];
  const gates = selectedPackage ? selectedPackage.quality_gates : [];
  const reviewGates = reviewWorkbench?.quality_gates || [];
  const reviewRecords = reviewWorkbench?.review_records || [];
  const handoffCandidates = handoffManifest?.candidates || [];
  const monitoringHandoffs = handoffManifest?.monitoring_collaborations || [];
  const handoffGates = handoffManifest?.quality_gates || [];
  const warnings = selectedPackage?.parser_warnings?.slice(0, 4) || [];
  const actionOrder = [
    "mark_medical_reviewed",
    "request_pv_confirmation",
    "return_for_source_check",
    "accept_no_action",
    "reset_review",
  ];
  const latestReviewStatus = reviewRecords.length ? reviewRecords[reviewRecords.length - 1].new_status : "";
  const currentStatus = reviewWorkbench?.current_status || latestReviewStatus || selectedSignal?.confirmation_status || "待医学/PV确认";
  const availableActions = new Set(reviewWorkbench?.available_actions || []);
  const sourceAdmission = reviewWorkbench?.source_admission;
  const sourceAdmissionReady = Boolean(sourceAdmission?.ready_for_use);
  const canRequestPv = currentStatus === "医学已复核" && sourceAdmissionReady;

  const submitReviewAction = (action) => {
    onReviewAction(action, reviewComment);
  };

  return (
    <section className="panel tfl-manifest-panel safety-pv-panel">
      <SectionTitle
        title="安全信号审阅工作台"
        action={<button onClick={onRefresh} disabled={loading} title={loading ? "安全资料清单正在生成" : "刷新安全资料包与信号候选"}>{loading ? "生成中" : "刷新安全资料清单"}</button>}
      />
      <div className="safety-pv-boundary">
        以下内容为待医学/PV确认的安全信号审阅记录和协同交接候选，不构成最终安全性结论或监管递交意见；报告性判断和递交流程由PV流程确认。
      </div>
      <div className="safety-pv-stats">
        <div><strong>{manifest?.package_count || 0}</strong><span>真实安全资料包</span></div>
        <div><strong>{formatMaybeNumber(manifest?.total_listing_domains)}</strong><span>listing域</span></div>
        <div><strong>{formatMaybeNumber(manifest?.total_documents)}</strong><span>安全资料文件</span></div>
        <div><strong>{formatMaybeNumber(manifest?.total_signal_candidates)}</strong><span>待确认候选</span></div>
        <div><strong>{formatMaybeNumber(manifest?.quality_gate_count)}</strong><span>质量门</span></div>
      </div>
      {message && <div className="source-registry-message">{message}</div>}
      <div className="tfl-package-tabs">
        {packages.map((item) => (
          <button
            key={item.package_id}
            className={item.package_id === selectedPackage?.package_id ? "active" : ""}
            onClick={() => onSelectPackage(item.package_id)}
            disabled={selectionLocked}
            title={selectionLocked ? "正在保存当前信号的医学处置，暂不能切换资料包" : `切换到${item.package_label}`}
          >
            {item.package_label}
          </button>
        ))}
      </div>
      {selectedPackage ? (
        <>
          <div className="tfl-package-summary safety-package-summary">
            <div><span>项目</span><strong>{selectedPackage.project_code}</strong></div>
            <div><span>资料包</span><strong>{selectedPackage.source_root_label}</strong></div>
            <div><span>资料角色</span><strong>{selectedPackage.package_role}</strong></div>
            <div><span>listing / 文件</span><strong>{selectedPackage.listing_domains.length} 个域 / {selectedPackage.documents.length} 个文件</strong></div>
            <div><span>候选 / 质量门</span><strong>{selectedPackage.signal_candidates.length} 个候选 / {selectedPackage.quality_gates.length} 个质量门</strong></div>
          </div>
          <div className="tfl-quality-gates">
            <Tag tone="warning">待医学/PV确认</Tag>
            <Tag tone="neutral">不替代PV系统</Tag>
            <Tag tone={selectedPackage.listing_domains.length ? "success" : "warning"}>安全域已登记</Tag>
            <Tag tone={selectedPackage.documents.length ? "success" : "warning"}>源资料已登记</Tag>
          </div>
          {warnings.length ? (
            <div className="tfl-warning-list">
              {warnings.map((warning) => <span key={warning}>{warning}</span>)}
            </div>
          ) : null}
          <ModuleSourceAdmissionBand
            projectId={projectId}
            admission={sourceAdmission}
            loading={reviewLoading}
            onRefresh={onRefreshReview}
            contextLabel="安全信号审阅与PV协同"
          />
          <div className="safety-review-workbench">
            <div className="safety-review-head">
              <div>
                <h3>安全信号审阅工作台</h3>
                <p>{reviewWorkbench?.formal_output_boundary || "当前仅形成待医学/PV确认的审阅记录和交接候选。"}</p>
              </div>
              <div className="safety-review-head-actions">
                <Tag tone={currentStatus === "PV确认候选" ? "success" : currentStatus === "退回补充资料" ? "warning" : "info"}>{currentStatus}</Tag>
                <Tag tone="neutral">不替代PV系统</Tag>
                <button onClick={onRefreshHandoff}>刷新交接候选</button>
              </div>
            </div>
            {reviewMessage && <div className="source-registry-message">{reviewMessage}</div>}
            <div className="safety-review-grid">
              <aside className="safety-review-selector">
                <h3>候选安全信号</h3>
                <div className="safety-review-candidate-list">
                  {candidates.map((candidate) => (
                    <button
                      key={candidate.signal_id}
                      className={candidate.signal_id === reviewWorkbench?.selected_signal_id ? "active" : ""}
                      onClick={() => onSelectSignal(candidate.signal_id)}
                      disabled={selectionLocked}
                      title={selectionLocked ? "正在保存当前信号的医学处置，暂不能切换候选" : `审阅${candidate.signal_label}`}
                    >
                      <span>{candidate.signal_label}</span>
                      <strong>{candidate.title}</strong>
                      <em>{candidate.source_domains.slice(0, 4).join(" / ") || "来源待补充"}</em>
                      <Tag tone={statusClass(candidate.severity)}>{severityLabel(candidate.severity)}</Tag>
                    </button>
                  ))}
                </div>
              </aside>
              <section className="safety-review-detail">
                <div className="safety-signal-summary">
                  <Tag tone={statusClass(selectedSignal?.severity)}>{severityLabel(selectedSignal?.severity)}</Tag>
                  <h3>{selectedSignal?.title || "请选择安全信号候选"}</h3>
                  <p>{selectedSignal?.observation || "等待读取候选详情。"}</p>
                  <div className="safety-source-facts">
                    {(reviewWorkbench?.listing_context || []).slice(0, 4).map((domain) => (
                      <div key={domain.domain_id}>
                        <Tag tone="info">原始listing</Tag>
                        <strong>{domain.sheet_name} · {domain.domain_label}</strong>
                        <span>{domain.row_count}条记录 · {domain.subject_count}例受试者 · {domain.site_count}个中心</span>
                        <small>{domain.key_fields.slice(0, 6).join("、") || "关键字段待识别"}</small>
                      </div>
                    ))}
                    {(reviewWorkbench?.document_context || []).slice(0, 4).map((document, index) => (
                      <div key={`${document.document_id}:${document.public_title}:${index}`}>
                        <Tag tone="neutral">原始文件</Tag>
                        <strong>{document.public_title}</strong>
                        <span>{document.document_type} · {document.file_format}</span>
                        <small>{document.key_topics.slice(0, 5).join("、") || document.role_hint || "文件级资料"}</small>
                      </div>
                    ))}
                  </div>
                  <details className="safety-source-locators">
                    <summary>查看来源定位</summary>
                    <div>{(selectedSignal?.evidence_locators || []).slice(0, 8).map((locator) => <span key={locator}>{locator}</span>)}</div>
                  </details>
                </div>
                <div className="safety-review-gates">
                  {reviewGates.map((gate) => (
                    <div key={gate.gate_id}>
                      <Tag tone={safetyGateTone(gate.status)}>{gateStatusLabel(gate.status)}</Tag>
                      <strong>{gate.gate_label}</strong>
                      <span>{gate.detail}</span>
                    </div>
                  ))}
                </div>
                <label className="safety-review-comment">
                  <span>医学意见与协同说明</span>
                  <textarea
                    value={reviewComment}
                    onChange={(event) => setReviewComment(event.target.value)}
                    placeholder="填写本次医学复核理由、来源定位、需PV确认的问题或退回补充资料要求。"
                    rows={4}
                  />
                </label>
                <div className="safety-review-actions">
                  {actionOrder.map((action) => {
                    const needsComment = true;
                    const actionAllowed = availableActions.has(action);
                    const requiresSourceAdmission = ["mark_medical_reviewed", "request_pv_confirmation", "accept_no_action"].includes(action);
                    const disabled = reviewLoading ||
                      Boolean(applyingReviewAction) ||
                      !selectedSignal ||
                      !actionAllowed ||
                      (needsComment && !reviewComment.trim()) ||
                      (requiresSourceAdmission && !sourceAdmissionReady) ||
                      (action === "request_pv_confirmation" && !canRequestPv);
                    const actionLabel = action === "accept_no_action" && currentStatus === "PV确认候选"
                      ? "撤回PV候选并关闭"
                      : safetyReviewActionLabel(action);
                    return (
                      <button
                        key={action}
                        className={action === "mark_medical_reviewed" ? "primary-button" : ""}
                        disabled={disabled}
                        title={!actionAllowed ? `当前“${currentStatus}”状态不可执行该动作` : !sourceAdmissionReady && requiresSourceAdmission ? "需先完成当前来源的内容核验或确认沿用" : disabled ? "请选择安全信号并填写本次医学复核意见；正在处理时不可重复提交" : actionLabel}
                        onClick={() => submitReviewAction(action)}
                      >
                        {applyingReviewAction === action ? "处理中" : actionLabel}
                      </button>
                    );
                  })}
                </div>
                {!canRequestPv && <p className="safety-review-hint">标记PV协同确认前，需要来源已准入，并基于当前来源版本保存医学意见形成“医学已复核”状态。</p>}
              </section>
              <aside className="safety-review-side">
                <section className="safety-review-audit">
                  <h3>审计记录</h3>
                  {reviewRecords.length ? reviewRecords.map((record) => (
                    <div className="safety-review-record" key={record.record_id}>
                      <Tag tone={record.new_status === "PV确认候选" || record.new_status === "医学已复核" ? "success" : "warning"}>{record.new_status}</Tag>
                      <strong>{safetyReviewActionLabel(record.action)}</strong>
                      <span>{record.actor} · {new Date(record.created_at).toLocaleString("zh-CN")}</span>
                      <p>{record.comment || "未填写意见"}</p>
                    </div>
                  )) : <div className="empty-state">尚无审阅动作记录。</div>}
                </section>
                <section className="safety-handoff-panel">
                  <h3>PV协同交接候选</h3>
                  <div className="safety-handoff-gates">
                    {handoffGates.map((gate) => (
                      <Tag key={gate.gate_id} tone={safetyGateTone(gate.status)}>{gate.gate_label}</Tag>
                    ))}
                  </div>
                  {monitoringHandoffs.length ? monitoringHandoffs.slice(0, 6).map((handoff) => (
                    <div className={`safety-handoff-card monitoring ${handoff.is_current ? "" : "stale"}`} key={handoff.handoff_id}>
                      <Tag tone={handoff.is_current ? statusClass(handoff.severity) : "warning"}>
                        {handoff.is_current ? "医学监查协作" : "需重新复核"}
                      </Tag>
                      <strong>{handoff.title}</strong>
                      <span>{handoff.subject_id} · {handoff.rule_id}</span>
                      <p>{handoff.is_current ? handoff.review_comment : handoff.stale_reason}</p>
                    </div>
                  )) : null}
                  {handoffCandidates.length ? handoffCandidates.slice(0, 6).map((candidate) => (
                    <div className="safety-handoff-card" key={candidate.candidate_id}>
                      <Tag tone={statusClass(candidate.severity)}>{severityLabel(candidate.severity)}</Tag>
                      <strong>{candidate.title}</strong>
                      <span>{candidate.recommended_handoff_sections.join(" / ")}</span>
                      <p>{candidate.review_comment}</p>
                    </div>
                  )) : monitoringHandoffs.length ? null : <div className="empty-state">暂无PV协同交接候选。</div>}
                </section>
              </aside>
            </div>
          </div>
          <div className="tfl-manifest-grid">
            <div className="tfl-table-block">
              <h3>安全listing域清单</h3>
              <div className="tfl-table-scroll safety-domain-table">
                <table>
                  <thead>
                    <tr>
                      <th>域</th>
                      <th>医学标签</th>
                      <th>安全性用途</th>
                      <th>记录数</th>
                      <th>受试者</th>
                      <th>中心</th>
                      <th>关键字段</th>
                      <th>状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {domains.map((domain) => (
                      <tr key={domain.domain_id}>
                        <td><strong>{domain.sheet_name}</strong><span>{domain.domain}</span></td>
                        <td>{domain.domain_label}</td>
                        <td>{domain.safety_relevance}</td>
                        <td>{formatMaybeNumber(domain.row_count)}</td>
                        <td>{formatMaybeNumber(domain.subject_count)}</td>
                        <td>{formatMaybeNumber(domain.site_count)}</td>
                        <td>{domain.key_fields.slice(0, 6).join(", ") || "待识别"}</td>
                        <td>{parserStatusDisplay(domain.parser_status)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="tfl-table-block">
              <h3>安全资料文件</h3>
              <div className="tfl-table-scroll safety-doc-table">
                <table>
                  <thead>
                    <tr>
                      <th>资料</th>
                      <th>类型</th>
                      <th>用途</th>
                      <th>主题</th>
                      <th>状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {documents.map((document, index) => (
                      <tr key={`${document.document_id}:${document.relative_path || document.public_title}:${index}`}>
                        <td><strong>{document.public_title}</strong><span>{document.relative_path}</span></td>
                        <td>{document.file_format}</td>
                        <td>{document.role_hint}</td>
                        <td>{document.key_topics.slice(0, 3).join(" / ")}</td>
                        <td>{parserStatusDisplay(document.parser_status)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
          <div className="tfl-table-block safety-wide-block">
            <h3>安全信号候选复核表</h3>
            <div className="tfl-table-scroll safety-candidate-table">
              <table>
                <thead>
                  <tr>
                    <th>候选类型</th>
                    <th>标题</th>
                    <th>优先级</th>
                    <th>来源域</th>
                    <th>观察</th>
                    <th>医学/PV边界</th>
                    <th>下一步</th>
                    <th>状态</th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.map((candidate) => (
                    <tr key={candidate.signal_id}>
                      <td><strong>{candidate.signal_label}</strong><span>{candidate.signal_type}</span></td>
                      <td>{candidate.title}</td>
                      <td><Tag tone={statusClass(candidate.severity)}>{severityLabel(candidate.severity)}</Tag></td>
                      <td>{candidate.source_domains.slice(0, 5).join(" / ")}</td>
                      <td>{candidate.observation}</td>
                      <td>{candidate.medical_pv_boundary}</td>
                      <td>{candidate.recommended_next_step}</td>
                      <td>{candidate.confirmation_status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <div className="tfl-table-block safety-wide-block">
            <h3>PV协同质量门</h3>
            <div className="tfl-table-scroll safety-gate-table">
              <table>
                <thead>
                  <tr>
                    <th>质量门</th>
                    <th>状态</th>
                    <th>负责角色</th>
                    <th>说明</th>
                    <th>来源</th>
                  </tr>
                </thead>
                <tbody>
                  {gates.map((gate) => (
                    <tr key={gate.gate_id}>
                      <td><strong>{gate.gate_label}</strong></td>
                      <td><Tag tone={safetyGateTone(gate.status)}>{gate.status === "ok" ? "通过" : gate.status === "warning" ? "需确认" : "阻断"}</Tag></td>
                      <td>{gate.owner}</td>
                      <td>{gate.detail}</td>
                      <td>{gate.source_refs.slice(0, 4).join("；") || "待补充"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <div className="tfl-note-list">
            {(manifest.parser_notes || []).map((note) => <span key={note}>{note}</span>)}
          </div>
        </>
      ) : (
        <div className="empty-state">尚未生成安全资料清单。</div>
      )}
    </section>
  );
}

function PicosDecisionWorkspace({
  workflow,
  loading,
  message,
  selectedQuestionId,
  onSelectQuestion,
  rationales,
  setRationales,
  onAction,
  busyAction,
  onRefresh,
}) {
  const steps = workflow?.steps || [];
  const selectedStep = steps.find((step) => step.question_id === selectedQuestionId) || steps[0];
  const selectedOption = selectedStep?.options?.find((option) => option.option_id === selectedStep.selected_option_id);
  const rationaleValue = rationales[selectedStep?.question_id] ?? selectedStep?.user_rationale ?? "";
  const busyFor = (action) => selectedStep && busyAction === `${selectedStep.question_id}:${action}`;
  const canSaveRationale = Boolean(selectedStep?.selected_option_id && rationaleValue.trim());
  const canMarkCandidate = Boolean(selectedStep?.selected_option_id && (selectedStep?.user_rationale || rationaleValue.trim()));

  if (loading && !workflow) {
    return <div className="panel-subsection picos-loading">PICOS 决策工作台读取中...</div>;
  }
  if (!selectedStep) {
    return <div className="empty-state">尚未生成 PICOS 决策工作台。</div>;
  }

  return (
    <div className="picos-workflow-panel">
      <div className="picos-workflow-head">
        <div>
          <h3>{workflow?.workflow_label || "PICOS 决策工作台"}</h3>
          <p>{workflow?.formal_output_boundary || "PICOS输出仅作为待医学批准候选。"}</p>
        </div>
        <div className="picos-head-tags">
          <Tag tone="warning">待医学确认</Tag>
          <Tag tone={workflow?.ai_gateway_status === "configured" ? "success" : "warning"}>{workflow?.ai_gateway_status === "configured" ? "独立AI已配置" : "独立AI未配置"}</Tag>
          <Tag tone="neutral">工作台独立运行</Tag>
          <button onClick={onRefresh} disabled={loading} title={loading ? "PICOS决策正在刷新" : "刷新PICOS决策"}>{loading ? "刷新中" : "刷新决策"}</button>
        </div>
      </div>
      {message && <div className="source-registry-message">{message}</div>}
      <div className="picos-workflow-stats">
        <div><strong>{workflow?.decision_count ?? 0}</strong><span>已选择</span></div>
        <div><strong>{workflow?.writing_candidate_count ?? 0}</strong><span>写作候选</span></div>
        <div><strong>{workflow?.blocking_gate_count ?? 0}</strong><span>阻断质量门</span></div>
        <div><strong>{steps.length}</strong><span>PICOS域</span></div>
      </div>
      <div className="picos-workflow-grid">
        <aside className="picos-question-list">
          {steps.map((step) => (
            <button
              key={step.question_id}
              className={step.question_id === selectedStep.question_id ? "active" : ""}
              onClick={() => onSelectQuestion(step.question_id)}
            >
              <span>{step.picos_domain}</span>
              <strong>{step.writing_target_section}</strong>
              <Tag tone={picosStatusTone(step.decision_status)}>{step.decision_status}</Tag>
            </button>
          ))}
        </aside>
        <section className="picos-decision-card">
          <div className="picos-card-top">
            <Tag tone={picosStatusTone(selectedStep.decision_status)}>{selectedStep.decision_status}</Tag>
            <Tag tone={safetyGateTone(selectedStep.quality_gate_status)}>{gateStatusLabel(selectedStep.quality_gate_status)}</Tag>
          </div>
          <h3>{selectedStep.question}</h3>
          <p>{selectedStep.current_evidence_summary}</p>
          <div className="picos-source-list">
            {selectedStep.source_refs.slice(0, 5).map((ref) => <span key={ref}>{ref}</span>)}
          </div>
          <div className="picos-option-list">
            {selectedStep.options.map((option) => (
              <button
                key={option.option_id}
                className={option.option_id === selectedStep.selected_option_id ? "selected" : ""}
                onClick={() => onAction(selectedStep.question_id, "select_option", { option_id: option.option_id, user_rationale: rationaleValue })}
                disabled={Boolean(busyAction)}
                title={busyAction ? "当前PICOS动作正在处理" : "选择该PICOS设计候选"}
              >
                <strong>{option.label}</strong>
                <span>{option.design_summary}</span>
                <em>{option.medical_rationale_prompt}</em>
              </button>
            ))}
          </div>
          <label className="picos-rationale-box">
            <span>医学理由与项目口径</span>
            <textarea
              value={rationaleValue}
              onChange={(event) => setRationales((current) => ({ ...current, [selectedStep.question_id]: event.target.value }))}
              placeholder="填写选择理由、适用人群/终点/设计边界、需跨部门确认的事项"
            />
          </label>
          <div className="button-row">
            <button
              disabled={!canSaveRationale || Boolean(busyAction)}
              title={!rationaleValue.trim() ? "请先填写医学理由与项目口径" : busyAction ? "当前PICOS动作正在处理" : "保存医学理由"}
              onClick={() => onAction(selectedStep.question_id, "save_rationale", { user_rationale: rationaleValue })}
            >
              {busyFor("save_rationale") ? "保存中" : "保存医学理由"}
            </button>
            <button
              className="primary-button"
              disabled={!canMarkCandidate || Boolean(busyAction)}
              title={!canMarkCandidate ? "请先选择候选并填写医学理由" : busyAction ? "当前PICOS动作正在处理" : "标记为待医学批准的写作候选"}
              onClick={() => onAction(selectedStep.question_id, "mark_writing_candidate", { user_rationale: rationaleValue, comment: "进入医学写作候选。" })}
            >
              {busyFor("mark_writing_candidate") ? "标记中" : "标记写作候选"}
            </button>
            <button
              disabled={Boolean(busyAction)}
              title={busyAction ? "当前PICOS动作正在处理" : "退回补充证据或跨部门确认"}
              onClick={() => onAction(selectedStep.question_id, "return_for_evidence", { comment: "退回补充来源或跨部门确认。" })}
            >
              退回补证
            </button>
            <button
              disabled={Boolean(busyAction)}
              title={busyAction ? "当前PICOS动作正在处理" : "重置当前PICOS决策"}
              onClick={() => onAction(selectedStep.question_id, "reset_decision", { comment: "重置当前PICOS决策。" })}
            >
              重置
            </button>
          </div>
        </section>
        <aside className="picos-handoff-panel">
          <h3>写作流转预览</h3>
          <div className="handoff-box">
            <span>目标章节</span>
            <strong>{selectedStep.writing_target_section}</strong>
          </div>
          <div className="handoff-box">
            <span>当前候选</span>
            <strong>{selectedOption?.label || "尚未选择候选"}</strong>
            <p>{selectedOption?.design_summary || "请选择候选并填写医学理由后，再标记为写作候选。"}</p>
          </div>
          <div className="handoff-box">
            <span>流转状态</span>
            <Tag tone={selectedStep.writing_handoff_status === "可作为医学写作候选输入" ? "success" : "warning"}>{selectedStep.writing_handoff_status}</Tag>
          </div>
          <div className="handoff-box">
            <span>风险与未决项</span>
            {(selectedOption?.risk_notes?.length ? selectedOption.risk_notes : ["需医学批准后才可进入正式内容。"]).map((note) => <p key={note}>{note}</p>)}
          </div>
          <div className="picos-audit">
            <strong>审计轨迹</strong>
            {(selectedStep.audit_trail || []).length ? selectedStep.audit_trail.map((record) => (
              <div key={record.record_id}>
                <Tag tone="neutral">{picosActionLabel(record.action)}</Tag>
                <span>{record.to_status}</span>
                <small>{record.actor}</small>
              </div>
            )) : <p>暂无用户决策记录。</p>}
          </div>
        </aside>
      </div>
    </div>
  );
}

function EvidenceDesignManifestPanel({ projectId, manifest, loading, message, onRefresh, selectedPackageId, onSelectPackage }) {
  const packages = manifest?.packages || [];
  const selectedPackage = packages.find((item) => item.package_id === selectedPackageId) || packages[0];
  const products = selectedPackage ? selectedPackage.products.slice(0, 12) : [];
  const trials = selectedPackage ? selectedPackage.trial_designs.slice(0, 12) : [];
  const results = selectedPackage ? [...selectedPackage.efficacy_results, ...selectedPackage.safety_results].slice(0, 14) : [];
  const documents = selectedPackage ? selectedPackage.documents.slice(0, 10) : [];
  const gates = selectedPackage ? selectedPackage.quality_gates : [];
  const warnings = selectedPackage?.parser_warnings?.slice(0, 4) || [];
  const [picosWorkflow, setPicosWorkflow] = useState(null);
  const [picosLoading, setPicosLoading] = useState(false);
  const [picosMessage, setPicosMessage] = useState("");
  const [selectedPicosQuestionId, setSelectedPicosQuestionId] = useState("");
  const [picosRationales, setPicosRationales] = useState({});
  const [picosBusyAction, setPicosBusyAction] = useState("");

  const loadPicosWorkflow = () => {
    if (!selectedPackage?.package_id) return;
    setPicosLoading(true);
    setPicosMessage("");
    fetch(`/api/projects/${projectId}/evidence-design/picos-workflow?package_id=${encodeURIComponent(selectedPackage.package_id)}`)
      .then((response) => response.ok ? response.json() : Promise.reject(response))
      .then((payload) => {
        setPicosWorkflow(payload);
        const steps = payload.steps || [];
        if (!steps.some((step) => step.question_id === selectedPicosQuestionId)) {
          setSelectedPicosQuestionId(steps[0]?.question_id || "");
        }
      })
      .catch((error) => setPicosMessage(`PICOS决策工作台读取失败：${error.status || error.message || "network"}`))
      .finally(() => setPicosLoading(false));
  };

  useEffect(() => {
    loadPicosWorkflow();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, selectedPackage?.package_id]);

  const submitPicosAction = async (questionId, action, extra = {}) => {
    if (!selectedPackage?.package_id) return;
    const actionKey = `${questionId}:${action}`;
    setPicosBusyAction(actionKey);
    setPicosMessage("");
    try {
      const response = await fetch(
        `/api/projects/${projectId}/evidence-design/picos-workflow/${encodeURIComponent(selectedPackage.package_id)}/questions/${encodeURIComponent(questionId)}/actions`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action, actor: "medical_manager", ...extra }),
        },
      );
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(apiDetailText(payload, `API ${response.status}`));
      }
      setPicosWorkflow(payload);
      setPicosMessage(action === "mark_writing_candidate" ? "已标记为医学写作候选，仍需医学批准后才能进入正式内容。" : "PICOS决策已保存。");
    } catch (error) {
      setPicosMessage(`PICOS动作失败：${error.message}`);
    } finally {
      setPicosBusyAction("");
    }
  };

  return (
    <section className="panel tfl-manifest-panel evidence-design-panel">
      <SectionTitle
        title="竞品证据清单与PICOS设计队列"
        action={<button onClick={onRefresh} disabled={loading} title={loading ? "证据清单正在生成" : "刷新竞品证据清单与PICOS设计队列"}>{loading ? "生成中" : "刷新证据清单"}</button>}
      />
      <div className="evidence-boundary">
        本工作面只展示来源可追溯的竞品证据、证据缺口和PICOS待决策问题；所有设计输出均为待医学确认/待医学批准内容，不代表已完成医学批准。
      </div>
      <div className="evidence-stats">
        <div><strong>{formatMaybeNumber(manifest?.total_products)}</strong><span>竞品/机制</span></div>
        <div><strong>{formatMaybeNumber(manifest?.total_trials)}</strong><span>试验设计</span></div>
        <div><strong>{formatMaybeNumber(manifest?.total_documents)}</strong><span>原始资料</span></div>
        <div><strong>{formatMaybeNumber(manifest?.total_result_rows)}</strong><span>结果行</span></div>
        <div><strong>{formatMaybeNumber(manifest?.picos_question_count)}</strong><span>PICOS问题</span></div>
        <div><strong>{formatMaybeNumber(manifest?.quality_gate_count)}</strong><span>质量门</span></div>
      </div>
      {message && <div className="source-registry-message">{message}</div>}
      <div className="tfl-package-tabs">
        {packages.map((item) => (
          <button
            key={item.package_id}
            className={item.package_id === selectedPackage?.package_id ? "active" : ""}
            onClick={() => onSelectPackage(item.package_id)}
          >
            {item.package_label}
          </button>
        ))}
      </div>
      {selectedPackage ? (
        <>
          <div className="tfl-package-summary evidence-package-summary">
            <div><span>适应症</span><strong>{selectedPackage.indication}</strong></div>
            <div><span>资料底座</span><strong>{selectedPackage.source_root_label}</strong></div>
            <div><span>资料角色</span><strong>{selectedPackage.package_role}</strong></div>
            <div><span>试验分布</span><strong>{Object.entries(selectedPackage.trial_count_by_phase).map(([key, value]) => `${key}:${value}`).join("；") || "未读取"}</strong></div>
            <div><span>结果覆盖</span><strong>{Object.entries(selectedPackage.endpoint_count_by_name).slice(0, 4).map(([key, value]) => `${key}:${value}`).join("；") || "未读取"}</strong></div>
          </div>
          <div className="tfl-quality-gates">
            <Tag tone="warning">待医学确认</Tag>
            <Tag tone="neutral">不使用既有深度报告作为输入</Tag>
            <Tag tone={selectedPackage.trial_designs.length ? "success" : "warning"}>竞品设计已登记</Tag>
            <Tag tone={selectedPackage.documents.length ? "success" : "warning"}>原始资料已登记</Tag>
            <Tag tone="warning">PICOS未批准</Tag>
          </div>
          {warnings.length ? (
            <div className="tfl-warning-list">
              {warnings.map((warning) => <span key={warning}>{warning}</span>)}
            </div>
          ) : null}

          <PicosDecisionWorkspace
            workflow={picosWorkflow}
            loading={picosLoading}
            message={picosMessage}
            selectedQuestionId={selectedPicosQuestionId}
            onSelectQuestion={setSelectedPicosQuestionId}
            rationales={picosRationales}
            setRationales={setPicosRationales}
            onAction={submitPicosAction}
            busyAction={picosBusyAction}
            onRefresh={loadPicosWorkflow}
          />

          <div className="evidence-picos-workbench">
            <div className="tfl-table-block">
              <h3>证据质量门</h3>
              <div className="tfl-table-scroll evidence-gate-table">
                <table>
                  <thead>
                    <tr>
                      <th>质量门</th>
                      <th>状态</th>
                      <th>负责角色</th>
                      <th>说明</th>
                      <th>来源</th>
                    </tr>
                  </thead>
                  <tbody>
                    {gates.map((gate) => (
                      <tr key={gate.gate_id}>
                        <td><strong>{gate.gate_label}</strong></td>
                        <td><Tag tone={safetyGateTone(gate.status)}>{gateStatusLabel(gate.status)}</Tag></td>
                        <td>{gate.owner}</td>
                        <td>{gate.detail}</td>
                        <td>{gate.source_refs.slice(0, 4).join("；")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <div className="tfl-table-block evidence-wide-block">
            <h3>竞品试验设计矩阵</h3>
            <div className="tfl-table-scroll evidence-trial-table">
              <table>
                <thead>
                  <tr>
                    <th>药物/研究</th>
                    <th>机制/申办方</th>
                    <th>分期/状态</th>
                    <th>地区/登记号</th>
                    <th>设计与样本量</th>
                    <th>干预/对照</th>
                    <th>主要终点</th>
                    <th>关键次要终点</th>
                    <th>Protocol/SAP/发表</th>
                    <th>证据状态</th>
                  </tr>
                </thead>
                <tbody>
                  {trials.map((trial) => (
                    <tr key={trial.trial_id}>
                      <td><strong>{trial.drug_name}</strong><span>{trial.trial_acronym || trial.trial_id}</span></td>
                      <td>{trial.target}<span>{trial.sponsor}</span></td>
                      <td>{trial.phase}<span>{trial.trial_status}</span></td>
                      <td>{trial.region}<span>{trial.registry_id}</span></td>
                      <td>{trial.design_type}<span>样本量：{trial.sample_size || "未披露"}</span></td>
                      <td>{trial.treatment_group}<span>对照：{trial.comparator || "待核对"}</span></td>
                      <td>{trial.primary_endpoint}<span>{trial.primary_timepoint}</span></td>
                      <td>{trial.key_secondary_endpoint || "待抽取"}</td>
                      <td>{trial.protocol_available} / {trial.sap_available} / {trial.publication_available}</td>
                      <td>{trial.verification_status}<span>{trial.evidence_level}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="tfl-manifest-grid">
            <div className="tfl-table-block">
              <h3>竞品概览</h3>
              <div className="tfl-table-scroll evidence-product-table">
                <table>
                  <thead>
                    <tr>
                      <th>竞品</th>
                      <th>机制</th>
                      <th>申办方</th>
                      <th>研究数</th>
                      <th>区域</th>
                      <th>状态线索</th>
                    </tr>
                  </thead>
                  <tbody>
                    {products.map((product) => (
                      <tr key={product.product_id}>
                        <td><strong>{product.drug_name}</strong></td>
                        <td>{product.target}</td>
                        <td>{product.sponsor}</td>
                        <td>{product.trial_count}</td>
                        <td>{Object.entries(product.region_summary).map(([key, value]) => `${key}:${value}`).join("；")}</td>
                        <td>{product.approval_status_hint}<span>{product.highest_evidence_level}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="tfl-table-block">
              <h3>原始资料索引</h3>
              <div className="tfl-table-scroll evidence-doc-table">
                <table>
                  <thead>
                    <tr>
                      <th>资料</th>
                      <th>类型</th>
                      <th>药物/研究</th>
                      <th>用途</th>
                      <th>证据等级</th>
                    </tr>
                  </thead>
                  <tbody>
                    {documents.map((document) => (
                      <tr key={document.document_id}>
                        <td><strong>{document.public_title}</strong><span>{document.relative_path}</span></td>
                        <td>{document.document_type}</td>
                        <td>{document.drug_name}<span>{document.trial_identifier}</span></td>
                        <td>{document.role_hint}</td>
                        <td>{document.evidence_level}<span>{document.verification_status}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <div className="tfl-table-block evidence-wide-block">
            <h3>疗效/安全性结果摘要</h3>
            <div className="tfl-table-scroll evidence-result-table">
              <table>
                <thead>
                  <tr>
                    <th>类型</th>
                    <th>药物/研究</th>
                    <th>终点</th>
                    <th>时间点</th>
                    <th>干预/对照</th>
                    <th>结果摘录</th>
                    <th>来源</th>
                    <th>边界</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((result) => (
                    <tr key={`${result.result_kind}:${result.result_id}`}>
                      <td>{result.result_kind === "safety" ? "安全性" : "疗效"}</td>
                      <td><strong>{result.drug_name}</strong><span>{result.trial_identifier || result.trial_id}</span></td>
                      <td>{result.endpoint_name}<span>{result.endpoint_type}</span></td>
                      <td>{result.timepoint || "未记录"}</td>
                      <td>{result.treatment_group}<span>对照：{result.comparator || "待核对"}</span></td>
                      <td>{result.effect_summary || "待抽取"}</td>
                      <td>{result.source_type}<span>{result.source_locator}</span></td>
                      <td>{result.medical_boundary}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="tfl-note-list">
            {(manifest.parser_notes || []).map((note) => <span key={note}>{note}</span>)}
          </div>
        </>
      ) : (
        <div className="empty-state">尚未生成竞品证据清单。</div>
      )}
    </section>
  );
}

function PlannedModulePage({ moduleKey, projectId, monitoringProjectId = "", onOpenMonitoringRisk, refreshWorkbenchInbox, refreshDashboard }) {
  const config = plannedModuleContent[moduleKey];
  const plannedModuleProjectIdRef = useRef(projectId);
  plannedModuleProjectIdRef.current = projectId;
  const candidates = (sourceRegistryCandidates[moduleKey] || []).filter((candidate) => candidate.projectIds.includes(projectId));
  const [registry, setRegistry] = useState({ entries: [], spans: [], content_validations: [] });
  const [loadingSources, setLoadingSources] = useState(false);
  const [registeringId, setRegisteringId] = useState("");
  const [message, setMessage] = useState("");
  const [aiTaskType, setAiTaskType] = useState(config.aiTasks[0] || "");
  const [runningAi, setRunningAi] = useState(false);
  const [evidenceManifest, setEvidenceManifest] = useState(null);
  const [evidenceManifestLoading, setEvidenceManifestLoading] = useState(false);
  const [evidenceManifestMessage, setEvidenceManifestMessage] = useState("");
  const [selectedEvidencePackageId, setSelectedEvidencePackageId] = useState("");
  const [tflManifest, setTflManifest] = useState(null);
  const [tflManifestLoading, setTflManifestLoading] = useState(false);
  const [tflManifestMessage, setTflManifestMessage] = useState("");
  const [selectedTflPackageId, setSelectedTflPackageId] = useState("");
  const [selectedTflOutputId, setSelectedTflOutputId] = useState("");
  const [tflReviewWorkbench, setTflReviewWorkbench] = useState(null);
  const [tflReviewLoading, setTflReviewLoading] = useState(false);
  const [tflReviewMessage, setTflReviewMessage] = useState("");
  const [tflActionLoading, setTflActionLoading] = useState("");
  const tflManifestInFlight = useRef(false);
  const tflReviewRequestId = useRef(0);
  const [safetyManifest, setSafetyManifest] = useState(null);
  const [safetyManifestLoading, setSafetyManifestLoading] = useState(false);
  const [safetyManifestMessage, setSafetyManifestMessage] = useState("");
  const [selectedSafetyPackageId, setSelectedSafetyPackageId] = useState("");
  const [selectedSafetySignalId, setSelectedSafetySignalId] = useState("");
  const [safetyReviewWorkbench, setSafetyReviewWorkbench] = useState(null);
  const [safetyReviewLoading, setSafetyReviewLoading] = useState(false);
  const [safetyReviewMessage, setSafetyReviewMessage] = useState("");
  const [safetyActionLoading, setSafetyActionLoading] = useState("");
  const [safetyReviewComment, setSafetyReviewComment] = useState("");
  const [safetyHandoffManifest, setSafetyHandoffManifest] = useState(null);
  const [safetyActiveView, setSafetyActiveView] = useState("risks");
  const [safetyRiskIndex, setSafetyRiskIndex] = useState(null);
  const [safetyRiskLoading, setSafetyRiskLoading] = useState(false);
  const [safetyRiskError, setSafetyRiskError] = useState("");
  const safetyRiskRequestId = useRef(0);
  const safetyReviewRequestId = useRef(0);
  const safetyManifestRequestId = useRef(0);
  const safetyHandoffRequestId = useRef(0);
  const safetySelectionRef = useRef({ projectId, packageId: "", signalId: "" });
  safetySelectionRef.current = {
    projectId,
    packageId: selectedSafetyPackageId,
    signalId: selectedSafetySignalId,
  };

  const moduleEntries = registry.entries.filter((entry) => entry.module === config.module);
  const moduleSpans = registry.spans.filter((span) => span.module === config.module);
  const currentModuleEntryIds = new Set(Object.values(moduleEntries.reduce((latest, entry) => {
    const previous = latest[entry.source_kind];
    if (!previous || new Date(entry.created_at) > new Date(previous.created_at)) latest[entry.source_kind] = entry;
    return latest;
  }, {})).map((entry) => entry.entry_id));
  const usableEntryIds = new Set((registry.content_validations || [])
    .filter((validation) => ["allowed", "confirmed_after_warning"].includes(validation.use_status))
    .map((validation) => validation.source_entry_id));
  const selectedSourceIds = moduleSpans
    .filter((span) => currentModuleEntryIds.has(span.entry_id) && usableEntryIds.has(span.entry_id))
    .slice(0, 12)
    .map((span) => span.source_id);

  const refreshSources = () => {
    setLoadingSources(true);
    fetch(`/api/projects/${projectId}/sources`)
      .then((response) => (response.ok ? response.json() : Promise.reject(response)))
      .then((data) => {
        if (data?.project_id !== plannedModuleProjectIdRef.current) {
          setRegistry({ entries: [], spans: [], content_validations: [] });
          setMessage("原始资料登记响应项目身份不匹配，已阻止写入当前模块。");
          return;
        }
        setRegistry({
          entries: data.entries || [],
          spans: data.spans || [],
          content_validations: data.content_validations || [],
        });
      })
      .catch((error) => setMessage(`原始资料登记读取失败：${error.status || error.message || "network"}`))
      .finally(() => setLoadingSources(false));
  };

  useEffect(() => {
    refreshSources();
  }, [moduleKey, projectId]);

  const refreshEvidenceManifest = () => {
    if (moduleKey !== "evidenceDesign") return;
    setEvidenceManifestLoading(true);
    setEvidenceManifestMessage("");
    fetch(`/api/projects/${projectId}/evidence-design/manifest`)
      .then((response) => (response.ok ? response.json() : Promise.reject(response)))
      .then((data) => {
        if (data?.project_id !== plannedModuleProjectIdRef.current) {
          setEvidenceManifest(null);
          setSelectedEvidencePackageId("");
          setEvidenceManifestMessage("竞品证据清单响应项目身份不匹配，已阻止写入当前模块。");
          return;
        }
        setEvidenceManifest(data);
        const packageIds = (data.packages || []).map((item) => item.package_id);
        if (!packageIds.includes(selectedEvidencePackageId)) {
          setSelectedEvidencePackageId(packageIds[0] || "");
        }
      })
      .catch((error) => setEvidenceManifestMessage(`竞品证据清单生成失败：${error.status || error.message || "network"}`))
      .finally(() => setEvidenceManifestLoading(false));
  };

  useEffect(() => {
    if (moduleKey === "evidenceDesign") {
      refreshEvidenceManifest();
    } else {
      setEvidenceManifest(null);
      setEvidenceManifestMessage("");
      setSelectedEvidencePackageId("");
    }
  }, [moduleKey, projectId]);

  const refreshTflManifest = (forceRefresh = true) => {
    if (moduleKey !== "tfl") return Promise.resolve(false);
    if (!forceRefresh && tflManifestInFlight.current) return Promise.resolve(false);
    tflManifestInFlight.current = true;
    setTflManifestLoading(true);
    setTflManifestMessage("");
    const params = new URLSearchParams();
    params.set("force_refresh", forceRefresh ? "true" : "false");
    return fetch(`/api/projects/${projectId}/tfl/manifest?${params.toString()}`)
      .then((response) => (response.ok ? response.json() : Promise.reject(response)))
      .then((data) => {
        if (data?.project_id !== plannedModuleProjectIdRef.current) {
          setTflManifest(null);
          setSelectedTflPackageId("");
          setSelectedTflOutputId("");
          setTflManifestMessage("TFL清单响应项目身份不匹配，已阻止写入当前模块。");
          return false;
        }
        setTflManifest(data);
        const packageIds = (data.packages || []).map((item) => item.package_id);
        if (!packageIds.includes(selectedTflPackageId)) {
          setSelectedTflPackageId(packageIds[0] || "");
        }
        return true;
      })
      .catch((error) => {
        setTflManifestMessage(`数据集与TFL清单生成失败：${error.status || error.message || "network"}`);
        return false;
      })
      .finally(() => {
        tflManifestInFlight.current = false;
        setTflManifestLoading(false);
      });
  };

  const refreshTflReviewWorkbench = (packageId = selectedTflPackageId, outputId = selectedTflOutputId) => {
    if (moduleKey !== "tfl") return Promise.resolve(false);
    const requestId = tflReviewRequestId.current + 1;
    tflReviewRequestId.current = requestId;
    setTflReviewLoading(true);
    setTflReviewMessage("");
    const params = new URLSearchParams();
    if (packageId) params.set("package_id", packageId);
    if (outputId) params.set("output_id", outputId);
    return fetch(`/api/projects/${projectId}/tfl/review-workbench?${params.toString()}`)
      .then((response) => (response.ok ? response.json() : Promise.reject(response)))
      .then((data) => {
        if (requestId !== tflReviewRequestId.current) return false;
        if (data?.project_id !== plannedModuleProjectIdRef.current) {
          setTflReviewWorkbench(null);
          setTflReviewMessage("TFL审阅工作台响应项目身份不匹配，已阻止写入当前模块。");
          return false;
        }
        setTflReviewWorkbench(data);
        if (data.package_id && data.package_id !== selectedTflPackageId) {
          setSelectedTflPackageId(data.package_id);
        }
        if (data.selected_output_id && data.selected_output_id !== selectedTflOutputId) {
          setSelectedTflOutputId(data.selected_output_id);
        }
        return true;
      })
      .catch((error) => {
        if (requestId === tflReviewRequestId.current) {
          setTflReviewMessage(`TFL审阅工作台读取失败：${error.status || error.message || "network"}`);
        }
        return false;
      })
      .finally(() => {
        if (requestId === tflReviewRequestId.current) setTflReviewLoading(false);
      });
  };

  useEffect(() => {
    if (moduleKey === "tfl") {
      refreshTflManifest(false);
    } else {
      setTflManifest(null);
      setTflManifestMessage("");
      setSelectedTflPackageId("");
      setSelectedTflOutputId("");
      setTflReviewWorkbench(null);
      setTflReviewMessage("");
    }
  }, [moduleKey, projectId]);

  useEffect(() => {
    if (moduleKey === "tfl" && selectedTflPackageId) {
      refreshTflReviewWorkbench(selectedTflPackageId, selectedTflOutputId);
    }
  }, [moduleKey, projectId, selectedTflPackageId, selectedTflOutputId]);

  const selectTflPackage = (packageId) => {
    setSelectedTflPackageId(packageId);
    setSelectedTflOutputId("");
  };

  const applyTflReviewAction = async (action, comment) => {
    const packageId = tflReviewWorkbench?.package_id || selectedTflPackageId;
    const outputId = tflReviewWorkbench?.selected_output_id || selectedTflOutputId;
    if (!packageId || !outputId) {
      setTflReviewMessage("请先选择TFL输出对象。");
      return false;
    }
    setTflActionLoading(action);
    setTflReviewMessage("");
    try {
      const response = await fetch(
        `/api/projects/${projectId}/tfl/review-workbench/${encodeURIComponent(packageId)}/outputs/${encodeURIComponent(outputId)}/actions`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action, actor: "medical_manager", comment }),
        },
      );
      const payload = await response.json();
      if (!response.ok) {
        if (response.status === 409 && payload.detail?.source_admission) {
          setTflReviewWorkbench((current) => current ? { ...current, source_admission: payload.detail.source_admission } : current);
        }
        throw new Error(apiDetailText(payload, `API ${response.status}`));
      }
      if (payload?.project_id !== plannedModuleProjectIdRef.current) {
        throw new Error("TFL审阅响应项目身份不匹配，未更新当前审阅状态。");
      }
      setTflReviewWorkbench(payload);
      setSelectedTflOutputId(payload.selected_output_id || outputId);
      setTflReviewMessage(`已更新审阅状态：${payload.current_status}`);
      return true;
    } catch (error) {
      setTflReviewMessage(`TFL审阅动作提交失败：${error.message}`);
      return false;
    } finally {
      setTflActionLoading("");
    }
  };

  const refreshSafetyManifest = () => {
    if (moduleKey !== "safety") return;
    const requestId = safetyManifestRequestId.current + 1;
    safetyManifestRequestId.current = requestId;
    setSafetyManifestLoading(true);
    setSafetyManifestMessage("");
    fetch(`/api/projects/${projectId}/safety-pv/manifest`)
      .then((response) => (response.ok ? response.json() : Promise.reject(response)))
      .then((data) => {
        if (requestId !== safetyManifestRequestId.current) return;
        if (data?.project_id !== projectId) {
          setSafetyManifest(null);
          setSelectedSafetyPackageId("");
          setSelectedSafetySignalId("");
          setSafetyManifestMessage("安全资料清单响应项目身份不匹配，已阻止写入当前模块。");
          return;
        }
        setSafetyManifest(data);
        const packageIds = (data.packages || []).map((item) => item.package_id);
        if (!packageIds.includes(selectedSafetyPackageId)) {
          setSelectedSafetyPackageId(packageIds[0] || "");
        }
      })
      .catch((error) => {
        if (requestId === safetyManifestRequestId.current) setSafetyManifestMessage(`安全资料清单生成失败：${error.status || error.message || "network"}`);
      })
      .finally(() => {
        if (requestId === safetyManifestRequestId.current) setSafetyManifestLoading(false);
      });
  };

  const refreshSafetyReviewWorkbench = (packageId = selectedSafetyPackageId, signalId = selectedSafetySignalId) => {
    if (moduleKey !== "safety") return Promise.resolve(false);
    const requestId = safetyReviewRequestId.current + 1;
    safetyReviewRequestId.current = requestId;
    setSafetyReviewLoading(true);
    setSafetyReviewMessage("");
    const params = new URLSearchParams();
    if (packageId) params.set("package_id", packageId);
    if (signalId) params.set("signal_id", signalId);
    return fetch(`/api/projects/${projectId}/safety-pv/review-workbench?${params.toString()}`)
      .then((response) => (response.ok ? response.json() : Promise.reject(response)))
      .then((data) => {
        if (requestId !== safetyReviewRequestId.current) return false;
        if (data?.project_id !== plannedModuleProjectIdRef.current) {
          setSafetyReviewWorkbench(null);
          setSafetyReviewMessage("安全信号审阅工作台响应项目身份不匹配，已阻止写入当前模块。");
          return false;
        }
        setSafetyReviewWorkbench(data);
        if (data.package_id && data.package_id !== selectedSafetyPackageId) {
          setSelectedSafetyPackageId(data.package_id);
        }
        if (data.selected_signal_id && data.selected_signal_id !== selectedSafetySignalId) {
          setSelectedSafetySignalId(data.selected_signal_id);
        }
        return true;
      })
      .catch((error) => {
        if (requestId === safetyReviewRequestId.current) {
          setSafetyReviewMessage(`安全信号审阅工作台读取失败：${error.status || error.message || "network"}`);
        }
        return false;
      })
      .finally(() => {
        if (requestId === safetyReviewRequestId.current) setSafetyReviewLoading(false);
      });
  };

  const refreshSafetyHandoff = () => {
    if (moduleKey !== "safety") return Promise.resolve(false);
    const requestId = safetyHandoffRequestId.current + 1;
    safetyHandoffRequestId.current = requestId;
    return fetch(`/api/projects/${projectId}/safety-pv/handoff-candidates`)
      .then((response) => (response.ok ? response.json() : Promise.reject(response)))
      .then((data) => {
        if (requestId !== safetyHandoffRequestId.current) return false;
        if (data?.project_id !== projectId) {
          setSafetyHandoffManifest(null);
          setSafetyReviewMessage("PV协同交接响应项目身份不匹配，已阻止写入当前模块。");
          return false;
        }
        setSafetyHandoffManifest(data);
        return true;
      })
      .catch((error) => {
        if (requestId === safetyHandoffRequestId.current) setSafetyReviewMessage(`PV协同交接候选读取失败：${error.status || error.message || "network"}`);
        return false;
      });
  };

  useEffect(() => {
    if (moduleKey === "safety") {
      refreshSafetyManifest();
      refreshSafetyHandoff();
    } else {
      setSafetyManifest(null);
      setSafetyManifestMessage("");
      setSelectedSafetyPackageId("");
      setSelectedSafetySignalId("");
      setSafetyReviewWorkbench(null);
      setSafetyReviewMessage("");
      setSafetyReviewComment("");
      setSafetyHandoffManifest(null);
    }
  }, [moduleKey, projectId]);

  useEffect(() => {
    if (moduleKey !== "safety") {
      setSafetyRiskIndex(null);
      setSafetyRiskError("");
      return undefined;
    }
    const riskProjectId = monitoringProjectId || projectId;
    const requestId = safetyRiskRequestId.current + 1;
    safetyRiskRequestId.current = requestId;
    setSafetyRiskLoading(true);
    setSafetyRiskError("");
    fetchCompleteMonitoringRiskIndex(riskProjectId, { safetyPvOnly: true, expectedProjectId: projectId })
      .then((data) => {
        if (requestId === safetyRiskRequestId.current) setSafetyRiskIndex(data);
      })
      .catch((error) => {
        if (requestId === safetyRiskRequestId.current) {
          setSafetyRiskIndex(null);
          setSafetyRiskError(`安全性医学风险读取失败：${apiErrorText(error)}`);
        }
      })
      .finally(() => {
        if (requestId === safetyRiskRequestId.current) setSafetyRiskLoading(false);
      });
    return undefined;
  }, [moduleKey, monitoringProjectId, projectId]);

  useEffect(() => {
    if (moduleKey === "safety" && selectedSafetyPackageId) {
      refreshSafetyReviewWorkbench(selectedSafetyPackageId, selectedSafetySignalId);
    }
  }, [moduleKey, projectId, selectedSafetyPackageId, selectedSafetySignalId]);

  const selectSafetyPackage = (packageId) => {
    setSelectedSafetyPackageId(packageId);
    setSelectedSafetySignalId("");
    setSafetyReviewComment("");
  };

  const selectSafetySignal = (signalId) => {
    setSelectedSafetySignalId(signalId);
    setSafetyReviewComment("");
  };

  const applySafetyReviewAction = async (action, comment) => {
    const packageId = safetyReviewWorkbench?.package_id || selectedSafetyPackageId;
    const signalId = safetyReviewWorkbench?.selected_signal_id || selectedSafetySignalId;
    if (!packageId || !signalId) {
      setSafetyReviewMessage("请先选择安全信号候选。");
      return false;
    }
    setSafetyActionLoading(action);
    setSafetyReviewMessage("");
    try {
      const response = await fetch(
        `/api/projects/${projectId}/safety-pv/review-workbench/${encodeURIComponent(packageId)}/signals/${encodeURIComponent(signalId)}/actions`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action,
            actor: "medical_manager",
            comment,
            expected_revision: safetyReviewWorkbench?.state_revision || 0,
            expected_source_binding_digest: safetyReviewWorkbench?.source_binding_digest || "",
            idempotency_key: globalThis.crypto?.randomUUID?.() || `safety-${Date.now()}-${Math.random().toString(16).slice(2)}`,
          }),
        },
      );
      const payload = await response.json();
      if (!response.ok) {
        if (response.status === 409 && payload.detail?.source_admission) {
          setSafetyReviewWorkbench((current) => current ? { ...current, source_admission: payload.detail.source_admission } : current);
        }
        if (response.status === 409) {
          await Promise.all([
            refreshSafetyReviewWorkbench(packageId, signalId),
            refreshSafetyHandoff(),
            refreshWorkbenchInbox?.(),
            refreshDashboard?.(),
          ]);
        }
        throw new Error(apiDetailText(payload, `API ${response.status}`));
      }
      if (payload?.project_id !== plannedModuleProjectIdRef.current) {
        throw new Error("安全信号审阅响应项目身份不匹配，未更新当前审阅状态。");
      }
      const currentSelection = safetySelectionRef.current;
      if (
        currentSelection.projectId === projectId &&
        currentSelection.packageId === packageId &&
        currentSelection.signalId === signalId
      ) {
        setSafetyReviewWorkbench(payload);
        setSelectedSafetySignalId(payload.selected_signal_id || signalId);
        setSafetyReviewComment("");
        setSafetyReviewMessage(`已更新审阅状态：${payload.current_status}`);
      }
      await Promise.all([
        refreshSafetyHandoff(),
        refreshWorkbenchInbox?.(),
        refreshDashboard?.(),
      ]);
      return true;
    } catch (error) {
      setSafetyReviewMessage(`安全信号审阅动作提交失败：${error.message}`);
      return false;
    } finally {
      setSafetyActionLoading("");
    }
  };

  const registerCandidate = async (candidate) => {
    setRegisteringId(candidate.id);
    setMessage("");
    const params = new URLSearchParams();
    params.set("candidate_id", candidate.id);
    params.set("module", candidate.module);
    try {
      const response = await fetch(`/api/projects/${projectId}/sources/local-candidate?${params.toString()}`, { method: "POST" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || `API ${response.status}`);
      if (payload?.entry?.project_id !== plannedModuleProjectIdRef.current) {
        throw new Error("原始资料登记响应项目身份不匹配，未更新当前项目登记。");
      }
      setMessage(`${candidate.title} 已登记：${payload.entry?.span_count || 0} 个证据片段。`);
      refreshSources();
    } catch (error) {
      setMessage(`${candidate.title} 登记失败：${error.message}`);
    } finally {
      setRegisteringId("");
    }
  };

  const submitAiTask = async () => {
    if (!selectedSourceIds.length) {
      setMessage("请先登记至少一个原始资料证据片段，再准备 AI 任务。");
      return;
    }
    setRunningAi(true);
    setMessage("");
    try {
      const response = await fetch(`/api/projects/${projectId}/ai-runs/from-sources`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          module: config.module,
          task_type: aiTaskType,
          expected_prompt_version: `${aiTaskType}_v0_1`,
          source_ids: selectedSourceIds,
          forbidden_source_ids: ["legacy_deep_dive_report", "generated_html_reference", "previous_ai_summary"],
          user_instruction: `仅基于已登记的原始证据片段，为${config.title}准备待医学确认的结构化输出。`,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || `API ${response.status}`);
      if (payload?.project_id !== plannedModuleProjectIdRef.current) {
        throw new Error("AI任务响应项目身份不匹配，未更新当前项目任务状态。");
      }
      setMessage(payload.status === "blocked" ? "AI 任务已建立，但外部模型服务未配置；已记录 blocked run。" : `AI 任务已提交：${payload.status}`);
    } catch (error) {
      setMessage(`AI 任务准备失败：${error.message}`);
    } finally {
      setRunningAi(false);
    }
  };

  if (moduleKey === "safety" && safetyActiveView === "risks") {
    return (
      <main className="page safety-pv-page">
        <SectionTitle eyebrow={config.eyebrow} title={config.title} />
        <div className="safety-pv-workspace-switch" role="tablist" aria-label="Safety/PV工作区">
          <button className="active" role="tab" aria-selected="true" onClick={() => setSafetyActiveView("risks")}>安全性医学风险</button>
          <button role="tab" aria-selected="false" onClick={() => setSafetyActiveView("documents")}>PV文件医学审阅</button>
        </div>
        <SafetyRiskProjection
          riskIndex={safetyRiskIndex}
          loading={safetyRiskLoading}
          error={safetyRiskError}
          onOpenMonitoringRisk={onOpenMonitoringRisk}
        />
      </main>
    );
  }

  return (
    <main className="page">
      <SectionTitle eyebrow={config.eyebrow} title={config.title} />
      {moduleKey === "safety" && (
        <div className="safety-pv-workspace-switch" role="tablist" aria-label="Safety/PV工作区">
          <button role="tab" aria-selected="false" onClick={() => setSafetyActiveView("risks")}>安全性医学风险</button>
          <button className="active" role="tab" aria-selected="true" onClick={() => setSafetyActiveView("documents")}>PV文件医学审阅</button>
        </div>
      )}
      <section className="panel">
        <div className="approval-meta">
          <Tag tone="info">{config.status}</Tag>
          <Tag tone="warning">{moduleKey === "safety" ? "待医学/PV确认" : "待医学确认"}</Tag>
          <Tag tone="neutral">医学相关模块</Tag>
          {moduleKey === "safety" && <Tag tone="neutral">不替代PV系统</Tag>}
          {moduleKey === "evidenceDesign" && <Tag tone="neutral">设计建议候选</Tag>}
        </div>
        <p className="module-summary">{config.summary}</p>
      </section>
      {moduleKey === "evidenceDesign" && (
        <EvidenceDesignManifestPanel
          projectId={projectId}
          manifest={evidenceManifest}
          loading={evidenceManifestLoading}
          message={evidenceManifestMessage}
          onRefresh={refreshEvidenceManifest}
          selectedPackageId={selectedEvidencePackageId}
          onSelectPackage={setSelectedEvidencePackageId}
        />
      )}
      {moduleKey === "safety" && (
        <SafetyPvManifestPanel
          projectId={projectId}
          manifest={safetyManifest}
          loading={safetyManifestLoading}
          message={safetyManifestMessage}
          onRefresh={refreshSafetyManifest}
          selectedPackageId={selectedSafetyPackageId}
          onSelectPackage={selectSafetyPackage}
          selectedSignalId={selectedSafetySignalId}
          onSelectSignal={selectSafetySignal}
          reviewWorkbench={safetyReviewWorkbench}
          reviewLoading={safetyReviewLoading}
          reviewMessage={safetyReviewMessage}
          reviewComment={safetyReviewComment}
          setReviewComment={setSafetyReviewComment}
          onRefreshReview={() => refreshSafetyReviewWorkbench(selectedSafetyPackageId, selectedSafetySignalId)}
          onReviewAction={applySafetyReviewAction}
          applyingReviewAction={safetyActionLoading}
          handoffManifest={safetyHandoffManifest}
          onRefreshHandoff={refreshSafetyHandoff}
          selectionLocked={Boolean(safetyActionLoading)}
        />
      )}
      <section className="panel source-registry-panel">
        <SectionTitle
          title="原始资料登记"
          action={<button onClick={refreshSources} disabled={loadingSources} title={loadingSources ? "原始资料登记正在读取" : "刷新原始资料登记"}>{loadingSources ? "读取中" : "刷新"}</button>}
        />
        <div className="source-stats">
          <div><strong>{moduleEntries.length}</strong><span>已登记资料包</span></div>
          <div><strong>{moduleSpans.length}</strong><span>证据片段</span></div>
          <div><strong>{selectedSourceIds.length}</strong><span>本次 AI 任务预选</span></div>
          <div><strong>{config.aiTasks.length}</strong><span>AI 任务类型</span></div>
        </div>
        {message && <div className="source-registry-message">{message}</div>}
        <div className="source-candidate-grid">
          {candidates.map((candidate) => (
            <article className="source-candidate-card" key={candidate.id}>
              <div>
                <Tag tone={candidate.kind === "local-file" ? "info" : "neutral"}>{sourceTypeLabel(candidate.sourceType)}</Tag>
                <h3>{candidate.title}</h3>
                <p>{candidate.purpose}</p>
                <span className="source-candidate-label">{candidate.title}</span>
              </div>
              <button onClick={() => registerCandidate(candidate)} disabled={Boolean(registeringId)} title={registeringId ? "当前有资料正在登记" : "登记该原始资料候选"}>
                {registeringId === candidate.id ? "登记中" : "登记"}
              </button>
            </article>
          ))}
        </div>
        <div className="registered-source-list">
          {moduleEntries.length ? moduleEntries.map((entry) => (
            <div className="registered-source-row" key={entry.entry_id}>
              <Tag tone={entry.parser_status === "parsed" ? "success" : "warning"}>{parserStatusLabel(entry.parser_status)}</Tag>
              <strong>{entry.public_title}</strong>
              <span>{sourceKindLabel(entry.source_kind)}</span>
              <span>{entry.span_count} 片段</span>
              <span>{compactLabel(entry.entry_id, 18)}</span>
            </div>
          )) : <div className="empty-state">当前模块尚未登记原始资料。</div>}
        </div>
      </section>
      {moduleKey === "tfl" && (
        <TflManifestPanel
          projectId={projectId}
          manifest={tflManifest}
          loading={tflManifestLoading}
          message={tflManifestMessage}
          onRefresh={() => refreshTflManifest(true)}
          selectedPackageId={selectedTflPackageId}
          onSelectPackage={selectTflPackage}
          reviewWorkbench={tflReviewWorkbench}
          reviewLoading={tflReviewLoading}
          reviewMessage={tflReviewMessage}
          selectedOutputId={selectedTflOutputId}
          onSelectOutput={setSelectedTflOutputId}
          onRefreshReview={() => refreshTflReviewWorkbench(selectedTflPackageId, selectedTflOutputId)}
          onApplyReviewAction={applyTflReviewAction}
          applyingReviewAction={tflActionLoading}
        />
      )}
      <section className="panel ai-task-prep-panel">
        <SectionTitle title="独立 AI 任务准备" />
        <div className="ai-task-prep">
          <label>
            <span>任务类型</span>
            <select value={aiTaskType} onChange={(event) => setAiTaskType(event.target.value)}>
              {config.aiTasks.map((task) => <option key={task} value={task}>{aiTaskDisplayName(task)}</option>)}
            </select>
          </label>
          <div className="selected-source-chips">
            {selectedSourceIds.length ? selectedSourceIds.map((sourceId) => (
              <Tag key={sourceId} tone="neutral">{sourceId.slice(0, 32)}</Tag>
            )) : <span>暂无可用 source_id</span>}
          </div>
          <button className="primary-button" onClick={submitAiTask} disabled={runningAi || !aiTaskType} title={!aiTaskType ? "请先选择AI任务类型" : runningAi ? "AI任务正在准备" : "基于已登记来源准备独立AI任务"}>
            {runningAi ? "准备中" : "准备 AI 任务"}
          </button>
        </div>
      </section>
      <div className="overview-grid">
        <section className="panel">
          <SectionTitle title="正式输入" />
          <div className="task-list">
            {config.inputs.map((item) => (
              <div className="task-row" key={item}>
                <span><Tag tone="info">来源</Tag></span>
                <strong>{item}</strong>
                <span>原始资料</span>
                <span>待索引</span>
              </div>
            ))}
          </div>
        </section>
        <section className="panel">
          <SectionTitle title="AI 任务" />
          <div className="task-list">
            {config.aiTasks.map((item) => (
              <div className="task-row" key={item}>
                <span><Tag tone="warning">任务</Tag></span>
                <strong>{aiTaskDisplayName(item)}</strong>
                <span>需独立模型服务</span>
                <span>未启用</span>
              </div>
            ))}
          </div>
        </section>
        <section className="panel">
          <SectionTitle title="下一步" />
          <div className="task-list">
            {config.next.map((item, index) => (
              <div className="task-row" key={item}>
                <span><Tag tone="neutral">{index + 1}</Tag></span>
                <strong>{item}</strong>
                <span>产品化任务</span>
                <span>P0/P1</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}

function ApprovalPage({ projectId, dashboard, refreshDashboard }) {
  const projectLabel = dashboard.project?.project_code
    || dashboard.project?.project_name
    || projectId;
  const approvalRows = useMemo(() => {
    return (dashboard.pending_approvals || []).map((item) => normalizeApprovalItem(item, projectLabel));
  }, [dashboard.pending_approvals, projectLabel]);
  const [selectedId, setSelectedId] = useState(approvalRows[0]?.id || "");
  const selected = approvalRows.find((item) => item.id === selectedId) || approvalRows[0] || null;
  const [comment, setComment] = useState("");
  const [approvalMessage, setApprovalMessage] = useState("");
  const [serverBlockers, setServerBlockers] = useState([]);
  const [qualityGateLoaded, setQualityGateLoaded] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const displayedBlockers = serverBlockers.length ? serverBlockers.map((item) => item.message || item.blocker_type) : (selected?.blockers || []);
  const hasBlockers = displayedBlockers.length > 0;

  useEffect(() => {
    if (approvalRows.length && !approvalRows.some((item) => item.id === selectedId)) {
      setSelectedId(approvalRows[0].id);
    }
  }, [approvalRows, selectedId]);
  useEffect(() => {
    setServerBlockers([]);
    setQualityGateLoaded(false);
  }, [selectedId]);
  useEffect(() => {
    setApprovalMessage("");
  }, [projectId]);

  const selectApproval = (item) => {
    setSelectedId(item.id);
    setApprovalMessage("");
    setServerBlockers([]);
    setQualityGateLoaded(false);
    setComment(item.comments || "");
  };

  const submitApprovalAction = async (action) => {
    if (!selected) return;
    setActionLoading(true);
    setApprovalMessage("");
    setServerBlockers([]);
    try {
      const response = await fetch(`/api/projects/${projectId}/approvals/${selected.id}/actions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, actor: "medical_manager", comment }),
      });
      const payload = await response.json();
      const result = response.ok ? payload : payload.detail || payload;
      if (!response.ok && response.status !== 409) throw new Error(result?.detail || `API ${response.status}`);
      if (result.blockers?.length) setServerBlockers(result.blockers);
      if (action === "view_quality_gate") setQualityGateLoaded(true);
      if (response.status === 409) {
        setApprovalMessage("质量门未通过：后端已记录阻断审计，审批状态未改变。");
        return;
      }
      setApprovalMessage(
        action === "approve"
          ? selected.isMonitoringDisposition
            ? "已批准内部Query草稿/处置建议并写入审计；尚未执行对外Query、风险关闭或归档。"
            : "已批准待医学确认内容并写入审计。"
          : action === "return_for_revision"
            ? "已退回修订并写入审计。"
            : action === "reject"
              ? "已驳回并标记为作废。"
              : "已读取后端质量门结果。"
      );
      refreshDashboard?.();
    } catch (error) {
      setApprovalMessage(`审批动作失败：${error.message}`);
    } finally {
      setActionLoading(false);
    }
  };

  if (!selected) {
    return (
      <main className="page">
        <SectionTitle eyebrow="审批中心" title="待医学批准内容" />
        <section className="panel empty-state">
          {approvalMessage && <div className="approval-message">{approvalMessage}</div>}
          <p>当前项目无待审批事项。系统不会用演示审批项填充真实项目队列。</p>
        </section>
      </main>
    );
  }

  return (
    <main className="page">
      <SectionTitle
        eyebrow="审批中心"
        title="待医学批准内容"
        action={<button className="primary-button" disabled={actionLoading} title={actionLoading ? "审批动作正在处理" : "查看当前审批项质量门"} onClick={() => submitApprovalAction("view_quality_gate")}>查看质量门</button>}
      />
      <div className="approval-layout">
        <section className="panel approval-list">
          {approvalRows.map((item) => (
            <button key={item.id} className={selected.id === item.id ? "selected" : ""} onClick={() => selectApproval(item)}>
              <strong>{item.title}</strong>
              <span>{item.detail || item.type}</span>
              <Tag tone={statusClass(item.state)}>{item.state}</Tag>
            </button>
          ))}
        </section>
        <section className="panel approval-detail">
          <SectionTitle title={selected.title} />
          <div className="approval-meta">
            <Tag tone="info">{selected.type}</Tag>
            <Tag tone={statusClass(selected.state)}>{selected.state}</Tag>
            <Tag tone={hasBlockers ? "warning" : "success"}>{selected.risk}</Tag>
          </div>
          <div className="detail-grid">
            <div><strong>AI 标记</strong><span>{selected.ai}</span></div>
            <div><strong>负责人</strong><span>{selected.owner}</span></div>
            <div><strong>证据覆盖</strong><span>{selected.evidenceCoverage ?? "未提供"}</span></div>
            <div><strong>审计记录</strong><span>{selected.auditCount ?? "请查看审计详情"}</span></div>
          </div>
          <div className={!qualityGateLoaded ? "approval-pending" : hasBlockers ? "approval-blockers" : "approval-clear"}>
            <strong>{!qualityGateLoaded ? "质量门待读取" : hasBlockers ? "质量门阻断" : "质量门通过"}</strong>
            {!qualityGateLoaded ? <p>请先读取当前审批项的后端质量门结果，再决定批准、退回或驳回。</p> : hasBlockers ? displayedBlockers.map((item) => <p key={item}>{item}</p>) : (
              <p>{selected.isMonitoringDisposition ? "无内部审批阻断；允许进入内部医学审阅，不代表对外Query、风险关闭或归档。" : "无开放 AI 修订、无高风险阻断项，允许进入医学批准。"}</p>
            )}
          </div>
          {selected.internalApprovalBoundary && <p className="boundary-note">{selected.internalApprovalBoundary}</p>}
          <textarea value={comment} onChange={(event) => setComment(event.target.value)} placeholder="填写审批意见，退回或批准均需留痕" />
          {approvalMessage && <div className="approval-message">{approvalMessage}</div>}
          <div className="button-row">
            <button
              className="primary-button"
              disabled={actionLoading || !qualityGateLoaded || hasBlockers || !comment.trim()}
              title={!qualityGateLoaded ? "请先查看后端质量门" : hasBlockers ? "当前质量门存在阻断" : !comment.trim() ? "请先填写审批意见" : actionLoading ? "审批动作正在处理" : "批准当前待医学批准内容"}
              onClick={() => submitApprovalAction("approve")}
            >
              {actionLoading ? "处理中" : "批准"}
            </button>
            <button disabled={actionLoading || !comment.trim()} title={!comment.trim() ? "请先填写退回修订意见" : actionLoading ? "审批动作正在处理" : "退回当前内容修订"} onClick={() => submitApprovalAction("return_for_revision")}>退回修订</button>
            <button disabled={actionLoading || !comment.trim()} title={!comment.trim() ? "请先填写驳回意见" : actionLoading ? "审批动作正在处理" : "驳回当前待审批内容"} onClick={() => submitApprovalAction("reject")}>驳回</button>
          </div>
        </section>
      </div>
    </main>
  );
}

function SourceRegistryPage({ projectId, onOpenModule }) {
  const [registry, setRegistry] = useState({ entries: [], content_validations: [], content_validation_histories: {} });
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [moduleFilter, setModuleFilter] = useState("all");
  const [useStatusFilter, setUseStatusFilter] = useState("all");
  const [showHistorical, setShowHistorical] = useState(false);
  const [selectedEntryId, setSelectedEntryId] = useState("");
  const [reason, setReason] = useState("");
  const [acknowledgedCodes, setAcknowledgedCodes] = useState([]);
  const [submitting, setSubmitting] = useState(false);

  const refresh = async () => {
    setLoading(true);
    setMessage("");
    try {
      const response = await fetch(`/api/projects/${projectId}/sources`);
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(apiDetailText(payload, `API ${response.status}`));
      setRegistry({
        entries: payload.entries || [],
        content_validations: payload.content_validations || [],
        content_validation_histories: payload.content_validation_histories || {},
      });
    } catch (error) {
      setMessage(`来源台账读取失败：${apiErrorText(error)}`);
      setRegistry({ entries: [], content_validations: [], content_validation_histories: {} });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setModuleFilter("all");
    setUseStatusFilter("all");
    setShowHistorical(false);
    setSelectedEntryId("");
    setReason("");
    setAcknowledgedCodes([]);
    refresh();
  }, [projectId]);

  const validationByEntry = useMemo(() => Object.fromEntries(
    (registry.content_validations || []).map((validation) => [validation.source_entry_id, validation]),
  ), [registry.content_validations]);
  const rows = useMemo(() => (registry.entries || []).map((entry) => ({
    entry,
    validation: validationByEntry[entry.entry_id] || null,
  })), [registry.entries, validationByEntry]);
  const currentRows = rows.filter((row) => row.entry.is_current !== false);
  const modules = [...new Set(currentRows.map((row) => row.entry.module))].sort();
  const filteredRows = rows.filter(({ entry, validation }) => (
    (showHistorical || entry.is_current !== false)
    &&
    (moduleFilter === "all" || entry.module === moduleFilter)
    && (useStatusFilter === "all" || (validation?.use_status || "not_assessed") === useStatusFilter)
  ));
  const selected = rows.find((row) => row.entry.entry_id === selectedEntryId) || filteredRows[0] || null;
  const selectedHistory = selected ? (registry.content_validation_histories?.[selected.entry.entry_id] || []) : [];
  const unresolvedChecks = (selected?.validation?.checks || []).filter((check) => ["warning", "mismatch"].includes(check.outcome));
  const canConfirm = selected?.validation?.use_status === "requires_confirmation"
    && unresolvedChecks.length > 0
    && unresolvedChecks.every((check) => acknowledgedCodes.includes(check.check_code))
    && reason.trim().length >= 10
    && !submitting;

  useEffect(() => {
    if (selected?.entry.entry_id && selected.entry.entry_id !== selectedEntryId) {
      setSelectedEntryId(selected.entry.entry_id);
    }
    setReason("");
    setAcknowledgedCodes([]);
  }, [selected?.entry.entry_id, projectId]);

  const confirmSelected = async () => {
    if (!selected || !canConfirm) return;
    setSubmitting(true);
    setMessage("");
    try {
      const response = await fetch(`/api/projects/${projectId}/sources/${selected.entry.entry_id}/content-validation/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          reason: reason.trim(),
          acknowledged_check_codes: acknowledgedCodes,
          expected_revision: selected.validation.revision,
          idempotency_key: requestKey("source-registry-confirmation"),
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(apiDetailText(payload, `API ${response.status}`));
      setMessage("确认沿用已记录。原内容警告或不一致状态保持不变，使用状态已更新。");
      await refresh();
    } catch (error) {
      setMessage(`确认沿用失败：${apiErrorText(error)} 请刷新后重新核对当前版本。`);
    } finally {
      setSubmitting(false);
    }
  };

  const confirmedCount = currentRows.filter((row) => row.validation?.use_status === "confirmed_after_warning").length;
  const pendingCount = currentRows.filter((row) => row.validation?.use_status === "requires_confirmation").length;
  const failedCount = currentRows.filter((row) => row.validation?.technical_status === "failed").length;

  return (
    <main className="page source-ledger-page">
      <SectionTitle eyebrow="项目级资料治理" title="来源台账" action={(
        <button className="icon-text-button" onClick={refresh} disabled={loading} title={loading ? "来源台账正在刷新" : "刷新来源台账"}>
          <RefreshCw size={15} />{loading ? "刷新中" : "刷新"}
        </button>
      )} />
      <section className="panel source-ledger-summary">
        <div><strong>{currentRows.length}</strong><span>当前登记来源</span></div>
        <div className={pendingCount ? "warning" : ""}><strong>{pendingCount}</strong><span>待确认沿用</span></div>
        <div><strong>{confirmedCount}</strong><span>已确认沿用</span></div>
        <div className={failedCount ? "danger" : ""}><strong>{failedCount}</strong><span>技术读取失败</span></div>
      </section>
      {message && <div className="source-registry-message">{message}</div>}
      <section className="panel source-ledger-workspace">
        <div className="source-ledger-index">
          <div className="source-ledger-toolbar">
            <label><span>模块</span><select value={moduleFilter} onChange={(event) => setModuleFilter(event.target.value)}><option value="all">全部模块</option>{modules.map((module) => <option key={module} value={module}>{moduleLabels[module] || module}</option>)}</select></label>
            <label><span>使用状态</span><select value={useStatusFilter} onChange={(event) => setUseStatusFilter(event.target.value)}><option value="all">全部状态</option><option value="allowed">可使用</option><option value="requires_confirmation">待确认沿用</option><option value="confirmed_after_warning">已确认沿用</option><option value="blocked_technical_failure">技术读取失败（阻断）</option></select></label>
            <label className="source-ledger-history-toggle"><input type="checkbox" checked={showHistorical} onChange={(event) => setShowHistorical(event.target.checked)} /><span>包含历史版本</span></label>
          </div>
          <div className="source-ledger-list" role="list">
            {filteredRows.map(({ entry, validation }) => (
              <button key={entry.entry_id} className={selected?.entry.entry_id === entry.entry_id ? "selected" : ""} onClick={() => setSelectedEntryId(entry.entry_id)} role="listitem">
                <div><strong title={sourceLedgerTitle(entry)}>{sourceLedgerTitle(entry)}</strong><span>{moduleLabels[entry.module] || entry.module} · {sourceKindLabel(entry.source_kind)}</span></div>
                <div>
                  {entry.is_current === false && <Tag tone="neutral">历史版本</Tag>}
                  <Tag tone={sourceAdmissionStatusTone(validation?.content_status || "not_assessed")}>{sourceAdmissionStatusLabel(validation?.content_status || "not_assessed")}</Tag>
                  <Tag tone={sourceAdmissionStatusTone(validation?.use_status || "not_assessed")}>{sourceAdmissionStatusLabel(validation?.use_status || "not_assessed")}</Tag>
                </div>
              </button>
            ))}
            {!filteredRows.length && <p className="empty-state">当前筛选条件下没有来源记录。</p>}
          </div>
        </div>
        <div className="source-ledger-detail">
          {selected ? (
            <>
              <header>
                <div><span>{moduleLabels[selected.entry.module] || selected.entry.module}</span><h2>{sourceLedgerTitle(selected.entry)}</h2><small>{sourceKindLabel(selected.entry.source_kind)} · {selected.entry.span_count} 个证据片段</small></div>
                <div>
                  <Tag tone={sourceAdmissionStatusTone(selected.validation?.technical_status || "not_assessed")}>{sourceAdmissionStatusLabel(selected.validation?.technical_status || "not_assessed")}</Tag>
                  <Tag tone={sourceAdmissionStatusTone(selected.validation?.content_status || "not_assessed")}>{sourceAdmissionStatusLabel(selected.validation?.content_status || "not_assessed")}</Tag>
                  <Tag tone={sourceAdmissionStatusTone(selected.validation?.use_status || "not_assessed")}>{sourceAdmissionStatusLabel(selected.validation?.use_status || "not_assessed")}</Tag>
                  {moduleToPage[selected.entry.module] && (
                    <button className="icon-text-button" onClick={() => onOpenModule(selected.entry.module)} title={`前往${moduleLabels[selected.entry.module] || selected.entry.module}`}>
                      前往模块 <ChevronRight size={14} />
                    </button>
                  )}
                </div>
              </header>
              <p className="source-ledger-boundary">仅核验技术可读性、文件角色、项目/研究标识及当前任务所需内容结构。确认沿用只改变使用状态，不会把原警告或不一致改为匹配。</p>
              <div className="source-ledger-checks">
                {(selected.validation?.checks || []).map((check) => (
                  <div key={check.check_code}><span>{check.label}</span><b>{sourceAdmissionStatusLabel(check.outcome)}</b><small title={check.observed_value}>{check.observed_value || "未识别到可核对内容"}</small></div>
                ))}
                {!selected.validation && <p className="quiet-text">该来源尚无内容核验记录。</p>}
              </div>
              {selected.validation?.use_status === "confirmed_after_warning" && (
                <div className="source-ledger-confirmed"><CheckCircle2 size={16} /><div><strong>已确认沿用</strong><span>{selected.validation.confirmation_reason}</span><small>{selected.validation.actor} · {new Date(selected.validation.created_at).toLocaleString("zh-CN")}</small></div></div>
              )}
              {selected.validation?.use_status === "requires_confirmation" && unresolvedChecks.length > 0 && (
                <div className="source-ledger-confirmation">
                  <div><AlertTriangle size={16} /><strong>逐项核对后确认沿用</strong></div>
                  <fieldset><legend>未通过自动核验的内容</legend>{unresolvedChecks.map((check) => (
                    <label key={check.check_code}><input type="checkbox" checked={acknowledgedCodes.includes(check.check_code)} onChange={(event) => setAcknowledgedCodes((current) => event.target.checked ? [...new Set([...current, check.check_code])] : current.filter((code) => code !== check.check_code))} /><span><strong>我已核对：{check.label}</strong><small>{check.observed_value || "未识别到可核对内容"}</small></span></label>
                  ))}</fieldset>
                  <label className="source-ledger-reason"><span>医学确认理由</span><textarea rows={3} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="说明为何当前来源仍可用于本项目，至少10个字。" /></label>
                  <button className="primary-button" onClick={confirmSelected} disabled={!canConfirm} title={submitting ? "确认记录正在保存" : "需逐项确认全部未决检查并填写至少10字理由"}>{submitting ? "记录中" : "确认沿用"}</button>
                </div>
              )}
              <div className="source-ledger-history">
                <h3>核验与确认记录</h3>
                {!selectedHistory.length && <p className="quiet-text">尚无历史核验记录。</p>}
                {selectedHistory.map((record) => <div key={record.validation_id}><span>R{record.revision}</span><b>{sourceAdmissionStatusLabel(record.content_status)} / {sourceAdmissionStatusLabel(record.use_status)}</b><small>{new Date(record.created_at).toLocaleString("zh-CN")} · {record.actor}</small>{record.confirmation_reason && <p>确认理由：{record.confirmation_reason}</p>}</div>)}
              </div>
            </>
          ) : <div className="empty-state">请选择一条来源记录。</div>}
        </div>
      </section>
    </main>
  );
}

function ModuleUnavailablePage({ moduleKey, message = "当前项目尚未配置该模块的真实来源与执行链路。" }) {
  return (
    <main className="page">
      <SectionTitle eyebrow={moduleLabels[moduleKey] || "当前模块"} title="功能未配置" />
      <section className="panel empty-state">{message}</section>
    </main>
  );
}

function MedicalWritingRuntimeGate({ readiness, onRetry }) {
  const checking = readiness.status === "checking";
  const payload = readiness.assessment?.payload;
  return (
    <main className="page writing-runtime-gate-page">
      <section
        className={`writing-runtime-gate ${checking ? "checking" : "blocked"}`}
        role={checking ? "status" : "alert"}
        data-testid="medical-writing-runtime-gate"
      >
        <div className="writing-runtime-gate-icon">
          {checking ? <RefreshCw size={22} /> : <ShieldAlert size={22} />}
        </div>
        <div className="writing-runtime-gate-copy">
          <span className="writing-runtime-gate-eyebrow">医学写作运行环境</span>
          <h1>{checking ? "正在核对前后端版本与必需能力" : "当前版本组合不可进入写作工作区"}</h1>
          {checking ? (
            <p>检查完成后将自动进入研究方案编辑界面。</p>
          ) : (
            <>
              <ul>
                {(readiness.assessment?.reasons || ["未获得运行时准备信息"]).map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
              <p>医学写作内容未被修改。请重新启动或同步更新前后端后再检查。</p>
            </>
          )}
          <div className="writing-runtime-gate-meta" aria-label="运行版本信息">
            <span>前端 {runtimeExpectation.frontendBuildId}</span>
            <span>期望后端 {runtimeExpectation.expectedBackendBuildId}</span>
            {payload?.backend_build_id && <span>当前后端 {payload.backend_build_id}</span>}
            <span>合同 {runtimeExpectation.apiContractVersion}</span>
          </div>
        </div>
        {!checking && (
          <button type="button" onClick={onRetry}>
            <RefreshCw size={16} />
            重新检查
          </button>
        )}
      </section>
    </main>
  );
}

export function App() {
  const initialMonitoringRouteRef = useRef(initialMonitoringBrowserState());
  const monitoringReturnScopeRef = useRef(
    initialMonitoringRouteRef.current.scope || "trial",
  );
  const monitoringReturnSiteIdRef = useRef(
    initialMonitoringRouteRef.current.site_id || "",
  );
  const [activePage, setActivePage] = useState(() => (
    typeof window !== "undefined" && window.location.pathname === "/monitoring"
      ? activePageFromMonitoringRoute(initialMonitoringRouteRef.current)
      : "overview"
  ));
  const [monitoringRouteState, setMonitoringRouteState] = useState(initialMonitoringRouteRef.current);
  const [monitoringFocusRiskId, setMonitoringFocusRiskId] = useState(
    initialMonitoringRouteRef.current.risk_instance_id
      || initialMonitoringRouteRef.current.risk_key
      || "",
  );
  const [subjectViewFocusRiskId, setSubjectViewFocusRiskId] = useState("");
  const [projects, setProjects] = useState([]);
  const [projectsLoaded, setProjectsLoaded] = useState(false);
  const [projectsLoadError, setProjectsLoadError] = useState("");
  const [monitoringProjectRouteError, setMonitoringProjectRouteError] = useState("");
  const [projectsRequestNonce, setProjectsRequestNonce] = useState(0);
  const [activeProjectId, setActiveProjectId] = useState("");
  const [dashboard, setDashboard] = useState({ project: null, modules: [], latest_batch: null, pending_approvals: [], recent_risks: [] });
  const [dashboardReadError, setDashboardReadError] = useState(null);
  const [sourceManifests, setSourceManifests] = useState({});
  const [sourceManifestReadErrors, setSourceManifestReadErrors] = useState({});
  const [workbenchInbox, setWorkbenchInbox] = useState(null);
  const [workbenchInboxReadError, setWorkbenchInboxReadError] = useState(null);
  const [monitoringWorkbenchInbox, setMonitoringWorkbenchInbox] = useState(null);
  const [selectedSubject, setSelectedSubject] = useState(
    initialMonitoringRouteRef.current.subject_id || DEFAULT_SUBJECT_ID,
  );
  const [monitoringSubjectCatalog, setMonitoringSubjectCatalog] = useState([]);
  const [subjectProfiles, setSubjectProfiles] = useState({});
  const [monitoringDataError, setMonitoringDataError] = useState("");
  const [monitoringSubjectRouteError, setMonitoringSubjectRouteError] = useState("");
  const [monitoringReadError, setMonitoringReadError] = useState(null);
  const [monitoringSubjectReadError, setMonitoringSubjectReadError] = useState(null);
  const [monitoringProfileReadError, setMonitoringProfileReadError] = useState(null);
  const [aiGatewayStatus, setAiGatewayStatus] = useState(null);
  const [aiRuns, setAiRuns] = useState([]);
  const [aiRunsReadError, setAiRunsReadError] = useState(null);
  const [runtimeReadiness, setRuntimeReadiness] = useState({ status: "checking", assessment: null });
  const [writingNavigationGuard, setWritingNavigationGuard] = useState(null);
  const [pendingWritingNavigation, setPendingWritingNavigation] = useState(null);
  const activeManifest = sourceManifests[activeProjectId] || null;
  const activeSourceManifestReadError = activeProjectId
    ? sourceManifestReadErrors[activeProjectId] || null
    : null;
  const eligibilityRouteProjectId = activeManifest?.route_bindings?.eligibility_review?.route_project_id || "";
  const monitoringBinding = activeManifest?.route_bindings?.medical_monitoring || null;
  const monitoringRouteProjectId = activeManifest?.route_bindings?.medical_monitoring?.route_project_id || "";
  const monitoringReadiness = monitoringSourceReadiness(
    monitoringBinding,
  );
  const monitoringExecutionReady = monitoringReadiness.canRead === true;
  const monitoringMetricConfigurationContext = useMemo(
    () => metricConfigurationContextFromMonitoring({
      projectId: monitoringRouteProjectId,
      routeState: monitoringRouteState,
      binding: monitoringBinding,
    }),
    [
      monitoringBinding,
      monitoringRouteProjectId,
      monitoringRouteState.batch_id,
      monitoringRouteState.protocol_version_id,
    ],
  );
  const activeProjectIdRef = useRef(activeProjectId);
  const monitoringResponseProjectIdRef = useRef(activeProjectId);
  activeProjectIdRef.current = activeProjectId;
  monitoringResponseProjectIdRef.current = activeProjectId;

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const handlePopState = () => {
      const isMonitoringPath = window.location.pathname === "/monitoring";
      if (
        isMonitoringPath
        && activePage === "writing"
        && writingNavigationGuard?.dirty
      ) {
        const preservedSearch = clearMedicalMonitoringRouteState(window.location.search);
        window.history.replaceState(
          window.history.state,
          "",
          `/${preservedSearch}${window.location.hash}`,
        );
        return;
      }
      if (!isMonitoringPath) {
        if (["monitoring", "subjectTimeline", "patientProfile"].includes(activePage)) {
          setActivePage("overview");
        }
        return;
      }
      const nextRoute = parseMedicalMonitoringRouteState(window.location.search);
      if (nextRoute.view === "checklist") {
        monitoringReturnScopeRef.current = nextRoute.scope || "trial";
        monitoringReturnSiteIdRef.current = nextRoute.site_id || "";
      }
      setMonitoringRouteState(nextRoute);
      setMonitoringFocusRiskId(nextRoute.risk_instance_id || nextRoute.risk_key || "");
      if (nextRoute.subject_id) setSelectedSubject(nextRoute.subject_id);
      if (nextRoute.project_id) setActiveProjectId(nextRoute.project_id);
      setActivePage(activePageFromMonitoringRoute(nextRoute));
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [activePage, writingNavigationGuard]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const isMonitoringPage = ["monitoring", "subjectTimeline", "patientProfile"].includes(activePage);
    if (!isMonitoringPage) {
      if (window.location.pathname === "/monitoring") {
        const preservedSearch = clearMedicalMonitoringRouteState(window.location.search);
        window.history.replaceState(
          window.history.state,
          "",
          `/${preservedSearch}${window.location.hash}`,
        );
      }
      return;
    }
    const nextView = monitoringViewFromActivePage(activePage, monitoringRouteState.view);
    const isSubjectView = ["subjectTimeline", "patientProfile"].includes(activePage);
    const nextScope = isSubjectView
      ? "subject"
      : monitoringRouteState.scope || "trial";
    const nextRoute = {
      ...monitoringRouteState,
      project_id: activeProjectId || monitoringRouteState.project_id,
      scope: nextScope,
      site_id: nextScope === "site" ? monitoringRouteState.site_id || "" : "",
      subject_id: nextScope === "subject"
        ? selectedSubject || monitoringRouteState.subject_id || ""
        : "",
      view: nextView,
    };
    const nextSearch = serializeMedicalMonitoringRouteState(
      nextRoute,
      window.location.search,
    );
    const nextUrl = `/monitoring${nextSearch}${window.location.hash}`;
    const currentUrl = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    if (nextUrl !== currentUrl) {
      window.history.replaceState(window.history.state, "", nextUrl);
    }
    setMonitoringRouteState((current) => {
      const currentSerialized = serializeMedicalMonitoringRouteState(current);
      const nextSerialized = serializeMedicalMonitoringRouteState(nextRoute);
      return currentSerialized === nextSerialized ? current : nextRoute;
    });
  }, [activePage, activeProjectId, selectedSubject, monitoringRouteState]);

  const refreshRuntimeReadiness = useCallback(async () => {
    setRuntimeReadiness({ status: "checking", assessment: null });
    try {
      const response = await fetch("/api/runtime-readiness", { cache: "no-store" });
      const payload = await response.json().catch(() => null);
      const assessment = assessRuntimeReadiness(payload, {
        httpOk: response.ok,
        httpStatus: response.status,
      });
      setRuntimeReadiness({ status: assessment.ready ? "ready" : "blocked", assessment });
    } catch {
      setRuntimeReadiness({
        status: "blocked",
        assessment: assessRuntimeReadiness(null, { httpOk: false, httpStatus: 0 }),
      });
    }
  }, []);

  useEffect(() => {
    refreshRuntimeReadiness();
  }, [refreshRuntimeReadiness]);

  const requestApplicationNavigation = useCallback((label, run) => {
    if (activePage !== "writing" || !writingNavigationGuard?.dirty) {
      run();
      return;
    }
    const persistedDraft = writingNavigationGuard.persistDraft?.();
    if (persistedDraft) {
      setWritingNavigationGuard((current) => current ? { ...current, hasRecoveryDraft: true } : current);
    }
    setPendingWritingNavigation({ label, run });
  }, [activePage, writingNavigationGuard]);

  const requestActivePage = useCallback((nextPage) => {
    if (!nextPage || nextPage === activePage) return;
    const label = navItems.find((item) => item.key === nextPage)?.label || "其他工作区";
    requestApplicationNavigation(`离开医学写作并进入“${label}”`, () => setActivePage(nextPage));
  }, [activePage, requestApplicationNavigation]);

  const resetMedicalMonitoringProjectState = useCallback((nextPage) => {
    setMonitoringRouteState({});
    setMonitoringFocusRiskId("");
    setSubjectViewFocusRiskId("");
    setSelectedSubject("");
    setMonitoringWorkbenchInbox(null);
    setMonitoringDataError("");
    setMonitoringSubjectRouteError("");
    setMonitoringProjectRouteError("");
    monitoringReturnScopeRef.current = "trial";
    monitoringReturnSiteIdRef.current = "";
    if (typeof window === "undefined") return;
    const preservedSearch = clearMedicalMonitoringRouteState(window.location.search);
    const nextPath = ["monitoring", "subjectTimeline", "patientProfile"].includes(nextPage)
      ? "/monitoring"
      : window.location.pathname === "/monitoring" ? "/" : window.location.pathname;
    window.history.replaceState(
      window.history.state,
      "",
      `${nextPath}${preservedSearch}${window.location.hash}`,
    );
  }, []);

  const requestProjectChange = useCallback((nextProjectId, nextPage = "overview") => {
    if (!nextProjectId || (nextProjectId === activeProjectId && nextPage === activePage)) return;
    const projectLabel = projects.find((item) => item.project_id === nextProjectId)?.project_code || nextProjectId;
    requestApplicationNavigation(`切换至项目“${projectLabel}”`, () => {
      resetMedicalMonitoringProjectState(nextPage);
      setActiveProjectId(nextProjectId);
      setActivePage(nextPage);
    });
  }, [activePage, activeProjectId, projects, requestApplicationNavigation, resetMedicalMonitoringProjectState]);

  const retryProjects = useCallback(() => {
    setProjectsRequestNonce((current) => current + 1);
  }, []);

  const handleProjectCreated = (project) => {
    if (!project?.project_id) return;
    setProjects((current) => [
      project,
      ...current.filter((item) => item.project_id !== project.project_id),
    ]);
    requestProjectChange(project.project_id, "writing");
  };

  useEffect(() => {
    let cancelled = false;
    setProjectsLoaded(false);
    setProjectsLoadError("");
    fetch("/api/projects")
      .then(readJsonOrThrow)
      .then((payload) => {
        if (cancelled) return;
        const canonicalProjects = Array.isArray(payload) ? payload : [];
        setProjects(canonicalProjects);
        const requestedMonitoringProjectId = initialMonitoringRouteRef.current.project_id || "";
        const requestedProjectAvailable = requestedMonitoringProjectId
          && canonicalProjects.some((item) => item?.project_id === requestedMonitoringProjectId);
        setMonitoringProjectRouteError(
          requestedMonitoringProjectId && !requestedProjectAvailable
            ? `医学监查链接中的项目“${requestedMonitoringProjectId}”当前不可访问或不在项目列表中。`
            : "",
        );
        setActiveProjectId((current) => {
          if (!canonicalProjects.length) return "";
          return resolveMedicalMonitoringProjectRoute(
            requestedMonitoringProjectId,
            canonicalProjects,
            current,
            INITIAL_PROJECT_ID,
          ).projectId;
        });
        setProjectsLoaded(true);
      })
      .catch(() => {
        if (!cancelled) {
          setProjects([]);
          setActiveProjectId("");
          setMonitoringProjectRouteError("");
          setProjectsLoadError("工作台服务未连接或项目列表暂不可用；未将未知状态当作“无项目”。");
          setProjectsLoaded(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [projectsRequestNonce]);

  useEffect(() => {
    if (!activeProjectId) {
      setDashboard({ project: null, modules: [], latest_batch: null, pending_approvals: [], recent_risks: [] });
      setDashboardReadError(null);
      return undefined;
    }
    let cancelled = false;
    setDashboardReadError(null);
    setDashboard({ project: null, modules: [], latest_batch: null, pending_approvals: [], recent_risks: [] });
    fetch(`/api/projects/${activeProjectId}/dashboard`)
      .then((response) => readJsonOrThrow(response))
      .then((data) => {
        if (cancelled) return;
        if (data?.project?.project_id !== activeProjectIdRef.current) {
          setDashboardReadError(monitoringReadContractError("项目总览响应项目身份不匹配，未更新当前页面数据。"));
          return;
        }
        if (!cancelled) {
          const normalizedModules = (data.modules || []).map((module) => ({
            ...module,
            label: moduleLabels[module.module] || module.label,
          }));
          setDashboard({ ...data, modules: normalizedModules });
          setDashboardReadError(null);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setDashboard({ project: null, modules: [], latest_batch: null, pending_approvals: [], recent_risks: [] });
          setDashboardReadError(error);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeProjectId]);

  useEffect(() => {
    if (!activeProjectId) return undefined;
    let cancelled = false;
    setSourceManifestReadErrors((current) => ({ ...current, [activeProjectId]: null }));
    fetch(`/api/projects/${activeProjectId}/source-manifest`)
      .then(readJsonOrThrow)
      .then((manifest) => {
        if (cancelled) return;
        if (manifest?.project_id !== activeProjectIdRef.current) {
          setSourceManifests((current) => ({ ...current, [activeProjectId]: null }));
          setSourceManifestReadErrors((current) => ({
            ...current,
            [activeProjectId]: monitoringReadContractError("来源清单响应项目身份不匹配，未更新当前项目路由。"),
          }));
          return;
        }
        setSourceManifests((current) => ({ ...current, [activeProjectId]: manifest }));
        setSourceManifestReadErrors((current) => ({ ...current, [activeProjectId]: null }));
      })
      .catch((error) => {
        if (!cancelled) {
          setSourceManifests((current) => ({ ...current, [activeProjectId]: null }));
          setSourceManifestReadErrors((current) => ({ ...current, [activeProjectId]: error }));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeProjectId]);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/ai-gateway/status")
      .then((response) => (response.ok ? response.json() : Promise.reject(response)))
      .then((data) => {
        if (!cancelled) setAiGatewayStatus(data);
      })
      .catch(() => {
        if (!cancelled) setAiGatewayStatus({ configured: false, semantic_ai_tasks_enabled: false, codex_runtime_dependency: false, provider: "unknown", model: "not_configured", missing_env: [] });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!activeProjectId) {
      setAiRuns([]);
      setAiRunsReadError(null);
      return undefined;
    }
    let cancelled = false;
    setAiRuns([]);
    setAiRunsReadError(null);
    fetch(`/api/projects/${activeProjectId}/ai-runs`)
      .then((response) => readJsonOrThrow(response))
      .then((data) => {
        if (cancelled) return;
        if (
          !Array.isArray(data)
          || data.some((run) => run?.project_id !== activeProjectIdRef.current)
        ) {
          setAiRunsReadError(monitoringReadContractError("独立 AI 运行记录响应结构或项目身份不匹配，未更新当前页面。"));
          return;
        }
        setAiRuns(data);
        setAiRunsReadError(null);
      })
      .catch((error) => {
        if (!cancelled) {
          setAiRuns([]);
          setAiRunsReadError(error);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeProjectId]);

  const refreshDashboard = () => {
    if (!activeProjectId) return Promise.resolve();
    setDashboardReadError(null);
    return fetch(`/api/projects/${activeProjectId}/dashboard`)
      .then((response) => readJsonOrThrow(response))
      .then((data) => {
        if (data?.project?.project_id !== activeProjectIdRef.current) {
          setDashboardReadError(monitoringReadContractError("项目总览刷新响应项目身份不匹配，未更新当前页面数据。"));
          return;
        }
        const normalizedModules = (data.modules || []).map((module) => ({
          ...module,
          label: moduleLabels[module.module] || module.label,
        }));
        setDashboard({ ...data, modules: normalizedModules });
        setDashboardReadError(null);
      })
      .catch((error) => {
        setDashboardReadError(error);
        return undefined;
      });
  };

  const refreshWorkbenchInbox = (payload) => {
    if (payload) {
      if (payload.project_id === activeProjectIdRef.current) {
        setWorkbenchInbox(payload);
        setWorkbenchInboxReadError(null);
      }
      return;
    }
    if (!activeProjectId) return;
    setWorkbenchInboxReadError(null);
    fetch(`/api/projects/${activeProjectId}/workbench-inbox`)
      .then((response) => readJsonOrThrow(response))
      .then((data) => {
        if (data.project_id !== activeProjectIdRef.current) {
          setWorkbenchInboxReadError(monitoringReadContractError("工作收件箱响应项目身份不匹配，未更新当前页面。"));
          return;
        }
        setWorkbenchInbox(data);
        setWorkbenchInboxReadError(null);
      })
      .catch((error) => setWorkbenchInboxReadError(error));
  };

  const refreshMonitoringWorkbenchInbox = (payload) => {
    if (payload) {
      if (payload.project_id === monitoringResponseProjectIdRef.current) {
        setMonitoringWorkbenchInbox(payload);
        setMonitoringReadError(null);
      }
      return;
    }
    if (!monitoringRouteProjectId || !monitoringExecutionReady) {
      setMonitoringWorkbenchInbox(null);
      setMonitoringReadError(null);
      return;
    }
    setMonitoringReadError(null);
    fetch(`/api/projects/${monitoringRouteProjectId}/workbench-inbox`)
      .then((response) => readJsonOrThrow(response))
      .then((data) => {
        if (data.project_id !== monitoringResponseProjectIdRef.current) {
          setMonitoringReadError(monitoringReadContractError("医学监查工作收件箱响应项目身份不匹配，未更新当前页面。"));
          return;
        }
        setMonitoringWorkbenchInbox(data);
        setMonitoringReadError(null);
      })
      .catch((error) => setMonitoringReadError(error));
  };

  useEffect(() => {
    setWorkbenchInbox(null);
    setWorkbenchInboxReadError(null);
    if (!activeProjectId) return undefined;
    let cancelled = false;
    fetch(`/api/projects/${activeProjectId}/workbench-inbox`)
      .then((response) => readJsonOrThrow(response))
      .then((data) => {
        if (cancelled) return;
        if (data?.project_id !== activeProjectIdRef.current) {
          setWorkbenchInboxReadError(monitoringReadContractError("工作收件箱响应项目身份不匹配，未更新当前页面。"));
          return;
        }
        setWorkbenchInbox(data);
        setWorkbenchInboxReadError(null);
      })
      .catch((error) => {
        if (!cancelled) {
          setWorkbenchInbox(null);
          setWorkbenchInboxReadError(error);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeProjectId]);

  useEffect(() => {
    if (!monitoringRouteProjectId || !monitoringExecutionReady) {
      setMonitoringWorkbenchInbox(null);
      setMonitoringReadError(null);
      return undefined;
    }
    let cancelled = false;
    setMonitoringReadError(null);
    fetch(`/api/projects/${monitoringRouteProjectId}/workbench-inbox`)
      .then((response) => readJsonOrThrow(response))
      .then((data) => {
        if (cancelled) return;
        if (data?.project_id !== monitoringResponseProjectIdRef.current) {
          setMonitoringReadError(monitoringReadContractError("医学监查工作收件箱响应项目身份不匹配，未更新当前页面。"));
          return;
        }
        setMonitoringWorkbenchInbox(data);
        setMonitoringReadError(null);
      })
      .catch((error) => {
        if (!cancelled) {
          setMonitoringWorkbenchInbox(null);
          setMonitoringReadError(error);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [monitoringRouteProjectId, monitoringExecutionReady]);

  useEffect(() => {
    setSubjectProfiles({});
    setMonitoringSubjectCatalog([]);
    setMonitoringDataError("");
    setMonitoringSubjectRouteError("");
    setMonitoringSubjectReadError(null);
    if (!monitoringRouteProjectId || !monitoringExecutionReady) return undefined;
    let cancelled = false;
    fetch(`/api/projects/${monitoringRouteProjectId}/monitoring/subjects`)
      .then((response) => readJsonOrThrow(response))
      .then((data) => {
        if (cancelled) return;
        if (data?.project_id !== monitoringResponseProjectIdRef.current) {
          setMonitoringSubjectCatalog([]);
          setMonitoringSubjectReadError(monitoringReadContractError("受试者目录响应项目身份不匹配，已阻止写入当前项目。"));
          return;
        }
        const nextSubjects = Array.isArray(data.subjects) ? data.subjects : [];
        const requestedSubjectId = monitoringRouteState.subject_id || "";
        const requestedSubjectResolution = resolveMedicalMonitoringSubjectRoute(
          requestedSubjectId,
          nextSubjects,
          "",
          DEFAULT_SUBJECT_ID,
        );
        setMonitoringSubjectCatalog(nextSubjects);
        setMonitoringSubjectReadError(null);
        setMonitoringSubjectRouteError(
          requestedSubjectResolution.status === "unavailable"
            ? `医学监查链接中的受试者“${requestedSubjectId}”当前项目目录中不存在。`
            : "",
        );
        setSelectedSubject((current) => {
          if (requestedSubjectId) return requestedSubjectResolution.subjectId;
          return resolveMedicalMonitoringSubjectRoute(
            "",
            nextSubjects,
            current,
            DEFAULT_SUBJECT_ID,
          ).subjectId;
        });
      })
      .catch((error) => {
        if (!cancelled) {
          setMonitoringSubjectCatalog([]);
          setMonitoringSubjectRouteError("");
          setMonitoringSubjectReadError(error);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [monitoringRouteProjectId, monitoringExecutionReady, monitoringRouteState.subject_id]);

  const selectedSubjectProfileKey = monitoringRouteProjectId && selectedSubject
    ? `${monitoringRouteProjectId}::${selectedSubject}`
    : "";
  const selectedSubjectProfile = selectedSubjectProfileKey
    ? subjectProfiles[selectedSubjectProfileKey]
    : null;

  useEffect(() => {
    if (!monitoringRouteProjectId || !selectedSubject || !monitoringExecutionReady) {
      setMonitoringProfileReadError(null);
      return undefined;
    }
    if (selectedSubjectProfile) {
      setMonitoringProfileReadError(null);
      return undefined;
    }
    let cancelled = false;
    const requestedProfileKey = `${monitoringRouteProjectId}::${selectedSubject}`;
    setMonitoringProfileReadError(null);
    fetch(`/api/projects/${monitoringRouteProjectId}/subjects/${selectedSubject}/monitoring`)
      .then((response) => readJsonOrThrow(response))
      .then((data) => {
        if (
          cancelled
        ) return;
        if (
          data?.project_id !== monitoringResponseProjectIdRef.current
          || data?.subject_id !== selectedSubject
        ) {
          setSubjectProfiles((current) => {
            if (!(requestedProfileKey in current)) return current;
            const next = { ...current };
            delete next[requestedProfileKey];
            return next;
          });
          setMonitoringProfileReadError(monitoringReadContractError("受试者画像响应项目或受试者身份不匹配，已阻止写入当前个例。"));
          setMonitoringDataError("受试者画像响应项目或受试者身份不匹配，已阻止写入当前个例。");
          return;
        }
        setSubjectProfiles((current) => ({ ...current, [requestedProfileKey]: data }));
        setMonitoringProfileReadError(null);
      })
      .catch((error) => {
        if (!cancelled) setMonitoringProfileReadError(error);
      });
    return () => {
      cancelled = true;
    };
  }, [monitoringRouteProjectId, selectedSubject, selectedSubjectProfile, monitoringExecutionReady]);

  const requestMonitoringWorkspace = useCallback((nextPage) => {
    if (nextPage === "monitoring") {
      const returnRiskId = subjectViewFocusRiskId;
      const returnScope = monitoringReturnScopeRef.current || "trial";
      setMonitoringRouteState((current) => ({
        ...current,
        scope: returnScope,
        site_id: returnScope === "site" ? monitoringReturnSiteIdRef.current || "" : "",
        subject_id: returnScope === "subject" ? selectedSubject || current.subject_id || "" : "",
        risk_instance_id: returnRiskId,
        view: "checklist",
      }));
      setMonitoringFocusRiskId(returnRiskId);
      setSubjectViewFocusRiskId("");
    }
    requestActivePage(nextPage);
  }, [requestActivePage, selectedSubject, subjectViewFocusRiskId]);

  const requestMonitoringSubjectView = useCallback((nextPage, riskId = "", subjectId = "") => {
    const targetSubjectId = subjectId || selectedSubject || "";
    monitoringReturnScopeRef.current = monitoringRouteState.scope || "trial";
    setMonitoringRouteState((current) => ({
      ...current,
      scope: "subject",
      subject_id: targetSubjectId || current.subject_id || "",
      risk_instance_id: riskId || current.risk_instance_id || "",
      view: nextPage === "subjectTimeline" ? "timeline" : "profile",
    }));
    if (targetSubjectId && targetSubjectId !== selectedSubject) setSelectedSubject(targetSubjectId);
    setSubjectViewFocusRiskId(riskId);
    requestActivePage(nextPage);
  }, [monitoringRouteState.scope, requestActivePage, selectedSubject]);

  const requestMonitoringRiskScope = useCallback((scope, target = {}) => {
    const nextScope = ["trial", "site", "subject"].includes(scope) ? scope : "trial";
    monitoringReturnScopeRef.current = nextScope;
    monitoringReturnSiteIdRef.current = nextScope === "site" ? target.siteId || "" : "";
    setMonitoringRouteState((current) => ({
      ...current,
      scope: nextScope,
      site_id: nextScope === "site" ? target.siteId || current.site_id || "" : "",
      subject_id: nextScope === "subject" ? target.subjectId || selectedSubject || "" : "",
      risk_scroll_top: "",
      view: "checklist",
    }));
  }, [selectedSubject]);

  const requestMonitoringRiskFocus = useCallback((risk) => {
    if (!risk?.id) return;
    setMonitoringRouteState((current) => ({
      ...current,
      risk_instance_id: risk.id,
      risk_key: risk.riskKey || current.risk_key || "",
      evidence_tab: current.evidence_tab || "disposition",
      view: "checklist",
    }));
  }, []);

  const requestMonitoringRiskFocusClear = useCallback(() => {
    setMonitoringRouteState((current) => clearMedicalMonitoringRiskFocusState(current));
    setMonitoringFocusRiskId("");
    setSubjectViewFocusRiskId("");
  }, []);

  const requestMonitoringEvidenceTab = useCallback((tab) => {
    setMonitoringRouteState((current) => (
      current.evidence_tab === tab ? current : { ...current, evidence_tab: tab }
    ));
  }, []);

  const requestMonitoringChecklistQuery = useCallback((query) => {
    const patch = riskChecklistRoutePatch(query);
    setMonitoringRouteState((current) => ({
      ...current,
      ...patch,
      risk_scroll_top: "",
      view: "checklist",
    }));
  }, []);

  const requestMonitoringScrollTop = useCallback((scrollTop) => {
    const normalized = normalizeMedicalMonitoringScrollTop(scrollTop);
    setMonitoringRouteState((current) => {
      const nextValue = normalized ? String(normalized) : "";
      if ((current.risk_scroll_top || "") === nextValue) return current;
      return { ...current, risk_scroll_top: nextValue };
    });
  }, []);

  const page = useMemo(() => {
    const subject = selectedSubject
      ? buildSubjectView(
        selectedSubjectProfile,
        selectedSubject,
        null,
        monitoringSubjectCatalog,
      )
      : null;
    if (activePage === "overview") {
      return (
        <OverviewPage
          projectId={activeProjectId}
          dashboard={dashboard}
          dashboardError={dashboardReadError}
          workbenchInbox={workbenchInbox}
          workbenchInboxError={workbenchInboxReadError}
          setActivePage={requestActivePage}
          setSelectedSubject={setSelectedSubject}
          aiGatewayStatus={aiGatewayStatus}
          setAiGatewayStatus={setAiGatewayStatus}
          aiRuns={aiRuns}
          aiRunsError={aiRunsReadError}
          refreshWorkbenchInbox={refreshWorkbenchInbox}
        />
      );
    }
    if (activePage === "evidenceDesign") {
      return activeManifest?.route_bindings?.evidence_design
        ? (
          <EvidenceDesignPage
            projectId={activeProjectId}
            aiGatewayStatus={aiGatewayStatus}
            onOpenApprovals={() => refreshDashboard().finally(() => setActivePage("approvals"))}
          />
        )
        : <ModuleUnavailablePage moduleKey="evidence_design" />;
    }
    if (activePage === "eligibility") {
      return eligibilityRouteProjectId
        ? <EligibilityPage projectId={activeProjectId} routeProjectId={eligibilityRouteProjectId} />
        : <ModuleUnavailablePage moduleKey="eligibility_review" />;
    }
    if (activePage === "monitoring") {
      if (activeSourceManifestReadError) {
        return <MonitoringReadUnavailable surface="monitoring_source_manifest" error={activeSourceManifestReadError} />;
      }
      if (!monitoringRouteProjectId) return <ModuleUnavailablePage moduleKey="medical_monitoring" />;
      return (
        <MonitoringPage
          key={monitoringRouteProjectId}
          monitoringProjectId={monitoringRouteProjectId}
          sourceManifest={activeManifest}
          aiGatewayStatus={aiGatewayStatus}
          selectedSubject={selectedSubject}
          setSelectedSubject={setSelectedSubject}
          subjectProfile={selectedSubjectProfile}
          subjectCatalog={monitoringSubjectCatalog}
          setActivePage={requestActivePage}
          onOpenSubjectView={requestMonitoringSubjectView}
          refreshDashboard={refreshDashboard}
          workbenchInbox={monitoringWorkbenchInbox}
          refreshWorkbenchInbox={refreshMonitoringWorkbenchInbox}
          initialRiskId={monitoringFocusRiskId}
          initialRiskView={monitoringRouteState.view || "checklist"}
          initialEvidenceTab={monitoringRouteState.evidence_tab || "disposition"}
          initialRiskScope={monitoringRouteState.scope || "trial"}
          initialRiskSiteId={monitoringRouteState.site_id || ""}
          initialRiskScrollTop={monitoringRouteState.risk_scroll_top || ""}
          initialChecklistQuery={riskChecklistQueryFromRoute(monitoringRouteState)}
          onRiskScopeChange={requestMonitoringRiskScope}
          onRiskFocusChange={requestMonitoringRiskFocus}
          onRiskFocusClear={requestMonitoringRiskFocusClear}
          onEvidenceTabChange={requestMonitoringEvidenceTab}
          onChecklistQueryChange={requestMonitoringChecklistQuery}
          onRiskScrollTopChange={requestMonitoringScrollTop}
          onInitialRiskConsumed={() => setMonitoringFocusRiskId("")}
          subjectRouteError={monitoringSubjectRouteError}
          monitoringDataError={monitoringDataError || (monitoringReadError || monitoringSubjectReadError || monitoringProfileReadError
            ? `${monitoringReadErrorInfo(
              monitoringReadError || monitoringSubjectReadError || monitoringProfileReadError,
              monitoringReadError ? "monitoring_inbox" : monitoringSubjectReadError ? "monitoring_subjects" : "monitoring_profile",
            ).title}：${monitoringReadErrorInfo(
              monitoringReadError || monitoringSubjectReadError || monitoringProfileReadError,
              monitoringReadError ? "monitoring_inbox" : monitoringSubjectReadError ? "monitoring_subjects" : "monitoring_profile",
            ).message}`
            : "")}
        />
      );
    }
    if (activePage === "subjectTimeline") {
      if (!monitoringRouteProjectId || !monitoringExecutionReady) {
        return <ModuleUnavailablePage moduleKey="medical_monitoring" message={monitoringReadiness.message || "当前项目医学监查来源尚未达到可读取条件。"} />;
      }
      if (!subject) return <ModuleUnavailablePage moduleKey="medical_monitoring" message={monitoringSubjectRouteError || "当前项目尚无可用于Subject Timeline的真实受试者数据。"} />;
      return (
        <MedicalMonitoringSubjectTimelinePage
          subject={subject}
          setSelectedSubject={setSelectedSubject}
          onNavigate={requestMonitoringWorkspace}
          subjectCatalog={monitoringSubjectCatalog}
          focusRiskId={subjectViewFocusRiskId}
          metricConfigurationContext={monitoringMetricConfigurationContext}
        />
      );
    }
    if (activePage === "patientProfile") {
      if (!monitoringRouteProjectId || !monitoringExecutionReady) {
        return <ModuleUnavailablePage moduleKey="medical_monitoring" message={monitoringReadiness.message || "当前项目医学监查来源尚未达到可读取条件。"} />;
      }
      if (!subject) return <ModuleUnavailablePage moduleKey="medical_monitoring" message={monitoringSubjectRouteError || "当前项目尚无可用于Patient Profile的真实受试者数据。"} />;
      return (
        <MedicalMonitoringPatientProfilePage
          subject={subject}
          setSelectedSubject={setSelectedSubject}
          onNavigate={requestMonitoringWorkspace}
          subjectCatalog={monitoringSubjectCatalog}
          focusRiskId={subjectViewFocusRiskId}
        />
      );
    }
    if (activePage === "tfl") {
      return activeManifest?.route_bindings?.data_analysis_tfl
        ? <PlannedModulePage moduleKey="tfl" projectId={activeProjectId} />
        : <ModuleUnavailablePage moduleKey="data_analysis_tfl" />;
    }
    if (activePage === "writing") {
      if (runtimeReadiness.status !== "ready") {
        return (
          <MedicalWritingRuntimeGate
            readiness={runtimeReadiness}
            onRetry={refreshRuntimeReadiness}
          />
        );
      }
      return activeManifest?.route_bindings?.medical_writing
        ? <WritingPage key={activeProjectId} projectId={activeProjectId} projectHeader={activeManifest?.header_project} projectSourceMode={activeManifest?.source_mode || ""} aiGatewayStatus={aiGatewayStatus} refreshDashboard={refreshDashboard} onNavigationGuardChange={setWritingNavigationGuard} />
        : <ModuleUnavailablePage moduleKey="medical_writing" />;
    }
    if (activePage === "safety") {
      return activeManifest?.route_bindings?.safety_pv
        ? (
          <PlannedModulePage
            moduleKey="safety"
            projectId={activeProjectId}
            monitoringProjectId={monitoringRouteProjectId}
            refreshWorkbenchInbox={refreshWorkbenchInbox}
            refreshDashboard={refreshDashboard}
            onOpenMonitoringRisk={(risk) => {
              if (risk.subject && risk.subject !== "-") setSelectedSubject(risk.subject);
              setMonitoringFocusRiskId(risk.id);
              requestMonitoringRiskFocus(risk);
              requestActivePage("monitoring");
            }}
          />
        )
        : <ModuleUnavailablePage moduleKey="safety_pv" />;
    }
    if (activePage === "sourceRegistry") {
      return <SourceRegistryPage projectId={activeProjectId} onOpenModule={(module) => requestActivePage(moduleToPage[module] || "overview")} />;
    }
    return <ApprovalPage projectId={activeProjectId} dashboard={dashboard} refreshDashboard={refreshDashboard} />;
  }, [activePage, activeProjectId, activeManifest, activeSourceManifestReadError, dashboard, dashboardReadError, sourceManifests, sourceManifestReadErrors, workbenchInbox, workbenchInboxReadError, monitoringWorkbenchInbox, monitoringReadError, monitoringSubjectReadError, monitoringSubjectRouteError, monitoringProfileReadError, selectedSubject, selectedSubjectProfile, monitoringSubjectCatalog, monitoringDataError, aiGatewayStatus, aiRuns, aiRunsReadError, eligibilityRouteProjectId, monitoringRouteProjectId, monitoringMetricConfigurationContext, monitoringFocusRiskId, subjectViewFocusRiskId, runtimeReadiness, refreshRuntimeReadiness, requestActivePage, requestMonitoringWorkspace, requestMonitoringSubjectView, requestMonitoringRiskScope, requestMonitoringRiskFocus, requestMonitoringRiskFocusClear, requestMonitoringChecklistQuery, requestMonitoringScrollTop]);

  const shellUsesMonitoringInbox = Boolean(
    monitoringRouteProjectId
    && ["monitoring", "subjectTimeline", "patientProfile"].includes(activePage),
  );
  const shellWorkbenchInbox = shellUsesMonitoringInbox ? monitoringWorkbenchInbox : workbenchInbox;
  const shellWorkbenchInboxError = shellUsesMonitoringInbox ? monitoringReadError : workbenchInboxReadError;

  return (
    <>
      <AppShell
        activePage={activePage}
        setActivePage={requestActivePage}
        dashboard={dashboard}
        projects={projects}
        projectsLoaded={projectsLoaded}
        projectsLoadError={projectsLoadError}
        projectRouteError={monitoringProjectRouteError}
        activeProjectId={activeProjectId}
        requestProjectChange={requestProjectChange}
        onRetryProjects={retryProjects}
        onClearProjectRoute={() => {
          resetMedicalMonitoringProjectState("overview");
          setActivePage("overview");
        }}
          sourceManifests={sourceManifests}
          workbenchInbox={shellWorkbenchInbox}
          workbenchInboxError={shellWorkbenchInboxError}
          aiGatewayStatus={aiGatewayStatus}
        onAiGatewayStatusChange={setAiGatewayStatus}
        onProjectCreated={handleProjectCreated}
      >
        <WorkbenchErrorBoundary resetKey={`${activeProjectId}:${activePage}`}>
          {page}
        </WorkbenchErrorBoundary>
      </AppShell>
      {pendingWritingNavigation && writingNavigationGuard?.dirty && (
        <div className="writing-unsaved-navigation-backdrop app-navigation-guard" role="presentation">
          <section className="writing-unsaved-navigation-dialog" role="dialog" aria-modal="true" aria-label="离开医学写作前处理未保存修订">
            <header>
              <ShieldAlert size={18} />
              <div>
                <strong>医学写作正文尚未保存</strong>
                <span>{pendingWritingNavigation.label}。当前章节“{writingNavigationGuard.sectionTitle}”仍有未保存修订。</span>
              </div>
            </header>
            <div className="writing-unsaved-navigation-actions">
              <button type="button" onClick={() => setPendingWritingNavigation(null)}>继续编辑</button>
              {writingNavigationGuard.hasRecoveryDraft && (
                <button type="button" onClick={() => { writingNavigationGuard.restoreDraft?.(); setPendingWritingNavigation(null); }}>恢复会话稿</button>
              )}
              <button
                type="button"
                className="danger-quiet"
                onClick={() => {
                  const pending = pendingWritingNavigation;
                  writingNavigationGuard.discardDraft?.();
                  setPendingWritingNavigation(null);
                  pending.run();
                }}
              >
                丢弃并切换
              </button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
