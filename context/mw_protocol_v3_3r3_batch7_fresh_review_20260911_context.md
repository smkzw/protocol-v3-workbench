# Task Context: mw_protocol_v3_3r3_batch7_fresh_review_20260911

Created: 2026-09-11 22:47:00 (ZCode takeover dispatch)
Objective: Independent fresh-context acceptance review of the batch7 chapter contract/skill/
fixture delivery (13 carriers: data management + ethics, chapters 12-13). Rule semantic
correctness against the source spec; list exact defects. READ-ONLY review.
Task type: code_open_audit (single fresh reviewer, verifier isolation)
Risk: high
Selected agent route: `zcode` / `GLM-5.3-Flash` / `max` (non-OpenAI family; the artifact
under review was produced by pi/openai-codex/gpt-5.6-luna)

## Why this review exists

The batch7 worker delivered 13 contracts + 13 skills + batch7.json (59 fixtures) +
test_chapter_batch7.py (13 tests). Main owner verified: combined batch1-7 suite 179 passed
(runs/mw_protocol_v3_3r3_batch7_20260911/main_owner_combined_1to7_20260911.xml), independent
assembly OK (13 chapters / 59 fixtures). You rule semantics.

## Source of truth (read-only inputs, paths relative to repo root)

Primary review targets:
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/v2_n_12_*.json,
  v2_n_13_*.json (13 files)
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_skills/ (same 13 ids)
- tests/fixtures/protocol_v3/chapter_content_v2/batch7.json
- tests/protocol_v3/test_chapter_batch7.py

Authoritative source obligations:
- reviews/mw_protocol_v3_3r3_batch7_content_spec_20260906.md (FULL — the binding spec)
- context/mw_protocol_v3_3r3_batch7_20260911_context.md (dispatch contract; its Authoring
  requirements list is binding, including the mandatory negative list)
- reviews/mw_protocol_v3_3r3_batch_coverage_reconciliation_20260906.md

References for conventions and ALL accumulated review precedents:
- runs/mw_protocol_v3_3r3_batch1_repair_20260908/assembled_batch1_registry.json
- reviews/mw_protocol_v3_3r3_batch{2,3,4,5,6}_acceptance_*.md — established precedents you
  MUST enforce: word_rules styles/bookmarks populated from node_tree (batch4 D1 + batch5
  D1/D2: full bookmark lists, no invented cross-reference ids); ownership declarations for
  new fact roots (batch3 D3/batch6 D6); conditional rules at CONTRACT level with declared
  trigger facts in fact_requirements (batch6 D1); bare booleans (batch6 D4); every
  source-specific negative with an expected-code assertion (batch4 D2/batch6 D3); no
  foreign-language character slips (batch5 D4); provenance windows within node_tree ranges
  (batch5 D5).
- packages/contracts/workbench_contracts/protocol_v3.py and
  services/api/app/protocol_workflow/registries/chapters.py
- Worker report: runs/mw_protocol_v3_3r3_batch7_20260911/report_omp_batch7.md

## Review checklist (rule each; cite file+field evidence)

G1 Thirteen exact identities, template id/sha256, word_rules populated from node_tree
  (styles AND complete bookmark lists; no invented cross-reference ids), contract<->
  skill binding, no provider/model fields, coverage roles correct.
G2 Data capture/source (12_1/12_2 area): actual study arrangements; EDC example-only;
  direct eCRF source vs copied source records distinct; no fabricated completed
  validation; copied company names forbidden (negative fails).
G3 Future use (12_7): purpose/location/duration/genetic testing/consent/review typed and
  separate from current-study assays; post-study consent-irrevocability NOT universal
  (project/legal review); future-use permission not inferred from ordinary consent
  (negative); study-data-conflation negative fails for its reason.
G4 Retention (12_8): trigger/duration/custody/disposition typed; five-year/optical-disc/
  sponsor-ownership universal assumptions forbidden; blank custody negative fails.
G5 Publication (12_9): actual agreements; no fabricated repository/committee/permission
  (negative fails forbidden_claim).
G6 Ethics/consent (13_1/13_2): prospective procedure/versions/roles/timing-before-
  procedures/capacity-representative-witness/new-information; witness not universal
  substitute; approval-ready != approval-obtained (unsigned-plan negative fails);
  GCP article numbers declared as provenance pending, not validated.
G7 Confidentiality (13_3): data/sample coding, recipients, access, transfer typed; no
  invented people/facilities.
G8 Compensation (13_4): arrangement/injury/insurance/contact required; missing facts
  trigger intake/recommendation resolution, never "inapplicable" or fabricated amounts
  (negative fails missing_required_fact).
G9 Fixtures/tests: 59 fixtures; ≥4 families/node; hyphen convention; bare booleans;
  synthetics conspicuous; 7 source-specific negatives each with expected-code assertion;
  13 tests batch-scoped; two-stage RED; deferred honesty; ownership declarations;
  conditional rules schema-correct with declared triggers.

## Hard boundaries

- READ-ONLY: create/modify/delete NOTHING (PYTHONDONTWRITEBYTECODE=1 for any python;
  authorized pytest command writes no files with -p no:cacheprovider). Your final message
  IS the report; do not write any report file.
- batch8 mutable files (v2_n_14_*/v2_n_15/v2_n_16* contracts/skills, batch8.json,
  test_chapter_batch8.py) are being written RIGHT NOW — do NOT read them.
- Authorized pytest command:
  env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw
  TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8
  PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:.
  runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest
  tests/protocol_v3/test_chapter_batch7.py -q -p no:cacheprovider --tb=short
- No web, credentials, services, product model calls, subagents.
- Challenge, do not repair. Verdict only.

## Output schema (your FINAL message, plain text, no file writes)

VERDICT: ACCEPT | ACCEPT_WITH_ACTIONS | REJECT
FINDINGS: [G1..G9 each] PASS | FAIL | PARTIAL — one-line evidence (file + field/test)
DEFECTS: numbered; file, exact location, violated item, minimal correct repair (empty if none)
TESTS_RUN: what you executed + result (or "relied on provided evidence")
RESIDUAL_RISK: what you could not verify and why
