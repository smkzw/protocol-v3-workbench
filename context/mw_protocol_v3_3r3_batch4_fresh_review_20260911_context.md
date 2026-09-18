# Task Context: mw_protocol_v3_3r3_batch4_fresh_review_20260911

Created: 2026-09-11 23:05:00 (ZCode takeover dispatch)
Objective: Independent fresh-context acceptance review of the batch4 chapter contract/skill/
fixture delivery (16 carriers: intervention and related procedures, chapters 6-8).
Rule semantic correctness against the source spec; list exact defects. READ-ONLY review.
Task type: code_open_audit (single fresh reviewer, verifier isolation)
Risk: high
Selected agent route: `zcode` / `GLM-5.3-Flash` / `max` (non-deepseek family; the artifact
under review was produced by codebuddy/deepseek-v4.1-flash)

## Why this review exists

The batch4 worker delivered 16 contracts + 16 skills + batch4.json (72 fixtures) +
test_chapter_batch4.py (29 tests). Main owner verified: combined suite 97 passed
(runs/mw_protocol_v3_3r3_batch4_20260911/main_owner_combined_124_20260911.xml = batch1 17 +
batch2 38 + batch4 29 + codex counterexamples 13), independent assembly semantically
identical (main_owner_assembled_batch4.json), partial lint exit 0, out-of-scope audit
clean. Tests and structure verified ≠ semantic correctness: you rule the content.

## Source of truth (read-only inputs, paths relative to repo root)

Primary review targets:
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/v2_n_6_*.json,
  v2_n_7_*.json, v2_n_8_*.json (16 files: v2_n_6_1_1, v2_n_6_1_2, v2_n_6_2_1..4, v2_n_6_3,
  v2_n_6_4_1..3, v2_n_7_1..3, v2_n_8_1..3)
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_skills/ (same 16 ids)
- tests/fixtures/protocol_v3/chapter_content_v2/batch4.json
- tests/protocol_v3/test_chapter_batch4.py

Authoritative source obligations:
- reviews/mw_protocol_v3_3r3_batch4_content_spec_20260906.md (FULL — the binding spec)
- context/mw_protocol_v3_3r3_batch4_20260911_context.md (dispatch contract; its Authoring
  requirements list is binding, including the mandatory negative list)
- reviews/mw_protocol_v3_3r3_batch_coverage_reconciliation_20260906.md

References for conventions:
- runs/mw_protocol_v3_3r3_batch1_repair_20260908/assembled_batch1_registry.json (accepted
  batch1 structure/vocabulary; fixture-ID convention)
- reviews/mw_protocol_v3_3r3_batch2_acceptance_20260911.md (accepted batch2 patterns)
- packages/contracts/workbench_contracts/protocol_v3.py and
  services/api/app/protocol_workflow/registries/chapters.py (schema/checker semantics)
- Worker report: runs/mw_protocol_v3_3r3_batch4_20260911/report_codebuddy_batch4.md

## Review checklist (rule each; cite file+field evidence)

C1 Sixteen exact identities, template id/sha256, style/bookmark matches vs node_tree.json,
    contract<->skill binding, no provider/model fields; coverage roles correct.
C2 Individual-vs-trial-level separation (the batch's highest-risk content, source 496-511
    conflation): v2_n_8_1 types individual temporary hold / individual permanent
    discontinuation / withdrawal-from-participation / trial-level suspension+termination
    separately; v2_n_8_2 declares NO trial-level facts; trial stopping criteria cannot
    become individual stopping rules; "efficacy shown" requires design-specific decision
    logic; individual_stop==trial_stop negative fails for that reason.
C3 Dose/administration/storage/adherence/rescue: typed route/regimen/start-max facts;
    template examples example-only; cross-section dose consistency obligations declared;
    storage units real; adherence denominator present; rescue strategy consistent with
    estimand (negative fails structurally on the linkage).
C4 Withdrawal/lost-to-followup semantics (518-546): reason requested-not-compulsory;
    pregnancy/progression/nonadherence scenario-specific; follow-up does not silently end
    at last dose; prior data not silently erased; discontinuation != consent withdrawal;
    LTFU requires project-specific contact attempts/records/classification; missed visit
    alone insufficient; "three calls" example-only; not-reachable != consent withdrawal;
    replacement policy agrees with sample-size/analysis (CtQ linkage).
C5 Evidence groups: independently required sources in SEPARATE groups; group = ANY-one-of;
    no mega-group; context window + quality floor present; wrong_source negatives degrade
    only their targeted group.
C6 Fixtures: 72 total; every node ≥4 families; the 8 spec-mandated source-specific
    negatives present and each fails for its INTENDED reason with exact error code
    asserted; fixture ID convention matches batch1 hyphen format; boolean triggers bare
    true/false; synthetic markers conspicuous.
C7 Tests: 29 tests batch-scoped (no global directory equality that later batches break);
    RED evidence precedes implementation (XML timestamps + failure content); iterations
    preserved without weakening assertions; batch1 coexistence cross-check claimed by
    worker — verify it holds now (batch1 files unchanged since 21:37).
C8 Deferred honesty: no medical/conditional-execution/provenance/Word acceptance claims.

## Hard boundaries

- READ-ONLY: create/modify/delete NOTHING (PYTHONDONTWRITEBYTECODE=1 for any python;
  authorized pytest command writes no files with -p no:cacheprovider). Your final message
  IS the report; do not write any report file.
- Do not read batch3 mutable files (v2_n_4_*/v2_n_5_*, batch3.json, test_chapter_batch3.py
  — being written right now by a concurrent worker). batch1/batch2 files are accepted and
  read-only-referenceable.
- Authorized pytest command:
  env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw
  TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8
  PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:.
  runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest
  tests/protocol_v3/test_chapter_batch4.py -q -p no:cacheprovider --tb=short
- No web, credentials, services, product model calls, subagents.
- Challenge, do not repair. Verdict only.

## Output schema (your FINAL message, plain text, no file writes)

VERDICT: ACCEPT | ACCEPT_WITH_ACTIONS | REJECT
FINDINGS: [C1..C8 each] PASS | FAIL | PARTIAL — one-line evidence (file + field/test)
DEFECTS: numbered; file, exact location, violated item, minimal correct repair (empty if none)
TESTS_RUN: what you executed + result (or "relied on provided evidence")
RESIDUAL_RISK: what you could not verify and why
