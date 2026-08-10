# Conference Participant Output: mw_protocol_v3_phase0_task08_acceptance_20260810 - general_grok45

## Boundary Check

- Role: `general_grok45` (Participant 2, evidence/contradiction verifier only).
- Provider/model assignment: `grok` / `grok-build` / `grok-4.5`. Hermes routes and Hermes identity files were not used as authority.
- Workspace: only the current Protocol v3 workbench root. No production paths outside the declared packet.
- Edit status: no source edits; no write to `runs/conference/mw_protocol_v3_phase0_task08_acceptance_20260810/general_grok45.md` (report returned for runner persistence).
- Prohibited scope held: no Word invocation, no service start, no security/adversarial/permission/path/symlink/TOCTOU/malicious-input/destructive tests, no Pi report, no medical-monitoring inspection.
- Tools this pass: none (round 3). Prior rounds read the conference context, Codex main-venue plan, `word_receipt` README/decision, both CMS final receipts, roundtrip lineage manifest, TP-MA-07 candidate (partial large file), D017 resume event, and a directory inventory under `pocs/protocol_v3/word_receipt/`. Planned `pytest` and further event reads were cancelled and are **not** claimed as observed.
- Authority residual: final visual, live Word inventory, original external sample hash re-check, and P0-WORD disposition remain Codex-only.

## Independent Work Product

### Verdict

**`READY_WITH_RESIDUALS`** for Task 0.8 frozen **P0-WORD** technical producer acceptance, scoped as: *at least one Microsoft Word native producer path on the target macOS workstation satisfies the frozen receipt contract on CMS-UC-301, including wording-edit → reimport → re-export lineage and page-evidence artifacts, while TP-MA-07 and D017 remain correctly non-upgraded blockers.*

This is **not** Protocol content quality, product API, cross-platform distribution, Phase 1+, or release acceptance.

### Challenge 1 — Does `decision.md` overstate the AppleScript bridge?

**Evidence (observed):**
- `pocs/protocol_v3/word_receipt/decision.md` selects “受控 AppleScript bridge” as Phase 0 producer; status `READY_FOR_INDEPENDENT_REVIEW`; Office Add-in is `DOCUMENTARY_ONLY`; LibreOffice/HTML/DOCX-only are `REJECTED`.
- Residual section states bridge is workstation-verifiable Phase 0 only; does **not** claim cross-platform distribution, signing, Add-in UX, or product API wiring (Phase 6–7).
- Compatibility notes admit Word 16.111 Mac collection/`next story` instability and limited story coverage (document-level stories + per-section first/even/primary headers/footers); future text-frame/comment/revision samples require re-validation.
- Final receipts bind:
  - Initial: `producer_identity.producer_type = applescript_bridge`, `producer_id = protocol-v3-word-mac-applescript-poc`, `word_application_version = Microsoft Word for Mac 16.111.3`, `workflow = open_without_repair_update_all_story_fields_toc_repaginate_check_bookmarks_refs_save_reopen_export_pdf`
    path: `pocs/protocol_v3/word_receipt/results/CMS-UC-301-e692a28e51ed/receipt.json`
  - Roundtrip: same producer type/id/version string, **different** `implementation_sha256`
    path: `pocs/protocol_v3/word_receipt/results/CMS-UC-301-wording-roundtrip-r2-18dc202605c6/receipt.json`

**Inference:** Decision language is **mostly not overstated** for a Phase 0 technical path: it ties claims to Word 16.111.3 runs and explicitly walls off productization. Mild overstatement risk is only if “PASS_CANDIDATE” is read as multi-corpus or multi-machine readiness; residual text already denies that.

**Contradiction to resolve:** Initial `implementation_sha256 = 1fd1fb09…56a91f66` vs roundtrip `f7d9d8b1…7a023a39`. That is consistent with key/receipt re-binding after producer code change, but it means the two CMS final receipts are **not** the same producer binary identity. Codex should treat them as two successful identities on the same bridge design, not one frozen producer hash for both.

### Challenge 2 — Are TP-MA-07 and D017 correctly prevented from upgrading?

