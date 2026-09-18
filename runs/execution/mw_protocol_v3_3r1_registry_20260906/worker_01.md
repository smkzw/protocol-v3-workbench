# Execution Output: mw_protocol_v3_3r1_registry_20260906 - worker_01

## Boundary And Context Check

- Worked only inside the runner-bound workspace. Read the initial read set (execution context, plan), then the declared source of truth: `.trellis/tasks/09-06-protocol-v3-3r1/{prd,design,implement,checkpoint}.md`, `reviews/mw_protocol_v3_tp_ma07_v2_readonly_preflight_20260905.md`, plan v2 Task 3R.1 (external read-only `plan-upgrade-20260905/mw_protocol_v3_implementation_plan_v2_20260905.md`), and convention references (`scripts/qc/protocol_v3/build_source_baseline.py`, `tests/protocol_v3/test_authority_locator_amendment.py`).
- Source DOCX SHA256 re-verified before and after: `018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756` — unchanged. Zip/XML read only; never saved.
- Legacy module `services/api/app/medical_writing_protocol_template.py` read only via `sed`/AST; never imported.
- Wrote exactly the five authorized files plus new evidence under `runs/mw_protocol_v3_3r1_registry_20260906/`. No preexisting evidence overwritten, no task-status edits, no runtime/contracts/legacy edits, no product activation, no commits, no cleanup. No conference, no peer review.

## Work Performed

Implemented the complete Task 3R.1 candidate registry within the five Plan3R1 files, red-first:

1. **Red first**: wrote `tests/protocol_v3/test_tp_ma_07_v2_registry.py` (27 tests) before the extractor existed; first run failed 4/23 errors (evidence preserved at `runs/mw_protocol_v3_3r1_registry_20260906/red_first_pytest.txt`).
2. **Extractor** `scripts/qc/protocol_v3/extract_tp_ma_07_v2_registry.py`: sha256 gate with explicit `RegistrySourceError("source hash mismatch…")`; stdlib zipfile/ElementTree DOCX structure extraction (styles with basedOn inheritance, heading-style tree vs outlined tree kept separate, immediate-next leaf rule, derived section numbers anchored to the 标题 1 1. style, front-matter items before the first numbered chapter, Normal/caption local-outline extras retained, per-node content-paragraph locators, table ownership/nested counts/captions, 8 sectPr with locators, bookmark/field inventories, three-scope 试验参与者/受试者 counts, semantic findings for unheaded preclinical content / estimand fifth-attribute tail / 示例-labeled paragraphs); AST-only legacy inventory (`_COMPANY_CHAPTERS` incl. AnnAssign and `.strip()` call forms, `_CONDITIONAL_PREFIXES`, `_CHAPTER_BODY_FACT_PATHS`, `_node_kind` dict, `_company_nodes` front nodes, `section_seeds` projection branches with line locators); explicit two-way mapping tables (109 legacy leaves each with a disposition from `mapped_to_v2/split/merged/retired/nonapplicable_phase1` + rationale; all 109 outlined leaves plus the heading-only leaf `v2_n_16` each with a reverse disposition `from_v1/new_in_v2/mixed`); fail-closed validation (unknown legacy node, missing reverse entry, non-leaf reverse entry, nonexistent target, projection-count drift); byte-identical deterministic JSON output (no timestamps/temp paths).
3. **Candidate artifacts** generated at `config/medical_writing/protocol_v3/templates/tp_ma_07_v2/` (template.json, node_tree.json, v1_to_v2_mapping.json), all `candidate_status: candidate_not_current` with explicit promotion requirements.
4. **Green**: all 27 tests pass (evidence at `runs/mw_protocol_v3_3r1_registry_20260906/green_pytest.txt`).

## Artifacts And Evidence

