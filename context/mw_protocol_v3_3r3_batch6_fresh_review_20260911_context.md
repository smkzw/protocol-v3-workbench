# Task Context: mw_protocol_v3_3r3_batch6_fresh_review_20260911

Created: 2026-09-11 22:40:00 (ZCode takeover dispatch)
Objective: Independent fresh-context acceptance review of the batch6 chapter contract/skill/
fixture delivery (13 carriers: statistics, section 11). Rule semantic correctness against
the source spec; list exact defects. READ-ONLY review.
Task type: code_open_audit (single fresh reviewer, verifier isolation)
Risk: high
Selected agent route: `codebuddy` / `deepseek-v4-flash` / `max` (non-OpenAI family; the
artifact under review was produced by pi/openai-codex/gpt-5.6-luna)

## Why this review exists

The batch6 worker delivered 13 contracts + 13 skills + batch6.json (61 fixtures) +
test_chapter_batch6.py (8 tests). Main owner verified: combined batch1-6 suite 166 passed
(runs/mw_protocol_v3_3r3_batch6_20260911/main_owner_combined_1to6_20260911.xml), independent
assembly OK (13 chapters / 61 fixtures), core untouched. You rule semantics. NOTE: 8 tests
is the smallest suite of the six batches — scrutinize whether the 8 tests genuinely cover
the batch's obligations or leave material gaps; and the first RED XML is a collection error
(test file absent), the second RED (red_contracts_missing.xml) is the substantive one.

## Source of truth (read-only inputs, paths relative to repo root)

Primary review targets:
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/v2_n_11_*.json
  (13 files: v2_n_11_1..3, v2_n_11_4_1..2, v2_n_11_4_3_1..2, v2_n_11_4_4..9)
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_skills/ (same 13 ids)
- tests/fixtures/protocol_v3/chapter_content_v2/batch6.json
- tests/protocol_v3/test_chapter_batch6.py

Authoritative source obligations:
- reviews/mw_protocol_v3_3r3_batch6_content_spec_20260906.md (FULL — the binding spec)
- context/mw_protocol_v3_3r3_batch6_20260911_context.md (dispatch contract; its Authoring
  requirements list is binding, including the mandatory negative list)
- reviews/mw_protocol_v3_3r3_batch_coverage_reconciliation_20260906.md (PK/PD/ER
  inheritance carrier mandate: v2_n_11_4_6 exploratory; confirmatory links main/secondary)

References for conventions:
- runs/mw_protocol_v3_3r3_batch1_repair_20260908/assembled_batch1_registry.json (accepted
  batch1 structure/vocabulary; fixture-ID convention)
- reviews/mw_protocol_v3_3r3_batch2_acceptance_20260911.md,
  reviews/mw_protocol_v3_3r3_batch3_acceptance_20260911.md,
  reviews/mw_protocol_v3_3r3_batch4_acceptance_20260912.md (accepted patterns and
  precedents: word_rules populated from node_tree; per-negative expected codes; ownership
  declarations for new fact roots; conditional rules at CONTRACT level with schema field
  names conditional_applicability_rule_id/triggering_fact_paths/condition/rationale/
  required_when_active_fact_paths)
- packages/contracts/workbench_contracts/protocol_v3.py and
  services/api/app/protocol_workflow/registries/chapters.py (schema/checker semantics)
- Worker report: runs/mw_protocol_v3_3r3_batch6_20260911/report_omp_batch6.md

## Review checklist (rule each; cite file+field evidence)

F1 Thirteen exact identities, template id/sha256, style/bookmark populated from node_tree
  (batch4 D1 precedent — NEVER empty), contract<->skill binding, no provider/model fields,
  coverage roles correct.
F2 Sample size (v2_n_11_1): typed endpoint/hypotheses/test-model/sidedness+alpha/power/
  assumptions+evidence/allocation+attrition/method+software/reproducible-result; interim
  adjustments and design effects conditional; assumptions aligned to estimand (competitor's
  N insufficient); high-risk decision obligations with evidence floor, no default N/formula;
  shared fact-path reuse (picos.primary_endpoint, framing.structured_design.*) without
  duplicate editable stores; 4 negatives (wrong-assumed-effect, N-without-inputs,
  missing-sidedness, missing-allocation) fail for their named reasons.
F3 Analysis sets (v2_n_11_2, 4_3_1): randomized/treated/available NOT interchangeable;
  inclusion/grouping/handling typed; rescue-treated not discarded without estimand-
  consistent justification; ANCOVA/MMRM/tipping-point preserved as method obligations in
  correct carriers, not universal; SAS example-only; sensitivity addresses intended
  assumption (placeholder-sensitivity-table negative); mislabeled-analysis-set negative.
F4 SAP vs protocol (v2_n_11_3): SAP status/timing/revision/unblinding typed; promised-later
  SAP does NOT waive protocol-level endpoint/estimand/primary-method/sample-size obligations
  (explicit preservation obligations present).
F5 Multiplicity (v2_n_11_4_8): actual confirmatory family, ordering, allocation,
  dependencies, procedure, applicability disposition; named-method-without-family negative;
  no-adjustment requires real disposition.
F6 Interim/alpha (v2_n_11_4_9): timing/information fraction/purpose/rules/decision
  responsibility/final-analysis impact; safety review does not auto-consume efficacy alpha;
  IDMC vs endpoint IRC distinct; stale source reference 14.6 resolved to canonical target;
  interim-timing-alpha-mismatch negative.
F7 PK/PD/ER inheritance (v2_n_11_4_6): carries inherited v2_n_11_4 obligations with honest
  declared-addition markers (source @783); exploratory stays exploratory; confirmatory
  links primary/secondary analysis contracts, never relabeled exploratory.
F8 Fixtures/tests quality: 61 fixtures; every node ≥4 families; hyphen ID convention; bare
  booleans; conspicuous synthetics; 9 source-specific negatives with exact failure reasons;
  8 tests — do they cover identities, obligations, families, partial/incomplete lint, batch
  scope, coexistence with later batches? List any MATERIAL coverage gap (test count alone is
  not a defect if coverage is genuine); RED evidence plausibility (two-stage); deferred
  honesty; ownership declarations for any new fact roots; conditional rules at contract
  level with schema field names.

## Hard boundaries

- READ-ONLY: create/modify/delete NOTHING. You may run the authorized pytest command
  (writes no files with -p no:cacheprovider):
  env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw
  TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8
  PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:.
  runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest
  tests/protocol_v3/test_chapter_batch6.py -q -p no:cacheprovider --tb=short
  (If Bash is denied in your mode, say so in TESTS_RUN and rely on the provided XMLs.)
- batch7 mutable files (v2_n_12_*/v2_n_13_* contracts/skills, batch7.json,
  test_chapter_batch7.py) are being written RIGHT NOW — do NOT read them.
- No web, credentials, services, product model calls, subagents.
- Challenge, do not repair. Verdict only.

## Output schema (your FINAL message, plain text, no file writes)

VERDICT: ACCEPT | ACCEPT_WITH_ACTIONS | REJECT
FINDINGS: [F1..F8 each] PASS | FAIL | PARTIAL — one-line evidence (file + field/test)
DEFECTS: numbered; file, exact location, violated item, minimal correct repair (empty if none)
TESTS_RUN: what you executed + result (or "relied on provided evidence")
RESIDUAL_RISK: what you could not verify and why
