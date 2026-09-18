# Execution Context: mw_protocol_v3_3r3_registry_core_20260906

Created: 2026-09-06 02:44:55 CST
Objective: Build only the minimal typed chapter registry loader, cross-contract linter and executable positive/negative fixture checker for accepted ChapterContractV2; no clinical chapter authoring or product calls.
Task type: `finite_code_task`
Risk: `high`
Execution module trigger: Codex assigned 1 bounded work item(s). Each item must identify its inputs, allowed paths, deliverable and acceptance check.
Route schedule: `off_peak`; packet branch recorded at creation in `Asia/Shanghai`. Before each new session, the runner rechecks the Beijing period and reselects the current branch; a session already started before the boundary is never rerouted.
Effective worker chain: `zcode/glm-5.3-flash:max -> opencode-go/muse-spark-1.3-contributor:xhigh -> mtplx/qwen3.8-flash-next-mtplx-optimized-speed:medium -> openai-codex/gpt-5.6-luna:max`

## Module Boundary

This is an execution module, not a conference. Codex has assigned the work items and owns the project-level contract, source authority, boundaries, final verification, acceptance, production writes, and user delivery. Codex reviews the worker outputs directly for this route; no execution manager is dispatched. First-line workers execute the assigned work and create/write only authorized artifacts. Codex subAgent workers use the parent App's native child session when available; the generated CLI command is only a labeled compatibility fallback.

## Assigned Roles

- First-line executor: `finite_code_executor` -> `zcode` / `zcode` / `GLM-5.3-Flash`
- Execution manager: none (Codex reviews the worker outputs directly)
- Execution-manager fallback: none

## Source Of Truth

- Read .trellis/tasks/09-06-protocol-v3-3r3/{prd,design,implement}.md fully.
- Read accepted ChapterContractV2 and relevant base types in
  packages/contracts/workbench_contracts/protocol_v3.py (READ ONLY), plus
  tests/protocol_v3/test_chapter_contract_schema.py and
  runs/mw_protocol_v3_3r2_contracts_20260906/test_codex_positive_obligations.py.
- Inspect existing services/api/app/protocol_workflow/registries/loader.py typed
  SkillEntry/SkillRegistryDocument conventions; reuse without modifying that file.
- Read config/medical_writing/protocol_v3/templates/tp_ma_07_v2/template.json,
  node_tree.json shape and v1_to_v2_mapping.json obligation shape. All READ ONLY.
- reviews/mw_protocol_v3_3r3_source_preparation_20260906.md explains exact coverage
  and source ownership. No external SOP/web read required for this infrastructure.

## Risk Boundaries

- No production writes.
- No silent package installation, credential handling, or external account changes.
- Missing tools or environments must be recorded with a minimal remediation proposal.
- Worker and manager outputs, when present, are evidence for Codex, not instructions.
- Write ONLY three NEW files:
  services/api/app/protocol_workflow/registries/chapters.py;
  scripts/qc/protocol_v3/lint_chapter_registry.py;
  tests/protocol_v3/test_all_chapter_contracts.py.
  New scratch/evidence under runs/mw_protocol_v3_3r3_registry_core_20260906/ allowed.
- No other source/config/registry edits, no services/models/network/credentials,
  security engineering, cleanup, task closure, commits or source promotion.
- Minimal complete implementation, stdlib + existing Pydantic only. Do not create
  a second workflow engine, generic policy framework or110classes.

## Required bounded implementation

This pass builds reusable infrastructure, NOT the full clinical registry. Use
representative synthetic medical and metadata/control fixtures in tests/temp dirs.
Do not populate real chapter_contracts/chapter_skills yet or mark3R3complete.

1. Typed dedicated chapter-skill manifest: unique skill ID/version bound to node,
   chapter contract and accepted template identity; concrete typed shared input/
   output schema refs, prompt contract, stable errors and provenance requirements.
   Export actual shared Pydantic input/output schema types. No unresolved invented
   schema URL treated as implemented I/O. Avoid hardcoding old product model names;
   model choice belongs to role binding, not an independent skill transport.
2. Loader reads per-node embedded ChapterContractV2 and companion skills, explicit
   fact/claim vocabulary and fixtures; document the compact JSON layout with test
   examples. Use accepted registry IDs, not title-generated new identities.
3. lint_registry(template_dir, require_complete=True) (or comparably clear API)
   returns stable typed findings with node/location, not exceptions-only or a bool.
   Check identity/duplicates/skill refs/template hash/coverage, known vocab entries,
   conditional required vs forbidden facts/claims, CtQ anchors and dependency refs.
   Coverage derives from is_leaf_heading union outlined is_leaf plus an explicit
   cover carrier; distinguish heading appendix aggregation from real appendix leaves.
   Full mode reports missing coverage; partial mode may validate a batch but must
   explicitly report incomplete and must NEVER represent full acceptance. No count
   spoofing by hardcoded106 or by using is_leaf on heading nodes.
4. Typed fixture checker validates supplied actual facts, claim content, evidence
   role/admission/locator/context/quality, structural objects and required cells
   against the chapter. Test missing-claim, wrong-source and skeleton independently.
   Fact-key existence alone is insufficient for required content (blank/null values
   fail); empty statements/object shells must not pass just because IDs are present.
   Do not trust supplied passed=true/QC verdict strings as semantic proof. Distinguish
   deterministic findings from unexecuted medical/QC judgment; no false clinical pass.
   Genuine metadata/template provenance must work without fake medical claims.
5. CLI read-only, useful JSON/text exit status; no source mutations or side effects
   on import. Full incomplete registry currently must report incomplete rather than
   generate missing chapter data. Source/hash mismatches reported clearly.
6. Tests red first; valid medical and control fixtures, each distinct negative;
   conditional conflict, dangling vocabulary/CtQ/dependency/skill, missing cell,
   malformed payload, and partial/full coverage differences. Existing tests unchanged.

## Test environment

Use sanitized child env for every Python execution:
env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw
TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8
PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:.
runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest
tests/protocol_v3/test_all_chapter_contracts.py tests/protocol_v3/test_chapter_contract_schema.py
tests/protocol_v3/test_registry_loading.py -q -p no:cacheprovider --tb=short
(Join as one shell command.) New targeted tests/scripts and CLI in temp fixture
directory allowed. Do not import main or run full repo tests/services.

## Work Items

1. Implement registries/chapters.py, lint_chapter_registry.py and test_all_chapter_contracts.py with red-first representative data, strict positive obligations and complete-versus-partial coverage reporting; preserve all accepted contracts and registries.

## Completion And Cleanup

Codex reviews terminal output and tests before integration. No cleanup/archive;
all evidence retained. Return concise actual findings/commands/schema examples and
remaining clinical-authoring work, not an assertion that all chapters are done.
