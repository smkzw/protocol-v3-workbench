import type { Editor } from '@tiptap/core'
import { Fragment, type Mark, type Node as ProseMirrorNode, type Slice } from '@tiptap/pm/model'
import type { SourceInfo } from '@genoffice/docx-engine'
import {
  addQueueAnchor,
  queueAnchorRange,
  removeQueueAnchors,
} from './editor/ai-queue-anchors'

const CITATION_RE = /^ADDIN CMS_CITATION (\S+)$/
const BIB_ENTRY_RE = /^ADDIN CMS_BIBLIOGRAPHY_ENTRY (\S+)$/
const BIB_HEADING = 'ADDIN CMS_BIBLIOGRAPHY_HEADING'

export interface ProtocolOfficeState {
  anchors: Map<string, { baseline: string; structureSignature: string }>
  undos: Map<string, { anchorId: string; before: Slice; after: string }>
  referenceBodies: Map<string, string>
}

export function createProtocolOfficeState(): ProtocolOfficeState {
  return { anchors: new Map(), undos: new Map(), referenceBodies: new Map() }
}

function fieldMark(editor: Editor, instruction: string) {
  return editor.state.schema.marks.instrField.create({ instr: instruction, dirty: false })
}

function markedInstruction(node: { marks?: readonly { type: { name: string }; attrs?: Record<string, unknown> }[] }) {
  return String(node.marks?.find((mark) => mark.type.name === 'instrField')?.attrs?.instr ?? '')
}

function selectionKind(editor: Editor): 'table_cell' | 'paragraph' {
  const { $from } = editor.state.selection
  for (let depth = $from.depth; depth > 0; depth--) {
    if ($from.node(depth).type.spec.tableRole === 'cell') return 'table_cell'
  }
  return 'paragraph'
}

function uniformInlineMarks(editor: Editor, from: number, to: number): Mark[] | null {
  let signature: string | null = null
  let marks: Mark[] = []
  let unsupported = false
  editor.state.doc.nodesBetween(from, to, (node, pos) => {
    if (!node.isInline) return true
    if (!node.isText) {
      unsupported = true
      return false
    }
    const selectedFrom = Math.max(from, pos)
    const selectedTo = Math.min(to, pos + node.nodeSize)
    if (selectedFrom >= selectedTo) return false
    const nextSignature = JSON.stringify(node.marks.map((mark) => mark.toJSON()))
    if (signature === null) {
      signature = nextSignature
      marks = [...node.marks]
    } else if (signature !== nextSignature) {
      unsupported = true
    }
    return false
  })
  return unsupported || signature === null ? null : marks
}

function inlineStructureSignature(editor: Editor, from: number, to: number): string | null {
  const marks = uniformInlineMarks(editor, from, to)
  if (!marks) return null
  return JSON.stringify({
    target_kind: selectionKind(editor),
    parent_type: editor.state.doc.resolve(from).parent.type.name,
    marks: marks.map((mark) => mark.toJSON()),
  })
}

