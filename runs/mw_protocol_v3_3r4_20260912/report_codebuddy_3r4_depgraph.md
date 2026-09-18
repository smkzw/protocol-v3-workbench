# Execution report: 3R.4 dependency graph (codebuddy/deepseek-v4.1-flash:max)

Saved by dispatching ZCode main owner from the runner stream.

---

STATUS: COMPLETED

FILES_CREATED
- `services/api/app/protocol_workflow/registries/dependency_graph.py` (NEW, 664 lines, stdlib-only: dataclasses/enum/hashlib/json/collections; sole imports from the app are the existing `chapters.load_chapter_registry` / `ChapterRegistryDocument`)
- `tests/protocol_v3/test_dependency_graph.py` (NEW, 734 lines, 10 tests)
- `runs/mw_protocol_v3_3r4_20260912/red_3r4_dependency_graph_pytest.xml`
- `runs/mw_protocol_v3_3r4_20260912/green_3r4_dependency_graph_pytest.xml`
- `runs/mw_protocol_v3_3r4_20260912/green_3r4_batch1_regression_pytest.xml`
- `runs/mw_protocol_v3_3r4_20260912/green_3r4_focused_and_batch1_pytest.xml` (combined run, 27 passed)
- `runs/mw_protocol_v3_3r4_20260912/adjacent_suites_3r4_pytest.xml` (extra regression probe, 117 passed)
- `runs/mw_protocol_v3_3r4_20260912/depgraph_3r4_diagnostics.json`
Nothing else was written. `find . -newermt <session start> -type f` outside my three owned paths lists only dispatcher/runner files (`context/…context.md`, `prompts/…md`, `dispatch.json`, `stdout_stream.jsonl`, `stderr.txt`). No contract/skill/batch JSON, core schema, loader/checker, assembler/lint, plan or checkpoint was modified. Runner-managed `report_codebuddy_3r4_depgraph.md` was not written by any tool.

RED_EVIDENCE
- `runs/mw_protocol_v3_3r4_20260912/red_3r4_dependency_graph_pytest.xml` — testsuite `errors="1" failures="0" tests="1"`, error text: `ModuleNotFoundError: No module named 'app.protocol_workflow.registries.dependency_graph'`, collected before the module existed. No xfail, no skipped tests anywhere.
- Transparent RED-phase corrections (both keep exact-equality assertions; neither weakens a binding test): (a) the `unknown_dependency_target` location expectation was written in the reverse of the module's uniform `dependency->dependent` order used by its sibling assertion — expectation corrected, module convention unchanged; (b) the single-adoption test asserted `combined > single` using `picos.intervention_dose_regimen`, whose closure turned out to be a subset of the endpoint closure, so the second probe was switched to `intervention.dose_regimen` (disjoint 7-chapter chain) and the union assertion became exact (`== 31`).

GREEN_EVIDENCE
Command (exact, from Success Criteria):
`env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:. runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest tests/protocol_v3/test_dependency_graph.py -q -p no:cacheprovider --tb=short --junitxml=…`
tail: `..........  [100%]` / `10 passed in 1.28s` → XML `runs/mw_protocol_v3_3r4_20260912/green_3r4_dependency_graph_pytest.xml` (`errors="0" failures="0" skipped="0" tests="10"`)
Batch1 unchanged: same env, `tests/protocol_v3/test_chapter_batch1.py` → `17 passed in 1.43s` → `runs/mw_protocol_v3_3r4_20260912/green_3r4_batch1_regression_pytest.xml` (`tests="17" failures="0" errors="0"`)
Extra adjacent regression probe (same env): `test_frozen_authority_manifest` + `test_repository_hygiene` + `test_registry_loading` + `test_all_chapter_contracts` + `test_chapter_contract_schema` + `test_source_baseline` → `117 passed` → `runs/mw_protocol_v3_3r4_20260912/adjacent_suites_3r4_pytest.xml`

