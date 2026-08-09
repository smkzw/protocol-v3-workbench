import { useEffect, useRef, useState } from "react";
import { EditorContent, useEditor } from "@tiptap/react";
import { Extension } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import TextAlign from "@tiptap/extension-text-align";
import Highlight from "@tiptap/extension-highlight";
import Subscript from "@tiptap/extension-subscript";
import Superscript from "@tiptap/extension-superscript";
import { Color, FontFamily, FontSize, TextStyle } from "@tiptap/extension-text-style";
import {
  AlignCenter,
  AlignJustify,
  AlignLeft,
  AlignRight,
  Bold,
  Eraser,
  Highlighter,
  IndentDecrease,
  IndentIncrease,
  Italic,
  List,
  ListOrdered,
  Link2,
  Palette,
  Redo2,
  Subscript as SubscriptIcon,
  Superscript as SuperscriptIcon,
  Underline as UnderlineIcon,
  Undo2,
} from "lucide-react";
import { WordEditingShortcuts } from "./WordEditingShortcuts";
import {
  CrossReferenceMark,
  insertCrossReference,
} from "./CrossReferenceMark";

const PARAGRAPH_DEFAULTS = {
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

const CellParagraphFormatting = Extension.create({
  name: "cellParagraphFormatting",
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
            : { "data-line-height": attributes.lineHeight, style: `line-height: ${attributes.lineHeight}` },
        },
        spacingBeforePt: {
          default: null,
          parseHTML: (element) => numericDataAttribute(element, "data-spacing-before-pt"),
          renderHTML: (attributes) => attributes.spacingBeforePt == null
            ? {}
            : { "data-spacing-before-pt": attributes.spacingBeforePt, style: `margin-top: ${attributes.spacingBeforePt}pt` },
        },
        spacingAfterPt: {
          default: null,
          parseHTML: (element) => numericDataAttribute(element, "data-spacing-after-pt"),
          renderHTML: (attributes) => attributes.spacingAfterPt == null
            ? {}
            : { "data-spacing-after-pt": attributes.spacingAfterPt, style: `margin-bottom: ${attributes.spacingAfterPt}pt` },
        },
        leftIndentChars: {
          default: null,
          parseHTML: (element) => numericDataAttribute(element, "data-left-indent-chars"),
          renderHTML: (attributes) => attributes.leftIndentChars == null
            ? {}
            : { "data-left-indent-chars": attributes.leftIndentChars, style: `margin-left: ${attributes.leftIndentChars}em` },
        },
        rightIndentChars: {
          default: null,
          parseHTML: (element) => numericDataAttribute(element, "data-right-indent-chars"),
          renderHTML: (attributes) => attributes.rightIndentChars == null
            ? {}
            : { "data-right-indent-chars": attributes.rightIndentChars, style: `margin-right: ${attributes.rightIndentChars}em` },
        },
        firstLineIndentChars: {
          default: null,
          parseHTML: (element) => numericDataAttribute(element, "data-first-line-indent-chars"),
          renderHTML: (attributes) => attributes.firstLineIndentChars == null
            ? {}
            : { "data-first-line-indent-chars": attributes.firstLineIndentChars, style: `text-indent: ${attributes.firstLineIndentChars}em` },
        },
      },
    }];
  },
});

const STYLE_PRESETS = [
  { id: "heading_1", label: "一级标题", node: "heading", level: 1, font: "黑体", size: "16pt", attrs: { lineHeight: 1, spacingBeforePt: 18, spacingAfterPt: 8, leftIndentChars: 0, rightIndentChars: 0, firstLineIndentChars: 0 } },
  { id: "heading_2", label: "二级标题", node: "heading", level: 2, font: "黑体", size: "14pt", attrs: { lineHeight: 1, spacingBeforePt: 14, spacingAfterPt: 6, leftIndentChars: 0, rightIndentChars: 0, firstLineIndentChars: 0 } },
  { id: "heading_3", label: "三级标题", node: "heading", level: 3, font: "黑体", size: "12pt", attrs: { lineHeight: 1, spacingBeforePt: 10, spacingAfterPt: 4, leftIndentChars: 0, rightIndentChars: 0, firstLineIndentChars: 0 } },
  { id: "heading_4", label: "四级标题", node: "heading", level: 4, font: "黑体", size: "10.5pt", attrs: { lineHeight: 1, spacingBeforePt: 8, spacingAfterPt: 3, leftIndentChars: 0, rightIndentChars: 0, firstLineIndentChars: 0 } },
  { id: "body", label: "正文", node: "paragraph", font: "宋体", size: "10.5pt", attrs: { lineHeight: 1.5, spacingBeforePt: 0, spacingAfterPt: 4, leftIndentChars: 0, rightIndentChars: 0, firstLineIndentChars: 0 } },
  { id: "note", label: "附注", node: "paragraph", font: "宋体", size: "9pt", attrs: { lineHeight: 1, spacingBeforePt: 2, spacingAfterPt: 2, leftIndentChars: 0, rightIndentChars: 0, firstLineIndentChars: 0 } },
];
const FONT_OPTIONS = ["宋体", "黑体", "仿宋", "楷体", "Arial", "Times New Roman"];
const FONT_SIZE_OPTIONS = ["8pt", "9pt", "10.5pt", "12pt", "14pt", "16pt", "18pt", "22pt"];
const HIGHLIGHT_OPTIONS = [
  { value: "", label: "无标黄" },
  { value: "#FFFF00", label: "黄色" },
  { value: "#00FF00", label: "绿色" },
  { value: "#00FFFF", label: "青色" },
  { value: "#FF00FF", label: "粉色" },
];

