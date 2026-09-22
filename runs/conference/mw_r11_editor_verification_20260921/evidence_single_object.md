I'll start by reading the assigned context files.

Plan file is a TODO skeleton. Let me explore the read set in parallel.

Bash is unavailable; I'll use Glob/Read only.

# Conference Output: mw_r11_editor_verification_20260921 - evidence_single_object

## Output

### 0. Evidence base, tool limits, and scope honesty

Read and inspected (full or cited ranges):

- `context/mw_r11_editor_verification_20260921_conference_context.md`, `plans/codex_main_venue_mw_r11_editor_verification_20260921.md` (plan is still a TODO skeleton — no decomposition, source packet, or checklist to audit against).
- `reviews/protocol-v3-requirements-v2/REQUIREMENTS_AMENDMENT.md` (R1–R5, §B, §D, §E), `ACCEPTANCE.md` (A01–A26, 发布说明要求).
- `ProtocolWritingDesk.jsx` (full), `ProtocolIntakeWorkspace.jsx` (full), `ProtocolIntakeWorkspace.css` (full), `StudyContextWorkspace.jsx` (full), `ManuscriptWorkspace.jsx` (full), `ManuscriptWorkspace.css` (full), `ChapterDraftPreview.jsx` (full).
- `office/GenOfficeFrame.jsx` (full), `office/GenOfficeFrame.css` (full), `office/GenOfficeFrame.test.jsx` (full), `office/bridge-shim.test.mjs` (full).
- `frontend/public/genoffice/bridge-shim.js` (full), `index.html`, `embedded.css`.
- `protocolWorkspaceApi.mjs` (full).
- Read-only backend cross-checks: `services/api/app/protocol_workflow/api/manuscript_drafts.py` lines 1–120, 180–250, 400–620; `application/manuscript_documents.py` lines 1–60, 690–880; `application/service.py` lines 780–812; `api/router.py` lines 418–434.

Not verified / limits (state plainly):

- **`Bash` is denied in this session.** I could not run `git diff`, the test suites, a build, or any browser/runtime check. Therefore: (a) I cannot attribute any finding to "this round" vs. pre-existing; (b) **no rendered visual acceptance was performed** — all layout judgments below are source/ CSS-level only; (c) test totals were not observed and are explicitly excluded as acceptance evidence per the contract.
- `manuscript_drafts.py` was read only in the ranges above (not end-to-end).
- The GenOffice renderer bundle (`frontend/public/genoffice/assets/index-DqUsVh4T.js`) is minified; I could confirm it exists and references `consumePendingOpenDocx`, but I could **not** verify how it interprets the shim's `{ok:false, conflict:true}` / `{ok:false, retryable:true}` return shapes. Any claim about the in-renderer UX of a failed save is UNVERIFIED.
- The plan file is empty, so I audited against `REQUIREMENTS_AMENDMENT.md` / `ACCEPTANCE.md` directly rather than against a Codex-declared success criteria set.

---

### 1. Verdict per critical criterion

Derived from the user requirement + the ACCEPTANCE items in this round's scope. `PASS` = proven from source on the stated path; `FAIL` = proven defect with a concrete trigger; `UNVERIFIED` = cannot be settled without running the product.

