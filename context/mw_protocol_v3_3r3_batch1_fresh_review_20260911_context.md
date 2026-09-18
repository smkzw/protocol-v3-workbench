# Task Context: mw_protocol_v3_3r3_batch1_fresh_review_20260911

Created: 2026-09-11 21:25:00 (ZCode takeover dispatch)
Objective: Independent fresh-context acceptance review of the interrupted-then-completed batch1
chapter contract/skill/fixture repair. Rule whether the repair is semantically correct and
acceptable, or list exact defects. READ-ONLY review; the reviewer edits nothing and closes nothing.
Task type: code_open_audit (single fresh reviewer, verifier isolation)
Risk: high
Selected agent route: `codebuddy` / `deepseek-v4-flash` / `max` (non-GLM family; artifact under
review was produced by GLM-5.3-Flash)

## Why this review exists

The batch1 repair worker (ZCode/GLM-5.3-Flash, sess_b91d51c2) was SIGINT'd by user pause on
2026-09-08 09:34 mid-repair; its files were already written and the focused suite now passes
30/30 (evidence: runs/mw_protocol_v3_3r3_batch1_repair_20260908/resume_baseline_zcode_20260911_2115.xml,
rerun 2026-09-11 21:15 by the takeover main owner). Tests green is necessary, not sufficient:
the repair has never received an independent semantic review. You are that reviewer.

## Source of truth (read-only inputs, all paths relative to repo root)

Primary review targets:
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/*.json (12 files)
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_skills/*.json (12 files)
- tests/fixtures/protocol_v3/chapter_content_v2/batch1.json
- tests/protocol_v3/test_chapter_batch1.py

Repair contract (what the repair was required to do):
- context/mw_protocol_v3_3r3_batch1_repair_20260908.md

The six original content counterexamples (immutable, must still be effective):
- runs/mw_protocol_v3_3r3_batch1_20260906/test_codex_batch_content.py
- runs/mw_protocol_v3_3r3_batch1_20260906/test_codex_batch_assembly.py
- runs/mw_protocol_v3_3r3_batch1_20260906/test_codex_multi_batch.py

Source obligations and authorities:
- reviews/mw_protocol_v3_3r3_batch1_content_spec_20260906.md (per-carrier source obligations)
- reviews/mw_protocol_v3_3r3_3r3_diagram_reference_check_20260906.md — correct path is
  reviews/mw_protocol_v3_3r3_diagram_reference_check_20260906.md (SVG identity/hash authority)
- runs/mw_protocol_v3_3r3_batch1_20260906/assembled_batch1_registry.json (PRE-repair registry;
  authoritative reference for the ORIGINAL 48 fixture IDs, underscore format)
- packages/contracts/workbench_contracts/protocol_v3.py (ChapterContractV2 schema — read-only)
- services/api/app/protocol_workflow/registries/chapters.py (checker semantics — read-only)

## Review checklist (rule each item; cite file+field evidence)

R1 Six content repairs semantically in place, not test-gamed:
   1. service-party contacts conditional (sponsor/PI unconditional; no phantom N/A contacts);
   2. allocation ratio conditional on actual randomization; diagram applicability documented
      for suitable simple designs; default diagram recommendation not silently dropped;
   3. cover/synopsis reuse framing.protocol_id / framing.document_title / framing.version /
      framing.study_phase; no duplicate editable synopsis.*/document_control.protocol_id;
      version and date not collapsed into one unstructured string;
   4. synopsis.registration_classification treated as drug application classification, never
      as proof of a clinical-trials registry record; no invented registration facts;
   5. glossary requires actual used-term entries (abbreviation + expansion + Chinese meaning
      + provenance), not headers only; unused template terms forbidden;
   6. diagram supporting SVG asset bound with real identity + sha256, example-only semantics;
      template example facts (1:1, IWRS, 12-week, placebo) cannot become project facts.
R2 Summary table 242 projection: all 17 row selectors present and distinct body-fact vs
   projected-cell obligations (17 rows listed in repair contract).
R3 Evidence source requirements: independently required claims sit in SEPARATE
   EvidenceSourceRequirement groups (group = ANY-one-of semantics); no mega-group accepting
   one claim to satisfy cover-identity + confidentiality + summary-objective + estimand
   + diagram-content simultaneously.
R4 Fixtures: 52 total = 48 semantic slots (12 carriers x positive/missing-control-or-claim/
   wrong-source/skeleton) + 4 new targeted fixtures (positive-no-service,
   missing-control-empty-entry, positive-randomized, positive-single-arm). Every negative
   fixture must fail for its INTENDED reason, not an unrelated identity error — check each
   negative's mutated field actually targets the obligation it claims to test.
R5 Fixture ID rename ruling: original 48 IDs used underscore node format
   (fixture:batch1:v2_front_block:positive); current files renamed ALL to hyphen format
   (fixture:batch1:v2-front-block:positive), mapping 1:1, zero slots lost, 4 added. Rule:
   is systematic rename acceptable (traceability preserved via 1:1 mapping + this review),
   or must IDs revert to original strings? Consider: rename was undocumented by the worker;
   the repair contract said "original 48 IDs preserved". Weigh intent (anti-gaming
   traceability) vs letter (string identity). Give a clear recommendation.
R6 No weakened real obligations vs reviews/mw_protocol_v3_3r3_batch1_content_spec_20260906.md;
   no deleted negative fixtures; no assertion/expected loosened in test_chapter_batch1.py
   beyond the two explicitly allowed batch-stage corrections (global exactly-12 -> selected
   batch exactly-12; unconditional service cells -> conditional with applicable cells still
   required).
R7 Newly authored SoA CtQ wording uses 试验参与者, no stray 受试者 (historical quotes exempt).
R8 Batch-scope coverage assertions only: selected batch exactly 12; later batch files
   appearing must not break batch1 tests (the tmp-copy missing-carrier probe must still
   exercise AssemblyInputError).
R9 Skills: 12 ChapterSkillManifest files consistent with their contracts (versions,
   obligations vocabulary); no invented medical validation claims; deferred conditional
   medical QC and real evidence admission explicitly deferred, not claimed executed.

## Hard boundaries

- READ-ONLY. Do not create, modify, or delete any file. Do not run write-producing commands.
- You may run the focused pytest suite read-only WITHOUT --junitxml (it writes no files with
  -p no:cacheprovider; skip if your mode blocks it and rely on the provided XML evidence):
  env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw
  TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8
  PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:.
  runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest
  tests/protocol_v3/test_chapter_batch1.py -q -p no:cacheprovider --tb=short
- No web, no credentials, no services, no product model calls, no subagents.
- You are not final authority over task closure; the dispatching ZCode main owner owns acceptance.

## Output schema (your FINAL message, plain text, no file writes)

VERDICT: ACCEPT | ACCEPT_WITH_ACTIONS | REJECT
FINDINGS:
- [R1..R9 each] PASS | FAIL | PARTIAL — one-line evidence (file + field/test name)
DEFECTS: numbered list; each with file, exact location, why it violates which checklist item,
  and the minimal correct repair (empty if none)
ID_RENAME_RULING: ACCEPT_RENAME | REVERT_TO_UNDERSCORE — one-line justification
TESTS_RUN: what you actually executed and the result (or "relied on provided XML")
RESIDUAL_RISK: anything you could not verify and why
