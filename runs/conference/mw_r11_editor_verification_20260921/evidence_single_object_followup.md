# Conference Output: mw_r11_editor_verification_20260921 - evidence_single_object

## Output

### 0. Session basis (read-only, no reruns)

Re-read this session: `plans/codex_main_venue_mw_r11_editor_verification_20260921.md` (now carries scope added after my first report — lines 6–10), `ManuscriptWorkspace.jsx` (full), `ManuscriptWorkspace.test.jsx` (new), `office/GenOfficeFrame.jsx` (full), `office/GenOfficeFrame.test.jsx`, `office/bridge-shim.test.mjs`, `frontend/public/genoffice/bridge-shim.js`, `application/manuscript_documents.py:694-868`, `api/manuscript_drafts.py:560-572`, `storage/sqlite.py:2594-2600`, `tests/protocol_v3/integration/test_office_working_copy_closure.py`, `runs/requirements_v2_20260919/t17_round11/office_browser_isolated/verification.json`.

Constraints held: `Bash` still denied, so no `git diff`, no test execution, no build, no browser, no network. **I did not rerun the owner's browser verification and do not claim it.** Nothing was written.

---

### 1. F1–F7 disposition

| # | Disposition | Proof |
|---|---|---|
| F1 | **RESOLVED (source)** | see 1.1 |
| F2 | **RESOLVED (source)** | see 1.2 |
| F3 | **RESOLVED (source) for the two in-app paths; outer-navigation unmount remains open** | see 1.3 |
| F4 | **OPEN SCOPE — unchanged, correctly declared** | see 1.4 |
| F5 | **RESOLVED at the user-visible layer; server header still absent** | see 1.5 |
| F6 | **RESOLVED (source), two residuals** | see 1.6 |
| F7 | **UNCHANGED, low, out of this round's scope** | see 1.7 |

#### 1.1 F1 — restored draft ownership

Evidence that the study-wide catch-all is gone: `ManuscriptWorkspace.jsx:106-127` now goes straight from state declarations to the readiness effect; a repo-wide grep for `getSavedManuscriptDocument` leaves only the API definition (`protocolWorkspaceApi.mjs:371`) and the test mock — no `src` caller.

The only remaining restore path is bound to the session's own receipt: `ManuscriptWorkspace.jsx:291-302` returns early unless `packet?.saveIntent || packet?.savedDocumentId`, and both are written by `saveCompleteDraft` (`:317`, `:325`) or the conflict branch (`:336`). `begin()` (`:360-361`) and the history restore (`:478`) write packets with neither, so no foreign document can be adopted.

Consequences confirmed fixed: the save action at `:489-490` is no longer suppressed (nothing sets `savedDocument` for a fresh draft), and the false alert at `:491` is now guarded by `savedDocument?.study_binding_status &&` so it cannot fire for an object that lacks the field. New regression test: `ManuscriptWorkspace.test.jsx:6-18` asserts `getSavedManuscriptDocument` is not called, no editor renders, and 「保存完整初稿」 is present.

Reload recovery is preserved by the stronger path: after a successful save the packet carries `saveIntent`, so `loadSavedDocument` (`:282-289`) re-derives the document from the receipt and returns `study_binding_status`. Verdict: **resolved**; runtime behaviour not verified by me.

#### 1.2 F2 — explicit 0 base + in-transaction head check

Four links now line up:

- `bridge-shim.js:41` — `let baseArtifactRevision = 0` (the "opened before any Office snapshot existed" sentinel), still overridden by `X-Artifact-Revision` when the open source is a snapshot (`:56-57`), and posted unconditionally (`:89`).
- `manuscript_drafts.py:490` — `base_artifact_revision: int | None = None` accepts `0`; the route passes `body.model_dump(mode='json')` through unchanged.
- `manuscript_documents.py:739-755` — the head is resolved **inside** the write transaction, replay is decided there, and the guard now fires on `base is not None`: `if latest is not None and base_artifact_revision is not None and latest.get('artifact_revision') != base_artifact_revision: raise OfficeWorkingCopyConflictError(latest)`. The previous out-of-transaction read (which the old comment justified as avoiding a nested-connection deadlock) is gone, closing the TOCTOU window.
- `sqlite.py:2594-2600` — `SqliteUnitOfWork.__enter__` issues `BEGIN IMMEDIATE` at depth 0, so a second concurrent save blocks on the database write lock and its head read sees the first save's committed event. The atomicity claim is now verified at source, not inferred.

