# Task Context: mw_protocol_v3_3r3_batch8_fresh_review_20260911

Created: 2026-09-11 23:00:00 (ZCode takeover dispatch)
Objective: Independent fresh-context acceptance review of the batch8 chapter contract/skill/
fixture delivery (12 carriers: quality/references/appendices, chapters 14-16 — the FINAL
3R.3 batch). Rule semantic correctness against the source spec; list exact defects.
READ-ONLY review.
Task type: code_open_audit (single fresh reviewer, verifier isolation)
Risk: high
Selected agent route: `codebuddy` / `deepseek-v4-flash` / `max` (non-deepseek-v4.1 family
separation; the artifact under review was produced by codebuddy/deepseek-v4.1-flash —
same harness, different model; where strict family isolation is preferred note that
batch1/batch3 reviews used this same pairing successfully with independent static audit)

## Why this review exists

The batch8 worker delivered 12 contracts + 12 skills + batch8.json (74 fixtures) +
test_chapter_batch8.py (28 tests). Main owner verified: combined batch1-8 suite 207 passed
(runs/mw_protocol_v3_3r3_batch8_20260911/main_owner_combined_1to8_20260911.xml), all-eight
assembly INDEPENDENTLY REPRODUCED (111 chapters / 556 fixtures, semantically identical:
main_owner_assembled_all8.json), full-mode lint status COMPLETE 111/111 exit 0
(main_owner_lint_full_all8.txt). You rule batch8 semantics.

## Source of truth (read-only inputs, paths relative to repo root)

Primary review targets:
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/v2_n_14_*.json,
  v2_n_15.json, v2_n_16.json, v2_n_16_x1/x2/x3.json (12 files)
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_skills/ (same 12 ids)
- tests/fixtures/protocol_v3/chapter_content_v2/batch8.json
- tests/protocol_v3/test_chapter_batch8.py

Authoritative source obligations:
- reviews/mw_protocol_v3_3r3_batch8_content_spec_20260906.md (FULL — the binding spec)
- context/mw_protocol_v3_3r3_batch8_20260911_context.md (dispatch contract)
- reviews/mw_protocol_v3_3r3_batch_coverage_reconciliation_20260906.md (v2_n_16
  heading-only container + outline leaves mandate)

References for conventions and accumulated review precedents:
- reviews/mw_protocol_v3_3r3_batch{2,3,4,5,6}_acceptance_*.md — enforce: word_rules
  populated from node_tree (complete bookmark lists, no invented xref ids); ownership
  declarations for new fact roots; conditional rules at contract level with declared
  trigger facts; bare booleans; every source-specific negative with expected-code
  assertion; no foreign-language slips; provenance windows within node_tree ranges.
- packages/contracts/workbench_contracts/protocol_v3.py and
  services/api/app/protocol_workflow/registries/chapters.py
- Worker report: runs/mw_protocol_v3_3r3_batch8_20260911/report_codebuddy_batch8.md

## Review checklist (rule each; cite file+field evidence)

H1 Twelve exact identities (incl. v2_n_16 heading-only container alongside x1/x2/x3
  outline leaves — coverage roles correct per reconciliation), template id/sha256,
  word_rules populated from node_tree, contract<->skill binding, no provider/model.
H2 CtQ/risk management (14_1): actual critical factors/risks/proportionate controls/
  responsibility/review linkage; generic slogan and placeholder plan name fail
  (both negatives present, exact codes asserted).
H3 Responsibilities (14_2): actual arrangements; no inferred completed training or
  signed acceptance (negatives fail); monitoring agrees with proportionate approach.
H4 Audit/deviations (14_3): distinct processes/records/impact/communication; important
  vs general deviations + urgent-hazard exceptions defined; TP-MA-15 title declared
  provenance-pending, not validated.
H5 Safety oversight (14_4 area): DSMB vs SMC vs endpoint IRC not interchangeable
  (negative); semiannual/escalation examples only; no fictional membership/charter.
H6 References (v2_n_15): from ACTUALLY USED sources; complete metadata; resolvable
  citations; template examples not a bibliography (negatives: unused/copy-pasted
  bibliography, in-text citation with no target).
H7 Appendix container (v2_n_16): aggregates actual applicable attachments; heading-leaf
  coverage preserved separately from outline leaves.
H8 Conditional appendices (x1/x2/x3): ECOG/NYHA conditional on actual assessments,
  version verified when selected (negative: irrelevant score appendix); laboratories/
  destruction provider genuine names/roles — the two sample labs and destruction company
  are template examples, not project suppliers (negative: blank or invented cells).
H9 Fixtures/tests: 74 fixtures; ≥4 families/node (incl. 2 conditional-inactive
  positives); hyphen convention; bare booleans; synthetics conspicuous; every
  source-specific negative with expected-code assertion; 28 tests batch-scoped;
  two-stage RED; deferred honesty; ownership declarations; conditional rules
  schema-correct.

## Hard boundaries

- READ-ONLY: create/modify/delete NOTHING. You may run the authorized pytest command
  (writes no files with -p no:cacheprovider):
  env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw
  TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8
  PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:.
  runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest
  tests/protocol_v3/test_chapter_batch8.py -q -p no:cacheprovider --tb=short
  (If Bash is denied in your mode, say so in TESTS_RUN and rely on provided XMLs.)
- batch7 review is concurrently reading other files — do NOT read batch7 review outputs;
  batch1-7 artifacts are stable and referenceable.
- No web, credentials, services, product model calls, subagents.
- Challenge, do not repair. Verdict only.

## Output schema (your FINAL message, plain text, no file writes)

VERDICT: ACCEPT | ACCEPT_WITH_ACTIONS | REJECT
FINDINGS: [H1..H9 each] PASS | FAIL | PARTIAL — one-line evidence (file + field/test)
DEFECTS: numbered; file, exact location, violated item, minimal correct repair (empty if none)
TESTS_RUN: what you executed + result (or "relied on provided evidence")
RESIDUAL_RISK: what you could not verify and why
