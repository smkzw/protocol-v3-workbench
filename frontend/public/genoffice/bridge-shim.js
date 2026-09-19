/**
 * GenOffice docs renderer bridge shim (T10/P3).
 *
 * Loaded inside the iframe BEFORE the renderer module script.  Implements the
 * slice of the Electron desktop bridge that a browser-embedded working copy
 * needs — open from the protocol-v3 workbench, save back as an immutable
 * office snapshot — and stubs everything else so the renderer boots exactly
 * as in its supported "dev renderer without the preload bridge" mode.
 *
 * Host passes parameters via the iframe query string:
 *   docUrl     absolute-path URL of the DOCX bytes to open
 *   docName    display name
 *   saveUrl    absolute-path URL of POST /office-draft/snapshots
 *   rev        expected semantic document revision for saves
 *   sha        expected document sha256 for saves
 *   actor      actor id
 */
;(function () {
  'use strict'
  const query = new URLSearchParams(window.location.search)
  const docUrl = query.get('docUrl')
  const docName = query.get('docName') || '研究方案工作稿.docx'
  const saveUrl = query.get('saveUrl')
  const actor = query.get('actor') || 'medical_manager'

  const noop = () => {}
  const asyncOk = async () => ({ ok: true })
  const unsubscribe = () => () => {}

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

  async function saveDocx(path, data) {
    if (!saveUrl) return { ok: false, error: 'no-save-url' }
    const response = await fetch(saveUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        operation_id: 'office-save:' + crypto.randomUUID(),
        actor_id: actor,
        expected_revision: Number(query.get('rev') || 0),
        expected_document_sha256: query.get('sha') || '',
        content_base64: bytesToBase64(data),
      }),
    })
    if (response.ok) return { ok: true }
    let detail = {}
    try { detail = await response.json() } catch { /* opaque error body */ }
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
    saveDocxAs: async (defaultName, data) => ({ ok: true, path: defaultName, ...(await saveDocx(defaultName, data)) }),
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
    setDocPassword: async () => ({ ok: true }),
    docPasswordIntentRevision: async () => 0,
    discardDocPasswordIntents: async () => ({ ok: true }),
    createDocument: async () => ({ ok: false, error: 'not-supported-in-embed' }),
    convertAltChunkHtml: async () => null,
  }

  window.desktop = new Proxy(precise, {
    get(target, prop) {
      if (prop in target) return target[prop]
      if (typeof prop === 'string' && prop.startsWith('on')) return unsubscribe
      return asyncOk
    },
  })
})()
