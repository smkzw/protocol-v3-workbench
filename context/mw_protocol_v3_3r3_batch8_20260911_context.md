# Task Context: mw_protocol_v3_3r3_batch8_20260911

Created: 2026-09-11 22:50:00 (ZCode takeover dispatch)
Objective: Author twelve source-bound quality/references/appendices chapter contracts,
dedicated skills and fixtures, in disjoint batch8 files; no core/runtime changes or
acceptance claims.
Task type: `finite_code_task`
Risk: `high`
Selected agent route: `codebuddy` / `deepseek-v4.1-flash` / `max`

## Trigger Reason

Final batch of 3R.3 (batch8 = 12 carriers; after this all 111 carriers are delivered).
No concurrent worker writes ch14-16 files. Assembly loads only selected coverage_roles
slices.

## Source Of Truth

Additional read-only inputs authorized here:
- reviews/mw_protocol_v3_3r3_batch8_content_spec_20260906.md (FULL — your primary source spec)
- reviews/mw_protocol_v3_3r3_batch_coverage_reconciliation_20260906.md
- packages/contracts/workbench_contracts/protocol_v3.py (v2 schema)
- services/api/app/protocol_workflow/registries/chapters.py
- scripts/qc/protocol_v3/assemble_chapter_registry.py
- scripts/qc/protocol_v3/lint_chapter_registry.py
- tests/protocol_v3/test_all_chapter_contracts.py
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/{template,node_tree,v1_to_v2_mapping}.json
- services/api/app/medical_writing_protocol_template.py (existing shared fact bindings)
- runs/mw_protocol_v3_3r3_batch1_repair_20260908/assembled_batch1_registry.json
  (accepted batch1 format/vocabulary example ONLY)
- tests/protocol_v3/test_chapter_batch1.py and tests/protocol_v3/test_chapter_batch4.py
  (accepted batch-scope test patterns, read-only)
Do NOT read or write other batches' mutable fixture/test files. Writing any file outside
your Scope is forbidden.

## Scope

Explicit EDIT authorization exclusively for NEW files:
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/<node_id>.json (12)
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_skills/<node_id>.json (12)
- tests/fixtures/protocol_v3/chapter_content_v2/batch8.json
- tests/protocol_v3/test_chapter_batch8.py
- runs/mw_protocol_v3_3r3_batch8_20260911/ (NEW diagnostics only)
Exact twelve leaf IDs (parent v2_n_14 is NOT a carrier; note v2_n_16 is a heading-only
CONTAINER carrier aggregated with its outline leaves — the reconciliation doc and node_tree
are authoritative):
v2_n_14_1, v2_n_14_2, v2_n_14_3, v2_n_14_4, v2_n_14_5, v2_n_14_6, v2_n_14_7,
v2_n_15, v2_n_16, v2_n_16_x1, v2_n_16_x2, v2_n_16_x3.
No other source/tests, core/schema/assembler/lint, plans, checkpoints, external files,
credentials, web, services, product model calls, subagents, dependency installation,
security engineering or task closure.

## Authoring requirements (binding)

Author meaningful source-obligation tests FIRST and record RED evidence under the run dir
(two-stage RED: missing test file, then failing assertions with test present), then
implement ChapterContractV2 plus dedicated Chinese ChapterSkillManifest for each node.
Preserve exact accepted source hash, node/bookmark/style IDs — word_rules.required_styles/
required_bookmarks MUST be populated from node_tree.json (batch4 D1 precedent; batch7
worker did this correctly, follow its pattern). New fact roots need ownership declarations
(batch3 D3/batch6 D6 precedent: shared namespace / StudyDefinition carrier / no second
in-chapter store). Conditional rules at CONTRACT level with schema field names
(conditional_applicability_rule_id/triggering_fact_paths/condition/rationale/
required_when_active_fact_paths); every path a rule references must be declared in
fact_requirements (batch6 D1 precedent); all rule/fact/claim paths must be in the batch
closed vocabularies. Boolean trigger facts bare true/false (batch6 D4 precedent).
No provider settings. READ THE FULL SPEC; key demands:
- CtQ/risk management (884-885, v2_n_14_1 area): actual critical factors, associated
  risks, proportionate controls, responsibility, review linkage to the trial's important
  decisions and data; generic list or placeholder plan name fails (negative: generic CtQ
  slogan without anchors).