**TP-MA-07 (observed):**
- Canonical failed-path run dir: `pocs/protocol_v3/word_receipt/results/TP-MA-07-dc6dfe33f78d/`
- Present: `receipt_candidate.json`, `events/001-reserved.json`, `002-word-invocation.json`, `003-candidate-ready.json`, `pages/`, `contact-sheets/`, `word-export.pdf`, `word-saved.docx`
- **Absent from inventory:** `receipt.json` / final receipt finalize event
- Candidate fields inspected: `field_count_before/after = 302`, `field_update_error_count = 0`, `page_count = 62`, `input_docx_sha256 = a28e95d738ffad9199eee44a965164d89a04022dbcac7ea01a999bde5cf34f5e` (matches decision), many `page_evidence[].visual_qc_status = pending_visual_qc` (pages 1–53+ in the portion read; none upgraded to `pass` in that sample)
- Decision: page-2 footer clip → keep `pending_visual_qc`, do not mint final receipt

**D017 (observed):**
- Run dir: `pocs/protocol_v3/word_receipt/results/D017-synopsis-import-70376ada005a/`
- Present: `events/001-reserved.json`, `002-word-invocation.json`, `003-postprocess-resumed.json`, `input.docx`, `word-export.pdf`, `word-saved.docx`
- **Absent from inventory:** `receipt.json`, `receipt_candidate.json`
- `003-postprocess-resumed.json`: `event = postprocess_resumed_without_word_replay` with `source_word_event_sha256 = 8f28642d93e468091bd8c690c05bbb3ab92f83001170454ea61ede4c709bebc5` — supports postprocess resume without Word re-side-effect
- Decision: typed blocker `WR_BOOKMARK_EVIDENCE` (stable business bookmark missing); must not upgrade to submittable protocol

**Inference:** On artifact shape alone, both paths are **correctly non-upgraded**: TP stops at candidate + pending visual QC; D017 stops before candidate/final receipt and records resume-without-replay. Multiple other `TP-MA-07-*` dirs with only reservation/word-invocation are intermediate debris, not success upgrades.

**Uncertainty:** Exact D017 failure code string was **not** re-read from a failure event body this session; only decision text + resume event + missing receipt files support the classification.

### Challenge 3 — Are CMS initial + wording-edit roundtrip receipts and PNG/contact sheets sufficient for frozen P0-WORD?

**Contract-facing positive evidence (CMS initial)** — `…/CMS-UC-301-e692a28e51ed/receipt.json`:
| Field | Value |
|---|---|
| `receipt_id` | `mwwr_v1_a8a815cb196ef9ed3c99e692a28e51ed` |
| `verification_status` | `word_native_verified` |
| `verification_engine` | `microsoft_word` |
| `open_without_repair` / `reopen_pass` / `repaginate_pass` | true |
| `field_update_scope` | `all_story_ranges` |
| fields | 126 → 126, errors 0 |
| `toc_count` | 1 |
| bookmarks | 5 (`_MWFIG_*`, `_MWREF_*`, `_MWTAB_*`), targets match |
| xrefs | 32 `PAGEREF`, all `resolved: true` |
| page_count / evidence | 27; all `visual_qc_status: pass`; landscape 9/10/14 (893×1263 vs 1263×893) |
| identities | input `cd5d483a…`, saved `bdf8b982…`, pdf `58ffbd2c…` distinct |
| lineage mode | `no_external_edit` |
| page producer | `pypdfium2` `5.12.1`, SPDX Apache-2.0 OR BSD-3-Clause, egress none |

**Contract-facing positive evidence (wording roundtrip)** — `…/CMS-UC-301-wording-roundtrip-r2-18dc202605c6/receipt.json` + `…/CMS-UC-301-wording-roundtrip/002-lineage-manifest.json`:
| Field | Value |
|---|---|
| `receipt_id` | `mwwr_v1_234418ce286849ee898f18dc202605c6` |
| `verification_status` | `word_native_verified` |
| fields / TOC / pages | 126/126/0 errors; TOC 1; 27 pages all `pass` |
| `semantic_document_revision` | `semantic-document-cms-uc-301-wording-r2` |
| lineage mode | `edit_reimport_export` |
| source sha | `bdf8b982…` (prior Word-saved) |
| edited / reimported / reexport-input sha | all `d9309158…` |
| run input / saved / pdf | `d9309158…` / `06e43188…` / `151c2812…` distinct |
| OOXML fingerprint | `2c82db48…` (matches decision) |
| artifact **ids** | four different labels: `word-saved-bdf8…`, `word-external-edit-d930…`, `word-reimport-d930…`, `word-input-d930…` |

