# Task Context: mw_protocol_v3_3r4_fresh_review_20260912

Created: 2026-09-11 23:35:00 (ZCode takeover dispatch)
Objective: Independent fresh-context acceptance review of the 3R.4 first deliverable:
the registry-level typed dependency/impact graph. Rule semantic correctness against the
binding prep doc; list exact defects. READ-ONLY review.
Task type: code_open_audit (single fresh reviewer, verifier isolation)
Risk: high
Selected agent route: `zcode` / `GLM-5.3-Flash` / `max` (non-deepseek family; the artifact
was produced by codebuddy/deepseek-v4.1-flash)

## Why this review exists

Worker delivered services/api/app/protocol_workflow/registries/dependency_graph.py (664
lines) + tests/protocol_v3/test_dependency_graph.py (734 lines, 10 tests). Main owner
verified: combined suite 217 passed (207 batch tests + 10 new;
runs/mw_protocol_v3_3r4_20260912/main_owner_combined_with_depgraph.xml); worker's own
adjacent regression 117 passed; core/registry files untouched. You rule the design and
semantics.

## Source of truth (read-only inputs)

Primary review targets:
- services/api/app/protocol_workflow/registries/dependency_graph.py
- tests/protocol_v3/test_dependency_graph.py

Binding requirements:
- reviews/mw_protocol_v3_3r4_dependency_preparation_20260906.md (FULL — BINDING, esp. the
  "Keep three relationships distinct" section and the deterministic test list)
- context/mw_protocol_v3_3r4_dependency_graph_20260912_context.md (dispatch contract)
- Worker report: runs/mw_protocol_v3_3r4_20260912/report_codebuddy_3r4_depgraph.md

Reference semantics:
- packages/contracts/workbench_contracts/protocol_v3.py (dependency_ids, conditional
  rules, repair ownership fields)
- services/api/app/protocol_workflow/registries/chapters.py (loader)
- runs/mw_protocol_v3_3r3_batch8_fresh_20260911/final_all8_assembled.json (the accepted
  111-carrier registry input)

## Review checklist (rule each; cite line-level evidence)

K1 Three relationship kinds genuinely distinct: FactMembership / SchedulingEdge /
   ConsistencyEdge typed separately; ONLY scheduling enters the DAG; scheduling edges
   come EXCLUSIVELY from explicit dependency_ids (no shared-fact or cross-reference
   promoted); test asserts the edge set equals the raw declared pairs.
K2 Conditional-fact resolution: BOTH conditional_applicability_rules fields (triggering
   + when-active) indexed; conditional-only paths reachable; obligation semantics
   (required/optional/forbidden) carried; no unconditional-only blind spot.
K3 Consistency edges: canonical left<right, reciprocal, shared_fact_paths; derived from
   shared fact membership; NO artificial scheduling cycle (reciprocal links legal);
   hard scheduling cycle still REJECTED.
K4 Impact computation: transitive closure over consistency edges + scheduling DAG;
   high-fan-out (dose/endpoint) returns the COMPLETE affected set without truncation;
   unrelated chapters stable; changed-material-facts basis (no blanket reopen-all).
K5 CAS purity: module is a pure function of (registry, changed facts); no second
   editable store; single adoption effect for the same fact update; graph is a
   projection, not a new authority (no mutation of inputs).
K6 Six binding deterministic tests present and genuinely binding (not weakened):
   hard cycle rejected; reciprocal legal; missing owner/unknown edge identified;
   unrelated stable; broad change complete set; single adoption. RED evidence real
   (module-not-found collection error precedes implementation); the worker's two
   RED-phase corrections (expectation order; probe switch to intervention.dose_regimen
   with exact ==31) — verify these did not weaken the binding tests.
K7 Engineering hygiene: stdlib-only; only imports chapters.load_chapter_registry /
   ChapterRegistryDocument; no writes; no runtime/service/medical claims; 664-line
   module is coherent (no dead code masses, no speculative config); diagnostics honest.
K8 Regression: batch suites unaffected (main owner's 217-pass is provided evidence;
   run the focused suite yourself if Bash available).

## Hard boundaries

- READ-ONLY: create/modify/delete NOTHING. Authorized pytest command (no files written
  with -p no:cacheprovider):
  env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw
  TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8
  PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:.
  runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest
  tests/protocol_v3/test_dependency_graph.py -q -p no:cacheprovider --tb=short
- No web, credentials, services, product model calls, subagents.
- Challenge, do not repair. Verdict only.

## Output schema (your FINAL message, plain text, no file writes)

VERDICT: ACCEPT | ACCEPT_WITH_ACTIONS | REJECT
FINDINGS: [K1..K8 each] PASS | FAIL | PARTIAL — one-line evidence (file + line/test)
DEFECTS: numbered; file, location, violated item, minimal correct repair (empty if none)
TESTS_RUN: what you executed + result (or "relied on provided evidence")
RESIDUAL_RISK: what you could not verify and why