Threaded proof exists: `test_office_working_copy_closure.py:138-153` runs two first-time editors with `base_artifact_revision=0` and asserts exactly one conflict and that the head equals the winner; `:93-119` covers the superseded-base case including the documented merge path.

Behaviour note (not a defect): with `BEGIN IMMEDIATE`, contention surfaces as a busy-timeout wait; on timeout the failure classifies as 500, which the shim treats as retryable with the same operation id (`bridge-shim.js:135-140`). Safe, but the user may see one transient 「保存结果暂未核实」 notice. I did not read `busy_timeout_ms`.

#### 1.3 F3 — history/new-draft actions while the editor is open

The guard is now explicit and wired end to end: `officeOpen` state at `ManuscriptWorkspace.jsx:112`; `onSessionChange={setOfficeOpen}` at `:493`; set true when the iframe opens (`GenOfficeFrame.jsx:117`) and false on close (`:136`). It gates `begin()` itself (`:348`), the 「按当前研究准备新稿」 button (`:471`), the history restore (`:478`), and the conflict "另存为新版本" button (`:494`).

Because `GenOfficeFrame.jsx:144` returns `null` on `!savedDocument`, and the only two paths that null it (`:361`, `:478`) are now unreachable while the editor is open, the unmount-without-confirmation path I flagged is closed in-app. Two residual notes: (a) the buttons disable silently, with no hint that closing the editor is the prerequisite; (b) browser refresh/close and outer project/module navigation still unmount the keyed subtree (`ManuscriptWorkspace.jsx:516-518`, `IntakeProject` keyed on `projectId`) — this is exactly the item the owner's plan lists as unresolved (plan line 10), and I confirm it is unchanged.

#### 1.4 F4 — explicit reconciliation

Confirmed still open and correctly not papered over. `protocolWorkspaceApi.mjs` contains only `office-draft` routes; there is no client method for `GET /manuscript-draft/reconciliation` or `/reconciliation/resolve` (`manuscript_drafts.py:425-460`), so no consumer could mislabel legacy semantic reconciliation as current Word reconciliation. The dead code half of my earlier finding is gone: grep for `saveBlockEdit|stashDraft|localDrafts|editNotice|editingBlockId|composingRef|draftsKey|editBusy|editManuscriptDraft|recoverEdit` in `ManuscriptWorkspace.jsx` returns **no matches**, and `ChapterDraftPreview.jsx:77`'s promise is now unreachable by construction (`edit={undefined}` at `:510` never renders the editor branch). This matches plan line 10. **Open scope, not a defect of this round.**

#### 1.5 F5 — download filename

`GenOfficeFrame.jsx:150` now sets an explicit `download` value on both branches — `研究方案工作稿_编辑版${head.artifact_revision}.docx` and `研究方案工作稿_初稿${savedDocument.document.revision}.docx` — and `:108` uses the same two-way rule for the in-editor `docName`, so the "Office edit revision vs initial draft revision" decision is applied consistently in both places. The backup link at `:158` is separately named `研究方案_未保存修改.docx`. The browser now uses the attribute, so the `content.docx` symptom is gone.

Residual (low): `manuscript_drafts.py:566-571` still emits no `Content-Disposition` on the snapshot content response, so any consumer that is not this `<a download>` (copy-link, open-in-new-tab, a future export) still receives `content.docx`. Worth one line in a later pass, not blocking.

#### 1.6 F6 — failed-save backup and frozen payload

Client: `bridge-shim.js:99-105` freezes the first attempt's bytes as `pendingData` when an operation id is minted, and `:104,118` always posts those frozen bytes for that operation id; `:105` detects newer typing and, on success, `:118` recurses once with the new bytes under a fresh operation id. `:107-112` handles a rejected transport by posting `save-failed` with the current bytes and returning `retryable` while keeping the operation id; `:123-125` posts `save-failed` for every non-ok response carrying the server message plus `conflict`/`latest_snapshot`; `:135-140` keeps the id on `>=500`; `:141-142` clears it on a definitive 4xx, so a rejected payload no longer pins stale bytes.

