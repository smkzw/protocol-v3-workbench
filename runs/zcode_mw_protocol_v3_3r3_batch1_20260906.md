# Z Code Task: mw_protocol_v3_3r3_batch1_20260906

## Boundary Check

- Read set honored: task context plus the twelve authorized inputs (2 review docs, 3 Trellis artifacts, v2 contract module, registry core, linter CLI, round2 test file, 3 template JSONs). No `.codex`/`.hermes` instruction files, no web, no services/product calls, no runtime activation.
- Writes confined to the six authorized new paths: 12 `chapter_contracts/*.json`, 12 `chapter_skills/*.json`, `tests/fixtures/protocol_v3/chapter_content_v2/batch1.json`, `scripts/qc/protocol_v3/assemble_chapter_registry.py`, `tests/protocol_v3/test_chapter_batch1.py`, `runs/mw_protocol_v3_3r3_batch1_20260906/`. No existing tracked file was modified; the batch1 report path itself was never touched by a write tool. Test environment used exactly the mandated isolated venv + `env -i` recipe; no dependency installs.

## Work Performed

**Authored 12 embedded `ChapterContractV2` contracts** (one per carrier: `v2_front_block` cover; `v2_n_front_1..8`; `v2_n_1_1..3`), each grounded in its zero-based body-child anchors from the content spec and the template registry's measured objects (e.g. version table[46] 4×5, three contact tables 89/91/93, glossary table[96] 3×50, summary table[242] 2×17+nested, SOA table[265] 6×33 in landscape section ordinal 6). Every contract carries: required facts/claims with project-specific substance (e.g. n_1_1 declares all 17 summary-table selector rows), optional facts, node-specific forbidden obligations (placeholder tokens, fabricated approvals/signatures, unused template abbreviations, cached TOC/page text, template example doses/scales/timelines, competitor contact data, stale AE/SAE-only table lists, stale figure refs), a project-primary evidence floor with context-window requirement, stable `required_object_cells` selectors, word rules using exact template style IDs (2/3/1/16/17/18/21/25/28), node-specific positive QC rules and CtQ anchors, and six conditional applicability rules (amendment rationale, additional signatory, service parties, figures present, escalation design, PK sampling). n_1_2 declares a bounded repair policy against its real dependency on the n_1_3 SOA contract; n_1_1 carries the registration-consistency obligation. Unsigned signature controls are modeled as intentional unsigned controls with forbidden completed receipts — no invented signing state anywhere.

**Authored 12 `ChapterSkillManifest` JSONs** with typed I/O refs pinned to the exact exported `ChapterSkillInput`/`ChapterSkillOutput` refs, node-specific Chinese prompt instructions and forbidden behaviors, per-node source-locator provenance requirements, and unique stable error codes. No model/provider transport fields.

**Authored `batch1.json`**: batch-scoped closed vocabularies (68 fact paths, 19 claim types, derived from the authored contracts for guaranteed closure), coverage roles (cover / outline_only_leaf / heading_leaf ×10), and **48 fixtures** — per node one positive, one missing-family (missing_control ×9, missing_claim ×3), one wrong_source, one skeleton — with conspicuously synthetic values throughout. Chapter JSON files were not duplicated in fixtures; each negative mutates its named obligation (blanked cells, dropped required facts/claims, company_style_only evidence, empty content).

**Wrote `assemble_chapter_registry.py`**: stdlib CLI joining contract/skill files + batch document into the accepted `ChapterRegistryDocument` shape, with mandatory library validation (`ChapterContractV2`, `ChapterSkillManifest`, fail-closed `load_chapter_registry`), stdout-only output, no writes/activation/promotion. Reusable for later batches.

**Red-first honored**: `tests/protocol_v3/test_chapter_batch1.py` (8 tests: file/skill identities, derived coverage roles for all twelve IDs, table-cell obligations exercised, 48 families with per-node named-defect codes, no-shell substantive assertions, partial lint clean-but-incomplete, full lint failing remaining coverage, CLI read-only round-trip) was run before authoring and observed failing (2 failed + 6 errors, missing artifacts).

## Evidence And Observations

- Red run: `FileNotFoundError: .../chapter_contracts` — captured in `runs/mw_protocol_v3_3r3_batch1_20260906/red_first_run.txt`.
- Targeted tests: **8 passed in 1.07s** (mandated venv, `pytest -q -p no:cacheprovider`).
- Full `tests/protocol_v3` directory: **1663 passed, 1 failed** — the failure is `test_repository_hygiene_mutator.py::TestIntegrityFollowup4::test_raw_tempfile_var_alias_path_accepted`, environmental and pre-existing: it asserts `tempfile.TemporaryDirectory` lands under `/var`, but the mandated `env -i` recipe strips `TMPDIR` so Python uses `/tmp`; re-run with `TMPDIR=/var/tmp` gives **1 passed**. Both that test and its subject script were already modified in the working tree before this task; I changed nothing in them.
- Assembly CLI: exit 0, 184,954-byte registry on stdout (`assembled_batch1_registry.json`).
- Lint CLI partial: exit 0, `mode: partial`, `status: incomplete`, 99 missing carriers enumerated, `partial_mode_not_full_acceptance` present (`lint_partial.txt`).
- Lint CLI full: exit 1, coverage `expected=111 covered=12 leaf_union=110 cover=v2_front_block`, exactly **99** `missing_coverage` errors, none on the twelve batch carriers (`lint_full.txt`).
- Coverage truth derived at lint time from `node_tree.json` (`is_leaf_heading` ∩/∪ `is_leaf`, front_block presence, mapping-row cover identity `document_control.front_matter → v2_front_block`).

## Verification And Gaps

- Verified: schema validation of all 24 authored files against the accepted library models; fail-closed registry load; vocabulary closure; conditional/forbidden non-contradiction; CtQ anchor resolution; skill/contract/template identity binding; all 48 positive/negative fixture behaviors with per-node named error codes; partial-vs-full lint semantics; CLI read-only/stdout behavior (input directory listing unchanged).
- Explicitly deferred (by design, recorded as `deferred_qc_obligations` in every deterministic pass): medical/QC judgment, positive QC rule and skeleton-risk evaluation, conditional-rule execution, and all native Word checks (field updates, landscape section, header/footer, table styles — 7R obligations). The partial registry is never full acceptance.
- Gaps: the remaining 99 carriers (later batches) are uncovered, as expected; the wrong-source family proves source-role admission failure deterministically but cannot prove clinical wrongness of values — that stays with product QC; `sk-`-style credential scan and `material_sha256` stability were not separately exercised beyond the library's own round2 tests.

## Next Action For Codex

1. Independently review the 24 authored contract/skill files and 48 fixtures against the TP-MA-07 v2 source (clinical source interpretation and acceptance are yours; my fixture values are synthetic, not project facts).
2. If accepted, keep these files as the batch1 slice and reuse `assemble_chapter_registry.py` for batch2; the 99 missing carriers and the full-mode lint output define the remaining coverage surface.
3. Optionally consider whether the pre-existing `test_raw_tempfile_var_alias_path_accepted` failure under the `env -i` recipe (missing `TMPDIR`) should be fixed in that test's environment setup — outside my scope, untouched.
