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
 *   openedStudySha study-definition baseline sha the document was opened against
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
  const documentSha = query.get('sha') || ''
  const openedStudySha = query.get('openedStudySha') || ''

  let closeCheck = null
  function requestDirtyState() {
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(() => closeCheck?.())
  }
  if (typeof document !== 'undefined') {
    for (const type of ['input', 'click', 'keyup']) document.addEventListener(type, requestDirtyState, true)
  }
  const noop = () => {}
  const unsubscribe = () => () => {}

  // The Office working-copy revision this editor session opened against; the
  // save receipt refreshes it so consecutive saves chain correctly.
  let baseArtifactRevision = Number(query.get('baseArtifactRevision') || 0)

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
        expected_document_sha256: documentSha,
        content_base64: bytesToBase64(data),
        base_artifact_revision: baseArtifactRevision,
        opened_study_revision_sha256: openedStudySha || null,
      }),
    })
  }

  async function saveDocx(path, data) {
    if (!saveUrl) return { ok: false, error: 'no-save-url' }
    // One save = one operation identity. A lost receipt is recovered with the
    // same id instead of re-posting a new snapshot (audit F04).
    const requestedData = data
    if (!saveDocx.operationId) {
      saveDocx.operationId = 'office-save:' + crypto.randomUUID()
      saveDocx.pendingData = new Uint8Array(data).slice().buffer
    }
    data = saveDocx.pendingData
    const hasNewChanges = await sha256Hex(data) !== await sha256Hex(requestedData)
    const operationId = saveDocx.operationId
    let response
    try { response = await postSnapshot(operationId, data) }
    catch (error) {
      window.parent.postMessage({ type: 'protocol-office:save-failed', error: '保存结果暂未核实，请保留页面并下载本地备份。', data: requestedData }, window.location.origin)
      return { ok: false, retryable: true, error: '保存结果暂未核实，请保留页面并重试。' }
    }
    if (response.ok) {
      let receipt
      try { receipt = await response.json() }
      catch {
        window.parent.postMessage({ type: 'protocol-office:save-failed',
          error: '保存接口未返回可核对的版本信息，本次修改仍标记为未保存。', data: requestedData }, window.location.origin)
        return { ok: false, retryable: true, error: '保存回执无法核对，请保留页面并重试。' }
      }
      const persistedHash = await sha256Hex(data)
      const expectedRevision = Number(query.get('rev') || 0)
      const validReceipt = receipt?.persisted === true
        && receipt.operation_id === operationId
        && receipt.content_sha256 === persistedHash
        && Number.isInteger(receipt.artifact_revision)
        && receipt.artifact_revision >= baseArtifactRevision
        && receipt.document_revision === expectedRevision
        && receipt.study_revision_sha256 === (openedStudySha || receipt.study_revision_sha256)
      if (!validReceipt) {
        window.parent.postMessage({ type: 'protocol-office:save-failed',
          error: '保存接口返回的版本身份与本次文档不一致，本次修改仍标记为未保存。', data: requestedData }, window.location.origin)
        return { ok: false, retryable: true, error: '保存版本身份无法核对，请保留页面并重试。' }
      }
      baseArtifactRevision = receipt.artifact_revision
      saveDocx.operationId = null
      saveDocx.pendingData = null
      window.parent.postMessage({ type: 'protocol-office:saved', receipt }, window.location.origin)
      requestDirtyState()
      if (hasNewChanges) return saveDocx(path, requestedData)
      return { ok: true, snapshot: receipt }
    }
    let detail = {}
    try { detail = await response.json() } catch { /* opaque error body */ }
    window.parent.postMessage({ type: 'protocol-office:save-failed',
      error: detail?.detail?.message || '本次修改尚未保存。请下载本地备份后重试。', data: requestedData,
      conflict: response.status === 409, latest_snapshot: detail?.detail?.latest_snapshot }, window.location.origin)
    if (response.status === 409 && detail?.detail?.code === 'manuscript_office_base_conflict') {
      // Keep the editor dirty; the user decides how to merge with the
      // version that arrived while they were editing.
      const latest = detail.detail.latest_snapshot || {}
      // Do not advance the base without reopening/merging the other version.
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
    onCloseCheck: (handler) => { closeCheck = handler; requestDirtyState(); return () => { if (closeCheck === handler) closeCheck = null } },
    reportCloseCheck: (state) => window.parent.postMessage({ type: 'protocol-office:dirty', dirty: Boolean(state.dirty) }, window.location.origin),
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
