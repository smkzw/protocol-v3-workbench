/**
 * GenOffice docs renderer bridge shim (T10/P3; audit G1 rework).
 *
 * Loaded inside the iframe BEFORE the renderer module script.  Implements the
 * slice of the Electron desktop bridge that a browser-embedded working copy
 * needs — open from the protocol-v3 workbench, save back as an immutable
 * office snapshot — and reports every other desktop capability as an explicit
 * typed `unsupported` instead of a fake success (audit F02): pretending
 * writeRecoveryCopy/exportPdf/password succeeded would lie to the user about
 * durability of their document.
 *
 * Host passes parameters via the iframe query string:
 *   docUrl     absolute-path URL of the DOCX bytes to open
 *   docName    display name
 *   saveUrl    absolute-path URL of POST /office-draft/snapshots
 *   rev        expected semantic document revision for saves
 *   sha        expected document sha256 for saves
 *   actor      actor id
 *   studySha   study-definition baseline sha the document was opened against
 *
 * Save flow (audit F04): the open receipt carries the Office artifact
 * revision (X-Artifact-Revision); each save pins it as base_artifact_revision
 * so a second editor window cannot silently become the new head.  A 409
 * base-conflict keeps the editor dirty and surfaces the latest version.
 */
;(function () {
  'use strict'
  const query = new URLSearchParams(window.location.search)
  const docUrl = query.get('docUrl')
  const docName = query.get('docName') || '研究方案工作稿.docx'
  const saveUrl = query.get('saveUrl')
  const actor = query.get('actor') || 'medical_manager'
  const studySha = query.get('sha') || ''

  const noop = () => {}
  const unsubscribe = () => () => {}

  // The Office working-copy revision this editor session opened against; the
  // save receipt refreshes it so consecutive saves chain correctly.
  let baseArtifactRevision = null

  function bytesToBase64(bytes) {
    let binary = ''
    const chunk = 0x8000
    const view = new Uint8Array(bytes)
    for (let i = 0; i < view.length; i += chunk) {
      binary += String.fromCharCode.apply(null, view.subarray(i, i + chunk))
    }
    return btoa(binary)
  }

  async function fetchDocBytes() {
    const response = await fetch(docUrl, { credentials: 'same-origin' })
    if (!response.ok) throw new Error('doc fetch failed: ' + response.status)
    const revisionHeader = response.headers.get('X-Artifact-Revision')
    if (revisionHeader) baseArtifactRevision = Number(revisionHeader)
    return response.arrayBuffer()
  }

  async function sha256Hex(arrayBuffer) {
    const digest = await crypto.subtle.digest('SHA-256', arrayBuffer)
    return Array.from(new Uint8Array(digest))
      .map((b) => b.toString(16).padStart(2, '0'))
      .join('')
  }

  async function openDocx() {
    const data = await fetchDocBytes()
    return {
      path: docUrl,
      name: docName,
      data,
      hash: await sha256Hex(data),
    }
  }

  async function postSnapshot(operationId, data) {
    return fetch(saveUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        operation_id: operationId,
        actor_id: actor,
        expected_revision: Number(query.get('rev') || 0),
        expected_document_sha256: studySha,
        content_base64: bytesToBase64(data),
        base_artifact_revision: baseArtifactRevision,
        opened_study_revision_sha256: studySha || null,
      }),
    })
  }

  async function saveDocx(path, data) {
    if (!saveUrl) return { ok: false, error: 'no-save-url' }
    // One save = one operation identity. A lost receipt is recovered with the
    // same id instead of re-posting a new snapshot (audit F04).
    if (!saveDocx.operationId) saveDocx.operationId = 'office-save:' + crypto.randomUUID()
    const operationId = saveDocx.operationId
    const response = await postSnapshot(operationId, data)
    if (response.ok) {
      const receipt = await response.json().catch(() => ({}))
      if (receipt.artifact_revision) baseArtifactRevision = receipt.artifact_revision
      saveDocx.operationId = null
      return { ok: true, snapshot: receipt }
    }
    let detail = {}
    try { detail = await response.json() } catch { /* opaque error body */ }
    if (response.status === 409 && detail?.detail?.code === 'manuscript_office_base_conflict') {
      // Keep the editor dirty; the user decides how to merge with the
      // version that arrived while they were editing.
      const latest = detail.detail.latest_snapshot || {}
      if (latest.artifact_revision) baseArtifactRevision = latest.artifact_revision
      return { ok: false, conflict: true,
        error: detail.detail.message || '另一窗口已保存新版本',
        latest_snapshot: latest }
    }
    if (response.status >= 500) {
      // Unknown outcome: keep the operation id so a retry recovers the same
      // save instead of creating a second snapshot.
      return { ok: false, retryable: true,
        error: detail?.detail?.message || ('save failed: ' + response.status) }
    }
    saveDocx.operationId = null
    return { ok: false, error: detail?.detail?.message || ('save failed: ' + response.status) }
  }

  // The renderer consumes exactly one pending open at boot; without a docUrl
  // it must fall back to a blank document. Deliver the query-passed docUrl as
  // that one-shot pending open, or the embedded frame would always land on
  // "已新建空白文档" regardless of the requested working copy.
  const pendingOpen = docUrl ? openDocx() : null
  const precise = {
    getLanguage: async () => 'zh',
    getTheme: async () => 'system',
    getAutoSaveDefault: async () => ({ on: false, updatedAt: 0 }),
    openDocx,
    openDocxPath: openDocx,
    openDocxDecrypt: async () => ({ ok: false, reason: 'unsupported' }),
    saveDocx,
    saveDocxAs: async (defaultName, data) => {
      // 浏览器嵌入内"另存为"无法写本地文件系统：沿用同一保存管道并如实回执。
      const result = await saveDocx(defaultName, data)
      return { path: defaultName, ...result }
    },
    saveDocxNew: async (defaultName, data) => saveDocx(defaultName, data),
    consumePendingOpenDocx: async () => {
      const result = pendingOpen
      if (!result) return null
      return result
    },
    consumeNewBlankDoc: async () => false,
    consumeAiDocContent: async () => null,
    consumeHeadlessExport: async () => null,
    headlessExportDone: noop,
    respellKick: async () => {},
    spellDiag: noop,
    docPasswordIntentRevision: async () => 0,
    convertAltChunkHtml: async () => null,
  }

  // 能力矩阵（audit F02）：未知/未实现的桌面能力一律显式 unsupported，
  // 决不伪造 {ok:true}。渲染器据此隐藏或禁用对应入口。
  const unsupported = (prop) => async () => ({
    ok: false, unsupported: true, capability: prop,
    error: `浏览器嵌入版不支持「${prop}」，该操作未执行。`,
  })
  // 这些能力在嵌入环境明确不可用且涉及数据安全（恢复副本/导出/加密）。
  for (const name of ['writeRecoveryCopy', 'exportPdf', 'setDocPassword',
    'discardDocPasswordIntents', 'revealDocInShell', 'openExternal']) {
    precise[name] = unsupported(name)
  }

  window.desktop = new Proxy(precise, {
    get(target, prop) {
      if (prop in target) return target[prop]
      if (typeof prop === 'string' && prop.startsWith('on')) return unsubscribe
      // Unknown capability: typed unsupported, never a fake success.
      return unsupported(String(prop))
    },
  })
})()
