# Conference Participant Output: mw_protocol_v3_3r1_fresh_20260906 - general_single_object

## Boundary Check

- Read-only final pass on the current frozen candidate: `scripts/qc/protocol_v3/extract_tp_ma_07_v2_registry.py` (2482 lines), `runs/mw_protocol_v3_3r1_registry_20260906/test_codex_semantic_obligations.py` (9 tests — the actual Codex probes), the three regenerated JSONs (02:00), plus the approved DOCX (read-only zip/XML) and legacy AST. No worker reports, no edits, no services/network/OCR/translation/cleanup; report returned, not written.
- **Correction to my round-2 report, stated plainly:** I did not run the Codex probe file in round 2 — it exists at `runs/mw_protocol_v3_3r1_registry_20260906/`, outside `tests/`, and my name/content grep missed it. My round-2 "[INFERENCE]" identifying the four in-file distinction tests as the probes was wrong. This round I executed the real file: **51/51 pass (42 registry + 9 Codex probes)** on the pinned venv with `PYTHONPATH=tests/protocol_v3:services/api:packages:.` and `-p no:cacheprovider`. I claim only tests executed this round.
- Scope: candidate-registry fidelity only. 3R.3 leaf contracts, M11 anchor verification, and Word render remain later obligations; nothing here completes them. Codex is final authority.

## Independent Work Product

**Verdict: ACCEPT** — candidate `tp_ma_07_v2` registry accepted as a faithful, honestly-deferred source-bound extraction. All round-1 items (R1–R4) and round-2 items (D1, D2) verified closed in implementation, artifacts, and tests. No new defects found; one trivial non-blocking note below.

**D1 repair verified (missing reverse edges restored + enforced):** all 9 round-2 pairs now cited — `v2_n_9_2` gained `immunogenicity` + `biomarker` (7 entries), `v2_n_9_1` gained `biomarker`, `v2_n_12_2` is `mixed` [crf, source], `v2_n_1_3`/`v2_n_9_3`/`v2_n_16_x3` extended, `v2_n_10_2_2` cites [sae, reporting, appendices.safety_reporting]. Re-ran my round-2 agreement check: **zero residual missing edges**. The builder invariant (script L2083–87) is correctly one-directional — forward targets holding reverse entries must cite; container targets (no reverse keys) and `FRONT_BLOCK_ID` are naturally exempt, so the documented forward-container/reverse-descendant convention survives untouched. The 8 reverse-only descendant citations (e.g. `v2_n_10_1_1←safety.ae`) remain legitimate. Negative test `test_missing_reverse_edge_is_rejected` proves the invariant fires. Dispositions now 77/7/7/18 = 109, zero `retired`.

**D2 repair verified (slice ownership exact):** every resolution slice in committed `v1_to_v2_mapping.json` carries `actual_owner_v2_node_ids`; the two former container cases now read precisely — nonclinical @286→`v2_n_2_2_2`, @288–294→`v2_n_2_2_2_1`; definitions @597–599→`v2_n_10_1_1`, @709–710→`v2_n_10_2_1`. Builder (L2131–66) validates ownership (node title/content, table, front block) plus carrier-ancestry, rejecting chapter-head text cited from leaf slices and vice versa; `test_resolution_locators_have_exact_content_owners` and `test_valid_index_in_wrong_carrier_is_rejected` both pass. Constant table unmutated (computed into fresh dicts; zero `actual_owner` keys in `SOURCE_RESOLUTIONS`; committed JSON matches regen per green test). 41 partials = 39 leaves + 2 containers (`procedures_assessments.schedule`, `safety.definitions` — both legitimately resolved); exact-set partial↔resolution invariant holds.

**Immunogenicity downgrade verified honest:** now `mapped_to_v2 / partial / partially_carried` — "源文仅列通用免疫学检测及样本处理框架；不等同免疫原性策略…须在3R.3按产品证据建立." Source-true: @575 lists 免疫学检测 among generic special assays (full text verified round 2); the generic≠drug-specific judgment is Codex's semantic call, recorded as partial + 3R.3 deferral rather than coverage. `test_generic_immunology_does_not_prove_immunogenicity_contract` guards it. This is exactly the honest-deferral pattern 3R.1 requires.

**Preserved round-2 evidence (re-confirmed current):** committee separation source-true (9_4 @587–589 efficacy IRC vs 14_7 @917–921 DSMB/SMC); ten retained conditionals all carrier-bound with original rules; own-product @299 vs same-class @298, handling @574–575 vs future-use @830–836, pregnancy 10_6≡[749,750,751] with testing-only-elsewhere, ECOG/NYHA example tables — all distinctions intact; zero-match claims confirmed (过量/给药错误/overdose 0; 2_2_1 content solely @284; 机制 hits only in 10_1_3 boilerplate); finance product-convention default, 13.4 `required`, clean field allowlist + footer PAGE/NUMPACKAGES (`test_word_inventory_includes_footer_page_fields` green), M11 provenance 124/6 with 17 `new_in_v2` explicitly unverified; counts/mechanics unchanged; `candidate_not_current` gate intact.

**Trivial note (non-blocking, no revision demanded):** `dispositions_vocabulary` still lists unused `retired`. Suggest annotating historic or dropping at next touch.

## Evidence And Assumptions

**Evidence (this round, observed):** 51/51 executed passes; D1/D2 artifact diffs enumerated above; builder code read (L167–76 allowlist, L2083–87 edge invariant, L2131–66 ownership + ancestry + fresh-dict emission); committed JSON field checks (owners, citations, statuses, summary counts); DOCX re-verification of @575 generic-assay text and zero-match terms.
**Evidence (carried, rounds 1–2):** SHA re-hash match; ~70 body-child locator dump vs claimed text/owners; 124-row legacy identity @lineno 398; committee/pregnancy/specimen/appendix locator verification.
**Inference:** none material — all verdict inputs directly observed this round.
**Assumptions:** DOCX at PRD path is the approved authority (PRD + hash gate); @306/@729 regulatory-tension annotations are out-of-scope judgments (locators only checked); semantic closure of partials and 3R.3 contracting belong to promotion, explicitly gated.

## Risks, Gaps, And Verification Needs

1. No residual fidelity risk found in this pass. The highest prior risk (D1 reverse invisibility of immunogenicity/biomarker) is closed and regression-guarded by builder + probe.
2. Standing promotion conditions (unchanged, owned by Codex): independent semantic review of the 41 partials + findings; 8 `awaiting_3r3_contract` resolutions contracted in 3R.3; M11 anchor verification against current guideline text; no `current`/runtime use before all pass.
3. No further verification requested by this role. Meaningful-test bar met: Codex probes assert structural invariants (bidirectionality, ownership, rejection negatives), not text echoes.

## Recommended Next Step

**Accept the 3R.1 candidate as-is** (no further revision round needed from this role). Promotion path for Codex: (a) complete the gated semantic review of partials/findings, (b) feed the 8 awaiting + 11 partially-carried slices as explicit input to 3R.3 leaf contracting, (c) verify M11 anchors against current E6(R3) text. Optional hygiene: drop or annotate the unused `retired` vocabulary entry at the next regeneration.