| # | Criterion | Verdict | One-line basis |
|---|---|---|---|
| C1 | 宽屏下研究上下文与真实文档同屏并行 | **PASS (source only)** | `.pvi-writing-desk` 2-col grid, sticky design pane, `ProtocolIntakeWorkspace.css:202-212` |
| C2 | 减少过度间距与冗余 AI 文本、短逻辑要点 | **UNVERIFIED** | Requires rendering; source shows spacing overrides but not perceived density |
| C3 | 避免竞争性简化编辑器（单一编辑面） | **PASS (with caveat)** | In-page preview is read-only (`ManuscriptWorkspace.jsx:589`), Office is the only editor — but the read-only preview still re-renders the whole document beside the real one |
| C4 | 保存/下载的就是实际编辑的文档 | **FAIL** | Two distinct defects: wrong-document adoption (§2 F1) and non-identifiable download filename (§2 F5) |
| C5 | 重新打开仍是该版本 | **PASS (source only)** | `latestOfficeSnapshot` → snapshot `docUrl`; head drives download link (`GenOfficeFrame.jsx:76-103,131`) |
| C6 | AI 建议与已确认医学事实分离；核对项绑定本版本 | **FAIL** | No reconciliation surface reachable from this frontend; the only clue-producing path is dead code (§2 F4) |
| C7 | 非关键缺口不阻断、可定位 | **PASS (source only)** | `readiness.chapter_dispositions`, `kept_as_gap` summary, `ManuscriptWorkspace.jsx:508-515,558-567` |
| C8 | 加载/错误/恢复不丢稿 | **FAIL** | Unmount destroys unsaved Office edits without the close confirmation (§2 F3); failed-save recovery loops with no host escape (§2 F6) |
| C9 | 版本竞争（双窗口不静默覆盖） | **FAIL** | Conflict check is inert on the first save of a session (§2 F2) |
| C10 | 无回归到旧行为 | **UNVERIFIED** | No `git diff` available; regression attribution is not provable in this session |

---

### 2. Findings

Ordered by impact. Each separates **evidence** (what the source says), **inference**, **recommendation**.

---

#### F1 (HIGH) — The restored "saved document" is not bound to the current writing session; it hides the save action, raises a false alert, and auto-opens the editor on a different document

**Evidence**

- `ManuscriptWorkspace.jsx:114-123` — whenever `packet` exists and `savedDocument` is null, the session fetches `getSavedManuscriptDocument` and adopts whatever it returns:
  ```js
  if (!packet || savedDocument || !apiRef.current?.getSavedManuscriptDocument) return;
  ...apiRef.current.getSavedManuscriptDocument(projectId, studyDefinitionId, ...)
     .then(value => { ... if (value?.document) setSavedDocument(normalizeSavedDocument(value)); })
  ```
- The endpoint is study-scoped, not run-scoped: `manuscript_drafts.py:191-196` → `documents.saved(project_id, study_definition_id)`; `manuscript_documents.py:17-18` derives `manuscript_document_id` from `[project_id, study_id]` only. So it returns the study's current manuscript **regardless of which draft run is active**.
- `saveCompleteDraft` is reachable only through `ManuscriptWorkspace.jsx:568-569`:
  ```jsx
  {job?.complete_candidate && !savedDocument && <button ... onClick={saveCompleteDraft}>...
  ```
  The only other trigger, line 573, additionally requires `packet?.saveConflict`.
- `/saved` returns `{document, document_sha256, revision}` (`manuscript_documents.py:48-57`) — **no `study_binding_status`**; the other loaders (`getSemanticDocument` → `CurrentSemanticDocumentResponse`, `router.py:431-432`) do return it. Line 570 then evaluates `undefined !== 'current'`:
  ```jsx
  {savedDocument && savedDocument.study_binding_status !== 'current' && <p role="alert">研究信息已变化或暂不可读，这份已保存初稿尚未与当前研究重新核对。</p>}
  ```
- Effect B (`ManuscriptWorkspace.jsx:302-313`) only runs when `packet?.saveIntent || packet?.savedDocumentId` is set; `begin()` (`:358-379`) writes `{phase:'sources', sourceRunId, studySha}` with neither, and `HistoryVersions` restore (`:557`) writes a bare history entry. In those two flows nothing later overwrites the `/saved`-derived object.
- `GenOfficeFrame.jsx:109-113` auto-opens the editor once, off `headReady`, and `:130` returns `null` only when `savedDocument` is falsy.

**Trigger / consequence (inference, high confidence)**

Any of: (a) 「按当前研究准备新稿，保留原记录」(line 548-550) when `plan.study_sha256 !== packet.studySha`; (b) `begin()` after localStorage was cleared / a different browser / a re-started flow while the study already has a saved manuscript; (c) restoring a history entry. In all three the pane immediately adopts the **previous** saved document, and then:

