# Task Context: mw_protocol_v3_3r3_batch2_20260908

Created: 2026-09-08 09:22:55
Objective: Author sixteen source-bound background/objective/estimand chapter contracts, dedicated skills and fixtures, in disjoint batch2 files; no core/runtime changes or acceptance claims.
Task type: `finite_code_task`
Risk: `high`
Selected agent route: `zcode` / `GLM-5.3-Flash` / `max`

## Trigger Reason

Disjoint chapter authorship provides material parallelism while batch1 is repaired. Codex retains source interpretation and independent verification; acceptance stays batch-ordered.

## Source Of Truth

Additional read-only inputs authorized here:
- reviews/mw_protocol_v3_3r3_batch2_content_spec_20260906.md (FULL)
- reviews/mw_protocol_v3_3r3_batch_coverage_reconciliation_20260906.md
- packages/contracts/workbench_contracts/protocol_v3.py (v2 schema and related types)
- services/api/app/protocol_workflow/registries/chapters.py
- scripts/qc/protocol_v3/assemble_chapter_registry.py
- scripts/qc/protocol_v3/lint_chapter_registry.py
- tests/protocol_v3/test_all_chapter_contracts.py
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/{template,node_tree,v1_to_v2_mapping}.json
- services/api/app/medical_writing_protocol_template.py (existing shared fact bindings)
- runs/mw_protocol_v3_3r3_batch1_20260906/assembled_batch1_registry.json
  (immutable format example ONLY; content is not accepted and must not be copied)
No reads of mutable batch1 contract/skill/fixture/test files while its repair runs.

## Scope

Explicit EDIT authorization exclusively for NEW files:
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/<node_id>.json
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_skills/<node_id>.json
- tests/fixtures/protocol_v3/chapter_content_v2/batch2.json
- tests/protocol_v3/test_chapter_batch2.py
- runs/mw_protocol_v3_3r3_batch2_20260908/ (NEW diagnostics only)
Exact sixteen IDs: v2_n_2_1, v2_n_2_2_1, v2_n_2_2_2_1, v2_n_2_2_3,
v2_n_2_3, v2_n_3_1_1, v2_n_3_1_2_1, v2_n_3_1_2_2, v2_n_3_1_2_3,
v2_n_3_1_2_4, v2_n_3_2_1, v2_n_3_2_2, v2_n_3_3_1, v2_n_3_3_2,
v2_n_3_4_1, v2_n_3_4_2.
No other source/tests, core/schema/assembler, plans, checkpoints, external files,
credentials, web, services, product calls, subagents, dependency installation,
security engineering or task closure. Runner owns its report/log paths.

Author meaningful source-obligation tests first and record RED, then implement
ChapterContractV2 plus dedicated Chinese ChapterSkillManifest for each node.
Preserve exact accepted source hash, node/bookmark/style IDs. No provider settings.
Reuse existing fact paths where meanings match, not duplicate editable stores.
Distinct estimand summary measure must NOT reuse picos.population_summary (that
means population description). Body323 fifth attribute belongs to v2_n_3_1_2_4;
do not invent a fifth heading. Retain unheaded toxicology, PK, general pharmacology,
own clinical evidence299 and inherited mechanism with honest provenance.
Competitor evidence cannot satisfy own-product clinical claims. Independently
required sources need separate EvidenceSourceRequirement groups: each group
accepts ANY conforming claim, not all. Preserve conditional exploratory and
route-specific obligations; no source examples hardcoded as project requirements.
No fabricated project facts or human approval receipts.

Use existing assemble_registry for exact batch slice (coverage_roles). Never count
all JSONs in shared directories. Batch contains closed vocabularies, sixteen roles
and at least four exercised families per node: positive, missing_claim OR
missing_control, wrong_source, skeleton (minimum64). Add source-specific negatives
for competitor substituted for own clinical evidence, empty ICE entries, missing
population summary and independent evidence. Synthetic examples conspicuous;
negative failures must target their reason, not unrelated identity errors.
Conditional medical QC and actual admitted provenance remain deferred: do not
claim medical coherence merely from nonempty keys.

## Success Criteria

- Targeted checks cover exact16 identities, source obligations, exercised fixtures,
  partial clean/incomplete status and full expected missing coverage.
- Report actual RED/GREEN evidence, changed files, limitations and next action.
  No full-project, clinical, visual or native Word acceptance claim.
- Existing venv only, no unrelated legacy whole-suite reruns:
  env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw
  TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8
  PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:.
  runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest
  tests/protocol_v3/test_chapter_batch2.py -q -p no:cacheprovider --tb=short
  Preserve new XML diagnostics for each run.

## Risk Boundaries

- Do not write to production paths until Codex review gate passes and writable paths are explicit.
- The delegated agent is not final authority; Codex owns verification and acceptance.

## Timeout Policy

- Do not mark the delegated agent failed for slow response alone.
- For complex or artifact-heavy work, wait and poll generously; use conference mode when multiple independent model perspectives are needed.
- Failure requires terminal error, provider exhaustion/rate limit after controlled retry, empty/truncated retry output, or no progress after hard wait plus one retry.
- A provider catalog/auth/transport preflight is diagnostic, not a live capability verdict: timeout, auth refresh failure, malformed output, or a stale/incomplete catalog must be recorded and followed by one real route attempt. Explicit user-selected routes are not blocked merely because the catalog does not list them; only a missing executable or native transport boundary may stop before that attempt.

## Loop Log

- 2026-09-08 09:22:55: Task initialized by `tools/hermes_workflow_guard.py init-task`.
