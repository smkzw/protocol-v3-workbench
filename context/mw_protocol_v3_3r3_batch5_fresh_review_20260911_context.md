# Task Context: mw_protocol_v3_3r3_batch5_fresh_review_20260911

Created: 2026-09-11 22:22:00 (ZCode takeover dispatch)
Objective: Independent fresh-context acceptance review of the batch5 chapter contract/skill/
fixture delivery (19 carriers: efficacy evaluation + safety, chapters 9-10). Rule semantic
correctness against the source spec; list exact defects. READ-ONLY review.
Task type: code_open_audit (single fresh reviewer, verifier isolation)
Risk: high
Selected agent route: `zcode` / `GLM-5.3-Flash` / `max` (non-deepseek family; the artifact
under review was produced by codebuddy/deepseek-v4.1-flash)

## Why this review exists

The batch5 worker delivered 19 contracts + 19 skills + batch5.json (113 fixtures) +
test_chapter_batch5.py (41 tests). Main owner verified: combined batch1-5 suite 158 passed
(runs/mw_protocol_v3_3r3_batch5_20260911/main_owner_combined_1to5_20260911.xml), independent
assembly OK (19 chapters / 113 fixtures), out-of-scope audit clean. You rule semantics.

## Source of truth (read-only inputs, paths relative to repo root)

Primary review targets:
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/v2_n_9_*.json,
  v2_n_10_*.json (19 files; exact ids in the dispatch context)
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_skills/ (same 19 ids)
- tests/fixtures/protocol_v3/chapter_content_v2/batch5.json
- tests/protocol_v3/test_chapter_batch5.py

Authoritative source obligations:
- reviews/mw_protocol_v3_3r3_batch5_content_spec_20260906.md (FULL — the binding spec)
- context/mw_protocol_v3_3r3_batch5_20260911_context.md (dispatch contract; its Authoring
  requirements list is binding, including the mandatory negative list)
- reviews/mw_protocol_v3_3r3_batch_coverage_reconciliation_20260906.md

References for conventions:
- runs/mw_protocol_v3_3r3_batch1_repair_20260908/assembled_batch1_registry.json (accepted
  batch1 structure/vocabulary; fixture-ID convention)
- reviews/mw_protocol_v3_3r3_batch2_acceptance_20260911.md and
  reviews/mw_protocol_v3_3r3_batch4_acceptance_20260912.md (accepted patterns; note batch4
  D1 precedent: word_rules styles/bookmarks MUST be populated from node_tree, not empty)
- packages/contracts/workbench_contracts/protocol_v3.py and
  services/api/app/protocol_workflow/registries/chapters.py (schema/checker semantics)
- Worker report: runs/mw_protocol_v3_3r3_batch5_20260911/report_codebuddy_batch5.md

## Review checklist (rule each; cite file+field evidence)

E1 Nineteen exact identities, template id/sha256, style/bookmark matches vs node_tree.json
   (batch4 D1 precedent: word_rules must NOT be empty), contract<->skill binding, no
   provider/model fields; coverage roles correct.
E2 AE/SAE/TEAE taxonomy (the batch's highest-risk content): AE definition/collection
   interval/TEAE derivation distinct; severity vs seriousness distinct typed facts and
   scales; SUSAR != SAE; expectedness != causality; five-level causality NOT collapsed to
   binary; AE-collection != TEAE; corresponding negatives fail for their named reasons.
E3 Dual reporting clocks: investigator SAE reporting (recipient/clock/first-awareness/
   record) is a DIFFERENT typed object from sponsor SUSAR clocks (incl. separate follow-up
   clock); no single number copied into both; signed-form-day-zero and
   report-time-by-convenience forbidden with negatives.
E4 Pregnancy: not automatically SAE, not automatic withdrawal from all follow-up; both
   negatives present. CTCAE version project-bound (template v5 example-only); AESI list
   not copied from template.
E5 Efficacy evaluation (ch9): endpoints traceable to objectives/estimand (reference batch2
   namespaces declaratively, no duplicate editable stores); assessment procedures typed
   with units/windows consistent with SoA semantics (batch1 v2_n_1_3); PK endpoints linked;
   IRC distinct from safety committee.
E6 Parent-body inheritance: v2_n_9, v2_n_10, v2_n_10_1/2/3 area text inherited into
   appropriate leaf carriers with honest declared-addition markers; parent-safety-framing-
   dropped negative fails.
E7 Evidence groups: independently required sources SEPARATE groups; group = ANY-one-of; no
   mega-group; context window + quality floor; wrong_source negatives degrade only their
   targeted group; comparator evidence cannot satisfy own-safety claims (negative present).
E8 Fixtures/tests: 113 fixtures; every node ≥4 families; hyphen ID convention; bare
   true/false triggers; conspicuous synthetic markers; 34 source-specific negatives each
   failing for its INTENDED reason with exact codes asserted (batch4 D2 precedent: no
   vacuous assertion like "x or y" where y is a substring of x); 41 tests batch-scoped
   (no global directory equality); RED precedes implementation; deferred honesty.

## Hard boundaries

- READ-ONLY: create/modify/delete NOTHING (PYTHONDONTWRITEBYTECODE=1 for any python;
  authorized pytest command writes no files with -p no:cacheprovider). Your final message
  IS the report; do not write any report file.
- batch6 mutable files (v2_n_11_* contracts/skills, batch6.json, test_chapter_batch6.py)
  are being written RIGHT NOW by a concurrent worker — do NOT read them.
- Authorized pytest command:
  env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw
  TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8
  PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:.
  runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest
  tests/protocol_v3/test_chapter_batch5.py -q -p no:cacheprovider --tb=short
- No web, credentials, services, product model calls, subagents.
- Challenge, do not repair. Verdict only.

## Output schema (your FINAL message, plain text, no file writes)

VERDICT: ACCEPT | ACCEPT_WITH_ACTIONS | REJECT
FINDINGS: [E1..E8 each] PASS | FAIL | PARTIAL — one-line evidence (file + field/test)
DEFECTS: numbered; file, exact location, violated item, minimal correct repair (empty if none)
TESTS_RUN: what you executed + result (or "relied on provided evidence")
RESIDUAL_RISK: what you could not verify and why
