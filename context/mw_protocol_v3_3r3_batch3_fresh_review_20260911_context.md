# Task Context: mw_protocol_v3_3r3_batch3_fresh_review_20260911

Created: 2026-09-11 23:30:00 (ZCode takeover dispatch)
Objective: Independent fresh-context acceptance review of the batch3 chapter contract/skill/
fixture delivery (10 carriers: study design + population, chapters 4-5). Rule semantic
correctness against the source spec; list exact defects. READ-ONLY review.
Task type: code_open_audit (single fresh reviewer, verifier isolation)
Risk: high
Selected agent route: `grok` / `grok-build` / `grok-4.6` / high-per-probe
(non-OpenAI family; the artifact under review was produced by pi/openai-codex/gpt-5.6-luna)

## Why this review exists

The batch3 worker delivered 10 contracts + 10 skills + batch3.json (48 fixtures) +
test_chapter_batch3.py (20 tests). Main owner verified: combined suite 117 passed
(runs/mw_protocol_v3_3r3_batch3_20260911/main_owner_combined_1234_20260911.xml = batch1 17 +
batch2 38 + batch3 20 + batch4 29 + codex counterexamples 13), independent assembly OK
(10 chapters / 48 fixtures), out-of-scope audit clean. You rule semantic correctness.

## Source of truth (read-only inputs, paths relative to repo root)

Primary review targets:
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/v2_n_4_1..5.json,
  v2_n_5_1..5.json (10 files)
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_skills/ (same 10 ids)
- tests/fixtures/protocol_v3/chapter_content_v2/batch3.json
- tests/protocol_v3/test_chapter_batch3.py

Authoritative source obligations:
- reviews/mw_protocol_v3_3r3_batch3_content_spec_20260906.md (FULL — the binding spec,
  including its "Exact carrier and shared-fact bindings (Sep8 recheck)" tail section)
- context/mw_protocol_v3_3r3_batch3_20260911_context.md (dispatch contract; its Authoring
  requirements list is binding, including the mandatory negative list)
- reviews/mw_protocol_v3_3r3_batch_coverage_reconciliation_20260906.md

References for conventions:
- runs/mw_protocol_v3_3r3_batch1_repair_20260908/assembled_batch1_registry.json (accepted
  batch1 structure/vocabulary; fixture-ID convention)
- reviews/mw_protocol_v3_3r3_batch1_repair_acceptance_20260911.md and
  reviews/mw_protocol_v3_3r3_batch2_acceptance_20260911.md (accepted patterns)
- packages/contracts/workbench_contracts/protocol_v3.py and
  services/api/app/protocol_workflow/registries/chapters.py (schema/checker semantics)
- Worker report: runs/mw_protocol_v3_3r3_batch3_20260911/report_omp_batch3.md

## Review checklist (rule each; cite file+field evidence)

D1 Ten exact identities, template id/sha256, style/bookmark matches vs node_tree.json,
    contract<->skill binding, no provider/model fields; coverage roles correct per the
    reconciliation doc (batch3 = 10).
D2 Parent-body inheritance (the batch's highest-risk content): parent v2_n_5 body372-379
    population framing lives in the inclusion carrier v2_n_5_1 with an honest
    declared-inheritance marker; exclusion v2_n_5_2 references it WITHOUT duplicating
    inverse criteria and WITHOUT fabricating a parent leaf.
D3 Predicate typing: inclusion = all-applicable-criteria, exclusion = any-applicable-
    criterion; typed logic/units/thresholds/windows/exceptions (not free-text numbering);
    no duplicate inverse criteria; no incompatible thresholds (the threshold-contradiction
    negative fails for that reason).
D4 Template examples not project facts: oral dosing, one-month contraception, blanket
    pregnancy exclusion, smoking/device restrictions, IWRS/1:1/stratified-block inference,
    "statistics section 9" stale cross-reference — none hardcoded; the copied-contraception
    and stale-reference negatives fail for their reasons.
D5 Completion vs overall study end distinct; screen failure vs rescreening distinct with
    reasons/timing/records; "not randomized" does not classify every consented
    nonrandomized person as criterion failure; end-of-treatment not substituted for
    follow-up (negative fails).
D6 High-risk design choices (comparator, NI margin, placebo, dose) are explicit
    project-instance human decisions — obligations state decision + evidence floor, never
    a template default; wrong-comparator/ratio and dose-other-regimen negatives fail for
    their reasons.
D7 Evidence groups: independently required sources in SEPARATE groups; group = ANY-one-of;
    no mega-group; context window + quality floor; wrong_source negatives degrade only
    their targeted group. Phantom approval receipt negative (v2_n_5_5) fails structurally.
D8 Fixtures/tests: 48 fixtures; every node ≥4 families; fixture ID convention batch1
    hyphen format; bare true/false triggers; conspicuous synthetic markers; 20 tests
    batch-scoped (no global directory equality later batches break); RED evidence
    precedes implementation; iterations preserved without weakening; deferred honesty
    (no medical/conditional/provenance/Word acceptance claims).

## Hard boundaries

- READ-ONLY: create/modify/delete NOTHING. You may run the authorized pytest command
  (writes no files with -p no:cacheprovider):
  env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw
  TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8
  PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:.
  runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest
  tests/protocol_v3/test_chapter_batch3.py -q -p no:cacheprovider --tb=short
- Do NOT read batch5 mutable files (v2_n_9_*/v2_n_10_*, batch5.json, test_chapter_batch5.py
  — being written right now by a concurrent worker).
- No web, credentials, services, product model calls, subagents.
- Challenge, do not repair. Verdict only.

## Output schema (your FINAL message, plain text, no file writes)

VERDICT: ACCEPT | ACCEPT_WITH_ACTIONS | REJECT
FINDINGS: [D1..D8 each] PASS | FAIL | PARTIAL — one-line evidence (file + field/test)
DEFECTS: numbered; file, exact location, violated item, minimal correct repair (empty if none)
TESTS_RUN: what you executed + result (or "relied on provided evidence")
RESIDUAL_RISK: what you could not verify and why
