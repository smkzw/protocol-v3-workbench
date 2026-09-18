# Task Context: mw_protocol_v3_3r3_batch3_20260911

Created: 2026-09-11 21:40:00 (ZCode takeover dispatch)
Objective: Author ten source-bound design/population chapter contracts, dedicated skills and
fixtures, in disjoint batch3 files; no core/runtime changes or acceptance claims.
Task type: `finite_code_task`
Risk: `high`
Selected agent route: `pi` / `openai-codex` / `gpt-5.6-luna` / `xhigh`
(off-peak finite_code_task chain, third node: mlx-serve skipped on 64k input gate,
codebuddy/deepseek-v4.1-flash occupied by concurrent batch2)

## Trigger Reason

Batch-ordered acceptance with overlapping authorship (approved pattern, implement.md 2026-09-08).
batch2 (16 carriers) is concurrently authored by another worker; assembly loads only selected
coverage_roles slices, so concurrent NEW files in shared directories are structurally safe.

## Source Of Truth

Additional read-only inputs authorized here:
- reviews/mw_protocol_v3_3r3_batch3_content_spec_20260906.md (FULL — your primary source spec)
- reviews/mw_protocol_v3_3r3_batch_coverage_reconciliation_20260906.md
- packages/contracts/workbench_contracts/protocol_v3.py (v2 schema and related types)
- services/api/app/protocol_workflow/registries/chapters.py
- scripts/qc/protocol_v3/assemble_chapter_registry.py
- scripts/qc/protocol_v3/lint_chapter_registry.py
- tests/protocol_v3/test_all_chapter_contracts.py
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/{template,node_tree,v1_to_v2_mapping}.json
- services/api/app/medical_writing_protocol_template.py (existing shared fact bindings)
- runs/mw_protocol_v3_3r3_batch1_repair_20260908/assembled_batch1_registry.json
  (immutable CURRENT batch1 format/vocabulary example ONLY; follow its STRUCTURE and
  fixture-ID convention, never copy its content)
Do NOT read or write any other batch's mutable contract/skill/fixture/test files:
batch1 (config/.../v2_front_block.json, v2_n_front_*.json, v2_n_1_*.json and their skills,
tests/fixtures/protocol_v3/chapter_content_v2/batch1.json, tests/protocol_v3/test_chapter_batch1.py)
is under fresh review; batch2 files (v2_n_2_*/v2_n_3_* contracts/skills, batch2.json,
test_chapter_batch2.py) are being written right now. Reading them races; writing them is forbidden.

## Scope

Explicit EDIT authorization exclusively for NEW files:
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/<node_id>.json (10)
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_skills/<node_id>.json (10)
- tests/fixtures/protocol_v3/chapter_content_v2/batch3.json
- tests/protocol_v3/test_chapter_batch3.py
- runs/mw_protocol_v3_3r3_batch3_20260911/ (NEW diagnostics only)
Exact ten IDs: v2_n_4_1, v2_n_4_2, v2_n_4_3, v2_n_4_4, v2_n_4_5,
v2_n_5_1, v2_n_5_2, v2_n_5_3, v2_n_5_4, v2_n_5_5.
No other source/tests, core/schema/assembler/lint, plans, checkpoints, external files,
credentials, web, services, product model calls, subagents, dependency installation,
security engineering or task closure.

## Authoring requirements (binding)

Author meaningful source-obligation tests FIRST and record RED evidence under the run dir,
then implement ChapterContractV2 plus dedicated Chinese ChapterSkillManifest for each node.
Preserve exact accepted source hash, node/bookmark/style IDs. No provider settings.
Reuse existing fact paths where meanings match (spec lists: framing.structured_design,
picos.study_epochs, framing.population_intent, picos.population_summary), not duplicate
editable stores. Key semantic obligations from the spec:
- Parent v2_n_5 body372–379 population framing lives in the inclusion carrier (no fabricated
  extra leaf); exclusion references it without duplicating inverse criteria.
- Inclusion = all-applicable-criteria predicate; exclusion = any-applicable-criterion. Typed
  boolean logic, units, thresholds, windows, exceptions — not free-text numbering only.
- No duplicate inverse inclusion/exclusion; no incompatible thresholds; no template examples
  (oral dosing, one-month contraception, blanket pregnancy exclusion, smoking/device
  restrictions, IWRS/1:1/stratified blocks, "per statistics section 9" stale cross-reference)
  hardcoded as project requirements.
- Completion vs overall study end are distinct definitions; screen failure vs rescreening
  distinct with permitted reasons/timing/records; "not randomized" example must not
  uncritically classify every consented nonrandomized person as criterion failure.
- High-risk design choices (NI margin, placebo, dose) remain explicit project-instance human
  decisions — obligations state what must be decided and its evidence floor, never a default.
- Independently required sources get separate EvidenceSourceRequirement groups (ANY-of
  semantics inside a group).
- Fixture ID convention: match CURRENT batch1 hyphen format, e.g.
  fixture:batch3:v2-n-4-1:positive.
- Spec's negative-fixture list is mandatory material: wrong comparator/ratio, dose evidence
  for another regimen, end-of-treatment substituted for follow-up, inclusion/exclusion
  threshold contradiction, copied sample contraception duration, phantom completed approval,
  stale numbered reference, nonspecific per-protocol descriptions.

Use existing assemble_registry for the exact batch slice (coverage_roles) — never glob or
count shared directories; batch-scope assertions only (selected batch exactly 10; other
batches' files appearing must never affect your tests). Closed vocabularies, ten roles, at
least four exercised families per node (positive, missing_claim OR missing_control,
wrong_source, skeleton; minimum 40) plus the spec's source-specific negatives. Synthetic
examples conspicuous; negative failures must target their reason, not unrelated identity
errors. Conditional medical QC and actual admitted provenance remain deferred: do not claim
medical coherence merely from nonempty keys.

## Success Criteria

- Targeted checks cover exact 10 identities, source obligations, exercised fixtures,
  partial clean/incomplete status and full expected missing coverage.
- Report actual RED/GREEN evidence, changed files, limitations and next action.
  No full-project, clinical, visual or native Word acceptance claim.
- Existing venv only, no unrelated legacy whole-suite reruns:
  env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw
  TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8
  PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:.
  runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest
  tests/protocol_v3/test_chapter_batch3.py -q -p no:cacheprovider --tb=short
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
FILES_CREATED: list with counts (10 contracts / 10 skills / fixtures file / test file / diagnostics)
RED_EVIDENCE: path(s) of pre-implementation failing runs
GREEN_EVIDENCE: exact pytest command + tail summary line + XML path
FIXTURES: total count, per-family breakdown, source-specific negatives list
SEMANTIC_NOTES: parent-body372-379 placement, predicate typing, example-vs-project separation,
  evidence-group separation (node ids)
DEFERRED: obligations deliberately deferred with reasons
LIMITS_AND_NEXT: what remains for acceptance
