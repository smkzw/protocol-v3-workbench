# Task Context: mw_protocol_v3_3r3_batch6_20260911

Created: 2026-09-11 23:40:00 (ZCode takeover dispatch)
Objective: Author thirteen source-bound statistics chapter contracts, dedicated skills and
fixtures, in disjoint batch6 files; no core/runtime changes or acceptance claims.
Task type: `finite_code_task`
Risk: `high`
Selected agent route: `pi` / `openai-codex` / `gpt-5.6-luna` / `xhigh`
(off-peak finite_code_task chain; mlx-serve skipped on 64k input gate; codebuddy occupied
by concurrent batch5)

## Trigger Reason

Batch-ordered acceptance with overlapping authorship (approved pattern). batch5 is
concurrently authored on another harness; assembly loads only selected coverage_roles
slices, so concurrent NEW files in shared directories are safe.

## Source Of Truth

Additional read-only inputs authorized here:
- reviews/mw_protocol_v3_3r3_batch6_content_spec_20260906.md (FULL — your primary source spec)
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
Do NOT read or write other batches' mutable fixture/test files: batch5 (v2_n_9_*/v2_n_10_*
contracts/skills, batch5.json, test_chapter_batch5.py — being written right now).
batch1/2/3/4 contracts+skills are delivered; treat ALL batch fixture/test files other than
your own as read-only reference at most. Writing any file outside your Scope is forbidden.

## Scope

Explicit EDIT authorization exclusively for NEW files:
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/<node_id>.json (13)
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_skills/<node_id>.json (13)
- tests/fixtures/protocol_v3/chapter_content_v2/batch6.json
- tests/protocol_v3/test_chapter_batch6.py
- runs/mw_protocol_v3_3r3_batch6_20260911/ (NEW diagnostics only)
Exact thirteen leaf IDs (parents v2_n_11, v2_n_11_4, v2_n_11_4_3 are NOT carriers — their
body obligations are inherited into leaves per the reconciliation doc):
v2_n_11_1, v2_n_11_2, v2_n_11_3,
v2_n_11_4_1, v2_n_11_4_2, v2_n_11_4_3_1, v2_n_11_4_3_2, v2_n_11_4_4, v2_n_11_4_5,
v2_n_11_4_6, v2_n_11_4_7, v2_n_11_4_8, v2_n_11_4_9.
No other source/tests, core/schema/assembler/lint, plans, checkpoints, external files,
credentials, web, services, product model calls, subagents, dependency installation,
security engineering or task closure.

## Authoring requirements (binding)

Author meaningful source-obligation tests FIRST and record RED evidence under the run dir,
then implement ChapterContractV2 plus dedicated Chinese ChapterSkillManifest for each node.
Preserve exact accepted source hash, node/bookmark/style IDs. No provider settings.
Reuse existing fact paths where meanings match (estimand paths from batch2:
estimand.primary.*; SoA/endpoint paths from batch1 — reference, do not duplicate editable
stores). READ THE FULL SPEC; key semantic demands:
- SAP status/timing (757-760): promised-later SAP does NOT waive protocol-level endpoint/
  estimand/primary-method/sample-size obligations; SAP revision linkage matches actual
  analysis and unblinding arrangements.
- Sample size (761-772): typed endpoint/hypotheses/test-model/sidedness+alpha/power/
  assumptions+their-evidence/allocation+attrition/method+software-version/reproducible-
  result. Interim adjustments and design effects explicit where applicable. Assumptions
  align with the selected estimand/analysis — a cited competitor's N is not an assumption
  basis. Sample-size card is high-risk human decision territory: obligations state
  decision + evidence floor + sensitivity demands, never a default N or formula.
- Analysis sets (773-777): randomized / treated / available-assessments NOT interchangeable;
  typed inclusion+grouping+handling rules; no blind discard of exposed participants or
  rescue-treated participants from template example; ANCOVA/MMRM/tipping-point examples
  (777) preserved as method obligations in the correct semantic carrier, not universal
  prescriptions; sensitivity analysis must address the intended assumption/estimand
  (different method name alone insufficient); SAS (779) is an example, software reflects
  actual arrangements + workbench calculations need their own reproducibility evidence.
