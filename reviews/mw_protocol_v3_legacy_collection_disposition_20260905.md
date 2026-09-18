# Legacy collection reconciliation — open

This is evidence and disposition planning, not a passing full-repository result.
Current scope is the isolated Protocol v3 project; no live code or historical
records have been changed. The four collection failures remain due before P1R-G1.

| Test | Observed dependency | Required disposition |
|---|---|---|
| test_cross_indication_quality_scorecard_schema.py | jsonschema plus missing records/active_slices/medical_writing_cross_indication_reference_gate_20260718/quality_scorecard.schema.json | Identify historical asset authority; do not invent schema from expected examples. Installing dependency alone is insufficient. Preserve scientific quality obligations in applicable v3 tests. |
| test_phase1_translation_manifest.py | module loaded from absent records/active_slices/medical_writing_phase1_autoimmune_mnc_corpus_20260716/build_medical_review_manifest.py | Historical batch-tool contract, not an import of product v3. Locate authority or explicitly classify archived-tool suite; never relaunch translation to recreate it. |
| test_phase1_translation_runner.py | absent run_production_translations.py under same historical batch | Same dependency reconciliation; no download/OCR/model execution authorized by this test problem. |
| test_medical_writing_dynamic_section_matrix.py | absent private _REQUIRED_CORE_BODY_SEMANTIC_IDS in current legacy template module | Scientific projection obligations still matter. Do not skip/delete suite or invent a constant solely for collection. Reconcile actual module behavior with template authority and v3 leaf contracts. |

The dynamic matrix also explicitly expects drafting placeholders (`待补充`,
lines405–427 and463–465), whereas final v3 output must contain none. This is
not necessarily a conflict: unfinished editor state and final export have
different contracts. Any migration must preserve that distinction. Required
chapters cannot silently disappear; unknown clinical facts cannot be fabricated.

Adjacent source inspected: medical_writing_protocol_template.py retains
_RETAIN_NA_SEMANTIC_NODES and _project_chapter_body_draft, so the absent private
constant is not proof that all legacy projection functionality was removed.
No current test expectations were changed in this reconciliation pass.

Evidence: runs/mw_protocol_v3_1r_integration_20260905/1r2_full_repo_collection.xml
(8988 collected, four errors); source reinspection during1R.3 fresh review wait.
Next: establish the explicit maintained-suite boundary and current projection
obligations before changing test selection. Report excluded historical suites
as not executed, never PASS. User-authorized obsolete-constraint upgrades do
not authorize erasing scientific coverage.

## Current-source clarification during 1R.4 verification wait

The missing core-body constant is not the only drift. Current
medical_writing_protocol_template.py1934 deliberately returns empty clinical
text when facts are absent; _section_drafting_readiness separately assigns an
actionable blocker with missing inputs and next actions, persisted on seeds at
3105. This contradicts old dynamic-matrix tests405ff expecting a drafting
placeholder, but does not itself imply a lost obligation.

Direct synthetic checks of maintained tests
test_medical_writing_protocol_template.py143 and184 passed2/2 in0.65s:
runs/mw_protocol_v3_1r_integration_20260905/legacy_readiness_obligation_probe.xml.
They cover applicable I/II/III sections having classified state, complete blocker
details, and materialization preserving the blocker without inserting it into
clinical prose. No Word/model calls or live writes occurred.

Next disposition must preserve the dynamic matrix's per-study applicability and
confirmed-fact obligations while replacing obsolete placeholder assertions with
typed-readiness checks. Do not restore a dead constant solely to unblock import.
This is new evidence, not full-repository acceptance; all four collection debts
remain open until tests are reconciled and rerun.

Full dynamic-matrix test read also found its
test_projected_seed_text_never_contains_fabricated_clinical_numbers only checks
that text does not start with `（待补充`; it does not compare numeric facts or
their sources. Its green status cannot establish absence of invented numbers.
Retain historical test; reconciliation needs an actual confirmed-fact/provenance
comparison, distinguishing boilerplate numbering from clinical parameters. Do not
claim scientific coverage from this misleading test name. Conditional modules
and typed design fixture drift also require reconciliation, not just the import.

