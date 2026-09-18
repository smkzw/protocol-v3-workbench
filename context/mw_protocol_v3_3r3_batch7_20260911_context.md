# Task Context: mw_protocol_v3_3r3_batch7_20260911

Created: 2026-09-11 22:35:00 (ZCode takeover dispatch)
Objective: Author thirteen source-bound data-management/ethics chapter contracts, dedicated
skills and fixtures, in disjoint batch7 files; no core/runtime changes or acceptance claims.
Task type: `finite_code_task`
Risk: `high`
Selected agent route: `pi` / `openai-codex` / `gpt-5.6-luna` / `xhigh`

## Trigger Reason

Batch-ordered acceptance with overlapping authorship (approved pattern). batch8 is not yet
dispatched; no concurrent worker writes ch12-13 files. Assembly loads only selected
coverage_roles slices.

## Source Of Truth

Additional read-only inputs authorized here:
- reviews/mw_protocol_v3_3r3_batch7_content_spec_20260906.md (FULL — your primary source spec)
- reviews/mw_protocol_v3_3r3_batch_coverage_reconciliation_20260906.md
- packages/contracts/workbench_contracts/protocol_v3.py (v2 schema)
- services/api/app/protocol_workflow/registries/chapters.py
- scripts/qc/protocol_v3/assemble_chapter_registry.py
- scripts/qc/protocol_v3/lint_chapter_registry.py
- tests/protocol_v3/test_all_chapter_contracts.py
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/{template,node_tree,v1_to_v2_mapping}.json
- services/api/app/medical_writing_protocol_template.py (existing shared fact bindings)
- runs/mw_protocol_v3_3r3_batch1_repair_20260908/assembled_batch1_registry.json
  (accepted batch1 format/vocabulary example ONLY)
- tests/protocol_v3/test_chapter_batch1.py and tests/protocol_v3/test_chapter_batch4.py
  (accepted batch-scope test patterns, read-only)
Do NOT read or write other batches' mutable fixture/test files (batch5 review in flight;
batch6 review imminent). Writing any file outside your Scope is forbidden.

## Scope

Explicit EDIT authorization exclusively for NEW files:
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/<node_id>.json (13)
- config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_skills/<node_id>.json (13)
- tests/fixtures/protocol_v3/chapter_content_v2/batch7.json
- tests/protocol_v3/test_chapter_batch7.py
- runs/mw_protocol_v3_3r3_batch7_20260911/ (NEW diagnostics only)
Exact thirteen leaf IDs (parents v2_n_12, v2_n_13 are NOT carriers):
v2_n_12_1, v2_n_12_2, v2_n_12_3, v2_n_12_4, v2_n_12_5, v2_n_12_6, v2_n_12_7,
v2_n_12_8, v2_n_12_9, v2_n_13_1, v2_n_13_2, v2_n_13_3, v2_n_13_4.
No other source/tests, core/schema/assembler/lint, plans, checkpoints, external files,
credentials, web, services, product model calls, subagents, dependency installation,
security engineering or task closure.

## Authoring requirements (binding)

Author meaningful source-obligation tests FIRST and record RED evidence under the run dir
(two-stage RED preferred: missing test file, then failing assertions with test present —
collection errors alone are weaker evidence), then implement ChapterContractV2 plus
dedicated Chinese ChapterSkillManifest for each node. Preserve exact accepted source hash,
node/bookmark/style IDs — word_rules.required_styles/required_bookmarks MUST be populated
from node_tree.json (NEVER empty; batch4 D1 precedent). No provider settings.
Reuse existing fact paths where meanings match. READ THE FULL SPEC; key demands:
- Data capture/source identification/review-query/corrections/lock-export/responsibilities
  reflect ACTUAL study arrangements; EDC is a source example, not proof of a vendor or
  validated system; direct eCRF source data vs copied source records distinct identification.
