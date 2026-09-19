/**
 * T07 feasibility spike: GenOffice docx-engine opens, patches and saves the
 * real protocol export (Chinese/English, tables, headers/footers, sections,
 * TOC field, hyperlinks, bookmarks) with byte-preserving untouched parts.
 *
 * Evidence is written to runs/requirements_v2_20260919/genoffice_feasibility.json
 * in the protocol-v3-workbench repository.
 */
import { describe, expect, it } from 'vitest'
import { parseDocx, saveDocx } from '../src/index'
import { patchParagraphTexts } from '../src/text-patch'
import { readFileSync, writeFileSync } from 'node:fs'
import JSZip from 'jszip'

const PROTOCOL = '/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/mw_protocol_v3_unified_tests_20260919/acceptance_evidence/12_final_clean.docx'
const EVIDENCE_OUT = '/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/requirements_v2_20260919/genoffice_feasibility.json'

const bytesOf = (buffer: Buffer): Uint8Array => new Uint8Array(buffer)

async function partMap(bytes: Uint8Array): Promise<Map<string, string>> {
  const zip = await JSZip.loadAsync(bytes)
  const map = new Map<string, string>()
  zip.forEach((path, file) => {
    if (!file.dir) map.set(path, path)
  })
  return map
}

async function partText(bytes: Uint8Array, path: string): Promise<string> {
  const zip = await JSZip.loadAsync(bytes)
  return (await zip.file(path)?.async('string')) ?? ''
}

function countOf(haystack: string, needle: string): number {
  return haystack.split(needle).length - 1
}