1. `保存完整初稿` never renders (line 568) and `saveConflict` is not set, so **the newly generated draft cannot be saved from this page at all** — there is no alternative control (`begin()` requires `!packet`, `begin(true)` requires a study-sha mismatch). The user is stuck with a complete draft and no save action.
2. The static alert at line 570 fires permanently with the wrong message ("研究信息已变化或暂不可读") even when the binding is current.
3. `GenOfficeFrame` mounts and auto-opens the editor against `latestOfficeSnapshot`, i.e. the **old** working copy, labelled 「已保存工作稿 · 第 N 版」, with a download link to it. A medically-sensitive user can reasonably edit and download the wrong version, believing the new draft is in play.

**Recommendation (smallest coherent repair)**

Bind the restore to the session, not to the study. Two lines of intent, one of which must be chosen:

- Preferred: gate the effect on the packet actually being in a post-save state — move `savedDocument` recovery out of the `!savedDocument` catch-all and give the packet an explicit owner, e.g. `if (!packet?.savedDocumentId && !packet?.saveIntent) return;` (the two paths that already know which receipt they belong to), and set `savedDocumentId` in `saveCompleteDraft` from the save receipt instead of relying on a study-wide lookup.
- If reload-recovery for a `begin()`-fresh packet is genuinely required, carry the owning document id/revision in the packet and reject a `/saved` response whose `document.revision`/`document.intent` lineage does not match the packet — never adopt it silently.
- Independently, fix the alert source: `study_binding_status` must not be read from an endpoint that does not return it (either route `/saved` through `getSemanticDocument`, or default the field and only alert on an explicit `'changed'`/`'missing'`).

---

#### F2 (HIGH) — The Office head-conflict guard is inert on the first save of a session, so a second window can silently supersede the saved working copy

**Evidence**

- `GenOfficeFrame.jsx:76-93` — when no snapshot exists, the open source is the **semantic export**:
  ```js
  let docUrl = semanticDocUrl;
  try { const latest = await api?.latestOfficeSnapshot?.(...); if (latest?.operation_id && latest?.artifact_revision) { docUrl = `${snapshotsBase}/${latest.operation_id}/content`; ... } }
  catch (error) { if (error?.status !== 404) { ...; return; } }
  ```
- The semantic export route sets only `X-Document-Sha256`, `X-Output-Sha256`, `X-Export-Scope` (`manuscript_drafts.py:228-230`). The Office snapshot route sets `X-Artifact-Revision` (`manuscript_drafts.py:548-550`).
- `bridge-shim.js:53-59` derives the base **only** from that header: `const revisionHeader = response.headers.get('X-Artifact-Revision'); if (revisionHeader) baseArtifactRevision = Number(revisionHeader);` — so on the semantic-export source it stays `null`, and `bridge-shim.js:89` posts `base_artifact_revision: null`.
- Server gate: `manuscript_documents.py:741-745`
  ```python
  latest = self.latest_office_snapshot(project_id, study_id)
  base_artifact_revision = intent.get('base_artifact_revision')
  if latest is not None and base_artifact_revision is not None and latest.get('artifact_revision') != base_artifact_revision:
      raise OfficeWorkingCopyConflictError(latest)
  ```
  `base is None` ⇒ **no check at all**.
- The host already knows the head revision and drops it: `GenOfficeFrame.jsx:103` stores `officeRevision` in `session`, and only `session.query` is ever read (`:128`); the iframe query (`:94-102`) carries `rev`, `sha`, `openedStudySha` — no base revision.

**Trigger / consequence (inference, high confidence)**

