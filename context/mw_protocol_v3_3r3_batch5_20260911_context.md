# Task Context: mw_protocol_v3_3r3_batch5_20260911

Created: 2026-09-11 23:05:00 (ZCode takeover dispatch)
Objective: Author nineteen source-bound evaluation/safety chapter contracts, dedicated
skills and fixtures, in disjoint batch5 files; no core/runtime changes or acceptance claims.
Task type: `finite_code_task`
Risk: `high`
Selected agent route: `codebuddy` / `deepseek-v4.1-flash` / `max`
(off-peak finite_code_task chain; mlx-serve skipped on 64k input gate)

## Trigger Reason

Batch-ordered acceptance with overlapping authorship (approved pattern). batch3 is
concurrently authored by another worker (different chapter range); assembly loads only
selected coverage_roles slices, so concurrent NEW files in shared directories are safe.

## Source Of Truth

Additional read-only inputs authorized here:
- reviews/mw_protocol_v3_3r3_batch5_content_spec_20260906.md (FULL — your primary source spec)
- reviews/mw_protocol_v3_3r3_batch_coverage_reconciliation_20260906.md
- packages/contracts/workbench_contracts/protocol_v3.py (v2 schema)
- services/api/app/protocol_workflow/registries/chapters.py
- scripts/qc/protocol_v3/assemble_chapter_registry.py
- scripts/qc/protocol_v3/lint_chapter_registry.py
- tests/protocol_v3/test_all_chapter_contracts.py
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/{template,node_tree,v1_to_v2_mapping}.json
- services/api/app/medical_writing_protocol_template.py (existing shared fact bindings)
- runs/mw_protocol_v3_3r3_batch1_repair_20260908/assembled_batch1_registry.json
  (accepted batch1 format/vocabulary example ONLY — follow STRUCTURE and fixture-ID
  convention, never copy content)
- tests/protocol_v3/test_chapter_batch1.py and tests/protocol_v3/test_chapter_batch4.py
  (accepted batch-scope test patterns, read-only)
Do NOT read or write other batches' mutable contract/skill/fixture/test files:
batch3 (v2_n_4_*/v2_n_5_* files, batch3.json, test_chapter_batch3.py — being written right
now). batch1/batch2/batch4 contracts+skills are accepted/committed but treat their batch
fixture/test files as read-only reference only. Writing any file outside your Scope is
forbidden.

## Scope

Explicit EDIT authorization exclusively for NEW files:
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/<node_id>.json (19)
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_skills/<node_id>.json (19)
- tests/fixtures/protocol_v3/chapter_content_v2/batch5.json
- tests/protocol_v3/test_chapter_batch5.py
- runs/mw_protocol_v3_3r3_batch5_20260911/ (NEW diagnostics only)
Exact nineteen leaf IDs (parents v2_n_9, v2_n_10, v2_n_10_1, v2_n_10_2, v2_n_10_3 are NOT
carriers — their body obligations are inherited into the leaves per the reconciliation doc):
v2_n_9_1, v2_n_9_2, v2_n_9_3, v2_n_9_4,
v2_n_10_1_1, v2_n_10_1_2, v2_n_10_1_3, v2_n_10_1_4, v2_n_10_1_5, v2_n_10_1_6,
v2_n_10_2_1, v2_n_10_2_2, v2_n_10_2_3,
v2_n_10_3_1, v2_n_10_3_2, v2_n_10_3_3,
v2_n_10_4, v2_n_10_5, v2_n_10_6.
No other source/tests, core/schema/assembler/lint, plans, checkpoints, external files,
credentials, web, services, product model calls, subagents, dependency installation,
security engineering or task closure.

## Authoring requirements (binding)

