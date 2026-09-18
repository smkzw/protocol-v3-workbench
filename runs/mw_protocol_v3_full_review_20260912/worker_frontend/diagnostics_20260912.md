# worker_02 Frontend/User-Flow Diagnostics — mw_protocol_v3_full_review_20260912

Date: 2026-09-12. Worker: zcode/GLM-5.3-Flash (worker_02, 有限代码). Read-only review; this file is the only artifact written.

## Scope actually read (coverage)

- frontend/AGENTS.md (full)
- frontend/src/App.jsx (16002 lines): WritingPage 7901-12009 region, intake modal 1440-1509, project create 1296-1340, editor 6363-6520+, recovery-draft store 6153-6250, helpers 5525-5725, revision flows 9468-10055, working-copy save/freeze/recovery 10056-10756, full-draft/export 10415-10660, rail/panel JSX 10836-11999.
- features/medical-writing: MedicalWritingAuthoringJourneySetup.jsx (structure + 737-2600 implementation incl. pipeline poll, prefill generate/adopt/composite, corpus override, createDocument), MedicalWritingSynopsisProjectIntake.jsx (full), useDurableMwJob.js (full), durableJobState.mjs (full), protocol-workbench/protocolWorkspaceApi.mjs (full), editorSourceMapping.js (full), structure skims of AuthoringCandidatePackagePanel.jsx / TableCellRichEditor.jsx / StructuredTableDesigner.jsx / MedicalWritingLiteraturePanel.jsx.
- CSS: src/styles.css font-size survey; .protocol-editor/.ProseMirror rules 18340-18420.
- Backend route spot-checks in services/api/app/main.py (working-copies 6908/7056/7171, project-intake 7308-7423, full-drafts 7789-7842, greenfield-document 8961-9362, document-exports 9810, revision-threads 10647-10737, journey stages/draft/commit 8388/8473, prefill adopt-composite 8330, corpus-gate override 8508, fact-intake 6671-6756).
- Backend greenfield section scaffold: services/api/app/medical_writing_greenfield.py 1690-1920.
- Prior claims: handoff/2026-09-11/HANDOFF_PROTOCOL_V3_3R4_20260912.md (full), .trellis/tasks/09-12-protocol-v3-review-replan/checkpoint.md (full).
- Not read in depth: StructuredTableDesigner.jsx body, StudySchemaEditor.jsx, InterventionRulesEditor.jsx, AuthoringCompetitorDrawer.jsx, LegacyAuthoringBootstrapPanel.jsx, structured-table-designer.css, MedicalWritingAuthoringJourneySetup.css (structure-level only via grep/labels). No servers, browsers, or tests executed (out of assigned bounds).

## Confirmed architecture facts

1. WritingPage render chain (App.jsx:11271-11344): StudySchemaEditor → RichProtocolEditor → (greenfieldSetupAvailable) MedicalWritingAuthoringJourneySetup → blocked canvas. Journey also mounts in the study-design drawer (App.jsx:11994) with `existingDocument`.
2. Real projects: `backendSectionId = selectedSection` (App.jsx:8203); the 4-entry static map writingSectionBackendIds (App.jsx:5525-5530) applies to the demo session only. AI revision is available on every real section with a loaded session + content.
3. `protocol-workbench/protocolWorkspaceApi.mjs` has zero consumers in src/ and tests/ (grep verified). The entire `/protocol-workflow` v3 backend surface is unreachable from the UI. Matches handoff §1.3 line "6R 受控编辑面+写作链+新WritingPage ⬜（20点击/5自由文本硬预算）".
4. Rail tabs `["AI","证据","文献","风险","审阅","版本"]` (App.jsx:10836); enabled sets (10837-10839) never include "风险"; no render branch exists for it (chain 11360 → 11779 → 11876 → 11883 → 11891-fallback). "证据" works via the fallback branch rendering WritingReferencePanel (11891-11897).
5. Editor body font: `.protocol-editor p` 15px (styles.css:18399); `[data-style-preset="body"]` 10.5pt = 14px (styles.css:18382-18385). ≥14px body requirement met. UI chrome dominated by 11-12px (314×12px, 267×11px in styles.css).
6. Backend greenfield sections always ship `[heading_block, body_block]` (medical_writing_greenfield.py:1873 `content_blocks=[heading_block, body_block]`); plain body is an empty scaffold paragraph with source_kind greenfield_scaffold/greenfield_project_decision (1847-1858).

## Reachable-failure / defect findings