| File | Content |
|---|---|
| `scripts/qc/protocol_v3/extract_tp_ma_07_v2_registry.py` | Deterministic extractor + CLI (`--out-dir`), mapping tables, fail-closed validations |
| `tests/protocol_v3/test_tp_ma_07_v2_registry.py` | 27 source-bound tests (hash gate, determinism, counts, tree invariants, mapping coverage, conditional registrations, projection evidence) |
| `config/.../tp_ma_07_v2/template.json` | Candidate summary: authoritative counts, terminology, conditional registrations, 5 candidate findings, projection reconciliation pointer |
| `config/.../tp_ma_07_v2/node_tree.json` | 135/106 heading-style tree, 139/109 outlined tree (4 extras preserved), 17 tables (1 nested), 8 sections, bookmark/field inventories, semantic findings, front block |
| `config/.../tp_ma_07_v2/v1_to_v2_mapping.json` | 130 legacy nodes AST-extracted (cms_* ids literal), 109 leaf dispositions (mapped 70 / split 15 / merged 7 / retired 10 / nonapplicable_phase1 7), 110 reverse entries (16 new_in_v2), per-leaf projection evidence with `file:line` locators |
| `runs/mw_protocol_v3_3r1_registry_20260906/` | `red_first_pytest.txt`, `green_pytest.txt`, `explore_heading_tree.txt`, `smoke_out/` (retained per no-cleanup rule) |

Reproduced preflight numbers exactly: 940 direct paragraphs; 135/106 heading-style; 139/109 outlined; 17/18 tables; 8 sections; 0 tracked changes; 314 bookmarks (264 `_Toc`); fields TOC×2/HYPERLINK×136/PAGEREF×134/REF×7/SEQ×9; 试验参与者 218/22/240; 受试者 0. Legacy AST identity: 124 rows/103 row leaves + 6 front nodes = 130 nodes/109 leaves, 7 phase:1 leaves.

## Commands And Observations

- Test command (per context, sanitized env):
  `env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:. runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest -p no:cacheprovider tests/protocol_v3/test_tp_ma_07_v2_registry.py`
  → red: `4 failed, 23 errors in 0.20s`; green: `27 passed in 0.29s`.
- `extract_tp_ma_07_v2_registry.py [--out-dir X]` → deterministic three-file output; two independent builds byte-identical (asserted by test) and committed artifacts equal regeneration (drift guard test).
- Bugs found and fixed during implementation: ROOT depth (`parents[3]` for scripts), `AnnAssign` handling for `_CHAPTER_BODY_FACT_PATHS`, `_node_kind` returns `{...}.get(...)` (Call, not Dict), body-child-index vs paragraph-ordinal locators (front block is `[0, 44]`, blank outlined at 76/272/295/296 — both correct in body-child coordinates; earlier 43/73/255/278/279 were paragraph ordinals), section-counter derivation for level jumps, reverse-mapping required-set = outlined leaves ∪ heading-only leaf (`v2_n_16`).
- Observation for Codex: AST-measured explicit projection evidence covers **35 of 109** legacy leaves (`_CHAPTER_BODY_FACT_PATHS` + `section_seeds` branches + node-kind branch), far below the plan's "约 76" claim — recorded as candidate finding `projection_claim_76_not_accepted`, not silently reconciled.

## Blockers Or Missing Environment

None. All required tools existed (isolated venv, source DOCX, pytest). One caveat for the reviewer: mapping dispositions with `confidence: partial` (listed in the mapping's candidate finding) rest on structural adjacency, not content verification — they are flagged for Codex semantic review per contract, not presented as accepted mappings.

## Rerun Requests Or Next Step

No rerun needed. Suggested next steps for Codex: (1) independently review the 35-vs-76 projection reconciliation and the partial/retired mapping entries (especially 6.3 剂量调整→6.1.2/8.1, 4.6 安全性委员会→9.4, 12.5 关键角色→14.2/14.3/14.4 joint carrying, retired conditional chapters); (2) dispatch the fresh independent source review; promotion to current remains Codex-owned — the artifacts self-declare `candidate_not_current`.
