# Task Context: mw_protocol_v3_3r3_batch2_resume_20260911

Created: 2026-09-11 21:25:00 (ZCode takeover dispatch; supersedes the interrupted
mw_protocol_v3_3r3_batch2_20260908 dispatch which delivered nothing)
Objective: Author sixteen source-bound background/objective/estimand chapter contracts,
dedicated skills and fixtures, in disjoint batch2 files; no core/runtime changes or
acceptance claims.
Task type: `finite_code_task`
Risk: `high`
Selected agent route: `codebuddy` / `deepseek-v4.1-flash` / `max`
(off-peak finite_code_task chain; pi/mlx-serve primary skipped at dispatch: 64k
input-context gate incompatible with this file-heavy authoring session)

## Trigger Reason

Original batch2 worker (zcode/GLM-5.3-Flash, sess_4df83643) read materials but was
SIGINT'd 2026-09-08 09:34 before delivering any file. Reconciliation confirmed zero
batch2 files exist, so this is the same-scope continuation, not an overlapping re-dispatch.

## Source Of Truth

Additional read-only inputs authorized here:
- context/mw_protocol_v3_3r3_batch2_20260908_context.md (original batch2 context; still authoritative for scope/boundaries)
- reviews/mw_protocol_v3_3r3_batch2_content_spec_20260906.md (FULL)
- reviews/mw_protocol_v3_3r3_batch_coverage_reconciliation_20260906.md
- packages/contracts/workbench_contracts/protocol_v3.py (v2 schema and related types)
- services/api/app/protocol_workflow/registries/chapters.py
- scripts/qc/protocol_v3/assemble_chapter_registry.py
- scripts/qc/protocol_v3/lint_chapter_registry.py
- tests/protocol_v3/test_all_chapter_contracts.py
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/{template,node_tree,v1_to_v2_mapping}.json
- services/api/app/medical_writing_protocol_template.py (existing shared fact bindings)
- runs/mw_protocol_v3_3r3_batch1_repair_20260908/assembled_batch1_registry.json
  (immutable CURRENT batch1 format/vocabulary example ONLY; its content is repaired but
  not yet independently accepted — follow its STRUCTURE and fixture-ID convention, never
  copy its content)
Do NOT read or write the mutable batch1 contract/skill/fixture/test files under
config/.../chapter_contracts|chapter_skills, tests/fixtures/protocol_v3/chapter_content_v2/batch1.json,
tests/protocol_v3/test_chapter_batch1.py — batch1 is under concurrent fresh review and may change.

## Scope

Explicit EDIT authorization exclusively for NEW files:
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/<node_id>.json (16)
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_skills/<node_id>.json (16)
- tests/fixtures/protocol_v3/chapter_content_v2/batch2.json
- tests/protocol_v3/test_chapter_batch2.py
- runs/mw_protocol_v3_3r3_batch2_resume_20260911/ (NEW diagnostics only)
Exact sixteen IDs: v2_n_2_1, v2_n_2_2_1, v2_n_2_2_2_1, v2_n_2_2_3,
v2_n_2_3, v2_n_3_1_1, v2_n_3_1_2_1, v2_n_3_1_2_2, v2_n_3_1_2_3,
v2_n_3_1_2_4, v2_n_3_2_1, v2_n_3_2_2, v2_n_3_3_1, v2_n_3_3_2,
v2_n_3_4_1, v2_n_3_4_2.
No other source/tests, core/schema/assembler/lint, plans, checkpoints, external files,
credentials, web, services, product model calls, subagents, dependency installation,
security engineering or task closure. Runner owns its report/log paths.

## Authoring requirements (binding)

Author meaningful source-obligation tests FIRST and record RED evidence under the run dir,
then implement ChapterContractV2 plus dedicated Chinese ChapterSkillManifest for each node.
Preserve exact accepted source hash, node/bookmark/style IDs. No provider settings.
Reuse existing fact paths where meanings match, not duplicate editable stores.
- Distinct estimand summary measure must NOT reuse picos.population_summary (that means
  population description). Body323 fifth attribute (population-level summary measure)
  belongs to v2_n_3_1_2_4; do not invent a fifth heading; it is not an ICE.
- Retain unheaded toxicology, PK, general pharmacology, own-product clinical evidence299
  and inherited mechanism with honest provenance (not dropped just because not leaf headings).
- Competitor evidence cannot satisfy own-product clinical claims (body299 sits inside a
  competitor-titled area; keep ownership explicit).
- Independently required sources need separate EvidenceSourceRequirement groups: each group
  accepts ANY one conforming claim, not all.
- Preserve conditional exploratory and route-specific obligations; no source examples
  hardcoded as project requirements; no fabricated project facts or human approval receipts.
- Fixture ID convention: match CURRENT batch1 hyphen format, e.g.
  fixture:batch2:v2-n-2-1:positive (see assembled_batch1_registry.json fixtures).

Use existing assemble_registry for the exact batch slice (coverage_roles) — never count all
JSONs in shared directories; batch-scope assertions only (selected batch exactly 16; future
batches appearing must not break your tests). Closed vocabularies, sixteen roles, and at
least four exercised families per node: positive, missing_claim OR missing_control,
wrong_source, skeleton (minimum 64). Add source-specific negatives for: competitor evidence
substituted for own clinical evidence, empty ICE entries, missing population summary
measure, missing independent evidence group. Synthetic examples conspicuous; negative
failures must target their reason, not unrelated identity errors. Conditional medical QC
and actual admitted provenance remain deferred: do not claim medical coherence merely from
nonempty keys.

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
  tests/protocol_v3/test_chapter_batch2.py -q -p no:cacheprovider --tb=short
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
SEMANTIC_NOTES: how estimand 5th attribute / competitor-vs-own evidence / unheaded PK-tox
  obligations / evidence-group separation were handled (node ids)
DEFERRED: obligations deliberately deferred with reasons
LIMITS_AND_NEXT: what remains for acceptance