DESIGN_NOTES
- Edge typing. Three frozen dataclasses, one per relationship kind, each exposing `kind`: `FactMembership` (chapter↔fact path), `SchedulingEdge` (upstream dependency → dependent chapter, plus `repair_owner` / `repair_policy_id`), `ConsistencyEdge` (canonical `left<right` pair, `reciprocal=True`, `shared_fact_paths`). `graph.edges` returns all three; `edge_kinds()` names them. The scheduling relation is the only one that enters the DAG; it comes exclusively from explicit `ChapterContractV2.dependency_ids` — no shared fact, cross-reference or numbering is ever promoted into a hard edge (test asserts the edge set equals the raw declared pairs, 41 edges over 34 carriers).
- Conditional-fact resolution. Membership rows carry `source ∈ {fact_requirement, conditional_trigger, conditional_when_active}` and `obligation` (required/optional/forbidden; `None` for conditional rows) plus `conditional_rule_ids`. Every obligation is indexed and both `conditional_applicability_rules` fields (triggering paths and when-active obligations) are indexed, so conditional-only paths such as `procedure.contact_visit_date` are first-class change targets; accepted registry indexes 724 distinct paths across 891 rows (759 requirement rows, 52 trigger rows, 80 when-active rows; required 586 / optional 88 / forbidden 85).
- Impact algorithm. Seeds = chapters declaring any changed path; then a deterministic level-BFS closure adds reciprocal consistency neighbours (undirected, transitive) and scheduling dependents (downstream only, following the DAG), repeating to a fixed point. Classification = the relation by which a chapter first entered the set, so `direct + consistency + scheduling` is an exact partition of the affected set. High-fan-out probes: `picos.primary_endpoint` 4 direct → 24 affected (4 direct/14 consistency/6 scheduling); `picos.intervention_dose_regimen` 1 → 24; `intervention.dose_regimen` 1 → 7 (1/1/5). No cap, no truncation; each closure equals an independent naive closure computed in the test straight from the raw accepted JSON.
- Identified errors, never dropped. Unknown dependency target → `unknown_dependency_target` error finding and the edge stays in `edges`/`findings` (it is excluded only from node ordering, so it cannot corrupt or block the DAG). Declared dependency not covered by the repair policy → `missing_repair_owner` finding with `repair_owner=None`. A hard scheduling cycle raises `DependencyGraphError` listing the unresolved carriers; shared-fact consistency links never legalise it, and the same fixture with the closing edge removed builds cleanly with all pairwise consistency edges.
- CAS-purity declaration (in the module docstring). `build_dependency_graph` and `DependencyGraph.impact` are pure functions of (accepted registry, changed material facts): no module-level mutable state, no cache, no store; every value object is a frozen dataclass of tuples/scalars; `impact_sha256 = f(registry_sha256, normalised+sorted changed paths, classified affected sets)` is the single adoption key, identical across repeated calls, reordered/duplicated inputs and a rebuilt graph; `projection()`/`projection_sha256()` are a read-only rendering carrying the registry identity, explicitly "not a content authority and not a second editable store". Confirmation invalidation is keyed to changed material facts: an unindexed path invalidates nothing (asserted) rather than reopening all 111.
- Input discipline. `build_dependency_graph` accepts an already-loaded `ChapterRegistryDocument`, a path or a mapping, and routes paths/mappings through the existing fail-closed `load_chapter_registry`; all fixture registries in the tests are validated by that same loader before use. `registry_sha256` is the SHA-256 of `document.model_dump_json()` (accepted registry: `4b9a54d5551b62f9…`; projection digest `73e42eb136e43fb8…`; accepted graph findings: `()`).

TESTS
Binding six: `test_hard_scheduling_cycle_rejected`; `test_reciprocal_consistency_links_are_legal_and_create_no_false_cycle`; `test_missing_repair_owner_and_unknown_target_are_identified`; `test_unrelated_chapters_remain_stable`; `test_broad_dose_endpoint_change_returns_every_affected_chapter_without_truncation`; `test_same_fact_update_has_a_single_adoption_effect`.
Extras (4): `test_typed_edges_keep_the_three_relationship_kinds_distinct`; `test_accepted_registry_graph_is_complete_acyclic_and_error_free`; `test_conditional_fact_paths_resolve_to_their_chapters`; `test_build_dependency_graph_accepts_document_mapping_and_path`.

DEFERRED (deliberately out of scope)
End-to-end document-edit impact pipeline and its store wiring (remains 6R); any registry/contract content change; API/router/service surface; persistence or CAS-ledger implementation; medical adequacy or QC judgment on any fact, chapter or contract; frontend/visual work.

LIMITS_AND_NEXT (for the reviewer and main owner)
- The impact closure is defined as: consistency neighbours transitively **plus scheduling dependents downstream**. Upstream re-checking after a downstream change is intentionally not propagated; if the owner wants bidirectional propagation, that is a semantic decision, not a defect — flag it rather than assuming.
- `ContractV2` cannot express a partially covered repair policy as an error, so `missing_repair_owner` is detectable only at graph level; the accepted registry has zero such findings today.
- Consistency linkage is sparse by construction (43 edges, 30 of 111 carriers linked; 81 chapters have no shared-fact partner) because 724 distinct fact paths serve 111 chapters. Fan-out is therefore registry-bounded: 24 of 111 carriers is the observed maximum closure for the highest-fan-out dose/endpoint facts. This is the accepted artifact's real shape, not a truncated result.
- Fixture-based defect tests use synthetic registries that pass the real loader; the cycle/unknown-owner/dangling cases do not exist in the accepted registry, so they are proven on fixtures plus the accepted-registry soundness test.
- Not claimed: task closure, acceptance, integration, medical adequacy — acceptance belongs to the dispatching main owner; a fresh independent reviewer should challenge the closure semantics, the classification partition and the CAS-purity claim.