Host: `GenOfficeFrame.jsx:59-81` consumes `protocol-office:save-failed`, sets a notice and materialises a Blob backup URL; `:158` exposes it as a download; `:80` revokes the URL on unmount. Test `bridge-shim.test.mjs:37-47` pins the exact contract: same operation id and byte-identical `content_base64` across the lost-receipt retry (`bodies[0] === bodies[1]`), then a new operation id and the new bytes (`bodies[2].content_base64 === 'Ag=='`).

The design is idempotency-correct in the cases I traced (409 base conflict / 409 revision-changed / >=500 / network reject / non-retryable 4xx). Two residuals:

- **(a)** `latest_snapshot` and `conflict` are transmitted (`:125`) but ignored by the host, so the notice cannot name the competing version, and `head` is not refreshed from the conflict payload — the header and download keep showing the pre-conflict head while the user stares at a failure.
- **(b)** A base conflict still has no in-editor resolution: the operation id and frozen bytes are retained deliberately, so every retry reproduces the same 409 and the only exit is close-and-reopen, which the notice does now state. Correct behaviour, thin escape.

Also worth recording as an observation, not a defect: the backup bytes are captured at save-attempt time, so the backup reflects the last attempted save rather than a continuous autosave. The label 「下载未保存修改（本地备份）」 is accurate to that boundary.

#### 1.7 F7

`GenOfficeFrame.jsx:4-11,83-87,122-126` unchanged: a failed `HEAD /genoffice/index.html` probe returns after `initialOpen.current` was already set, so auto-open never retries in that mount (the manual button re-probes). Still UNVERIFIED whether any deployed path rejects `HEAD`; I cannot execute the probe. Low, out of this round's repair scope.

---

### 2. New material findings

#### N1 (MEDIUM-HIGH, newly characterised — the mechanism behind the owner's declared open item) — a stale Office head is silently re-labelled with the newer draft revision, and the header/download default to the stale copy

Evidence:

- `GenOfficeFrame.jsx:92-99` opens from `latestOfficeSnapshot` with **no comparison** against the current `savedDocument`; grep for `document_revision|document_sha256|base_artifact_revision` in that file returns only `:111` (`sha: savedDocument.document_sha256`). The two payload fields needed for the comparison already exist and are unused: `manuscript_documents.py:786-787` emit `document_revision` and `document_sha256`.
- `GenOfficeFrame.jsx:110-111` posts the **current** semantic `rev` and `sha`, while `:95` supplies the old snapshot as the open source; `:145,148,150` make the stale head the header label and the download target.
- `manuscript_documents.py:759-761` CAS-checks only against the current semantic revision, and `:783-787` writes `document_revision: current.revision` into the new snapshot payload.

Concrete trigger and consequence (inference, high confidence): save draft v1 → semantic R1, Office head S1 (bound to R1); confirm a new design and click 「按当前研究准备新稿」; save → semantic R2 with `savedDocument` = R2, Office head still S1. On mount the editor now opens S1 and the page labels it 「已保存工作稿 · 第 N 版」 with the download pointing at S1 — i.e. the old Word content is presented as the current draft. If the user edits and saves, `base_artifact_revision` still equals the head, so the guard passes and a new snapshot is written whose payload asserts `document_revision = R2` over content authored against R1. Provenance survives inside the event (`base_artifact_revision`), but nothing on the receipt or the UI says the content predates R2.

This is **not introduced by this round's repairs** — the unconditional snapshot open predates them — but with F1 closed it is now the most likely wrong-document path a medical writer can hit, and it is the exact case the plan defers (line 10).

#### N2 (LOW, a deliberate trade of the F1 fix) — silent loss of reload recovery when the save receipt is unreadable

`ManuscriptWorkspace.jsx:298-300` swallows 404: `if (!aborted && reason?.status !== 404) setError(...)`. If `recoverManuscriptSave` returns 404 on reload (receipt unreadable/pruned), `savedDocument` stays null and the user gets **no message and no entry point** to the study's saved manuscript — where the removed study-wide `/saved` call would have shown it. I consider the removal correct (it was F1's root cause); the residual is only the missing user-initiated fallback.