- Descriptive/missing rules (781): actual variable types and conventions; missing outcomes
  vs intercurrent events are not synonyms.
- Analysis families (781-800): demographics/baseline, adherence/concomitant, primary
  main/sensitivity, secondary, safety, exploratory, subgroup — each study-specific methods
  and data definitions; blank headings and "same as previous protocol" (794/796/798) fail.
- Multiplicity (802-803): actual confirmatory family, ordering, allocation, dependencies;
  a list of Holm/Hochberg/sequence examples is not a selected procedure; no-adjustment
  needs a real applicability disposition.
- Interim analyses (805-806): applicable timing/information fraction, purpose, rules,
  decision responsibility, impact on final analysis; safety review does not automatically
  consume efficacy alpha; stale source reference 14.6 resolved to the accepted canonical
  target; IDMC responsibilities distinct from endpoint IRC responsibilities.
- Parent-body inheritance: v2_n_11 body (SAP framing), v2_n_11_4 (PK/PD/exposure-response)
  and v2_n_11_4_3 body obligations inherited into appropriate leaves with honest
  declared-addition markers. PK/PD/ER: v2_n_11_4_6 carries exploratory uses; confirmatory
  uses must LINK the relevant primary/secondary analysis contract, never relabel as
  exploratory (reconciliation doc mandate).
- Cross-batch consistency hooks: endpoint/estimand/sample-size/SoA/dose consistency
  obligations reference the other batches' fact namespaces declaratively (the
  cross-contract dependency graph is 3R.4; here declare the obligation, don't implement
  a checker).
- Independently required sources get separate EvidenceSourceRequirement groups (ANY-of
  inside a group); every group has context window + quality floor.
- Fixture ID convention: fixture:batch6:v2-n-11-1:positive style (batch1 hyphen format).
- Boolean trigger facts bare true/false; synthetic values conspicuous; negative failures
  target their reason, not unrelated identity errors.
- Mandatory negative material (from the spec): wrong assumed effect versus source; N
  without reproducible inputs; missing sidedness or allocation; mislabeled analysis set;
  placeholder sensitivity table; rescue handling inconsistent with estimand; named
  multiplicity method without actual family; interim timing/alpha inconsistent with final
  design.

Use existing assemble_registry for the exact batch slice (coverage_roles) — never glob or
count shared directories; batch-scope assertions only (selected batch exactly 13; other
batches' files appearing must never affect your tests). Closed vocabularies, thirteen
roles, at least four exercised families per node (positive, missing_claim OR
missing_control, wrong_source, skeleton; minimum 52) plus the spec's source-specific
negatives.

## Success Criteria

- Targeted checks cover exact 13 identities, source obligations, exercised fixtures,
  partial clean/incomplete status and full expected missing coverage.
- Report actual RED/GREEN evidence, changed files, limitations and next action.
  No full-project, clinical, statistical-validity, visual or native Word acceptance claim.
- Existing venv only, no unrelated legacy whole-suite reruns:
  env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw
  TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8
  PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:.
  runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest
  tests/protocol_v3/test_chapter_batch6.py -q -p no:cacheprovider --tb=short
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
FILES_CREATED: list with counts (13 contracts / 13 skills / fixtures file / test file / diagnostics)
RED_EVIDENCE: path(s) of pre-implementation failing runs
GREEN_EVIDENCE: exact pytest command + tail summary line + XML path
FIXTURES: total count, per-family breakdown, source-specific negatives list
SEMANTIC_NOTES: sample-size obligation typing, analysis-set separation, multiplicity
  family binding, interim/alpha semantics, PK-PD-ER inheritance carrier, SAP-vs-protocol
  obligation split (node ids)
DEFERRED: obligations deliberately deferred with reasons
LIMITS_AND_NEXT: what remains for acceptance