**Page/contact-sheet inventory (existence only, not visual judgment):**
- Initial: `pages/page-0001.png`…`page-0027.png`, `contact-sheets/contact-01.png`…`contact-04.png`
- Roundtrip r2: same 27 pages + 4 contact sheets
- TP candidate: 62 pages + `contact-01`…`contact-07` (block evidence, not success)

**Highest-impact defect / uncertainty (active peer challenge):**

1. **Lineage language vs content hashes.**
   `decision.md` / README say source/edited/reimported/re-exported “artifact identity 四者不同”. Observed: **four IDs differ**, but **three content SHA-256 values are identical** (`d9309158…` for edited = reimported = reexport/input). The new Word-saved (`06e43188…`) and PDF (`151c2812…`) are **not** the fields named `reexport_artifact_*`.
   - If the frozen contract means four **ids**, CMS passes.
   - If a reviewer reads “四者不同” as four **content hashes**, the decision **overstates**.
   - **Remediation for Codex:** confirm against `contract.py` that same-byte reimport staging is allowed when `artifact_id` labels differ and only source sha must differ from the edited stream; if required, rename decision wording to “四个 artifact_id 不同；source 内容 hash 与 edited 流不同；reexport 产出另用 saved/pdf identity 证明” or fix lineage field names so `reexport_artifact_*` points at the new saved DOCX.

2. **`reexport_artifact_sha256` equals reimport input, not post-Word re-export.**
   That weakens a naive reading of “再导出 identity”. The run-level `saved_docx_sha256` / `pdf_sha256` still prove a new export product. Codex should either accept this as intentional staging semantics or treat it as a contract/docs consistency residual (not necessarily a runtime failure).

3. **Independent verifier did not execute the 67 focused tests or the frozen receipt validator this session** (shell cancelled). Codex main-venue plan marks them done; that is **Codex observation**, not this participant’s observation.

4. **Visual QC authority.** Receipts mark all CMS pages `pass`; contact sheets and PNGs exist. This participant did **not** open images. Codex checklist claims 27-page visual review — retain Codex as sole visual acceptor.

5. **Font environment thinness.** Both CMS receipts report `font_count: 2`, `missing_fonts: []`, `substituted_fonts: []`. For a Chinese 27-page protocol this may be a complete **task-bound** manifest or an under-counted inventory. Residual, not alone blocking if Codex already accepted font gate semantics.

6. **Template/semantic revision drift between CMS runs** (`legacy-cms-uc-301-20260727` vs `cms-uc-301-representative-v0.1`; different semantic revisions) is expected for edit→merge but means acceptance is “representative closed loop on CMS family,” not “one frozen template revision for all evidence.”

**Conclusion on sufficiency:** For the frozen P0-WORD bar (“≥1 producer, real Word, objects, immutable deliverables, edit→reimport→re-export, page evidence, failed paths not upgraded”), the **immutable receipt + event + page file set is sufficient as functional evidence**, with residuals above. Do **not** expand TP machine success or D017 Word progress into producer-wide pass.

### Objection list for Codex (actionable)

| # | Objection | Proposed resolution | Blocks P0-WORD? |
|---|---|---|---|
| O1 | Lineage “四者不同” vs identical edited/reimport/reexport content SHA | Re-validate with frozen validator; clarify decision wording or lineage field mapping | Only if contract requires four distinct **content** hashes |
| O2 | `implementation_sha256` changed between CMS initial and roundtrip | Record both hashes as accepted identities; pin which hash is “current” for future replay | No, if each receipt self-binds |
| O3 | 67 tests / validator not re-run by this role | Codex re-run or cite prior log path in disposition | Residual if Codex log already exists |
| O4 | Visual pass is receipt-encoded, not re-verified here | Codex keeps visual disposition | No for this role |
| O5 | D017 typed code not re-read from event payload | Codex confirms `WR_BOOKMARK_EVIDENCE` (or equivalent) in events | Residual classification only |

### Bounded questions for Codex

1. Under `contract.py`, must `edit_reimport_export` enforce four distinct **content** SHA-256 values, or four distinct **artifact_id** values with source≠edited content sufficient?
2. Is `reexport_artifact_*` defined as the staged re-export **input** or the Word **saved** re-export product?
3. Which `implementation_sha256` is the frozen Task 0.8 producer pin for post-acceptance replay?

**Safe provisional path if unanswered:** Dispose P0-WORD as technical pass on CMS final receipts with residual lineage-documentation note; do not treat TP/D017 as pass; do not claim multi-producer or product ship.

## Evidence And Assumptions

