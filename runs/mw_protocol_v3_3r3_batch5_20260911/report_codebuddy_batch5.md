# Execution report: 3R.3 batch5 (codebuddy/deepseek-v4.1-flash:max)

Saved by dispatching ZCode main owner from the runner stream.
Route identity: codebuddy/deepseek-v4.1-flash, modelUsage echo, duration 797112ms, 190 turns.

---

All green and consistent — final XML is newer than every artifact. Report follows.

STATUS: COMPLETED

FILES_CREATED
- `config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/`: 19 NEW ChapterContractV2 files — v2_n_9_1/_2/_3/_4, v2_n_10_1_1.._6, v2_n_10_2_1.._3, v2_n_10_3_1.._3, v2_n_10_4/_5/_6 (contract_version 3.3.0; batch5 model: `contract:v2-n-10-1-1:v2`)
- `config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_skills/`: 19 NEW dedicated Chinese ChapterSkillManifest files (no provider/model fields; schema refs = shared `ChapterSkillInput/Output`; real node bookmarks; provenance binds template sha256 + zero-based body-child windows)
- `tests/fixtures/protocol_v3/chapter_content_v2/batch5.json`: NEW (6494 lines; 19 coverage roles, closed fact/claim vocabularies 120/63, 113 fixtures)
- `tests/protocol_v3/test_chapter_batch5.py`: NEW (1538 lines, 41 tests)
- `runs/mw_protocol_v3_3r3_batch5_20260911/`: diagnostics — `red_preimplementation_20260911.xml`, `green_iter1_20260911.xml`, `green_iter2_20260911.xml`, `green_final_20260911.xml`, `crosscheck_batch1_shared_dir_20260911.xml`, `assembled_batch5_registry.json`, `lint_partial_batch5.txt`

RED_EVIDENCE
- `runs/mw_protocol_v3_3r3_batch5_20260911/red_preimplementation_20260911.xml` — authored tests ran before any contract/skill/fixture existed: `5 failed, 36 errors in 1.94s` (all 41 tests fail on missing artifacts).

GREEN_EVIDENCE
- Command (exact context command): `env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:. runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest tests/protocol_v3/test_chapter_batch5.py -q -p no:cacheprovider --tb=short`
- Tail summary: `41 passed in 1.28s`
- XML: `runs/mw_protocol_v3_3r3_batch5_20260911/green_final_20260911.xml` (written after the last artifact edit; mtimes: artifacts ≤ 22:10:38, XML 22:10:44)
- Read-only CLI checks: assembly exit 0 → `assembled_batch5_registry.json`; `lint_chapter_registry.py --partial --check-fixtures` exit 0 → `mode: partial`, `status: incomplete`, `coverage: expected=111 covered=19`, zero `[WARNING]`, zero lint findings outside fixture results.

FIXTURES
- Total 113: positive 22 (19 canonical + 3 conditional-branch), missing_control 45, missing_claim 7, wrong_source 20, skeleton 19; every node has all four families (minimum floor 76 exceeded).
- Canonical families use the convention `fixture:batch5:v2-n-9-1:positive|missing-claim|…`; every positive passes, every negative fails for its named reason (`missing_required_fact/claim/cell`, `forbidden_fact/claim_present`, `wrong_source_role`, `missing_structural_object`, `skeleton_content`).
- 34 source-specific negatives (33 asserted by name in the test map + 1 extra): endpoint-not-traceable, instrument-version-missing; lab-value-without-units, blanket-restriction-no-rationale, specimen-volume-or-purpose-missing, comparator-evidence-for-own-safety, empty-monitoring-schedule; pk-endpoint-unlinked, population-pk-schedule-missing; irc-conflated-with-safety-committee; copied-oncology-exception, parent-safety-framing-dropped; ctcae-version-from-template, severity-seriousness-conflated, wrong-scale-version, empty-severity-table; causality-collapsed-binary, adr-mapping-reused-for-expedited; ae-collection-equals-teaee, template-period-cutoffs-copied; report-time-by-convenience; label-only-event-record; sae-from-severity-alone, empty-seriousness-criteria-table; signed-form-delays-report; followup-outcome-missing; susr-equals-sae; reporting-clock-copied, adr-mapping-reused-for-expedited-reporting; causality-disagreement-dismissed; invented-clinical-receipt; aesi-from-template-list; pregnancy-auto-sae, pregnancy-auto-withdrawal.
- Negative fixtures carry only the codes they are named for (forbidden-material fixtures are additionally constrained to forbidden_* ∪ missing_* — no unrelated source/identity errors); synthetic values are conspicuous `【合成夹具】`, boolean triggers bare `true/false`, evidence locators carry the source window + synthetic marker.

