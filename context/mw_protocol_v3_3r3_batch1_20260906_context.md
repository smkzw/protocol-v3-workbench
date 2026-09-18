# Task Context: mw_protocol_v3_3r3_batch1_20260906

Created: 2026-09-06 03:38:51
Objective: Implement source-bound batch1 chapter contracts, skills and exercised fixtures for the accepted TP-MA-07 v2 candidate registry; no runtime activation or clinical acceptance.
Task type: `finite_code_task`
Risk: `high`
Selected agent route: `zcode` / `GLM-5.3-Flash` / `max`

## Trigger Reason

Bounded data-contract implementation provides context relief for twelve distinct
front/summary carriers; Codex owns clinical source interpretation and acceptance.

## Source Of Truth

Read the following additional files fully as authorized task inputs:
- reviews/mw_protocol_v3_3r3_batch1_content_spec_20260906.md
- reviews/mw_protocol_v3_3r3_source_preparation_20260906.md
- .trellis/tasks/09-06-protocol-v3-3r3/{prd,design,implement}.md
- packages/contracts/workbench_contracts/protocol_v3.py (v2 schema and related types)
- services/api/app/protocol_workflow/registries/chapters.py
- scripts/qc/protocol_v3/lint_chapter_registry.py
- tests/protocol_v3/test_all_chapter_contracts.py
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/{template,node_tree,v1_to_v2_mapping}.json
Existing files above are read-only. Accepted core has 96 focused tests passing
and same-session independent round2 ACCEPT; medical judgment is not evaluated.
No web research, credentials, external SOP access, services or product calls.

## Scope

Explicit EDIT authorization, exclusively NEW paths below:
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/<node_id>.json
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_skills/<node_id>.json
- tests/fixtures/protocol_v3/chapter_content_v2/batch1.json
- scripts/qc/protocol_v3/assemble_chapter_registry.py
- tests/protocol_v3/test_chapter_batch1.py
- runs/mw_protocol_v3_3r3_batch1_20260906/ (new diagnostic evidence only)
Only twelve node IDs: v2_front_block; v2_n_front_1 through v2_n_front_8;
v2_n_1_1, v2_n_1_2, v2_n_1_3. Use node IDs as filenames, semantic IDs within
contract per accepted mapping. No other batch, runtime activation, schema/core
modification, plan/status close, or existing fixture/test edits.

Author dedicated embedded ChapterContractV2 and companion ChapterSkillManifest
for each node, grounded in the batch1 obligations. Preserve exact existing Word
style/bookmark IDs and source hash. Every positive requirement must be substantive,
not a chapter-title-plus-one-generic-fact shortcut. Include all summary row and
SOA/diagram controls, correct metadata provenance, intentional unsigned signature
controls, actual revision/abbreviation/index behavior. Do not hardcode clinical
examples or pretend fixture receipts are real project approval. Skill prompts are
node-specific Chinese content instructions with typed I/O and explicit obligations,
not model/provider settings. Template/source locators belong in prompt provenance
requirements; no extra fields unsupported by the accepted schema.

Batch fixture document must carry explicit fact/claim vocabularies and one positive,
missing_claim OR missing_control, wrong_source, skeleton per node (48 minimum).
Use conspicuously synthetic project examples. Each negative actually mutates the
named obligation and fails for its named reason, not unrelated identity errors.
Chapter JSON files remain the single authored contracts; do not duplicate them
manually in fixtures. Add a small stdlib assembly CLI/helper reading these files
and fixture/vocabulary documents to produce the accepted ChapterRegistryDocument
shape (entries with coverage_role, contract and skill). No new engine/abstraction.
Use library model validation and read-only linter. Output assembly to stdout; no
hidden writes, activation or promotion. Later batches reuse this same assembly.
Author batch-scoped source-obligation assertions first, observe failure before
implementing. Include file/skill identity, table cell obligation, all twelve IDs,
48 exercised families, partial lint clean but status incomplete, full lint failing
remaining coverage. Keep medical and native Word checks explicitly deferred.

## Success Criteria

- Targeted tests pass using existing isolated venv; four fixture families/node
  genuinely exercise their purpose. Partial registry is never full acceptance.
- All writes stay within named paths; no dependency installation or test dilution.
- Return exact checks, gaps, read sources and changed files; do not close task.

Test environment: runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python;
env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw
LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
PYTHONPATH=tests/protocol_v3:services/api:packages:. Use pytest -q -p no:cacheprovider.
No app.main import or live runtime. Manual source edits via apply_patch.

## Risk Boundaries

- Do not write to production paths until Codex review gate passes and writable paths are explicit.
- The delegated agent is not final authority; Codex owns verification and acceptance.

## Timeout Policy

- Do not mark the delegated agent failed for slow response alone.
- For complex or artifact-heavy work, wait and poll generously; use conference mode when multiple independent model perspectives are needed.
- Failure requires terminal error, provider exhaustion/rate limit after controlled retry, empty/truncated retry output, or no progress after hard wait plus one retry.
- A provider catalog/auth/transport preflight is diagnostic, not a live capability verdict: timeout, auth refresh failure, malformed output, or a stale/incomplete catalog must be recorded and followed by one real route attempt. Explicit user-selected routes are not blocked merely because the catalog does not list them; only a missing executable or native transport boundary may stop before that attempt.

## Loop Log

- 2026-09-06 03:38:51: Task initialized by `tools/hermes_workflow_guard.py init-task`.