## 20:00 current reconciliation

Dynamic matrix collection repaired without restoring the dead private constant.
Its old required-core/nonempty placeholder expectations were superseded by typed
readiness for EVERY applicable chapter, preserving existing test functions and
all applicability/isolation/verbatim assertions. Unknown facts require empty
prose plus actionable metadata.19existingtests passed0.45s. Added a real numeric
provenance test: synthetic137,2:1,12.5% cannot appear in sample-size chapters
until source is confirmed, then must project verbatim with correct source ID.
Combined dynamic/template suite47passed1.57s inlegacy_dynamic_provenance_green.xml.
This is a local legacy projection obligation, not TP-MA-07v2 leaf acceptance.

The other three tests were read fully: they depend exclusively on absent dated
records batch artifacts, not product imports. Retain original tests unchanged;
classify them as historical-tool tests NOT EXECUTED, not product PASS. Their
scientific obligations remain: reviewed scores cannot be fabricated; automated
translation fidelity is not medical approval/admission; source and contract
hashes must match; review notes bind valid segments. Explicit current product
coverage is due under3R/4R/7R, not inferred from these absent assets.

Next collection command may explicitly ignore these THREE named historical
files to inspect maintained code; no hidden pytest.ini/conftest exclusion.
This does not claim an unqualified full-repository pass. No source schema or
translation script is fabricated from examples; no old pipeline rerun.

## Maintained runtime first pass and bounded reconciliation

maintained_legacy_runtime_20260905.xml:20failed,3466passed,1skipped455.93s;
maxfail20 stopped at45%, remaining cases unexecuted. This is not full PASS.
Two chapter projection placeholder assertions are now typed readiness checks;
all chapter/dynamic/template cases59passed1.82s, legacy_all_readiness_green.xml.
Reference-context test passes with WORKBENCH_INCLUDE_REFERENCE_PROJECTS=true
in a fresh isolated runtime. The RUX approval test still fails StopIteration
in that environment; it is monitoring-owned and is not modified here.
Evidence legacy_reference_environment_recheck.xml:1passed1failed25.85s.

Other findings remain open, not silently excluded: route namespace assertion;
translation backend runnable status; synthetic batch retry state; frontend
disabled explanations/empty state/frozen translation scope source assertions;
monitoring source-manifest/risk assertions (readonly); missing isolated8911
launcher; competitor reason specificity; superseded model restriction tests;
missing-thread422versus404; binding fixture export body threshold.

The latter fixture supplies19-character imported text without original_protocol_docx
source_kind; repository applies its existing80-character substantive threshold
even to draft_preview. Do not simply lower final acceptance to make this pass.
Review product requirement separately: partial editor preview and complete Word
export should be distinct; body length alone does not establish scientific
completeness. Carry semantic completeness refinement into3R/7R.

Bounded fixture corrections (no product code changes):
- Frozen-route namespace assertion now expects the actual isolated role profile,
  additionally checks routeB endpoint/model while all frozen physicalrouteA
  assertions remain.9passed0.40s,legacy_route_freeze_namespace_final.xml.
- Retained legacy model policy already explicitly permits exact DeepSeekFlash
  authoring/synopsis. Superseded two Pro-only assumptions; retained missing/wrong
  model negatives and checks every task's actualresponseidentity.8passed0.32s,
  legacy_retained_model_policy.xml. This does not change v3GLMdefault or activate
  another model; no new security engineering.
- Missing-thread fixture now uses a valid server-generated idempotency key
  instead of two-characterk1, reaching threadlookup without changing404/409
  expected.5passed2.47s,legacy_missing_thread_valid_request.xml.
- ImportedDocumentService fixture now declares original_protocol_docx together
  with its existing docx:paragraph locator, matching its source-backed purpose.
  This exercises existing imported-source path, not weakening generated-document
  completeness.12passed0.74s,legacy_import_binding_source_kind.xml. Synthetic
  binding tests are not evidence of source DOCX fidelity or scientific sufficiency.

Full remaining maintained run is separate (20961), collected before these last
fixture revisions; incremental verification above must accompany its result.