SEMANTIC_NOTES
- AE/SAE/TEAE taxonomy: distinct required facts per node — AE definition/collection interval/TEAE derivation/pre-existing handling/term binding (v2_n_10_1_1); severity scale version/grading/distinctness (10_1_2); seriousness criteria + version binding + severity distinction (10_2_1); SUSAR definition/expectedness/IB-RSI binding (10_3_1). `ae_equals_teaee`, `seriousness_equals_severity`, `sae_classified_from_severity`, `susar_equals_sae`, `expectedness_equals_causality` are forbidden claims with exercised negatives.
- Dual reporting clocks: investigator SAE clock (v2_n_10_2_2: recipient/clock/first-awareness/record; signed-form-day-zero forbidden) is a different typed object from the sponsor SUSAR clocks (v2_n_10_3_2: sponsor clock + separate follow-up clock + authority/ethics communications; reporting matrix cells). The two positive fixtures' clock values differ, cross-copying is a forbidden claim with a negative, and neither node declares the other's clock fact.
- Five-level causality: `causality.five_level_terminology` required and reproduced verbatim in the table cell; statistical ADR grouping ≠ expedited algorithm; draft guidance ≠ current law; negatives `causality-collapsed-binary` and `adr-mapping-reused-for-expedited(-reporting)`.
- Pregnancy (v2_n_10_6): testing, prevention, exposure reporting, partner consent, outcome follow-up, abnormal-outcome event reporting, withdrawal arrangement and continued-collection arrangement are separate required facts; `pregnancy_equals_sae`, `pregnancy_forces_total_withdrawal`, `pregnancy_stops_all_followup` forbidden; three/six-month periods are a forbidden template example; `discontinuation.continued_assessment_scope` (batch4) is reused to keep cessation semantics single-sourced.
- CTCAE project-binding: `ae.severity_scale_version` required (positive contains “项目已确认绑定”), template example path forbidden; no claim that v5.0 is latest and no v6.0 activation condition.
- Parent-body inheritance placement: v2_n_9 → `evaluation.framework_scope` (v2_n_9_1); v2_n_10 → `ae.chapter_scope_framing` (v2_n_10_1_1); v2_n_10_3 area paragraph → `susar.chapter_area_framing` (v2_n_10_3_1); heading-only parents v2_n_10_1/v2_n_10_2 declare a no-body crosswalk onto their leaf ranges (v2_n_10_1_1, v2_n_10_2_1). All carry “继承声明” markers; parents are not carriers (assembled slice = exactly 19 leaf nodes).
- Cross-batch reuse (no duplicate stores): `picos.primary_objectives/primary_endpoint` (9.1), `exploratory.population_pk/exposure_response/immunogenicity/biomarker` (9.3), `picos.aesi_definitions` (10.5), `discontinuation.continued_assessment_scope` (10.6); all declared in the batch5 closed vocabulary.
- Source windows bound to node_tree heading/body indexes (549–563, 565–581, 583–585, 586–589, 596–599, 601–607, 608–649, 650–661, 663–700, 702–704, 708–710, 712–716, 717–718, 721–722, 723–729, 730–731, 732–738, 739–747, 748–751). v2_n_10_1_4 is documented as the one carrier whose first content paragraph is at heading+2 (body 651 belongs to no node/table — a non-content element excluded by the accepted extraction); the test asserts that exclusion rather than inventing an offset.

DEFERRED
- Conditional applicability rules, positive QC rules, CtQ items, skeleton-risk rules and project-specific elements are reported by the registry as `deferred_qc_obligations` — no runtime conditional evaluation or drafting was implemented (core/schema/assembler untouched by contract).
- Native Word rendering of bound bookmarks/styles and any visual/PDF check: not performed.
- Cross-batch dependency_ids (e.g. 9.1 → batch2 objective contract) were deliberately not declared, because they would dangle in a batch5-only slice; the agreement obligation is carried by reused fact paths + QC rules instead.
- Section 10.2.3 has only one source paragraph; its contract binds new-information reporting and outcome documentation but no additional source-specific negative beyond `followup-outcome-missing`.
- Regulatory currency (GVP/GCP article applicability, CDE FAQ interpretation) remains a human/Codex acceptance question; nothing in batch5 asserts current-law status.

LIMITS_AND_NEXT
- No full-registry, clinical, visual or native-Word acceptance claim: partial lint is clean but `incomplete` by construction (19/111 carriers; remaining 92 belong to other batches). Cross-batch impact check was bounded to batch1's shared-directory glob tests (`3 passed, 14 deselected`) — batch3's mutable files were never read or written.
- For the main owner's acceptance: combined-registry lint once batch3 lands, a source-text-level review of the 19 contracts against sections 9–10 (body 547–751), confirmation that batch3 has not changed shared-path expectations, and acceptance of the two documented scope calls (assessment-restriction typing placed in v2_n_9_2; heading-only parents handled by declared crosswalk).
- The venv python path and TMPDIR both existed; no environment improvisation was needed.