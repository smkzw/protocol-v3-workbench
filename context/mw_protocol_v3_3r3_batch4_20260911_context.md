# Task Context: mw_protocol_v3_3r3_batch4_20260911

Created: 2026-09-11 22:20:00 (ZCode takeover dispatch)
Objective: Author sixteen source-bound intervention/procedure chapter contracts, dedicated
skills and fixtures, in disjoint batch4 files; no core/runtime changes or acceptance claims.
Task type: `finite_code_task`
Risk: `high`
Selected agent route: `codebuddy` / `deepseek-v4.1-flash` / `max`
(off-peak finite_code_task chain; mlx-serve skipped on 64k input gate; codebuddy slot free)

## Trigger Reason

Batch-ordered acceptance with overlapping authorship (approved pattern). batch3 is
concurrently authored by another worker; assembly loads only selected coverage_roles
slices, so concurrent NEW files in shared directories are structurally safe.

## Source Of Truth

Additional read-only inputs authorized here:
- reviews/mw_protocol_v3_3r3_batch4_content_spec_20260906.md (FULL — your primary source spec)
- reviews/mw_protocol_v3_3r3_batch_coverage_reconciliation_20260906.md
- packages/contracts/workbench_contracts/protocol_v3.py (v2 schema)
- services/api/app/protocol_workflow/registries/chapters.py
- scripts/qc/protocol_v3/assemble_chapter_registry.py
- scripts/qc/protocol_v3/lint_chapter_registry.py
- tests/protocol_v3/test_all_chapter_contracts.py
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/{template,node_tree,v1_to_v2_mapping}.json
- services/api/app/medical_writing_protocol_template.py (existing shared fact bindings)
- runs/mw_protocol_v3_3r3_batch1_repair_20260908/assembled_batch1_registry.json
  (immutable accepted batch1 format/vocabulary example ONLY — follow STRUCTURE and
  fixture-ID convention, never copy content)
- tests/protocol_v3/test_chapter_batch1.py (accepted batch-scope test patterns, read-only)
Do NOT read or write other batches' mutable contract/skill/fixture/test files:
batch2 (v2_n_2_*/v2_n_3_* files, batch2.json, test_chapter_batch2.py — under fresh review)
and batch3 (v2_n_4_*/v2_n_5_* files, batch3.json, test_chapter_batch3.py — being written
right now). Reading them races; writing them is forbidden.

## Scope

Explicit EDIT authorization exclusively for NEW files:
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/<node_id>.json (16)
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_skills/<node_id>.json (16)
- tests/fixtures/protocol_v3/chapter_content_v2/batch4.json
- tests/protocol_v3/test_chapter_batch4.py
- runs/mw_protocol_v3_3r3_batch4_20260911/ (NEW diagnostics only)
Exact sixteen IDs: v2_n_6_1_1, v2_n_6_1_2, v2_n_6_2_1, v2_n_6_2_2, v2_n_6_2_3,
v2_n_6_2_4, v2_n_6_3, v2_n_6_4_1, v2_n_6_4_2, v2_n_6_4_3, v2_n_7_1, v2_n_7_2,
v2_n_7_3, v2_n_8_1, v2_n_8_2, v2_n_8_3.
No other source/tests, core/schema/assembler/lint, plans, checkpoints, external files,
credentials, web, services, product model calls, subagents, dependency installation,
security engineering or task closure.

## Authoring requirements (binding)

Author meaningful source-obligation tests FIRST and record RED evidence under the run dir,
then implement ChapterContractV2 plus dedicated Chinese ChapterSkillManifest for each node.
Preserve exact accepted source hash, node/bookmark/style IDs. No provider settings.
Reuse existing fact paths where meanings match, not duplicate editable stores. Key
semantic obligations from the spec (read the FULL spec; these are highlights):
- Dose/regimen/administration: typed route/regimen/start/max facts; template examples
  (titration, specific mg) are example-only, never project facts; cross-section dose
  consistency with design and SoA.
- Storage/handling/accountability: real units and conditions, not empty or template text.
- Adherence and permitted rescue strategy must agree with the estimand and analysis
  contracts (rescue inconsistent with estimand is a negative fixture).
- Individual-level and trial-level events stay typed and separated: individual temporary
  hold, permanent treatment discontinuation, withdrawal from participation, trial-level
  suspension/termination (source 496-511 mixes them under one heading — do not replicate
  that conflation). Trial stopping criteria cannot become individual stopping rules;
  "efficacy shown" requires design-specific decision logic, not a template phrase.
- Continued assessments after discontinuation (512-516): data types, time limits,
  existing-data treatment, basis for collection; discontinuation ≠ consent withdrawal;
  replacement policy must agree with sample-size/analysis contracts.
- Withdrawal (518-535): recorded reason may be requested but must not be compulsory;
  pregnancy/progression/nonadherence scenario-specific; follow-up and already-collected
  data must not be silently erased.
- Lost to follow-up (536-546): project-specific contact attempts, records, classification;
  a missed visit alone is not sufficient; "more than three calls" is an example, not a
  universal minimum; not reaching a participant is not consent withdrawal.
- Visit/procedure windows: units + reference events; phone contacts counted as actual
  visits where applicable (consistent with batch1 SoA carrier semantics).
- Independently required sources get separate EvidenceSourceRequirement groups
  (ANY-of inside a group); every group has context window + quality floor.
- Fixture ID convention: match batch1 hyphen format, e.g. fixture:batch4:v2-n-6-1-1:positive.
- Mandatory negative material from the spec: conflicting dose/regimen facts across
  sections; copied grade thresholds without support; empty storage units; adherence
  denominator omitted; rescue inconsistent with estimand; follow-up silently ending at
  last dose; individual stop equated with trial stop; invented approval/consent receipts.
- Synthetic examples conspicuous (【合成夹具】-style markers); boolean trigger facts use
  bare true/false (batch1 D5 convention); negative failures must target their reason,
  not unrelated identity errors.

Use existing assemble_registry for the exact batch slice (coverage_roles) — never glob or
count shared directories; batch-scope assertions only (selected batch exactly 16; other
batches' files appearing must never affect your tests). Closed vocabularies, sixteen roles,
at least four exercised families per node (positive, missing_claim OR missing_control,
wrong_source, skeleton; minimum 64) plus the spec's source-specific negatives.

## Success Criteria

- Targeted checks cover exact 16 identities, source obligations, exercised fixtures,
  partial clean/incomplete status and full expected missing coverage.
- Report actual RED/GREEN evidence, changed files, limitations and next action.
  No full-project, clinical, visual or native Word acceptance claim.
- Existing venv only, no unrelated legacy whole-suite reruns:
  env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw
  TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8
  PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:.
  runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest
  tests/protocol_v3/test_chapter_batch4.py -q -p no:cacheprovider --tb=short
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
FILES_CREATED: list with counts (16 contracts / 16 skills / fixtures file / test file / diagnostics)
RED_EVIDENCE: path(s) of pre-implementation failing runs
GREEN_EVIDENCE: exact pytest command + tail summary line + XML path
FIXTURES: total count, per-family breakdown, source-specific negatives list
SEMANTIC_NOTES: individual-vs-trial-level event separation, rescue/estimand agreement,
  withdrawal semantics, example-vs-project separation, evidence-group separation (node ids)
DEFERRED: obligations deliberately deferred with reasons
LIMITS_AND_NEXT: what remains for acceptance