function blockType(editor) {
  return editor?.isActive("heading") ? "heading" : "paragraph";
}

function blockAttributes(editor) {
  return editor?.getAttributes(blockType(editor)) || {};
}

function updateBlock(editor, attrs) {
  return editor?.chain().focus().updateAttributes(blockType(editor), attrs).run();
}

function cellDocument(value, plainText) {
  if (value?.type === "doc" && Array.isArray(value.content)) return value;
  if (value?.type) return { type: "doc", content: [value] };
  return {
    type: "doc",
    content: [{
      type: "paragraph",
      content: plainText ? [{ type: "text", text: String(plainText) }] : undefined,
    }],
  };
}

export function TableCellRichEditor({
  cell,
  readOnly = false,
  documentIndex = null,
  focusRequest = 0,
  onChange,
  onNavigateCell,
}) {
  const [paragraphSettingsOpen, setParagraphSettingsOpen] = useState(false);
  const onChangeRef = useRef(onChange);
  const readOnlyRef = useRef(readOnly);
  const onNavigateCellRef = useRef(onNavigateCell);
  const documentBaselineRef = useRef("");
  const editorReadyRef = useRef(false);
  onChangeRef.current = onChange;
  readOnlyRef.current = readOnly;
  onNavigateCellRef.current = onNavigateCell;
  const editor = useEditor({
    extensions: [
      StarterKit,
      TextStyle,
      FontFamily,
      FontSize,
      Color,
      Subscript,
      Superscript,
      CrossReferenceMark,
      Highlight.configure({ multicolor: true }),
      TextAlign.configure({ types: ["heading", "paragraph"] }),
      CellParagraphFormatting,
      WordEditingShortcuts,
    ],
    editable: !readOnly,
    content: cellDocument(cell?.rich_text, cell?.text),
    onCreate: ({ editor: current }) => {
      documentBaselineRef.current = JSON.stringify(current.getJSON());
      editorReadyRef.current = true;
    },
    onUpdate: ({ editor: current }) => {
      if (readOnlyRef.current || !cell?.cell_id) return;
      if (!editorReadyRef.current) return;
      const nextDocument = current.getJSON();
      const serialized = JSON.stringify(nextDocument);
      if (serialized === documentBaselineRef.current) return;
      documentBaselineRef.current = serialized;
      onChangeRef.current?.({
        text: current.getText({ blockSeparator: "\n" }),
        rich_text: nextDocument,
      });
    },
    editorProps: {
      handleKeyDown: (_view, event) => {
        if (event.key !== "Tab" || readOnlyRef.current) return false;
        event.preventDefault();
        onNavigateCellRef.current?.(event.shiftKey ? -1 : 1);
        return true;
      },
    },
  }, [cell?.cell_id]);

  useEffect(() => {
    editor?.setEditable(!readOnly);
  }, [editor, readOnly]);

  useEffect(() => {
    if (!editor || !cell?.cell_id) return;
    const incoming = cellDocument(cell.rich_text, cell.text);
    if (JSON.stringify(editor.getJSON()) !== JSON.stringify(incoming)) {
      editor.commands.setContent(incoming, { emitUpdate: false });
    }
    documentBaselineRef.current = JSON.stringify(editor.getJSON());
  }, [editor, cell?.cell_id, cell?.rich_text, cell?.text]);

  useEffect(() => {
    if (!editor || readOnly || !focusRequest) return;
    const frame = globalThis.requestAnimationFrame?.(() => editor.commands.focus("end"));
    return () => globalThis.cancelAnimationFrame?.(frame);
  }, [editor, focusRequest, readOnly]);

  if (!cell?.cell_id || !editor) {
    return <div className="std-cell-rich-empty">选择单元格后可编辑文字与段落格式</div>;
  }

  const attrs = blockAttributes(editor);
  const styleId = attrs.stylePreset
    || (editor.isActive("heading") ? `heading_${Math.min(Number(editor.getAttributes("heading")?.level || 1), 4)}` : "body");
  const preset = STYLE_PRESETS.find((item) => item.id === styleId) || STYLE_PRESETS[4];
  const textStyle = editor.getAttributes("textStyle") || {};
  const highlight = editor.getAttributes("highlight")?.color || "";
  const disabled = readOnly || !editor;
  const crossReferenceTargets = [
    ...(documentIndex?.tables || []),
    ...(documentIndex?.figures || []),
  ];
  const setNumber = (key, raw) => {
    const value = Number(raw);
    if (Number.isFinite(value)) updateBlock(editor, { [key]: value });
  };
  const applyStyle = (presetId) => {
    const next = STYLE_PRESETS.find((item) => item.id === presetId);
    if (!next) return;
    const chain = editor.chain().focus();
    if (next.node === "heading") chain.setHeading({ level: next.level });
    else chain.setParagraph();
    chain.updateAttributes(next.node, { stylePreset: next.id, ...next.attrs }).run();
  };
  const adjustIndent = (delta) => {
    const current = Number(blockAttributes(editor).leftIndentChars || 0);
    updateBlock(editor, { leftIndentChars: Math.min(20, Math.max(0, current + delta)) });
  };

  return (
    <section className="std-cell-rich-panel" aria-label="当前单元格文字与段落编辑">
      <div className="std-cell-rich-identity">
        <strong>当前单元格</strong>
        <span>{cell.rowIndex + 1} 行 / {cell.columnIndex + 1} 列</span>
      </div>
      <div className="rich-toolbar std-rich-toolbar" aria-label="单元格格式工具栏">
        <div className="rich-toolbar-row rich-toolbar-text-row">
          <label className="rich-toolbar-select rich-style-select"><span>样式</span><select aria-label="单元格段落样式" value={styleId} disabled={disabled} onChange={(event) => applyStyle(event.target.value)}>{STYLE_PRESETS.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
          <label className="rich-toolbar-select rich-font-select"><span>字体</span><select aria-label="单元格字体" value={textStyle.fontFamily || preset.font} disabled={disabled} onChange={(event) => editor.chain().focus().setFontFamily(event.target.value).run()}>{FONT_OPTIONS.map((font) => <option key={font} value={font}>{font}</option>)}</select></label>
          <label className="rich-toolbar-select rich-size-select"><span>字号</span><select aria-label="单元格字号" value={textStyle.fontSize || preset.size} disabled={disabled} onChange={(event) => editor.chain().focus().setFontSize(event.target.value).run()}>{FONT_SIZE_OPTIONS.map((size) => <option key={size} value={size}>{size.replace("pt", "")}</option>)}</select></label>
          <span className="rich-toolbar-separator" aria-hidden="true" />
          {[
            ["加粗", Bold, editor.isActive("bold"), () => editor.chain().focus().toggleBold().run()],
            ["斜体", Italic, editor.isActive("italic"), () => editor.chain().focus().toggleItalic().run()],
            ["下划线", UnderlineIcon, editor.isActive("underline"), () => editor.chain().focus().toggleUnderline().run()],
            ["上标", SuperscriptIcon, editor.isActive("superscript"), () => editor.chain().focus().toggleSuperscript().run()],
            ["下标", SubscriptIcon, editor.isActive("subscript"), () => editor.chain().focus().toggleSubscript().run()],
          ].map(([label, Icon, active, run]) => <button type="button" key={label} className={active ? "active" : ""} disabled={disabled} onClick={run} title={label} aria-label={`单元格${label}`}><Icon size={15} /></button>)}
          <span className="rich-toolbar-separator" aria-hidden="true" />
          <label className="rich-color-control" title="文字颜色"><Palette size={15} /><span className="rich-color-swatch" style={{ backgroundColor: textStyle.color || "#222222" }} /><input type="color" aria-label="单元格文字颜色" value={/^#[0-9a-f]{6}$/i.test(textStyle.color || "") ? textStyle.color : "#222222"} disabled={disabled} onChange={(event) => editor.chain().focus().setColor(event.target.value.toUpperCase()).run()} /></label>
          <label className="rich-highlight-control" title="文字标黄"><Highlighter size={15} /><span className="rich-color-swatch" style={{ backgroundColor: highlight || "#ffff00" }} /><select aria-label="单元格文字标黄" value={highlight} disabled={disabled} onChange={(event) => event.target.value ? editor.chain().focus().setHighlight({ color: event.target.value }).run() : editor.chain().focus().unsetHighlight().run()}>{HIGHLIGHT_OPTIONS.map((item) => <option key={item.value || "none"} value={item.value}>{item.label}</option>)}</select></label>
          <button type="button" disabled={disabled} title="清除直接格式" aria-label="清除单元格直接格式" onClick={() => editor.chain().focus().unsetAllMarks().updateAttributes(blockType(editor), { ...PARAGRAPH_DEFAULTS, stylePreset: attrs.stylePreset || null }).run()}><Eraser size={15} /></button>
        </div>
        <div className="rich-toolbar-row rich-toolbar-paragraph-row">
          {[
            ["项目符号", List, editor.isActive("bulletList"), () => editor.chain().focus().toggleBulletList().run()],
            ["编号", ListOrdered, editor.isActive("orderedList"), () => editor.chain().focus().toggleOrderedList().run()],
            ["左对齐", AlignLeft, editor.isActive({ textAlign: "left" }), () => editor.chain().focus().setTextAlign("left").run()],
            ["居中", AlignCenter, editor.isActive({ textAlign: "center" }), () => editor.chain().focus().setTextAlign("center").run()],
            ["右对齐", AlignRight, editor.isActive({ textAlign: "right" }), () => editor.chain().focus().setTextAlign("right").run()],
            ["两端对齐", AlignJustify, editor.isActive({ textAlign: "justify" }), () => editor.chain().focus().setTextAlign("justify").run()],
            ["减少左缩进", IndentDecrease, false, () => adjustIndent(-1)],
            ["增加左缩进", IndentIncrease, false, () => adjustIndent(1)],
          ].map(([label, Icon, active, run]) => <button type="button" key={label} className={active ? "active" : ""} disabled={disabled} onClick={run} title={label} aria-label={`单元格${label}`}><Icon size={15} /></button>)}
          <span className="rich-toolbar-separator" aria-hidden="true" />
          <label className="rich-toolbar-select rich-line-height-select"><span>行距</span><select aria-label="单元格行距" value={attrs.lineHeight ?? preset.attrs.lineHeight} disabled={disabled} onChange={(event) => setNumber("lineHeight", event.target.value)}>{[1, 1.15, 1.25, 1.5, 2].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
          <div className="rich-paragraph-settings">
            <button type="button" className={paragraphSettingsOpen ? "active" : ""} disabled={disabled} aria-expanded={paragraphSettingsOpen} onClick={() => setParagraphSettingsOpen((value) => !value)}>段落</button>
            {paragraphSettingsOpen && <div className="rich-paragraph-popover" role="dialog" aria-label="单元格段落设置">{[
              ["首行缩进（字符）", "firstLineIndentChars", attrs.firstLineIndentChars ?? preset.attrs.firstLineIndentChars, -10, 20, 0.5],
              ["左缩进（字符）", "leftIndentChars", attrs.leftIndentChars ?? 0, 0, 20, 0.5],
              ["右缩进（字符）", "rightIndentChars", attrs.rightIndentChars ?? 0, 0, 20, 0.5],
              ["段前（磅）", "spacingBeforePt", attrs.spacingBeforePt ?? preset.attrs.spacingBeforePt, 0, 72, 1],
              ["段后（磅）", "spacingAfterPt", attrs.spacingAfterPt ?? preset.attrs.spacingAfterPt, 0, 72, 1],
            ].map(([label, key, value, min, max, step]) => <label key={key}><span>{label}</span><input type="number" min={min} max={max} step={step} value={value} onChange={(event) => setNumber(key, event.target.value)} /></label>)}</div>}
          </div>
          <span className="rich-toolbar-separator" aria-hidden="true" />
          <button type="button" disabled={disabled || !editor.can().undo()} title="撤销" aria-label="撤销单元格编辑" onClick={() => editor.chain().focus().undo().run()}><Undo2 size={15} /></button>
          <button type="button" disabled={disabled || !editor.can().redo()} title="重做" aria-label="重做单元格编辑" onClick={() => editor.chain().focus().redo().run()}><Redo2 size={15} /></button>
          <span className="rich-toolbar-separator" aria-hidden="true" />
          <label className="rich-cross-reference-picker" title="在当前单元格插入表或图的交叉引用">
            <Link2 size={15} aria-hidden="true" />
            <select
              aria-label="单元格插入交叉引用"
              value=""
              disabled={disabled || !crossReferenceTargets.length}
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
        </div>
      </div>
      <EditorContent editor={editor} className="std-cell-rich-editor" />
    </section>
  );
}