### Evidence (directly observed this session)

- Context: `context/mw_protocol_v3_phase0_task08_acceptance_20260810_conference_context.md`
- Plan: `plans/codex_main_venue_mw_protocol_v3_phase0_task08_acceptance_20260810.md` (checklist claims 67 tests, validator, visual, inventory — Codex-side claims)
- `pocs/protocol_v3/word_receipt/decision.md`, `README.md`
- Final receipts:
  - `pocs/protocol_v3/word_receipt/results/CMS-UC-301-e692a28e51ed/receipt.json`
  - `pocs/protocol_v3/word_receipt/results/CMS-UC-301-wording-roundtrip-r2-18dc202605c6/receipt.json`
- Lineage: `pocs/protocol_v3/word_receipt/results/CMS-UC-301-wording-roundtrip/002-lineage-manifest.json`
- TP candidate: `pocs/protocol_v3/word_receipt/results/TP-MA-07-dc6dfe33f78d/receipt_candidate.json` (large file partially read)
- D017: `…/D017-synopsis-import-70376ada005a/events/003-postprocess-resumed.json`
- Directory inventory under `pocs/protocol_v3/word_receipt/` confirming presence/absence of final receipts, pages, contact sheets (context path `results/…` maps to this PoC results tree)

### Inference

- AppleScript bridge is a substantiated Phase 0 producer candidate, not a documentary-only claim, because two finalized `word_native_verified` receipts bind Word 16.111.3 workflow fields and distinct deliverable hashes.
- Failure handling is correctly asymmetric: machine object success without visual/bookmark gates does not yield final receipt.
- Decision residual language already prevents the worst overclaim (product/API/cross-platform).

### Assumptions

- Frozen Task 0.7 contract in `contract.py` accepts the receipt shapes observed (not re-executed validator here).
- Codex visual pass on CMS 27 pages and original sample hash checks remain valid as chair evidence.
- Roundtrip wording change described in decision was real Word-side edit; only hashes/ids were independently checked here.

### Uncertainty

- pytest `pocs/protocol_v3/word_receipt/tests` result this session: **unknown** (cancelled).
- Full `contract.py` line-level rules for lineage SHA equality: **not re-read after cancellation**.
- D017 exact error code payload: **not re-read**.
- PNG/contact-sheet pixel content: **not inspected** (existence only).
- Whether `font_count: 2` satisfies contract “font manifest” intent: **uncertain**.

## Risks, Gaps, And Verification Needs

| Risk/gap | Category | Needed verification (Codex-owned or allowed) |
|---|---|---|
| Lineage wording vs identical edited stream hashes | Contract semantics | Frozen validator on both CMS `receipt.json`; confirm field definitions |
| Producer `implementation_sha256` drift | Identity pin | Record both; pick current pin for replay matrix |
| Tests not re-observed by Grok | Independent re-proof | Re-run `python3 -m pytest pocs/protocol_v3/word_receipt/tests -q` if disposition requires dual observation |
| Visual QC | Authority | Codex only; do not reassign to participants |
| TP page-2 clip / D017 bookmarks | Intentional blockers | Keep out of producer-wide pass language |
| Story coverage residual | Corpus bound | Already stated in decision; no P0-WORD expansion to text-frame/comments |

No security testing recommended or performed.

## Recommended Next Step

1. **Codex disposition (recommended):** Accept Task 0.8 **P0-WORD technical pass with residuals**, based on:
   - `CMS-UC-301-e692a28e51ed` receipt `mwwr_v1_a8a815cb196ef9ed3c99e692a28e51ed`
   - `CMS-UC-301-wording-roundtrip-r2-18dc202605c6` receipt `mwwr_v1_234418ce286849ee898f18dc202605c6`
   - intentional non-upgrade of `TP-MA-07-dc6dfe33f78d` (candidate only / `pending_visual_qc`) and `D017-synopsis-import-70376ada005a` (no final/candidate receipt; resume-without-replay event)
2. **Before or in the same disposition note, resolve O1/O2** in one short decision sentence: lineage field semantics + which producer implementation hash is frozen.
3. **Do not** promote TP machine object success or D017 Word progress to P0-WORD success; **do not** treat Office Add-in docs as alternate producer pass.
4. **Scope label for user:** P0-WORD unlocks only the Word native producer technical gate; Protocol content, A+C workbench, Phase 6–8, and final release remain separate.

**Participant decision string:** `READY_WITH_RESIDUALS`