export function runProtocolOfficeCommand(
  editor: Editor,
  state: ProtocolOfficeState,
  command: string,
  payload: Record<string, unknown> = {},
  sources: SourceInfo[] = [],
  setSources?: (next: SourceInfo[]) => void,
  setSourcesDirty?: (dirty: boolean) => void,
): Record<string, unknown> {
  if (command === 'capture-selection') {
    const { from, to, empty, $from, $to } = editor.state.selection
    if (empty) throw new Error('请先在 Word 中选中需要修改的文字。')
    if (!$from.sameParent($to) || !$from.parent.isTextblock) {
      throw new Error('一次请选择同一段落或同一表格单元格内的文字。')
    }
    const structureSignature = inlineStructureSignature(editor, from, to)
    if (!structureSignature) {
      throw new Error('当前选区包含多种文字格式或内嵌对象。为避免破坏 Word 格式，请一次选择同一格式的连续文字。')
    }
    const baseline = editor.state.doc.textBetween(from, to, '\n', ' ')
    const anchorId = `protocol-office:${crypto.randomUUID()}`
    addQueueAnchor(editor, anchorId, from, to)
    state.anchors.set(anchorId, { baseline, structureSignature })
    return {
      anchor_id: anchorId,
      text: baseline,
      target_kind: selectionKind(editor),
      structure_mode: 'uniform_inline',
      structure_signature: structureSignature,
    }
  }

  if (command === 'replace-selection') {
    const anchorId = String(payload.anchor_id ?? '')
    const replacement = String(payload.replacement_text ?? '')
    const anchor = state.anchors.get(anchorId)
    const range = queueAnchorRange(editor.state, anchorId)
    if (!anchor || !range) throw new Error('原选区已不存在，请重新选择后生成建议。')
    const current = editor.state.doc.textBetween(range.from, range.to, '\n', ' ')
    if (current !== anchor.baseline) throw new Error('选区内容已被修改，候选没有写入。请重新生成建议。')
    const currentSignature = inlineStructureSignature(editor, range.from, range.to)
    if (currentSignature !== anchor.structureSignature) {
      throw new Error('选区格式已发生变化，候选没有写入。请重新选择后生成建议。')
    }
    if (!replacement) throw new Error('替换内容为空，系统没有改动文档。')
    const marks = uniformInlineMarks(editor, range.from, range.to)
    if (!marks) throw new Error('当前选区格式无法安全保留，系统没有改动文档。')
    const before = editor.state.doc.slice(range.from, range.to)
    const undoId = `protocol-office-undo:${crypto.randomUUID()}`
    editor.view.dispatch(editor.state.tr.replaceWith(
      range.from,
      range.to,
      editor.state.schema.text(replacement, marks),
    ))
    removeQueueAnchors(editor, [anchorId])
    state.anchors.delete(anchorId)
    addQueueAnchor(editor, undoId, range.from, range.from + replacement.length)
    const operationId = String(payload.operation_id ?? crypto.randomUUID())
    state.undos.set(operationId, { anchorId: undoId, before, after: replacement })
    return {
      operation_id: operationId,
      replaced: true,
      structure_mode: 'uniform_inline',
      structure_signature: anchor.structureSignature,
    }
  }

  if (command === 'undo-replacement') {
    const operationId = String(payload.operation_id ?? '')
    const undo = state.undos.get(operationId)
    const range = undo ? queueAnchorRange(editor.state, undo.anchorId) : null
    if (!undo || !range) throw new Error('该修改之后的目标位置已变化，无法自动撤销。')
    const current = editor.state.doc.textBetween(range.from, range.to, '\n', ' ')
    if (current !== undo.after) throw new Error('该修改之后又有新编辑，系统没有覆盖这些新内容。')
    editor.view.dispatch(editor.state.tr.replace(range.from, range.to, undo.before))
    removeQueueAnchors(editor, [undo.anchorId])
    state.undos.delete(operationId)
    return { operation_id: operationId, undone: true }
  }

  if (command === 'release-selection') {
    const anchorId = String(payload.anchor_id ?? '')
    removeQueueAnchors(editor, [anchorId])
    state.anchors.delete(anchorId)
    return { released: true }
  }

  if (command === 'insert-project-citation') {
    const reference = (payload.reference ?? {}) as Record<string, unknown>
    const referenceId = String(reference.reference_id ?? '').trim()
    const title = String(reference.title ?? '').trim()
    if (!referenceId || !title) throw new Error('文献信息不完整，尚未插入。')
    const tag = `CMS_${referenceId.replace(/[^A-Za-z0-9_-]/g, '_').slice(0, 120)}`
    const authors = Array.isArray(reference.authors)
      ? reference.authors.map(String).filter(Boolean)
      : []
    const source: SourceInfo = {
      tag,
      type: String(reference.journal ?? '').trim() ? 'JournalArticle' : 'InternetSite',
      author: authors.join(', '),
      ...(authors.length > 1 ? { authors } : {}),
      title,
      year: String(reference.year ?? ''),
      ...(String(reference.journal ?? '').trim()
        ? { publisher: String(reference.journal) }
        : {}),
      ...(String(reference.volume ?? '').trim() ? { volume: String(reference.volume) } : {}),
      ...(String(reference.issue ?? '').trim() ? { issue: String(reference.issue) } : {}),
      ...(String(reference.pages ?? '').trim() ? { pages: String(reference.pages) } : {}),
      ...(String(reference.doi ?? '').trim() ? { doi: String(reference.doi) } : {}),
      ...(String(reference.url ?? '').trim() ? { url: String(reference.url) } : {}),
    }
    if (!sources.some((item) => item.tag === tag)) {
      setSources?.([...sources, source])
      setSourcesDirty?.(true)
    }
    state.referenceBodies.set(tag, String(payload.formatted_entry_body ?? title))
    const at = editor.state.selection.to
    const mark = fieldMark(editor, `ADDIN CMS_CITATION ${tag}`)
    editor.view.dispatch(editor.state.tr.insert(at, editor.state.schema.text('[?]', [mark])))
    syncManagedProjectCitations(editor, state)
    editor.commands.focus()
    return { inserted: true, reference_id: referenceId, source_tag: tag }
  }

  throw new Error(`不支持的文档命令：${command}`)
}

interface InlineFieldRange {
  from: number
  to: number
  text: string
  tag: string
  marks: readonly unknown[]
}

interface BibliographyBlock {
  from: number
  to: number
  tag: string
  text: string
  node: ProseMirrorNode
}

function replaceBlockText(
  block: ProseMirrorNode | undefined,
  fallbackType: ProseMirrorNode['type'],
  fallbackAttrs: Record<string, unknown>,
  text: ProseMirrorNode,
): ProseMirrorNode {
  const type = block?.type ?? fallbackType
  const attrs = block?.attrs ?? fallbackAttrs
  return type.create(attrs, text)
}

