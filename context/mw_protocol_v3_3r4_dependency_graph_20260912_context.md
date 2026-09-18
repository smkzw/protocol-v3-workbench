# Task Context: mw_protocol_v3_3r4_dependency_graph_20260912

Created: 2026-09-11 23:18:00 (ZCode takeover dispatch; first 3R.4 execution)
Objective: Implement the registry-level typed dependency/impact graph over the accepted
111-carrier chapter registry, with deterministic impact computation and the prep doc's
binding test list. No product runtime/API changes; no registry content changes.
Task type: `finite_code_task`
Risk: `high`
Selected agent route: `codebuddy` / `deepseek-v4.1-flash` / `max`

## Source Of Truth

Read-only inputs:
- reviews/mw_protocol_v3_3r4_dependency_preparation_20260906.md (FULL — BINDING,
  including its deterministic test list)
- packages/contracts/workbench_contracts/protocol_v3.py (ChapterContractV2 dependency
  fields, repair ownership; DO NOT EDIT)
- services/api/app/protocol_workflow/registries/chapters.py (loader/checker; DO NOT EDIT)
- services/api/app/protocol_workflow/registries/loader.py
- scripts/qc/protocol_v3/assemble_chapter_registry.py (batch assembly; DO NOT EDIT)
- runs/mw_protocol_v3_3r3_batch8_fresh_20260911/final_all8_assembled.json (the accepted
  111-carrier assembled registry — your graph's input fixture; read-only)
- tests/protocol_v3/test_chapter_batch1.py (test style reference)
- .trellis/tasks/09-11-protocol-v3-3r4/checkpoint.md

## Scope

Explicit EDIT authorization exclusively for NEW files:
- services/api/app/protocol_workflow/registries/dependency_graph.py (or
  dependencies.py — one module, stdlib-only, no new deps)
- tests/protocol_v3/test_dependency_graph.py
- runs/mw_protocol_v3_3r4_20260912/ (NEW diagnostics only)
No other files. Do NOT edit contracts/skills/batch JSONs, core schema, loader/checker,
assembler/lint, plans, checkpoints. No web, credentials, services, product model calls,
subagents, dependency installation, security engineering or task closure.

## Requirements (binding; from the prep doc, read it in full)

1. THREE relationship kinds, explicitly typed and kept distinct:
   - fact_membership: chapter declares fact paths (already in contracts; your module
     indexes them, including CONDITIONAL fact paths from conditional_applicability_rules
     — resolve conditional dependencies too, not only unconditionally-required ones);
   - scheduling: ONLY hard/order edges admitted into the DAG (from explicit
     dependency_ids where contracts declare them; DO NOT infer that every
     cross-reference is a scheduling edge);
   - consistency_impact: reciprocal clinical relationships (summary/body, SoA/
     assessments, endpoint/estimand/statistics, dose/design/population — derive from
     shared fact membership) evaluated WITHOUT creating artificial scheduling cycles.
2. Registry-level edge representation: a small explicit typed-edge structure; carry
   actual contract IDs and repair owners from the accepted registry; missing owner or
   unknown edge target is an identified error, never silently dropped.
3. Impact computation: given changed material facts, return EVERY affected chapter
   without truncation (transitive over consistency edges, respecting scheduling DAG);
   high-fan-out changes (dose/endpoint) return the complete set. Project-confirmation
   invalidation uses the changed material facts, not blanket reopen-all.
4. CAS semantics: same fact update has a single adoption effect under the existing
   CAS ledger concept — your module must be a pure function of (registry, changed
   facts) and declare this; no second editable store; graph rendering is a projection,
   not a new authority.
5. Binding deterministic tests (from prep doc):
   - hard scheduling cycle rejected;
   - reciprocal consistency links legal (no false cycle);
   - missing owner / unknown edge identified;
   - unrelated chapters remain stable;
   - broad dose/endpoint changes return every affected chapter without truncation;
   - same fact update has a single adoption effect.
   Author these tests FIRST (RED), then implement.
6. Work against the accepted assembled registry file as input; support loading via
   the existing load_chapter_registry. Keep it offline/deterministic.

## Success Criteria

- RED evidence before implementation; GREEN: full focused suite passing.
  env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw
  TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8
  PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:.
  runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest
  tests/protocol_v3/test_dependency_graph.py -q -p no:cacheprovider --tb=short
- Also run the batch1 suite unchanged to prove no regression:
  same env, tests/protocol_v3/test_chapter_batch1.py
- No claim of end-to-end document-edit pipeline (that integration remains 6R);
  no medical adequacy claim.

## Risk Boundaries

- You own exactly the NEW module + NEW test file. The dispatching ZCode main owner owns
  acceptance; a fresh independent reviewer will challenge your delivery.

## Timeout Policy

- Work continuously; failure only on terminal error / provider exhaustion / empty output.

## Output schema (your FINAL message, plain text)

STATUS: COMPLETED | PARTIAL | FAILED
FILES_CREATED: list
RED_EVIDENCE: path(s)
GREEN_EVIDENCE: command + tail + XML path
DESIGN_NOTES: edge typing decisions, conditional-fact resolution approach, impact
  algorithm (brief), CAS-purity declaration
TESTS: list of the six binding deterministic tests + any extras
DEFERRED: what is deliberately out of scope
LIMITS_AND_NEXT: for the reviewer and main owner
