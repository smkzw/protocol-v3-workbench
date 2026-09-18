# Task Context: mw_protocol_v3_3r3_batch2_fresh_review_20260911

Created: 2026-09-11 22:05:00 (ZCode takeover dispatch)
Objective: Independent fresh-context acceptance review of the batch2 chapter contract/skill/
fixture delivery (16 carriers: background/objective/estimand). Rule semantic correctness
against the source spec; list exact defects. READ-ONLY review.
Task type: code_open_audit (single fresh reviewer, verifier isolation)
Risk: high
Selected agent route: `zcode` / `GLM-5.3-Flash` / `max` (non-deepseek family; the artifact
under review was produced by codebuddy/deepseek-v4.1-flash)

## Why this review exists

The batch2 resume worker delivered 16 contracts + 16 skills + batch2.json (77 fixtures) +
test_chapter_batch2.py (38 tests). Main owner verified: combined suite 68 passed
(runs/mw_protocol_v3_3r3_batch2_resume_20260911/main_owner_combined_batches12_20260911.xml),
independent assembly byte-identical to the worker's
(main_owner_assembled_batch2.json), partial lint exit 0 (16 covered / 111 expected,
486 deferred obligations). Tests and structure verified ≠ semantic correctness: you rule
the content against the source spec.

## Source of truth (read-only inputs, paths relative to repo root)

Primary review targets:
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/v2_n_2_*.json,
  v2_n_3_*.json (16 files; exactly: v2_n_2_1, v2_n_2_2_1, v2_n_2_2_2_1, v2_n_2_2_3,
  v2_n_2_3, v2_n_3_1_1, v2_n_3_1_2_1, v2_n_3_1_2_2, v2_n_3_1_2_3, v2_n_3_1_2_4, v2_n_3_2_1,
  v2_n_3_2_2, v2_n_3_3_1, v2_n_3_3_2, v2_n_3_4_1, v2_n_3_4_2)
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_skills/ (same 16 ids)
- tests/fixtures/protocol_v3/chapter_content_v2/batch2.json
- tests/protocol_v3/test_chapter_batch2.py

Authoritative source obligations:
- reviews/mw_protocol_v3_3r3_batch2_content_spec_20260906.md (FULL — the spec the worker
  was bound to)
- context/mw_protocol_v3_3r3_batch2_resume_20260911_context.md (the dispatch contract:
  authoring requirements list is binding)
- reviews/mw_protocol_v3_3r3_batch_coverage_reconciliation_20260906.md

References for conventions and prior accepted patterns:
- runs/mw_protocol_v3_3r3_batch1_repair_20260908/assembled_batch1_registry.json (accepted
  batch1 structure/vocabulary; batch2 should be consistent with it, never copy content)
- reviews/mw_protocol_v3_3r3_batch1_repair_acceptance_20260911.md (what batch1 acceptance
  covered; batch2 must not weaken anything it relies on)
- packages/contracts/workbench_contracts/protocol_v3.py, and
  services/api/app/protocol_workflow/registries/chapters.py (schema/checker semantics)
- Worker report: runs/mw_protocol_v3_3r3_batch2_resume_20260911/report_codebuddy_batch2_resume.md

## Review checklist (rule each; cite file+field evidence)

B1 Sixteen exact identities, template id/sha256, contract<->skill binding, no provider/
   model fields in skills; coverage roles correct per reconciliation doc.
B2 Estimand semantics (the batch's highest-risk content):
   - fifth attribute population-level summary measure lives ONLY in v2_n_3_1_2_4
     (estimand.primary.population_summary_measure or equivalent distinct path); no
     invented fifth heading/carrier; NOT modeled as an ICE;
   - picos.population_summary kept as population description only, never required as
     estimand summary measure; no vocabulary collision;
   - ICE handling: empty-ICE negative actually fails for the intended reason.
B3 Unheaded source content preserved with honest provenance: toxicology, PK, general
   pharmacology (v2_n_2_2_2_1 area), own-product clinical evidence within the
   competitor-titled area (body299) — competitor evidence can NEVER satisfy own-product
   clinical claims (check the evidence groups in v2_n_2_2_3); inherited mechanism (284)
   declared as inherited addition.
B4 Evidence groups: independently required sources in SEPARATE groups; group = ANY-one-of;
   no mega-group; every group has context window + quality floor; wrong_source negatives
   degrade only their targeted group.
B5 Source examples not hardcoded as project facts (headings 316-319 examples, 306/324
   wording, template placeholders); synthetic fixture values conspicuous.
B6 Fixtures: 77 total; every node ≥4 families; the 13 source-specific negatives present
   and each fails for its INTENDED reason (not unrelated identity errors); fixture ID
   convention matches batch1 hyphen format.
B7 Tests: 38 tests assert batch-scoped obligations (16 exact, no global directory
   equality assertions that later batches would break); RED evidence plausibly pre-dates
   implementation (check XML timestamps/content); no weakened assertion vs spec; the
   worker's r1→final assertion change (finding.message vs finding.location) preserved the
   semantic target.
B8 Deferred honesty: no claim of medical judgment, admitted provenance, conditional
   execution, or Word acceptance anywhere in the delivered files.

## Hard boundaries

- READ-ONLY: create/modify/delete NOTHING, including __pycache__ (set
  PYTHONDONTWRITEBYTECODE=1 if you run python). You may run the exact pytest command below
  (it writes no files with -p no:cacheprovider):
  env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw
  TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8
  PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:.
  runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest
  tests/protocol_v3/test_chapter_batch2.py -q -p no:cacheprovider --tb=short
- No web, credentials, services, product model calls, subagents.
- Challenge, do not repair. Verdict only; the main owner owns acceptance and any repair.

## Output schema (your FINAL message, plain text, no file writes)

VERDICT: ACCEPT | ACCEPT_WITH_ACTIONS | REJECT
FINDINGS: [B1..B8 each] PASS | FAIL | PARTIAL — one-line evidence (file + field/test)
DEFECTS: numbered; file, exact location, violated item, minimal correct repair (empty if none)
TESTS_RUN: what you executed + result (or "relied on provided evidence")
RESIDUAL_RISK: what you could not verify and why