describe('T07 GenOffice docx-engine feasibility on the real protocol export', () => {
  const source = bytesOf(readFileSync(PROTOCOL))
  const evidence: Record<string, unknown> = {
    source: PROTOCOL,
    source_bytes: source.byteLength,
  }

  it('opens the 140-page protocol: Chinese/English text, tables, TOC, headers', async () => {
    const parsed = await parseDocx(source)
    const documentXml = (parsed.internal as { documentXml: string }).documentXml
    evidence.parsed_blocks = parsed.blocks.filter((b) => !b.hidden).length
    expect(parsed.blocks.length).toBeGreaterThan(200)
    // Chinese and English content both parse.
    expect(documentXml).toContain('研究')
    expect(documentXml).toContain('试验参与者')
    // Tables, TOC field, hyperlinks, bookmarks, sections exist.
    expect(countOf(documentXml, '<w:tbl>')).toBeGreaterThan(3)
    expect(documentXml).toContain('TOC')
    evidence.tables = countOf(documentXml, '<w:tbl>')
    evidence.toc_fields = countOf(documentXml, 'TOC')
    evidence.hyperlinks = countOf(documentXml, '<w:hyperlink')
    evidence.bookmarks = countOf(documentXml, 'bookmarkStart')
    evidence.sections = countOf(documentXml, '<w:sectPr')
    expect(evidence.sections as number).toBeGreaterThanOrEqual(1)
    // Headers/footers are real parts.
    const parts = await partMap(source)
    const headerFooter = [...parts.keys()].filter((p) => /word\/(header|footer)\d+\.xml/.test(p))
    evidence.header_footer_parts = headerFooter.length
    expect(headerFooter.length).toBeGreaterThan(0)
  }, 120_000)

  it('round-trips unchanged content byte-for-byte', async () => {
    const parsed = await parseDocx(source)
    const finalBlocks = parsed.blocks
      .filter((b) => !b.hidden)
      .map((b) => ({ kind: 'original' as const, docxIndex: b.docxIndex }))
    const saved = await saveDocx(parsed, finalBlocks)
    evidence.unchanged_roundtrip_bytes = saved.byteLength
    expect(Buffer.from(saved).equals(Buffer.from(source))).toBe(true)
  }, 120_000)

  it('rewrites only the patched paragraph; headers, styles, tables, TOC survive', async () => {
    const parsed = await parseDocx(source)
    const target = parsed.blocks.find(
      (b) => !b.hidden && ['paragraph', 'heading', 'listItem'].includes(b.type)
        && typeof b.originalXml === 'string' && b.originalXml.includes('研究'),
    )
    expect(target).toBeDefined()
    const patchedXml = patchParagraphTexts(
      target.originalXml,
      '可行性验证：本段由GenOffice引擎按协议v3工作稿补丁保存路径改写（T07 spike）。',
    )
    expect(patchedXml).not.toBeNull()
    const finalBlocks = parsed.blocks
      .filter((b) => !b.hidden)
      .map((b) =>
        b.docxIndex === target.docxIndex
          ? { kind: 'xml' as const, xml: patchedXml, docxIndex: b.docxIndex }
          : ({ kind: 'original' as const, docxIndex: b.docxIndex }),
      )
    const saved = await saveDocx(parsed, finalBlocks, {
      modified: '2026-09-19T00:00:00.000Z',
    })
    writeFileSync(
      '/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/requirements_v2_20260919/genoffice_feasibility_patched.docx',
      Buffer.from(saved),
    )

    const docBefore = await partText(source, 'word/document.xml')
    const docAfter = await partText(saved, 'word/document.xml')
    expect(docAfter).toContain('可行性验证：本段由GenOffice引擎')
    // Everything else in the body survives.
    expect(countOf(docAfter, '<w:tbl>')).toBe(countOf(docBefore, '<w:tbl>'))
    expect(countOf(docAfter, 'TOC')).toBe(countOf(docBefore, 'TOC'))
    expect(countOf(docAfter, '<w:hyperlink')).toBe(countOf(docBefore, '<w:hyperlink'))
    expect(countOf(docAfter, 'bookmarkStart')).toBe(countOf(docBefore, 'bookmarkStart'))
    expect(countOf(docAfter, '<w:sectPr')).toBe(countOf(docBefore, '<w:sectPr'))

    // Non-document parts are byte-identical (headers, footers, styles, media).
    const partsBefore = await partMap(source)
    const partsAfter = await partMap(saved)
    const missing = [...partsBefore.keys()].filter((k) => !partsAfter.has(k))
    const added = [...partsAfter.keys()].filter((k) => !partsBefore.has(k))
    // word/media/flow.png is an orphan in the source export: its rId16
    // relationship exists but no r:embed / v:imagedata r:id references it in
    // document.xml.  The engine correctly prunes unreferenced media; the
    // source defect is recorded for the protocol-v3 export pipeline.
    const KNOWN_ORPHANS = ['word/media/flow.png']
    const unexpected = missing.filter((k) => !KNOWN_ORPHANS.includes(k))
    evidence.part_diff = { missing, added, known_orphans_dropped: KNOWN_ORPHANS }
    expect(unexpected).toEqual([])
    const beforeBuf = await JSZip.loadAsync(source)
    const afterBuf = await JSZip.loadAsync(saved)
    const compared = { identical: 0, changed: [] as string[] }
    for (const [path] of partsBefore) {
      const a = await beforeBuf.file(path)?.async('nodebuffer')
      const b = await afterBuf.file(path)?.async('nodebuffer')
      if (path === 'word/document.xml' || path === 'docProps/core.xml') continue
      if (KNOWN_ORPHANS.includes(path)) continue
      if (path === 'word/_rels/document.xml.rels') {
        // The only allowed rels change: the pruned orphan relationship.
        const relsBefore = (await beforeBuf.file(path)?.async('string')) ?? ''
        const relsAfter = (await afterBuf.file(path)?.async('string')) ?? ''
        const removed = relsBefore.split('<Relationship ').filter((r) => !relsAfter.includes(r))
        expect(removed.length).toBe(1)
        expect(removed[0]).toContain('flow.png')
        continue
      }
      if (Buffer.from(a ?? '').equals(Buffer.from(b ?? ''))) compared.identical += 1
      else compared.changed.push(path)
    }
    evidence.part_comparison = compared
    expect(compared.changed).toEqual([])

    // The saved file reparses cleanly (Word-shaped input/output invariance).
    const reparsed = await parseDocx(saved)
    expect(reparsed.blocks.length).toBeGreaterThan(200)

    evidence.patched_bytes = saved.byteLength
    writeFileSync(EVIDENCE_OUT, JSON.stringify(evidence, null, 2))
  }, 120_000)
})