#### N3 (LOW) — conflict payload ceiling; see 1.6 residual (a). The host has the competing receipt in hand and discards it, so the one moment the user most needs "最新是第9版" is the moment the UI stays silent.

#### N4 (LOW, latent) — `GenOfficeFrame.jsx:63-64` interpolates `event.data.error` into the notice without a fallback. Every failure branch of the shim currently sets `error` (`bridge-shim.js:110,124`), so this cannot render `undefined` today; one `|| '本次修改尚未保存。'` removes the latent case.

#### Evidence-quality note on the owner's browser artefact

Quoted as given, not rerun: `verification.json` records `before_sha256`→`after_sha256`, `changed_parts: [docProps/core.xml, word/document.xml]`, `header_unchanged: true`, `footer_unchanged: true`, `table_count: 1`, `saved_marker_present: true`. Two caveats for whoever cites it: `added_parts` mixes directory entries (`_rels/`, `customXml/`, `word/theme/`…) with real package parts, so it should not be read as "new parts added"; and the run **preceded** the F2/F3/F5/F6 repairs, so it validates the earlier save/reopen/download loop only — it says nothing about `base_artifact_revision = 0`, the frozen-payload retry, the backup link, or the new download attribute.

---

### 3. Remaining open scope vs newly introduced defects

**Newly introduced by this round's repairs: none found at source level.** The three repairs are mutually coherent (removing the catch-all is what makes the `!savedDocument` save gate correct again; the `officeOpen` guard is what makes the removal safe), and the shim's retry chain keeps operation-id/byte pairing intact across every failure class I traced. The nearest candidate, N2, is a deliberate narrowing of a recovery path, not a regression.

**Open scope, confirmed and not silently resolved:** F4 (actual-Office reconciliation, plan line 10); outer project/module navigation unmount (plan line 10); N1 (older Office head coexisting with a new semantic draft — now characterised, with the trigger and the two lines of data needed to detect it); the two-window first-save case is proven at unit/integration level only — I saw no browser two-window evidence.

**Not provable in this session:** any execution-dependent claim; no test run, no browser, no rendered layout judgement, no `git diff`, so no regression attribution.

---

### 4. Minimum coherent next implementation (recommended, no new architecture)

One bounded change in the function already being repaired — `GenOfficeFrame.jsx` `beginSession`, roughly `:92-118` — with no new component, no new state, and no backend change:

1. After fetching `latest`, decide staleness from data already present: stale when `latest.document_sha256` exists and differs from `savedDocument.document_sha256`, falling back to `latest.document_revision != null && latest.document_revision !== revision`.
2. When stale, do **not** adopt the snapshot as the open source: keep `docUrl = semanticDocUrl`, keep `officeRevision = null` so `docName` reads 初稿N and the header does not label the old copy as current, and set a one-sentence notice that the previous Word edits belong to an earlier draft revision.
3. Keep the older snapshot reachable as an explicitly separate download pointer (its `/content` URL is already constructed by `snapshotUrl`), so nothing the user authored becomes unreachable.
4. Leave the choose/merge interaction deferred — the plan already scopes it separately, and this step only removes the silence.

That step closes N1's silent re-labelling while preserving every existing artefact. Two optional one-liners I would allow alongside: a reason hint when 「按当前研究准备新稿」 is disabled by `officeOpen`, and the N4 error fallback. I would **not** lift the editor above the route key, add a portal, or introduce a global navigation guard — that is the architecture change the owner asked to avoid; keep the unmount case as declared open scope, and at most add a `beforeunload` guard while `officeOpen` with the honest limitation that SPA navigation still bypasses it.

---

### 5. Residual uncertainty

- Nothing was executed. F2's atomicity rests on `sqlite.py:2598` plus the threaded test, not on my observation of a run.
- The F2 contention-to-error mapping depends on `busy_timeout_ms`, which I did not read; the classification to 500 → retryable is inferred from `checked()` (`manuscript_drafts.py:100-110`) and `bridge-shim.js:135-140`.
- N1's frequency depends on how often a new draft is prepared for a study that already has an Office head; the mechanism is proven, the rate is not.
- Renderer-side interpretation of `{ok:false, conflict:true, latest_snapshot}` (bundled `index-DqUsVh4T.js` is minified) remains unverified, as in my first report.