function retainedInlineMarks(block: ProseMirrorNode | undefined): Mark[] {
  let marks: Mark[] = []
  block?.descendants((node) => {
    if (marks.length === 0 && node.isText) {
      marks = node.marks.filter((mark) => mark.type.name !== 'instrField')
    }
    return marks.length === 0
  })
  return marks
}

/** Keep CMS-managed Word fields ordered by first appearance. */
export function syncManagedProjectCitations(editor: Editor, state: ProtocolOfficeState): void {
  const citations: InlineFieldRange[] = []
  const bibliographyBlocks: BibliographyBlock[] = []
  let headingPresent = false

  editor.state.doc.descendants((node, pos) => {
    if (!node.isText) return
    const instruction = markedInstruction(node)
    const citation = CITATION_RE.exec(instruction)
    if (citation) citations.push({ from: pos, to: pos + node.nodeSize, text: node.text ?? '', tag: citation[1], marks: node.marks })
  })
  editor.state.doc.forEach((block, offset) => {
    let tag = ''
    let heading = false
    block.descendants((node) => {
      if (!node.isText) return
      const instruction = markedInstruction(node)
      const entry = BIB_ENTRY_RE.exec(instruction)
      if (entry) tag = entry[1]
      if (instruction === BIB_HEADING) heading = true
    })
    if (tag) bibliographyBlocks.push({ from: offset, to: offset + block.nodeSize, tag, text: block.textContent, node: block })
    if (heading) {
      headingPresent = true
      bibliographyBlocks.push({ from: offset, to: offset + block.nodeSize, tag: '', text: block.textContent, node: block })
    }
  })

  const order = [...new Set(citations.map((item) => item.tag))]
  const numberByTag = new Map(order.map((tag, index) => [tag, index + 1]))
  const bodyByTag = new Map(state.referenceBodies)
  bibliographyBlocks.forEach((block) => {
    if (block.tag && !bodyByTag.has(block.tag)) {
      bodyByTag.set(block.tag, block.text.replace(/^\s*\[\d+\]\s*/, ''))
    }
  })
  let transaction = editor.state.tr
  for (const item of [...citations].sort((a, b) => b.from - a.from)) {
    const label = `[${numberByTag.get(item.tag)}]`
    if (item.text !== label) {
      transaction = transaction.replaceWith(
        item.from,
        item.to,
        editor.state.schema.text(label, item.marks as never),
      )
    }
  }

  const existingOrder = bibliographyBlocks.filter((block) => block.tag).map((block) => block.tag)
  const expectedTexts = order.map((tag, index) => `[${index + 1}] ${bodyByTag.get(tag) ?? tag}`)
  const existingTexts = bibliographyBlocks.filter((block) => block.tag).map((block) => block.text)
  const rebuild = headingPresent !== (order.length > 0)
    || existingOrder.join('\u0000') !== order.join('\u0000')
    || existingTexts.join('\u0000') !== expectedTexts.join('\u0000')
  if (rebuild) {
    const originalInsertion = bibliographyBlocks.length > 0
      ? Math.min(...bibliographyBlocks.map((block) => block.from))
      : editor.state.doc.content.size
    const headingTemplate = bibliographyBlocks.find((block) => !block.tag)?.node
    const entryTemplate = bibliographyBlocks.find((block) => block.tag)?.node
    for (const block of [...bibliographyBlocks].sort((a, b) => b.from - a.from)) {
      transaction = transaction.delete(
        transaction.mapping.map(block.from),
        transaction.mapping.map(block.to),
      )
    }
    if (order.length > 0) {
      const schema = editor.state.schema
      const headingMarks = retainedInlineMarks(headingTemplate)
      const entryMarks = retainedInlineMarks(entryTemplate)
      const heading = replaceBlockText(
        headingTemplate,
        schema.nodes.docHeading,
        { docxIndex: null, styleId: null, aiChanged: false, level: 1 },
        schema.text('参考文献', [...headingMarks, fieldMark(editor, BIB_HEADING)]),
      )
      const entries = order.map((tag, index) => replaceBlockText(
        entryTemplate,
        schema.nodes.docParagraph,
        { docxIndex: null, styleId: null, aiChanged: false },
        schema.text(`[${index + 1}] ${bodyByTag.get(tag) ?? tag}`, [...entryMarks,
          fieldMark(editor, `ADDIN CMS_BIBLIOGRAPHY_ENTRY ${tag}`),
        ]),
      ))
      transaction = transaction.insert(
        transaction.mapping.map(originalInsertion, -1),
        Fragment.fromArray([heading, ...entries]),
      )
    }
  }
  if (transaction.docChanged) {
    transaction.setMeta('addToHistory', false)
    editor.view.dispatch(transaction)
  }
}
