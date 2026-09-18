# Execution Output: mw_protocol_v3_3r4b_condition_matrix_20260913 - worker_01

## Boundary And Context Check

- Read initial read set first: `context/mw_protocol_v3_3r4b_condition_matrix_20260913_execution_context.md` and `plans/codex_execution_mw_protocol_v3_3r4b_condition_matrix_20260913.md`. Worked only inside the runner-provided CWD; wrote only `runs/mw_protocol_v3_3r4b_20260912/condition_worker/` (3 files). No product/source/test edits, no services, no model product calls, no OCR/translation/web, no cleanup, no credentials, no recursive agents, no final acceptance claimed.
- Read-only context used as authorized: plan §3R.4B, 49 rule contracts, node_tree.json, fact_bindings.json, the existing `applicability_obligation_matrix.json`, both source-window files, `registries/applicability.py`, `packages/contracts/workbench_contracts/protocol_v3.py` (material_sha256 region only).
- The authorized readonly DOCX was opened via stdlib zipfile/XML only after verifying its sha256 equals the authorized `018d28d…43756`; body-child extraction matched both source windows line-for-line.

## Work Performed

Produced a source-bound, one-row-per-rule proposal covering all 49 conditional-applicability rules (27 nodes), each row carrying: trigger-encoding analysis (fact_bindings value_type + contract rationale), an explicit predicate proposal, true/false/unknown obligations for facts/claims/objects with origin classification (source-required vs source-required-conditional-scope vs inherited-overrequirement vs contract-derived vs proposed-new), overlap disposition, and source evidence. Key results:

1. **Encoding inventory (decisive)**: only 10 of 49 triggers are declared bare booleans (`value_type=boolean` + rationale "裸 true/false"); 36 are `value_type=json`. Under `FactPredicate`'s strict type comparison, `expected=true` against a json fact is permanently CONDITIONAL — exactly the plan's "names ending applicable do not prove boolean encoding". Rows split: 10 executable, 19 unresolved-with-member-proposal (`members=("applicable",) expected=true`), 18 unresolved carrier-triggers (per-feature booleans needed), 2 non-scalar conditions needing dedicated boolean facts.
2. **14 fact-overlap rules adjudicated individually** (no uniform deletion): 8 promote-to-conditional (pk/pd/er ×3, interim ×10 facts, future-use ×7, dose-modification ×4, escalation self-trigger, background_therapy_rules, randomization_day_rules, individual-hold ×2), 5 remove-from-conditional-keep-unconditional (multiplicity disposition, background-rescue handling, hold-to-stop permanent facts, central-lab generic facts ×2), 1 keep-as-negative-disposition (rescreening) — each with a verbatim source quote.
3. **Special focus resolved**: interim-false releases 10 facts + canonical_reference + table (11 cells) + 2 claims and requires a new `not_planned_disposition`; `endpoint_irc_responsibilities` marked inherited-overrequirement with an interim×IRC composite-rule split proposal; central-vs-local lab needs 3 new central-specific facts plus a `lab_strategy` disposition (source [572]/[574]); permanent-stop facts stay unconditional while hold facts go conditional; multiplicity needs a `multi_confirmatory_endpoints` boolean to rebuild the missing "adjustment-needed" branch; IRC true/false fully adjudicated per [587]-[589]; pregnancy gap and suppliers per below.
4. **Defects found (evidence-backed)**: D1 `safety.central_lab_applicable` trigger fact is undeclared in v2_n_9_2's own fact_requirements; D2 v2_n_5_2 rule requires undeclared fact `population.exclusion.contraception_criterion_ref`; D3 the interim contract's canonical-target rule cites the virtual "v2_n_13_x 载体族" — chapter 13 is the ethics family, the real IDMC/oversight carrier is v2_n_14_7; D4 the 36 json triggers block predicate execution until the owner declares encodings; D5 claim-level overlaps (≈20) exist beyond the 14 counted fact overlaps.
5. Validation: programmatic asserts confirmed rule-set/order equality with the base matrix, equality of the 14-overlap set, FactPredicate schema conformance of every proposed predicate, and that all `executable_boolean_declared` predicates target boolean-typed facts. 33 rows carry non-empty explicit `unresolved[]` items; 15 rows carry false-branch negative-disposition proposals.

## Artifacts And Evidence

- `runs/mw_protocol_v3_3r4b_20260912/condition_worker/proposed_matrix.json` (49 rows; status `worker_proposal_pending_codex_adjudication`; `not_an_accepted_medical_conclusion: true`).
- `runs/mw_protocol_v3_3r4b_20260912/condition_worker/summary.md` (method, encoding inventory, 14-overlap table, 8 special-focus adjudications, defect list D1–D5, unresolved list, verification record).
- `runs/mw_protocol_v3_3r4b_20260912/condition_worker/build_proposed_matrix.py` (reproducible generator; reads only authorized inputs, writes only this directory).
- Source evidence embedded per row as `src[body_child_zero_index]` quotes, extracted from the authorized DOCX (sha256 verified) and cross-checked against `statistics_source_window.json` / `oversight_reference_source_window.json`.

## Commands And Observations

- `rg "3R.4B" plans/…` → located plan section; requirements extracted (typed predicates, per-item adjudication, interim-false full handling incl. canonical_reference/tables, v2_n_13_x correction).
- `python3` (stdlib json/zipfile/ElementTree, ~12 invocations): inspected matrix/contracts/fact_bindings/node_tree structures; extracted all 49 rule payloads, per-node unconditional obligations, trigger-fact rationales; dumped node source text from DOCX; verified sha256 and index alignment; generated and validated the deliverable. Observations of record: matrix status `source_inventory_only_not_executable` with all 49 decisions `not_yet_adjudicated`; v2_n_9_2 has zero fact_requirements entries containing "central"; `v2_n_13` appears once in v2_n_11_4_9.json inside the word_rule citing "v2_n_13_x 载体族"; node titles confirm 13.x = 伦理规范/知情同意/保密和隐私/补偿赔偿保险 and 14_7 = 安全性监督, 14_6 = 方案偏离.
- Validation script asserted: rule-id sequence equality, overlap-set equality, predicate schema conformance, boolean-typed targets for executable predicates — all passed ("ALL CHECKS PASSED").

## Blockers Or Missing Environment

None blocking. Environment had everything required. Owner-side dependencies (recorded, not blockers): encoding declarations for 36 json triggers (D4), two undeclared facts (D1/D2), canonical-target correction (D3), and decisions on the 33 rows' open items (e.g., src[798] thin source for 11_4_6, src[324] four-vs-five-attribute tension, disposition-style negative values in fact schemas).

## Rerun Requests Or Next Step

No rerun needed. Suggested next steps for Codex: (1) accept/adjust the 14 overlap dispositions and the 10 executable predicate declarations, then fold them into the 3R.4A serial contract revisions; (2) fix D1–D3 defects in the same revision pass; (3) decide the new-fact proposals (`statistics.interim.not_planned_disposition`, `safety.lab_strategy` + central-lab facts, `multi_confirmatory_endpoints`, interim×IRC split rule) before checker implementation. Everything I produced is a proposal for Codex's adjudication, not accepted state.