- Sponsor/monitor/investigator responsibilities (886-909): match actual arrangements; no
  inference of completed training or signed acceptance from intended responsibilities;
  monitoring statements agree with the chosen proportionate approach (no promise of
  unexamined universal source verification); copied company names forbidden (negative).
- Audit/inspection and deviations (910-915): distinct processes, records, impact
  assessment, applicable communication; important vs general deviations and urgent-hazard
  exceptions have actual definitions; a local TP-MA-15 title is not evidence of integrated
  content (declare provenance pending, do not validate).
- Safety oversight (916-921): actual suitable oversight/composition/roles/information/
  review; independent DSMB vs sponsor-involved SMC vs endpoint IRC NOT interchangeable
  (negative: incompatible committee roles); semiannual meetings and escalation examples
  only; no fictional membership or approved charter (negative: fabricated approval).
- References (926-969, v2_n_15): generated from ACTUALLY USED sources with complete
  bibliographic metadata and resolvable citations; formatting follows applicable template
  style; template example references are NOT a study bibliography (negative: unused/
  copy-pasted bibliography); every in-text citation must resolve (negative: in-text
  citation with no target).
- Appendix container v2_n_16 (970-972): aggregates actual applicable attachments;
  preserve heading-leaf coverage separately from outlined child leaves x1/x2/x3.
- ECOG/NYHA appendices (973-978, x-carriers): conditional on actual assessments; version
  and contents verified against appropriate sources when selected; not automatic inclusion
  (negative: irrelevant score appendix).
- Laboratories/destruction provider (981-995, x-carriers): genuine applicable names,
  identifying details, roles; the two sample laboratories and destruction company are
  template examples, not project suppliers (negative: blank or invented cells).
- Independently required sources get separate EvidenceSourceRequirement groups (ANY-of
  inside); context window + quality floor.
- Fixture ID convention: fixture:batch8:v2-n-14-1:positive style; conspicuous synthetic
  markers; negative failures target their reason with exact codes asserted (batch4 D2/
  batch6 D3 precedent: every source-specific negative has an expected-code assertion).

Use existing assemble_registry for the exact batch slice; batch-scope assertions only
(selected batch exactly 12; other batches' files never affect your tests). Closed
vocabularies, twelve roles, at least four exercised families per node (positive,
missing_claim OR missing_control, wrong_source, skeleton; minimum 48) plus the spec's
source-specific negatives.

## Success Criteria

- Targeted checks cover exact 12 identities, source obligations, exercised fixtures,
  partial clean/incomplete status; full-mode lint now reports 0 missing of 111 expected
  ONLY IF assembling ALL eight batches (use assemble_registries with all batch paths —
  do not claim it unless all eight assemble; otherwise report expected missing = 0 in
  your own batch's partial report is NOT applicable, keep partial-mode assertions).
- Report actual RED/GREEN evidence, changed files, limitations and next action.
  No full-project, clinical, legal, visual or native Word acceptance claim.
- Existing venv only, no unrelated legacy whole-suite reruns:
  env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw
  TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8
  PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:.
  runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest
  tests/protocol_v3/test_chapter_batch8.py -q -p no:cacheprovider --tb=short
  Preserve new XML diagnostics for each run under the run dir.

## Risk Boundaries

- Do not write outside the explicitly listed NEW files. The delegated agent is not final
  authority; the ZCode main owner owns verification and acceptance.

## Timeout Policy

- Do not mark yourself failed for slow progress; work continuously to completion.
- Failure requires terminal error, provider exhaustion/rate limit after controlled retry,
  or empty/truncated output.

## Output schema (your FINAL message, plain text)

STATUS: COMPLETED | PARTIAL | FAILED
FILES_CREATED: list with counts (12 contracts / 12 skills / fixtures file / test file / diagnostics)
RED_EVIDENCE: path(s) of pre-implementation failing runs
GREEN_EVIDENCE: exact pytest command + tail summary line + XML path
FIXTURES: total count, per-family breakdown, source-specific negatives list
SEMANTIC_NOTES: CtQ anchoring, committee-role separation, reference-bibliography
  generation semantics, appendix container vs outline leaves, conditional score
  appendices, laboratory/provider example separation (node ids)
DEFERRED: obligations deliberately deferred with reasons
LIMITS_AND_NEXT: what remains for acceptance
