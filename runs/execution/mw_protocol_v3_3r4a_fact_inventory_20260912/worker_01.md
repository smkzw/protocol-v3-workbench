All verification checks pass: 724 entries, zero missing fields, spot-checks consistent with sources, and the only files I wrote are the two authorized artifacts (the modified files in git status are the pre-existing session-start state, untouched by me).

# Execution Output: mw_protocol_v3_3r4a_fact_inventory_20260912 - worker_01

## Boundary And Context Check

Read the two assigned context files first (`context/..._execution_context.md`, `plans/codex_execution_..._20260912.md`). Worked read-only inside the workspace; wrote exactly two new artifacts under `runs/mw_protocol_v3_3r4a_20260912/fact_inventory_worker/`. No product/source/test edits, no services, no model/OCR/translation calls, no web, no cleanup, no recursive agents. `registries/chapters.py` was read only via `git show HEAD:` for binding-type evidence (the working tree carries the parent's in-flight JsonValue edits, which I did not use as inventory authority and did not modify). No acceptance claimed; Codex retains final authority.

## Work Performed

Complete read-only inventory of the 724 declared chapter fact paths, from four evidence layers: plan/PRD/design, the accepted assembled registry + 111 authored contracts, the canonical contracts module, and the review probes.

**Key findings:**

1. **Coverage reconciles exactly.** Independent extraction from the 111 contract JSONs across the four structured fact-path field families yields exactly 724 distinct paths, and the set equals the registry `fact_vocabulary` (724, duplicate-free; union−vocab = ∅, vocab−union = ∅). `fact_path_count: 724` in `source_and_graph_summary.json` is `len(fact_vocabulary)`. Family counts: fact_requirements 718, triggers 49, required-when-active 72, ctq links 214, registry-consistency 18. Disk contracts vs registry-embedded contracts: 111/111 compared, 0 value-level conflicts (32 files differ only by registry-side default-filled keys).

2. **Canonical schema is flat key lookup with no per-path types.** `StudyDefinitionV3.facts: dict[NonEmptyText, JsonValue]` (protocol_v3.py:654); `FactRequirement` has only path/obligation/rationale (1195–1198); no type/unit/alias field exists anywhere in the accepted contract layer. Binding layer at HEAD: `resolved_facts: Mapping[str,str]`, `ContentFact.value: Optional[str]`, `ContentCell.value: Optional[str]`; `conditional_probe.json` proves bool/number/object rejected, string `"false"` accepted.

3. **Type evidence: zero non-string evidence for all 724 paths.** All 2487 fixture fact values across 558 fixtures are JSON strings; "absent" is encoded as whitespace strings (51); trigger paths use bare strings `'true'`/`'false'` per the registry authority text (「布尔触发事实采用裸true/false编码」). Several boolean-*looking* trigger paths carry prose values — recorded, not type-inferred. Clinical semantic type/unit/timing is marked **undeclared for every path** in the artifact.

4. **Evidenced aliases/separations.** Projection family: 13 `synopsis.*` rationales declare 「投影…不设第二可编辑事实存储」， including the design-named `synopsis.sample_size` ↔ `statistics.sample_size.reproducible_result` pair. 25 reuse-binding rationales (e.g. cover/summary reuse of `framing.*`; `v2_n_11_4_3_1` forbids a second endpoint store). 12 separation constraints (e.g. `document_control.version_date` vs `framing.version`; `picos.population_summary` vs `estimand.primary.population_summary_measure` — 禁止互相替代).

5. **Conditional membership.** 49 trigger paths with per-path fixture encodings; **6 conditional-only paths** (`population.exclusion.contraception_criterion_ref`, `procedure.contact_visit_{assessments,date,modality,reason}`, `safety.central_lab_applicable`); 1 self-referential rule (`applicability:n-6-1-2:escalation`); **required-when-active ∩ same-contract unconditional required = 14 occurrences across 10 contracts** (matches the review's 14-item finding; disposition is 3R.4B scope, recorded here as current state). 8 paths show required/optional variation across chapters (chapter-scoped, recorded, not a conflict); 82 forbidden paths (template-example/anti-fabrication bans).

## Artifacts And Evidence

- `runs/mw_protocol_v3_3r4a_20260912/fact_inventory_worker/fact_inventory.json` (1.21 MB) — all 724 path entries with: per-chapter `fact_requirements` (node, contract_id, obligation, rationale), trigger/required-when-active/CTQ/registry-consistency links, in-text cross-references, reuse/projection/separation markers, fixture usage (kinds, encoded value samples), and a per-path `type_evidence` block that explicitly marks unsupported/ambiguous mappings. Plus meta sections: source hashes, coverage comparison, canonical-schema evidence, conditional membership, alias evidence.
- `runs/mw_protocol_v3_3r4a_20260912/fact_inventory_worker/fact_inventory_summary.md` — the concise evidence summary (sections 1–7 as above).
- Sources bound by sha256 in the JSON: registry `e4fd25b2…`, contracts dir concatenated `174e4bd4…`, `protocol_v3.py` `b76a048f…`, review summary `fa182d9e…`, probe `7b8f9b10…`, `chapters.py@HEAD` `9297ed91…`.

## Commands And Observations

Read-only inspection: `git show HEAD:...chapters.py` (binding types at accepted state; in-flight diff shown by `git diff` and recorded as context only); `python3` JSON extraction over the registry, 111 contracts, 558 fixtures, 8 batch documents, review probes; regex extraction of rationale cross-references; sha256 binding of inputs. Verification pass confirmed: valid JSON, 724 entries, 0 entries missing required fields, spot-checks (`synopsis.sample_size`, `statistics.interim.applicable`, `safety.central_lab_applicable`, `ae.template_example_ctcae_version`) consistent with sources, path-key set == vocabulary set, `git status` shows no writes by me outside the two authorized artifacts. One artifact bug found and fixed during verification (operator-precedence error made `conditional_only_paths` list 54 instead of 6).

## Blockers Or Missing Environment

None. All required inputs were present and readable.

## Rerun Requests Or Next Step

No rerun needed. For Codex: the inventory deliberately leaves type registration empty (nothing to discover in accepted artifacts), so 3R.4A's per-path resolution classes (canonical direct read / deterministic derivation-alias / explicitly unsupported) must be newly authored; the 14-occurrence intersection and the 6 conditional-only paths hand off to 3R.4B; the `intervention.dose_escalation_or_dlt_logic` self-referential rule may need a Codex ruling on whether trigger≠required is intended there.