Two editor sessions on the same study while no snapshot exists yet (two browser tabs, or a second window). Both open with `base = null`. Window A saves → snapshot rev 1, receipt "修改已保存，第 1 版". Window B (built from the semantic export, so it never contained A's edits) saves → `latest = rev 1`, but `base is None` ⇒ no conflict ⇒ snapshot rev 2 becomes the head, **silently dropping A's edits from the head**. This is precisely the F04 scenario the code comments claim to close (`GenOfficeFrame.jsx:20-21`, `manuscript_documents.py:722-728`). A's bytes remain in the immutable store, but no UI path exposes a non-head snapshot, so from the user's perspective A's work is gone.

**Recommendation**

Server-side is required — the client cannot express "there must still be no head" with `null`. Concretely: make the host always pass an explicit `baseArtifactRevision` query parameter (it already computes it at `:79-86`) and have the shim prefer it over the header; define an explicit sentinel for "opened with no head" and have `office_snapshot` treat it as `latest must be None, else conflict`. A frontend-only patch (forwarding `officeRevision`) reduces but does not close the race, because in the no-snapshot branch the host has no revision to forward. **This is a backend-touch decision for Codex**, not a routine frontend choice.

---

#### F3 (HIGH) — Unsaved Office edits are destroyed without the close confirmation when the document frame unmounts

**Evidence**

- `GenOfficeFrame.jsx:115-126` implements an explicit two-step close guard, and the button label warns: `确认关闭（未保存修改将丢失）`.
- `GenOfficeFrame.jsx:130` — `if (!savedDocument) return null;` — a prop change to null unmounts the component and its `iframe` outright, bypassing `requestClose`.
- Set to null without any confirmation at `ManuscriptWorkspace.jsx:372` (`begin()`: `remember(next); setJob(null); setSavedDocument(null); setSourceState(null);`) and at `:557` (`HistoryVersions` restore: `remember(entry); setJob(null); setSavedDocument(null); setSourceState(null);`).
- The editor is auto-opened on mount (`GenOfficeFrame.jsx:109-113`), so whenever `savedDocument` is set the iframe is live and may hold dirty state. The renderer's dirty flag is explicitly invisible to the host (`GenOfficeFrame.jsx:116`).

**Trigger / consequence**

User has the Word editor open with unsaved edits → clicks 「按当前研究准备新稿，保留原记录」(line 550) or restores a history entry (line 557) → iframe unmounts, in-editor edits are lost with no prompt and no copy anywhere. The one guard the design built is defeated by the unmount path. Same class as A12 ("不重复改稿…不自动新建操作覆盖").

**Recommendation**

Route both call sites through the existing guard instead of nulling the prop: before `setSavedDocument(null)`, if the frame is open, require the same confirmation (or block the action while `open`). Cheapest coherent shape: lift `open`/`session` state or expose an imperative `confirmDiscard()` from `GenOfficeFrame`; a `window.confirm`-free in-page prompt is preferred given the low-technical-familiarity user.

---

#### F4 (MEDIUM, requirement gap) — The explicit-reconciliation stage has no reachable UI, and the only code that produced version-bound fact clues is now dead

**Evidence**

- `ManuscriptWorkspace.jsx:589` renders `ChapterDraftPreview … edit={undefined}`; `ChapterDraftPreview.jsx:82-85` treats `edit = null` as read-only, so no in-page paragraph/table editing exists.
- `saveBlockEdit` (`:450-497`) — the only caller of `editManuscriptDraft`/`recoverEdit` and the only setter of `editNotice` (`:483`) — is never referenced in JSX. Same for `stashDraft`, `localDrafts`, `draftsKey`, `composingRef`, `editingBlockId`, `editBusy`. A repo-wide grep over `frontend/src` confirms `editManuscriptDraft` / `recoverEdit` appear **only** at their definition sites in `protocolWorkspaceApi.mjs:173,176`.
- The client has **no** method for the server's reconciliation surface. `manuscript_drafts.py:425-460` exposes `GET /manuscript-draft/reconciliation` and `POST /manuscript-draft/reconciliation/resolve`; a repo-wide grep for `reconciliation/resolve` / `manuscript-draft/reconciliation` in `frontend/` returns nothing in this feature.
- The Office path records `mapping_status: 'pending'` / `acceptance_scope: 'working_draft_only'` (`manuscript_documents.py:782-783`) but nothing computes or consumes a clue; `fact_clue_count`/`edit_clues` are read only at `ManuscriptWorkspace.jsx:479-482`, inside the dead function.
- `ChapterDraftPreview.jsx:77` still ships the now-unreachable promise 「修改会保存为新版本；涉及研究事实的内容会在显式核对中提示」.

**Consequence (inference, medium-high)**

R3 separates 保存工作稿 / 研究设计确认 / 文档一致性核对 / 最终交付验收; A09 requires 「出现绑定本次版本的核对项」 and A18 requires 「真实 cell.text 的剂量变化…进入核对线索」. On the current frontend, a dose change typed in Word reaches the server as opaque bytes bound to a document revision with `mapping_status: 'pending'` and **never produces a user-visible clue**; the only remaining signal is the coarse `study_binding_status` alert. The "AI 建议 vs 已确认医学事实" separation the user asked for is therefore preserved only at the intake/design layer, not at the document layer.

**Uncertainty / why this may be intentional**

Codex may have deliberately deferred the reconciliation UI to a later round, and removing the in-page editor is consistent with 「avoid competing simplified editors」. What is not defensible either way is leaving ~50 lines of unreachable code plus a user-facing promise (`ChapterDraftPreview.jsx:77`) that no path can honour.

**Recommendation**

Either (a) wire the reconciliation surface (client method + a read-only "本版本差异/缺口" panel that calls `GET /manuscript-draft/reconciliation` on demand), or (b) delete the dead edit path and neutralize the `ChapterDraftPreview` copy, and record the reconciliation UI as explicitly out of scope for this round. Do not leave both.

---

#### F5 (MEDIUM) — The downloaded working draft has no identifiable filename, and the version number shown in the header does not match the file the user gets

**Evidence**

- `GenOfficeFrame.jsx:136` — `<a href={currentUrl} download>` with **no `download` value**, so the browser falls back to `Content-Disposition`, then to the URL path.
- The Office snapshot content route returns a bare `Response` (`manuscript_drafts.py:546-550`) with `Content-Type` + `X-Artifact-Revision` only — **no `Content-Disposition`/filename**. The URL ends in `/content`, so the saved file is effectively `content.docx`.
- The fallback semantic export **does** set a filename, but it is a hash: `manuscript_drafts.py:221-229` → `filename=output_path.name` = `manuscript-<24-hex>.docx`.
- The in-editor document name uses the **semantic** revision while the host header shows the **Office artifact** revision: `GenOfficeFrame.jsx:96` `docName: 研究方案工作稿_第${revision}版.docx` (from `savedDocument.document.revision`) vs. `:134` `已保存工作稿 · 第 ${head.artifact_revision} 版`.

**Consequence**

A senior medical writer downloading revision 1, 2, 3 gets `content.docx`, `content (1).docx`, `content (2).docx` (or, before any Office save, `manuscript-9f3c…a1.docx`). Nothing on disk maps to 「第 N 版」, and the two numbering schemes in the UI disagree. This directly undercuts 「saved/downloaded document must be the actual edited document」 at the point of use, and there is no way for the user to prove after the fact which version they filed. A14/A13 acceptance ("下载，人工变化不被覆盖；重新打开仍为该版本") cannot be demonstrated by the user from the artifacts alone.

**Recommendation**

Server: add `Content-Disposition: attachment; filename*=UTF-8''<name>.docx` on the snapshot content route, built from the operation's `document_revision` + `artifact_revision`. Frontend: set an explicit `download` attribute value as a belt-and-braces. Align the two "第 N 版" labels to one numbering scheme.

---

#### F6 (MEDIUM) — A failed Office save creates an unrecoverable loop, and the host cannot see it

**Evidence**

- `bridge-shim.js:111-128` — only `detail.detail.code === 'manuscript_office_base_conflict'` and `status >= 500` are special-cased. On a base conflict the code returns early **without clearing `saveDocx.operationId`** (`:116-118`), and never advances `baseArtifactRevision`; the bundled test asserts exactly that (`bridge-shim.test.mjs:29-36`: after two conflicts, `bodies[1].base_artifact_revision === null`). Since no event was written, `recover_office_snapshot` returns `None` and the same request produces the same 409 forever.
- The semantic-revision failure takes the generic branch (`:126-127`): `saveDocx.operationId = null` and returns `{ok:false, error: detail?.detail?.message}`. The server maps `manuscript_document_revision_changed` → **409** with `detail.code = 'manuscript_document_revision_changed'` (`manuscript_drafts.py:69-72`), which the shim's 409 clause does not match, so every retry mints a fresh operation id and fails identically.
- The shim never calls the recover endpoint (`POST …/snapshots/{operation_id}/recover` exists at `manuscript_drafts.py:522-531` and `recoverOfficeSnapshot` exists in the client at `protocolWorkspaceApi.mjs:164-166`, but neither is used).
- `GenOfficeFrame` learns about saves **only** through the success `postMessage` (`:57-69`). A failed or conflicted save produces no host state change, so the header keeps reading 「已保存工作稿 · 第 N 版」 and the download link keeps serving the pre-conflict snapshot while the user is looking at a failure.

**Consequence (inference, medium confidence)**

Reachable via two windows (semantic revision advanced by another window's save) or via any T12 object-AI revision (`manuscript_drafts.py:552+`) applied while the editor is open. The user's Word edits stay in the renderer, but they can never be persisted from that session; the host UI actively misreports the state. The documented escape is close-and-reopen, but nothing in the host tells the user that, and reopening discards the edits.

**Recommendation**

Minimum: emit a `protocol-office:save-failed` message with `{conflict, latest_snapshot, error}` so `GenOfficeFrame` can set `notice` and, on `conflict`, refresh `head` from `latest_snapshot` and tell the user to close/reopen. Add a matching 409 branch for `manuscript_document_revision_changed` that stops re-minting the operation id and explains that the document was updated elsewhere. Note: the shim's *idempotent retry* design is sound for `status >= 500`; the gap is only the two 409 shapes.

---

#### F7 (LOW-MEDIUM) — `bundleInstalled()` HEAD probe failure is unilateral and sticky

`GenOfficeFrame.jsx:4-11,71-75,109-113`: `beginSession` awaits a `HEAD /genoffice/index.html` probe; if it is not `ok` the function returns after setting a notice — but the auto-open effect has already set `initialOpen.current = true`, so the editor will never auto-open again for this mount, and the manual button re-runs the same probe. UNVERIFIED whether any deployment in use answers `HEAD` on that path. Repair: retry the probe on manual open (already true) and make the auto-open ref reset on a successful probe, or drop the probe and rely on the iframe's own error surface.

---

### 3. Contradictions and challenges I want on the record

1. **The code comments claim guarantees the code does not have.** `GenOfficeFrame.jsx:20-21` says 「双窗口不会互相静默覆盖(F04)」 and `manuscript_documents.py:722-728` repeats it, but F2 shows the guard is inert on the first save. Similarly `ManuscriptWorkspace.jsx:112-113` claims the restore only makes "the saved working draft survive reloads", while it actually adopts any study-scoped document. I recommend treating these comments as assertions to re-verify rather than as evidence during final acceptance.
2. **`bridge-shim.test.mjs` was written to pin the current behaviour, and the current behaviour is the bug.** The assertion `assert.equal(b.bodies[1].base_artifact_revision, null)` (line 34) codifies "after a conflict, keep posting a null base". A test that locks in a defect is worse than no test when the test count is later cited as coverage. The same file never calls `openDocx`, so `fetchDocBytes` — the function F2 turns on — has **zero** coverage.
3. **`savedDocument` has three writers and no owner.** `ManuscriptWorkspace.jsx:114-123` (`/saved`), `:293-300` (`save/recover` → `/documents/{id}`), `:302-313` (both), plus `:476,348` (edit/conflict) and `:557` (history). Each produces a different shape, and at least one (`/saved`) is missing a field that a downstream renderer unconditionally reads (F1). This is the structural cause of F1 and is worth fixing at the type/loader level rather than per-field.
4. **The read-only preview duplicates the live document.** With the in-page editor removed, `ManuscriptWorkspace.jsx:580-590` still renders the full per-chapter document beside the real Office editor. The `<summary>` copy 「查看 AI 起草依据（只读，不代表当前 Word 内容）」 mitigates it, but on a wide screen two renderings of "the document" are visible at once. I do not consider this proven harmful — I flag it as the exact category the user asked to avoid, and it needs a rendered judgment, not a source judgment.
5. **Plan-vs-review mismatch.** The main-venue plan is a TODO skeleton: no success criteria, no participant-scoped criteria, no verification checklist. Whatever acceptance Codex writes must therefore be authored now, not read off the plan. If Codex later reports "PASS per plan", that would be circular.

---

### 4. Decision points where existing requirements cannot decide

1. **Where does the fact-clue reconciliation live now?** R3/A09/A18 require a version-bound check; the frontend has none. Whether the intended surface is (i) a new panel in the writing desk, (ii) a server-side diff of the Office snapshot against the semantic document surfaced at download time, or (iii) deferred out of this round, is a scope decision above my authority. It changes the deliverables materially, so Codex must decide it explicitly.
2. **Is a backend change authorized to close F2?** A frontend-only fix cannot close it. The context lists backend files as read-only for this review and mentions a concurrent backend worker; whether the owner-of-`office_snapshot` change belongs to this round is Codex's call.
3. **What is the download-version identity contract?** 「第 N 版」 currently means two different counters (semantic revision vs. Office artifact revision). Choosing which one is user-facing has product consequences for A13/A14/A23; it is not decidable from the requirements text.

---

### 5. Bounded questions for Codex

- **Q1.** Is a bounded repair authorized in this session for `ManuscriptWorkspace.jsx` (F1), or should I stop at the report? F1 blocks a complete draft from ever being saved; if unrepairable this round, say so and I will mark it as an accepted, disclosed gap.
- **Q2.** For F2, may I assume a server-side sentinel (`base_artifact_revision` = "no head existed") is in scope, or must the fix stay inside `GenOfficeFrame.jsx` + `bridge-shim.js`? The latter cannot fully close the race — if you choose it, acceptance for C9 must be downgraded to "reduced window".
- **Q3.** Is the explicit-reconciliation stage (F4) in scope for this round? A yes/no changes whether my recommended repair is "wire it" or "delete the dead path and correct the `ChapterDraftPreview.jsx:77` promise".
- **Q4.** Is a browser-rendered pass planned by anyone in this conference? Everything under C1/C2 and finding 4 above is source-level only; without a rendered pass those criteria must not be reported as accepted.
- **Q5.** Do you have the pre-change revision available so a reviewer **with shell access** can produce the diff? Regression attribution (C10) is not provable from a static snapshot.

---

### 6. What I would tell a skeptical reviewer

- Highest-confidence findings (fully traceable to named lines on both sides of the wire): **F1, F2, F5, F6, F7**. Each has a client line, a server line, and a concrete trigger.
- F3 is high confidence on mechanism (unmount bypasses the guard) and medium on frequency (requires a dirty editor at the moment of a design change or history restore).
- F4 is a verified code fact (dead path, missing client method) plus a requirement-gap inference. The requirement-gap half depends on Codex's scope answer (Q3).
- Nothing in this report proves a *regression*, because I could not obtain the diff. Anyone presenting these as "introduced this round" is asserting more than the available evidence supports.
- No test totals, no build output, no browser evidence was produced or is claimed.

**Resume point if budget is exhausted:** report complete through F7 and §3–§6; no artifact was written (per the runner-managed-path boundary); no source file was modified; no service, model, browser, network, test, or git mutation was executed.
