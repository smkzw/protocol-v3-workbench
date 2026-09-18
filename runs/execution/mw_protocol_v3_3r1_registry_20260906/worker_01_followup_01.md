# Execution Output: mw_protocol_v3_3r1_registry_20260906 - worker_01

## Boundary And Context Check

Same-session bounded repair. Read the initial read set plus the current state of all five worker-owned files before editing, the fresh review (`runs/conference/mw_protocol_v3_3r1_fresh_20260906/general_single_object.md`), and Codex source observations (`reviews/mw_protocol_v3_3r1_codex_source_checks_20260906.md`). Verified the source DOCX hash gate still guards the unchanged source. Codex's prior corrections were read and preserved untouched: safety_committee→14.7 (9.4 as efficacy-IRC new_in_v2), the ten formerly retired obligations retained with carriers, 13.4 `required`, corrected financial-disclosure rationale, footer `part_field_inventory`, and field-kind allowlist. Writes confined to `scripts/qc/protocol_v3/extract_tp_ma_07_v2_registry.py`, `tests/protocol_v3/test_tp_ma_07_v2_registry.py`, the three regenerated JSONs under `config/medical_writing/protocol_v3/templates/tp_ma_07_v2/`, and new evidence under the existing task run dir. No edits to Codex probes, task status, historical reports/logs, or any other source. Legacy module AST-only; DOCX zip/XML read-only; no services/network/OCR/commits/cleanup.

## Work Performed

Red-first: added 15 focused regression tests (13 failed on arrival — evidence `runs/mw_protocol_v3_3r1_registry_20260906/followup_red_pytest.txt`), then implemented and regenerated. Final suite: **46 passed** (42 in the test file + 4 Codex probes, `followup_green_pytest.txt`).

1. **Content-resolved partial mappings (repair item 1).** Dumped and read the actual DOCX content under every partial-mapping target (`content_dump_partial_targets.txt`), plus full-text keyword scans (过量/给药错误 0 hits; 背景治疗 only in estimand examples; sample 保存/处置 at 9.2). Added a `source_resolution` layer to all 41 partial forward entries: status `source_carried` (23) / `partially_carried` (10) / `awaiting_3r3_contract` (8) / `unresolved` (0, vocabulary kept), each with per-target slices carrying zero-based body-child-index locators. Traps handled explicitly: own-product early-clinical results carried at @299 vs same-class at @298 (2.2.3), pregnancy testing declared awaiting-3R.3 while contraception (@749) and pregnancy event reporting (@750-751) are carried, current sample handling retargeted to 9.2 (@574-575) with 12.7 future-use (new_in_v2) declared a distinct obligation, appendix instrument examples (@974/@978 tables) declared non-defining for project instruments. Content-verified retargets: specimen→9.2; unscheduled→7.3 (@492); contraception→5+10.6 (@378/@749); schedule→7+1.3 (SOA table @265); source-definition→12.1+12.2 (@813/@816); quality→14.1+14 (@883/@885). Genuinely uncarried obligations stay explicitly `awaiting_3r3_contract` (overdose/error, background therapy, statistics PK/PD/E-R, safety 总则, closeout) — never promoted, never claimed as source content.
2. **Reverse sync + conventions + retained conditionals (item 2).** Reverse entries synchronized: 9.2 gains specimen, 7.3 gains unscheduled, 10.6 gains contraception, 12.7 flipped to `new_in_v2` with a no-conflation rationale, 2.2.3 rationale rewritten around the own-product/same-class distinction. Added `mapping_conventions` (forward-container/reverse-descendant, source-vs-additional-content, retained-conditional) and a `retained_conditional_obligations` block listing all ten semantics with original applicability rules, honest `conditional_source` (`row_rules` / `conditional_prefixes` / `required_in_legacy` for 14.4), concrete carriers, and `retained_conditional_awaiting_3r3_contract` status; no `retired` disposition remains anywhere.
3. **Factual fixes (item 3).** `background.product.nonclinical` downgraded to `partial` with an unheaded-toxicology ambiguity note (fresh-review R3); the false "semantic judgment, Codex-reviewed" comment replaced with "worker semantic judgment, pending Codex review"; a regression test now asserts the label cannot return.
4. **Word source rules (item 4).** Sections now record `header_reference`/`footer_reference` bindings resolved via `word/_rels/document.xml.rels` to part paths (e.g., section 1 → header1.xml/rId5, footer1.xml/rId6) plus `pg_num_type` (recorded, empty in this source). `style_properties` exported for all 70 styles with raw and resolved outline, basedOn, numbering binding (style 68 标题 1 1. → numId 1/ilvl 0), and font facts (e.g., 24 half-points). No Word output/render claim made.
5. **M11 anchors (item 5).** Forward entries carry `m11_coverage_anchors` with `anchor_provenance` (`legacy_frozen_3_1_chapter_row` / `none_in_legacy`); a `m11_anchor_policy` block marks all 17 `new_in_v2` leaf ids as unverified anchor requirements deferred to 3R.3 and states that legacy codes are inventory labels, not verified E6(R3) B.x anchors. No new anchors invented.
6. **Tests and regeneration (item 6).** Regenerated all three JSONs; byte-identical regeneration and committed-match guards pass; existing 27 assertions untouched and green; 4 Codex probes green.

## Artifacts And Evidence

- `scripts/qc/protocol_v3/extract_tp_ma_07_v2_registry.py` — resolutions/retained/conventions/anchor-policy tables, style/section extraction, validations (partial↔resolution exact set match, status/locator legality, retained-set completeness), fail-closed on drift.
- `tests/protocol_v3/test_tp_ma_07_v2_registry.py` — +15 regression tests (resolutions coverage/locators, four trap distinctions, no-retired, retained block, conventions, anchor policy, section/style properties, nonclinical partial, no false label).
- `config/.../tp_ma_07_v2/{template,node_tree,v1_to_v2_mapping}.json` — regenerated; mapping now 218 KB with resolutions, conventions, retained block, anchor policy.
- `runs/mw_protocol_v3_3r1_registry_20260906/{followup_red_pytest.txt,followup_green_pytest.txt,content_dump_partial_targets.txt}` — red evidence, green evidence, source-content reading notes.

## Commands And Observations

- Red: `13 failed, 29 passed` → implemented → green: `46 passed in 0.45s` (`pytest -p no:cacheprovider` on both files, sanitized env, isolated venv, `PYTHONPATH=tests/protocol_v3:services/api:packages:.`).
- Key content observations recorded with locators: 8.1 content itself distinguishes 干预中止 vs 研究中止 (@511); statistics 11.4 has only a structural reference note (@783); 9.2 @574-575 carries specimen handling incl. MOP deferral; SAE/SUSAR day-0 and risk-justification wordings kept as source with 3R.3 QC flags cross-referenced to Codex source checks.

## Blockers Or Missing Environment

None. Two implementation bugs (a scope error and a comment line-wrap) were caught by the tests and fixed before green.

## Rerun Requests Or Next Step

No rerun needed. Remaining ambiguity for Codex: the 10 `partially_carried` entries and 8 `awaiting_3r3_contract` entries (detail in `forward_mapping[].source_resolution`), the unresolved 24h-contact-table and pregnancy-testing-schedule slices, and section 1 `pg_num_type` being empty in source (field recorded, nothing invented). Candidate remains `candidate_not_current`; no self-promotion or completion marking.