Author meaningful source-obligation tests FIRST and record RED evidence under the run dir,
then implement ChapterContractV2 plus dedicated Chinese ChapterSkillManifest for each node.
Preserve exact accepted source hash, node/bookmark/style IDs. No provider settings.
Reuse existing fact paths where meanings match. READ THE FULL SPEC; its key semantic demands:
- Efficacy/safety evaluation sections (ch9): endpoints must agree with objectives/estimand
  (batch2 bindings exist — reference, do not duplicate editable stores); assessment
  procedures typed with units/windows/reference events consistent with SoA (batch1 v2_n_1_3).
- AE/SAE/TEAE taxonomy (ch10): AE, SAE, TEAE, severity, seriousness, causality, expectedness
  are DISTINCT concepts with distinct typed facts; five-level causality assessment preserved
  (not collapsed to binary ADR judgment); investigator SAE reporting vs sponsor SUSAR
  reporting have different objects/clocks — separate obligations, no single number copied
  into both; pregnancy is not automatically an SAE nor automatic withdrawal from all
  follow-up; CTCAE version is project-bound (template v5 example is example-only); death,
  hospitalization, congenital anomaly etc. seriousness criteria typed per current definitions.
- Concomitant medications/procedures, alcohol/tobacco/other restrictions: typed with scope/
  timing/rationale bound to product risk and design, not blanket prohibitions.
- Clinical laboratory, vital signs, ECG and other assessments: units, reference ranges,
  windows, repeat/confirmation rules typed; template lab panels example-only.
- Biopsy/sampling/photography etc. special procedures where applicable: consent and
  handling consistent with withdrawal rules (batch4 v2_n_8_* semantics).
- Parent-body obligations (v2_n_9 body, v2_n_10 body, v2_n_10_1/2/3 area text) inherited
  into the appropriate leaf carriers with honest declared-addition markers — never dropped
  because they are not leaf headings, and no fabricated extra leaves.
- Independently required sources get separate EvidenceSourceRequirement groups (ANY-of
  inside a group); every group has context window + quality floor.
- Fixture ID convention: fixture:batch5:v2-n-9-1:positive style (batch1 hyphen format).
- Boolean trigger facts bare true/false; synthetic values conspicuous (【合成夹具】);
  negative failures must target their reason, not unrelated identity errors.
- Mandatory negative material (from the spec, read it fully for the exact list):
  severity/seriousness conflated; five-level causality collapsed to binary; single SAE
  reporting clock copied into investigator AND sponsor obligations; pregnancy auto-SAE or
  auto-withdrawal; CTCAE version hardcoded from template example; endpoint not traceable
  to objective/estimand; blanket restriction without design rationale; lab values without
  units/reference ranges; parent safety framing dropped.

Use existing assemble_registry for the exact batch slice (coverage_roles) — never glob or
count shared directories; batch-scope assertions only (selected batch exactly 19; other
batches' files appearing must never affect your tests). Closed vocabularies, nineteen
roles, at least four exercised families per node (positive, missing_claim OR
missing_control, wrong_source, skeleton; minimum 76) plus the spec's source-specific
negatives.

## Success Criteria

- Targeted checks cover exact 19 identities, source obligations, exercised fixtures,
  partial clean/incomplete status and full expected missing coverage.
- Report actual RED/GREEN evidence, changed files, limitations and next action.
  No full-project, clinical, visual or native Word acceptance claim.
- Existing venv only, no unrelated legacy whole-suite reruns:
  env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw
  TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8
  PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:.
  runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest
  tests/protocol_v3/test_chapter_batch5.py -q -p no:cacheprovider --tb=short
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
FILES_CREATED: list with counts (19 contracts / 19 skills / fixtures file / test file / diagnostics)
RED_EVIDENCE: path(s) of pre-implementation failing runs
GREEN_EVIDENCE: exact pytest command + tail summary line + XML path
FIXTURES: total count, per-family breakdown, source-specific negatives list
SEMANTIC_NOTES: AE/SAE/TEAE taxonomy typing, dual reporting clocks, five-level causality,
  pregnancy semantics, CTCAE project-binding, parent-body inheritance placement (node ids)
DEFERRED: obligations deliberately deferred with reasons
LIMITS_AND_NEXT: what remains for acceptance
