# Fact Inventory Summary — Task 3R.4A (worker_01)

2026-09-12 · Read-only inventory. No product/type edits, no clinical values, no type inference from path names.
Full per-path data: `fact_inventory.json` (same directory, 724 entries).

## 1. Coverage: the 724 count reconciles exactly

Independent extraction from the 111 authored contract JSONs
(`config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/`) over the four structured
fact-path field families gives **exactly 724 distinct paths**, and the set equals the accepted registry's
`fact_vocabulary` (724, duplicate-free):

| Field family | Distinct paths |
|---|---|
| `substantive_content.fact_requirements[].fact_path` | 718 |
| `conditional_applicability_rules[].triggering_fact_paths[]` | 49 |
| `conditional_applicability_rules[].required_when_active_fact_paths[]` | 72 |
| `ctq_items[].linked_fact_paths[]` | 214 |
| `registry_consistency_obligations[].eligibility_fact_paths[]` | 18 |
| **Union** | **724** |

- Union − vocabulary = ∅; vocabulary − union = ∅. No unused vocabulary entries, no undeclared uses.
- `source_and_graph_summary.json` `fact_path_count: 724` is `len(registry.fact_vocabulary)` — same set.
- Disk contracts vs registry-embedded contracts: 111/111 compared, **0 value-level conflicts**; 32 files
  differ only by registry-side default-filled keys (empty-list defaults, `schema_version` literals).

## 2. Canonical schema: flat key lookup, no per-path types

- `StudyDefinitionV3.facts: dict[NonEmptyText, JsonValue]` — `packages/contracts/workbench_contracts/protocol_v3.py:654`.
  Fact "resolution" is flat-dictionary key lookup; values are frozen JsonValue (`:674`). **The canonical
  contract declares no per-path type, unit, or timing for any path.**
- `FactRequirement` (protocol_v3.py:1195–1198) carries only `fact_path` / `obligation(required|optional|forbidden)` /
  `rationale`. No type or alias field exists anywhere in the contract layer.
- `fact_vocabulary` is an authored closed list of 724 path strings (merged by
  `scripts/qc/protocol_v3/assemble_chapter_registry.py`, sorted set union of batch documents). Identity only.
- Binding layer at HEAD 84488d3 (`chapters.py`): `ChapterSkillInput.resolved_facts: Mapping[str, str]`,
  `ContentFact.value: Optional[str]`, `ContentCell.value: Optional[str]` (display text, deliberately separate).
  Probe evidence `conditional_probe.json`: boolean true/false, number, structured value → rejected (`string_type`);
  literal `"false"` string → accepted. This is the type-fidelity defect 3R.4A step 1 targets.
  Note: the working tree carries the parent's unaccepted in-flight JsonValue edits to `chapters.py`; HEAD state
  is recorded as the accepted binding evidence. `ContentCell` display/typed separation already matches design §4.1.

## 3. Type evidence: zero non-string evidence for all 724 paths

- All **2487** fixture fact values across **558** fixtures are JSON strings. No null, no boolean, no number,
  no list, no object.
- "Absent" is encoded as whitespace strings (51 occurrences).
- Registry `authority` text declares 「布尔触发事实采用裸true/false编码」; fixture scan confirms the 49 trigger
  paths include bare-string `'true'`/`'false'` encodings (e.g. `statistics.interim.applicable: 'false'`,
  `irc.applicable: 'false'/'true'`), while other trigger paths carry prose values despite boolean-looking names
  (e.g. `design.rescue_treatment_planned`, `estimand.primary.background_treatment`) — names are **not** type evidence.
- Consequence for 3R.4A step 3: every per-path registration (canonical direct read / deterministic
  derivation-alias / explicitly unsupported) must be **newly declared**; there is no current declared type to
  preserve or discover. All 724 entries in `fact_inventory.json` carry
  `type_evidence.unsupported_or_ambiguous` = clinical semantic type/unit/timing NOT declared; do not infer from name.

## 4. Conditional membership

- **49 trigger paths**, 49 condition rules across contracts. Fixture encodings per trigger path are recorded in
  `fact_inventory.json` `conditional_membership.trigger_paths_with_fixture_encodings`.
- **6 conditional-only paths** (never unconditionally declared): `population.exclusion.contraception_criterion_ref`,
  `procedure.contact_visit_{assessments,date,modality,reason}`, `safety.central_lab_applicable`.
- **Self-referential rule**: `applicability:n-6-1-2:escalation` (v2_n_6_1_2) —
  `intervention.dose_escalation_or_dlt_logic` is both trigger and required-when-active.
- **required_when_active ∩ same-contract unconditional required**: 14 rule-level occurrences across 10 contracts
  (e.g. all 10 `statistics.interim.*` detail paths in v2_n_11_4_9; 7 `future_use.*` in v2_n_12_7) — matches the
  review's 14-item finding; disposition belongs to 3R.4B.

## 5. Evidenced aliases, projections, separations

- **Projection family (13 rationales, all v2_n_1_1 `synopsis.*` rows)**: each declares 「汇总行为正文既定事实的投影，
  不设第二可编辑事实存储」. Includes the design-named pair `synopsis.sample_size` (projection of the statistics
  chapter result; `statistics.sample_size.reproducible_result` is the computation-side fact, v2_n_11_1).
- **Reuse bindings (25 rationales)**: carriers rebind the same path instead of new storage, e.g. cover/summary reuse
  of `framing.protocol_id` / `framing.document_title` / `framing.version`; `v2_n_11_4_3_1` explicitly: primary
  analysis must reuse `picos.primary_endpoint`, 不建立第二终点存储.
- **Separation constraints (12 rationales)** — evidenced non-aliases: `document_control.version_date` vs
  `framing.version` (分离承载); `picos.population_summary` vs `estimand.primary.population_summary_measure`
  (含义不同，禁止互相替代); `efficacy.assessment_instrument_or_scale` not replaceable by "按 SoA"; others listed in JSON.
- **Obligation variation across chapters (8 paths)**: required in some chapters, optional in others
  (e.g. `picos.population_summary`) — chapter-scoped variation, not a conflict; recorded per path.
- **Forbidden obligations (82 paths)**: `*.template_example_*` bans and anti-fabrication integrity facts
  (e.g. `compensation.amount_unconfirmed`, `confidentiality.invented_person_or_facility`).

## 6. Explicitly unsupported / ambiguous

- Clinical semantic type, unit and timing: **not declared for any of the 724 paths** (see §3).
- 6 conditional-only paths have no unconditional obligation owner; their resolution depends on 3R.4B predicates.
- The 14 required-when-active ∩ unconditional-required overlaps and the 1 self-referential rule are recorded
  as current contract state, not adjudicated here (3R.4B scope).

## 7. Sources bound by hash

`fact_inventory.json` §`sources`: registry e4fd25b2…, contracts dir concatenated 174e4bd4…,
protocol_v3.py b76a048f…, review summary fa182d9e…, probe 7b8f9b10…, chapters.py@HEAD 9297ed91….