- D1 (UX dead control, minor, reachable always): "风险" rail tab is rendered but permanently disabled and has no panel. Evidence: App.jsx:10836-10839, 11348-11357 (disabled + `title="…面板尚未开放"`), no render branch. Smallest fix: remove "风险" from `writingRailTabs` until its panel exists, or hide via enabled-set intersection.
- D2 (contract drift risk): protocolWorkspaceApi.mjs (163 lines) is a frozen Task-1.9 transport contract with no consumer and no unit test. Any protocol_workflow route/shapes change will not fail any frontend check. Smallest fix: route-shape vitest (pattern exists: medical-monitoring/medicalMonitoringConsumerContract.test.mjs) even before 6R wiring; or explicitly park the file under the 6R workstream in the plan.
- D3 (latent, narrow reachability): `defaultRevisionWorkingBlock` third fallback can select a heading block (App.jsx:9464-9467) when a section has no text-bearing non-heading block and no blank greenfield scaffold paragraph (e.g. heading + empty legacy/source paragraph). submitRevisionRequest would then send the section title as `selected_text` with the heading `source_locator` (9479-9510). Today this is guarded in practice for greenfield (always a body block; table sections blocked by the table-cell gate 8492-8496) but remains a hazard for imported/legacy sections. Smallest fix: exclude headings from the fallback and set an explicit "本章无可修订目标" message.
- D4 (consistency debt): document-export (10545-10603) and full-draft (10415-10452) use hand-rolled pollers + localStorage keys storing only {project_id, job_id, mode/started_at} (10438-10441, 10581-10589), while section revision jobs use the buildLocator v2 + domain-ack discipline (9556-9683, durableJobState.mjs). Two polling stacks in one file; export/full-draft restore lacks the locator-version/operation lineage. Fix direction: migrate both to pollDurableMwJob/buildLocator + explicit domain ack (export ack = download receipt; full-draft ack = adopt result), or record why they are excluded from the durable discipline.
- D5 (maintainability): WritingPage declares ~100 useState/useRef in one component (App.jsx:7901-8040). Not a user-facing failure, but it is the concrete seam map for the 6R rewrite: session loader / working-copy editor / revision rail / quality dock / export+freeze controller / journey drawer.
- D6 (cosmetic): `const stage = payload?.pipeline?.stage` inside the pipeline poll shadows the component state `stage` (MedicalWritingAuthoringJourneySetup.jsx:893). Rename for clarity.
- D7 (minor): useDurableMwJob poll loop sets error text on every failed poll (useDurableMwJob.js:242-250); a backend outage spams error state each 3s. Debounce or set only on state change.

## Verified-good mechanisms (claims checked, kept)

- Save conflict path: 409 → recovery draft persisted, message tells user nothing was overwritten (App.jsx:10112-10117); recovery drafts hashed + baseRevision-keyed in sessionStorage (6153-6250) with conflict-aware restore prompt (11232-11246) and unsaved-navigation dialog (11906-11936).
- Atomic AI adoption: production uses `/revision-threads/{id}/accept-and-apply` with expected revision + protected-token gate (9805-9870); legacy two-step only for demo (9992-9998). Accept button disabled without working_copy_id (canSelectAndApplyRevision 10802-10807).
- Prefill single-path adoption fails closed on policy rejections without reload/auto-resubmit (journey 1224-1252); composite adoption uses structured 422 POLICY_REJECTED mapping (1316-1334); 409 → single reload + explicit no-auto-retry message.
- Corpus override requires per-item acknowledgement + ≥10-char reason (2273-2300); study rebind and template upgrade each require two explicit acknowledgements + ≥10-char reason (8650-8675, 8936-8957).
- Export gating: approved_final blocked unless all required sections frozen and consistency closed (10550, 11109-11119); draft preview blocked only on unsaved changes; both resume across reload via localStorage (10504-10544).
- Synopsis intake is resumable: poll survives 3 consecutive failures, cancel/resume/re-query/reset all wired (MedicalWritingSynopsisProjectIntake.jsx:112-152, 316-385).

## Click/text budget measurement (current legacy surface, from-zero greenfield, II/III期, prefill+corpus available)

1. 新建项目 → 从零开始 → 3 text fields → 创建并进入写作 = 3 clicks + 3 texts.
2. Framing: ~6 prefill adoptions (1 click each) + 完成/commit (1 click; +1 if impact confirm) ≈ 7-8 clicks.
3. PICOS: archetype select (1) + applicability confirms (0-2) + composite adopt confirm/skip per field (6-12) + commit (1) ≈ 8-15 clicks + 2-6 texts.
4. Corpus: triage confirm (1) + admission (0-2) + 进入写作平台 (1) ≈ 2-4 clicks.
5. Writing/export: per section 创建工作副本 (1) + AI起草 (1) + 选用并写入 (1) + 冻结 (1) = 4 clicks × ~25 required sections ≈ 100 clicks, + 预览 Word / 正式 Word (2).

Total ≈ 120-135 clicks, 5-15 free texts, ≥8 distinct confirmation forms. The 20-click/5-text budget is unreachable on the legacy surface by incremental tweaks; it requires the 6R AI-lead design (one-shot full-draft adoption already exists for greenfield: App.jsx:10415-10476 — extend to the default path; batch freeze; auto working-copy on first edit). This is the central planning input, not a regression.

## Prior-claim verdicts

- "6R 新WritingPage ⬜ (handoff line 70)" — CONFIRMED by absence: no new WritingPage; no protocol_workflow UI.
- "5R 8高风险逐卡 ⬜ (line 69)" — CONFIRMED not built as cards; the legacy surface already implements ≥8 distributed confirmation forms (impact preview, corpus override, study rebind ×2, template upgrade ×2, content disposition, binding recovery, intervention overwrite, synopsis warnings).
- frontend/AGENTS.md editor contract (lines 45-49) — substantially honored: AI actions in title-level group (10888-10986), fullscreen editor save path (11315-11322), status compact. working-copy-status-bar (11008) is a single-row band, acceptable under the contract.
- 正文≥14px — MET (see fact 5).

## Test targets proposed

- T1 (new): protocolWorkspaceApi route-shape vitest pinning URL builders + 4-field error normalization (kills D2).
- T2 (new, unit): editorSourceMapping groupEditorNodesBySourceBlockId error paths (currently only browser QC tests/editor_source_mapping_qc.mjs).
- T3 (extend): MedicalWritingSynopsisProjectIntake.test.jsx — poll failure resume + confirm gating edge cases.
- T4 (extend): durableJobState.test.mjs — pickFocusedRevisionJob priority + stale-screen ack paths.
- T5 (browser QC, server-bound, Codex to run): section create→AI起草→选用并写入→冻结→正式 Word click-count assertion to keep the 6R budget measurable.