- Computerized-system and data-governance statements reflect actual roles/records/
  arrangements, no fabricated completed validation.
- Future sample/data use (829-836) separate from required current-study assays: purpose,
  location, duration, genetic testing, consent, future-use review explicit when applicable;
  source 835's post-study consent-irrevocability is NOT a universal conclusion (project/
  legal review required); future-use permission must NOT be inferred from ordinary trial
  consent (negative).
- Record retention (837-842): applicable trigger, duration, custody, disposition; do not
  copy five years / optical discs / "all records owned by sponsor" as universal law.
- Publication/data sharing (843-849): actual agreements; no fabricated repository/
  committee/permission (negative: nonexistent repository).
- Ethics and consent (850-856): prospective procedure, versions, responsible roles, timing
  before relevant procedures, capacity/representative/witness arrangements where applicable,
  new-information handling; witness is not a universal consent substitute; approval-ready
  protocol must not imply approval already obtained (negative: unsigned plan claimed
  approved).
- Confidentiality (862-879): applicable data/sample coding, recipients, access, transfer
  arrangements; no invented people/facilities.
- Compensation/injury/insurance (880-881): required content with genuine project facts or
  referenced actual agreements; missing facts trigger intake/recommendation resolution,
  never "section inapplicable" or fabricated amounts (negative: missing mandatory
  compensation arrangement).
- Source GCP article numbers and retention/consent legal wording are provenance pending
  applicable-primary-source review — declare, do not validate.
- Independently required sources get separate EvidenceSourceRequirement groups (ANY-of
  inside); context window + quality floor.
- Fixture ID convention: fixture:batch7:v2-n-12-1:positive style; boolean triggers bare
  true/false; conspicuous synthetic markers; negative failures target their reason.
- Mandatory negatives from the spec: nonexistent repositories; blank custody/period fields;
  copied company names; unsigned plans claimed approved; study data conflated with optional
  future use; missing mandatory compensation arrangement; future-use permission inferred
  from ordinary consent.

Use existing assemble_registry for the exact batch slice; batch-scope assertions only
(selected batch exactly 13; other batches' files never affect your tests). Closed
vocabularies, thirteen roles, at least four exercised families per node (positive,
missing_claim OR missing_control, wrong_source, skeleton; minimum 52) plus the spec's
source-specific negatives.

## Success Criteria

- Targeted checks cover exact 13 identities, source obligations, exercised fixtures,
  partial clean/incomplete status and full expected missing coverage.
- Report actual RED/GREEN evidence, changed files, limitations and next action.
  No full-project, clinical, legal, visual or native Word acceptance claim.
- Existing venv only, no unrelated legacy whole-suite reruns:
  env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw
  TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8
  PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:.
  runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest
  tests/protocol_v3/test_chapter_batch7.py -q -p no:cacheprovider --tb=short
  Preserve new XML diagnostics for each run under the run dir.

## Risk Boundaries

- Do not write outside the explicitly listed NEW files. The delegated agent is not final
  authority; the ZCode main owner owns verification and acceptance.

## Timeout Policy

- Do not mark yourself failed for slow progress; work continuously to completion.
- Failure requires terminal error, provider exhaustion/rate limit after controlled retry,
  or empty/truncated output.

## Output schema (your FINAL message, plain text)

STATUS: COMPLETED | PARTIAL | FAILED
FILES_CREATED: list with counts (13 contracts / 13 skills / fixtures file / test file / diagnostics)
RED_EVIDENCE: path(s) of pre-implementation failing runs
GREEN_EVIDENCE: exact pytest command + tail summary line + XML path
FIXTURES: total count, per-family breakdown, source-specific negatives list
SEMANTIC_NOTES: future-use separation, retention-arrangement typing, ethics/consent
  prospective semantics, confidentiality recipients typing, compensation resolution path
  (node ids)
DEFERRED: obligations deliberately deferred with reasons
LIMITS_AND_NEXT: what remains for acceptance
