# Execution report: 3R.3 batch2 resume (codebuddy/deepseek-v4.1-flash:max)

Saved by dispatching ZCode main owner from the runner stream.
Route identity: codebuddy/deepseek-v4.1-flash, modelUsage echo deepseek-v4.1-flash,
duration 551489ms, 179 turns, is_error false. Dispatch: dispatch.json in this directory.
Main-owner verification: combined suite 68 passed (main_owner_combined_batches12_20260911.xml).

---

STATUS: COMPLETED

FILES_CREATED (all NEW; nothing else touched — audit by mtime + `git status`, forbidden core/schema/assembler/lint/batch1 paths unchanged):
- `config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/<node_id>.json` — 16 (exact IDs: v2_n_2_1, v2_n_2_2_1, v2_n_2_2_2_1, v2_n_2_2_3, v2_n_2_3, v2_n_3_1_1, v2_n_3_1_2_1..4, v2_n_3_2_1, v2_n_3_2_2, v2_n_3_3_1, v2_n_3_3_2, v2_n_3_4_1, v2_n_3_4_2)
- `config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_skills/<node_id>.json` — 16 dedicated manifests (bound to each contract/template identity, no provider/harness/model fields)
- `tests/fixtures/protocol_v3/chapter_content_v2/batch2.json` — 1 (167,884 bytes; closed vocab: 70 fact paths / 40 claim types; 16 coverage_roles)
- `tests/protocol_v3/test_chapter_batch2.py` — 1 (38 tests)
- diagnostics under `runs/mw_protocol_v3_3r3_batch2_resume_20260911/` — 6 new: `batch2_red_pre_implementation_20260911.xml`, `batch2_green_20260911_r1.xml`, `batch2_green_20260911_r2.xml`, `batch2_green_20260911_final.xml`, `assembled_batch2_registry.json`, `lint_batch2_partial.txt`, `lint_batch2_partial_fixtures.txt` (7 files). Runner-owned `dispatch.json`/`stderr.txt`/`stdout_stream.jsonl` untouched; the runner report path was not written.

RED_EVIDENCE:
- `runs/mw_protocol_v3_3r3_batch2_resume_20260911/batch2_red_pre_implementation_20260911.xml` — tests=38, failures=1, errors=37, all caused by the not-yet-authored batch2 files (189 `batch2.json` references in the failure text; assembly input errors and `missing authored batch document`).
- Intermediate green iteration `batch2_green_20260911_r1.xml` (failures=1) is preserved. The one failure was my test asserting the wrong format for an existing core finding (claim type is in `finding.message`, not `finding.location`); fixed the assertion to inspect messages — the semantic target (wrong-source finding must concern `own_product_clinical_evidence`) was kept, not weakened.

GREEN_EVIDENCE:
- Command (frozen env, existing venv, no whole-suite rerun):
  `env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:. runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest tests/protocol_v3/test_chapter_batch2.py -q -p no:cacheprovider --tb=short --junitxml=runs/mw_protocol_v3_3r3_batch2_resume_20260911/batch2_green_20260911_final.xml`
- Tail summary: `38 passed in 0.52s` (XML: tests=38, failures=0, errors=0, skipped=0)
- XML: `runs/mw_protocol_v3_3r3_batch2_resume_20260911/batch2_green_20260911_final.xml`
- Independent CLI check (same env): `assemble_chapter_registry.py ... --batch tests/.../batch2.json` exit 0 → `assembled_batch2_registry.json`; `lint_chapter_registry.py --registry <that> --template-dir ... --partial --check-fixtures` exit 0, `mode: partial / status: incomplete / coverage: expected=111 covered=16 leaf_union=110`, 16 fixture PASS / 61 FAIL, no error findings.

FIXTURES: total 77 (≥64), every one of the 16 nodes carries ≥4 fixtures and all four families; synthetic values are conspicuous (`【合成夹具】`), no `supplied_passed`/`supplied_qc_verdict` is set anywhere.
- Per family: positive 16, missing_claim 12, missing_control 15, wrong_source 17, skeleton 17.
- Source-specific negatives (13): `competitor-as-own-clinical` (wrong_source_role, no inadmissible_claim), `missing-own-clinical-evidence-group`, `missing-general-pharmacology-group` (fails at group index 3), `missing-mechanism-evidence-group`, `empty-ice-entries` (missing_required_cell), `missing-population-summary-measure`, `summary-measure-method-name-only` (both target `estimand.primary.population_summary_measure`), `analysis-set-equivalence-forbidden`, `label-only-variable-forbidden`, `treatment-effect-label-only-forbidden`, `ice-shell-placeholder-forbidden`, `numbered-placeholder-objective-forbidden`, `compensation-as-benefit-forbidden` (forbidden_claim_present).

SEMANTIC_NOTES:
- Estimand 5th attribute: distinct path `estimand.primary.population_summary_measure`, required only by `v2_n_3_1_2_4` (together with ICE facts/claims and table-1 cells); no fifth heading/carrier invented. `picos.population_summary` is kept as optional population description in `v2_n_3_1_2_1` and `v2_n_3_1_2_4` with explicit non-interchange rationales and is never required. Attribute-three's source label "治疗效应" is preserved via `estimand.primary.treatment_effect_label_clarification` + forbid-`treatment_effect_label_only` (`v2_n_3_1_2_3`).
- Competitor vs own evidence: `v2_n_2_2_3` has two separate groups — `{competitor_full_protocol → competitor_evidence_summary}` and `{project_primary → own_product_clinical_evidence}` — plus `background.own_product.clinical_study_context` requiring matching study context (not an IB file ID).
- Unheaded PK/tox/general pharmacology: `v2_n_2_2_2_1` carries four separate required facts, four required claims and four separate evidence groups (each satisfied by any one conforming unit) with a ≥4 paragraph obligation, so one PD paragraph cannot discharge the set; `background.clinical_pharmacology_context` preserves parent 2.2 framing. Inherited mechanism: `v2_n_2_2_1` requires `background.product.mechanism` with a declared-addition marker ("继承自 background.mechanism；源 @284 未显式含机制描述…").
- Evidence-group separation: every independently required source gets its own group; risk/benefit splits project assessment from regulatory framework; safety splits objective from endpoint definition; exploratory splits objective from disposition; all groups require a context window and a quality floor.

DEFERRED (deliberately not claimed): medical/QC judgment, conditional-rule evaluation, CtQ/skeleton-risk evaluation and project-specific element evaluation — the linter returns 486 deferred obligations and every deterministic pass is labeled `medical_and_qc_judgment_not_executed`. Also deferred: admitted provenance (`EvidenceUnit`/`MedicalAdmissionUnit`/`ClaimEvidenceLink` resolution), the parent-targeted inherited-obligation crosswalk for `v2_n_11_4`/`v2_n_5` (outside the sixteen carriers), exploratory/route-conditional obligations that only activate on confirmed project facts, and any Word/native-DOCX, visual or full-registry acceptance.

LIMITS_AND_NEXT: No acceptance or closure claimed — the dispatching main owner owns verification. Remaining for acceptance: independent source-content review of the 16 contracts against body children 273–339 (headings 316–319 examples not exported as headings; 306/324 wording bounded); confirmation that the container-level 2.2 narrative is judged adequately preserved through the leaf contracts/skills rather than requiring a separate crosswalk; full-registry coverage remains 16/111 with batch1, 3–8 outstanding (never counted as covered here); and a decision on whether the projected `picos.population_summary` meaning boundary needs an explicit migration note before any adoption.