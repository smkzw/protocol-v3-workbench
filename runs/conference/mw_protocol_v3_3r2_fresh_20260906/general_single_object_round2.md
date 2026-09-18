# Conference Participant Output: mw_protocol_v3_3r2_fresh_20260906 - general_single_object

## Boundary Check

- Read-only repair review in runner cwd; inspected `packages/contracts/workbench_contracts/protocol_v3.py:1177-1565`, `tests/protocol_v3/test_chapter_contract_schema.py` in full (748 lines, 14 tests), `runs/mw_protocol_v3_3r2_contracts_20260906/test_codex_positive_obligations.py` (9 cases), and runs-dir artifacts. No source edits, no model/browser calls, no production paths. Codex retains final acceptance; this verdict is schema-review input, not task closure.

## Independent Work Product

**Verdict: ACCEPT** — all four Codex-ordered repairs verified present, effective, and regression-clean. Round-1 blocking defect (HOLE-1) is closed under the strict Q1 reading; Q2/Q3 implemented as directed.

### Repair verification (evidence, all observed this pass)

1. **Required-positive substantive validator (Q1 strict).** `protocol_v3.py:1477-1484` now requires a REQUIRED fact, REQUIRED claim, evidence requirement, or project-specific element; bare `any()` gate retained above it (`:1464-1465`), object-only guard retained (`:1466-1476`). Probes: forbidden-only, optional-only, allowed-only, and qualified-only (with conditions) payloads **all rejected** with "content contract requires a positive substantive obligation". This is stricter than my round-1 proposal (which would have counted optional/allowed as positive) — the strict reading is correctly implemented: an empty body still satisfies none of these forms.
2. **Mandatory embedded `substantive_content` on `ChapterContractV2` with chapter-id match.** Field at `:1499` (required, no default); identity check at `:1512-1513` ("belongs to a different chapter contract"). Probes: mismatched `chapter_contract_id` in embedded payload rejected (matches `'different chapter'`); embedded `project_specific_elements` append moves chapter `material_sha256`; chapter `canonical_state` flip (frozen→quarantined) still hash-neutral. Format-plus-QC-only chapter construction (Codex case 6) rejected — my round-1 OBS-8 hole is closed by construction, not just by convention.
3. **Mandatory repair policy for dependencies (Q2).** `:1541-1542` raises when `dependency_ids` non-empty and policy is `None`. Probe: `_chapter_contract_v2(dependency_repair_policy=None)` rejected. Control fixture (`test_chapter_contract_schema.py:565-581`) now declares `dependency_ids=()` + `policy=None` — no longer inherits the irrelevant `contract:background:v1` default; template provenance stays in `template_id`/`template_sha256` + project elements, not in the dependency graph, exactly per Q2.
4. **Stable `required_object_cells` restored.** `StructuralObjectObligation.required_object_cells: tuple[StableId, ...] = ()` at `:1249` with uniqueness validator (`:1251-1254`); Codex roundtrip case passes. Default `()` keeps all existing builders valid; v1 `required_object_cells` semantics (e.g. `soa:visit:week12`) have a typed v2 home again.

### Test evidence (observed counts)

- Five-file focused command: **222 passed** (unchanged count — all 14 schema tests retain their assertions and pass against the stricter validators; `dependency_ids=()` case at `:662-663` still raises via the undeclared-dependency path since the default policy references the background contract).
- Codex file (9 cases: 5 parametrized no-positive-obligation + format/QC-only + deps-need-owner + cell roundtrip + embedded-identity/hash): **9 passed**.
- **Total 231 = 222 + 9**, matching the expected count exactly.
- v1 intact: pin JSON + all 6 dependency-bound material hashes pass inside the 222; `v1_fixtures_before.json` ≡ `v1_fixtures_after.json` ≡ `codex_v1_fixtures_after_repair.json` (`cmp` clean, 38204 bytes each); `substantive_content` absent from both v1 classes' `model_fields` (probed).
- Artifact trail: 5 red/verify XMLs preserved (`codex_initial`, `codex_positive_red`, `codex_extended_red`, `codex_binding_verify`, `codex_first_repair`); prior green/red logs retained.

### Self-challenge corrections to round-1 findings

- Round-1 HOLE-1 remedy (count optional/allowed as positive) is **superseded**: Codex Q1 strict correctly observes permissions/prohibitions impose nothing an empty body violates. Verified the stricter gate; my leniency concern about conditional chapters is answered by evidence requirements + project elements still counting as positive, plus conditional rules living on the chapter side.
- Round-1 OBS-4 (deps-without-policy) and OBS-8 (minimal-substance chapter) are **closed**, not deferred.
- Round-1 HOLE-3/HOLE-5/OBS-6/OBS-7/free-text-anchor notes collapse into the Q3 routing below; HOLE-5 (case-variant styles) re-probed and **still present** — carried as a minor limitation, not a defect.

## Evidence And Assumptions

- **Evidence:** suite outputs (222, 9); 10 in-memory probes (4 strict-positive rejections, identity rejection, hash coupling both directions, control provenance binding with hash distinctness, deps-policy rejection, v1 field absence); `cmp` triple-identity; file/line citations above; XML/JSON directory listing with sizes.
- **Inference:** the four repairs compose without conflict (control path satisfies the positive gate via project elements; default builders satisfy embedding via matched ids; mandatory-policy rule is vacuous for empty deps). No existing-test assertion required weakening — only builders gained the newly required content.
- **Assumptions:** `PYTHONPATH=tests/protocol_v3:...` resolution of the Codex file's `from test_chapter_contract_schema import ...` matches the runner's intended harness (it passed as run); XML contents taken as preserved evidence without re-parsing; downstream reducer/repository non-consumption of v2 types confirmed by design scope, not by re-reading those consumers this pass.

## Risks, Gaps, And Verification Needs

- **Explicitly deferred to 3R.3 (Q3, accepted):** cross-contract vocabulary lint (dangling CtQ/fact anchors are free text), content-forbidden vs conditional-required contradictions, applicability resolution. These are real but out of schema scope by Codex decision — 3R.3 must list the lint as a deliverable, not assume current contracts are clinically correct.
- **Residual minor limitations (no action required for 3R.2):** case-variant style conflicts accepted (exact-string check; OOXML `styleId` is case-sensitive, so any fix must compare-normalized, never rewrite); non-contiguous repair sequences accepted; QC rule specificity unenforceable at schema level (static contract vs document QC distinction stands); evidence-only content counts as positive via free-text admission types.
- **Integration note for 3R.3:** `ChapterContractV2` is now inseparable from its embedded content — the 110-contract authoring must emit the nested form; any consumer expecting standalone chapters needs the new shape. No product code changed in this task, so nothing is broken, but 3R.3 should not re-split them.

## Recommended Next Step

- Accept 3R.2 schema work; carry two items into 3R.3 acceptance: (a) cross-contract lint (vocabulary resolution, forbidden/required cross-checks, CtQ anchor resolution) as an explicit deliverable; (b) 110 contracts emitted in embedded chapter+content form with per-chapter repair policies wherever `dependency_ids` is non-empty.
- No further schema repair rounds needed from this role; no open questions — Q1/Q2/Q3 all verified as implemented.
