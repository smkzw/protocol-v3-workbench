# Same-session bounded delta review

Continue the existing general_single_object session. Original read-only boundaries
and isolated synthetic testing environment remain. No product/source/test edits,
no network/model/service calls, no credentials/global/live/monitoring changes.
Runner owns this report. Do not repeat the original broad exploration.

Additional allowed readset: services/api/app/medical_writing_template_upgrade.py,
tests/test_medical_writing_template_upgrade.py,
tests/test_medical_writing_study_consistency.py,
tests/test_runtime_directory_configuration.py, corresponding greenfield builder
and repository functions, plus the new XMLs below. Inspect current diffs and
independently run these THREE test files in an isolated runtime, not the fullsuite.

Changes landed after your initial scope snapshot:
- Template upgrade preserves typed completion state. Migration into an empty
  actionable-blocker target now becomes unclassified/template_upgrade_candidate,
  removes obsolete empty-body metadata and retains source provenance. New JSON
  reload regression was red: legacy_template_migrated_blocker_red.xml.
- Existing template test now verifies migrated text/rollback/replay but expects
  incomplete document export rejection. No Word fidelity claim.
- Study consistency rebind already succeeds before its final independent export
  call. Current test retains rebind/reconcile/refreeze assertions and distinguishes
  final_freeze_readiness.ready from substantive_body_missing on final export.
  Assess that actual call sequence; do not assume rebind invokes export. We do
  not pad fixture text or weaken the body threshold. Semantic quality replaces
  length-only quality later in3R/7R; this change does not claim clinical acceptance.
- Runtime path diagnostic pinpointed only ocr_gateway_configured=False on fresh
  credential-free runtime. Test keeps all store path assertions; bool readiness
  replaces unconditionalTrue. No actual OCR config/model change.

Evidence under runs/mw_protocol_v3_1r_integration_20260905/:
legacy_template_upgrade_status.xml,legacy_template_upgrade_final.xml,
legacy_template_migrated_blocker_red.xml,p1r_post_legacy_repairs.xml
(1538passed37.15s; allv3 plus templateupgrade/studyconsistency),
legacy_runtime_directory_diagnostic.xml,legacy_runtime_directory_projection.xml,
legacy_study_consistency_completeness.xml.

Correct/qualify original findings against source: ProtocolSection is legacy,
while2R NodeExecutionContract is in protocol_v3.py; a shared defect must be proved,
not inferred from the phrase typed readiness. Translation anchor assertions target
ReferenceTranslationBatchPanel.jsx, NOT App.jsx. App has a shared conditional
emptyProjectMetricValue; unsupported translation anchors remain a6R behavioral
obligation. Missing files observed now do not prove they NEVER existed.
Source-registry path literals are synthetic monitoring test examples; leave them.

Do not activate/change legacy Flash route. Tests mirror existing policy only;
v3default remainsGLM, alternative requires user's explicit activation.
Record optional positive endpoint-ready and nonempty substantive-seed checks as
followups if still absent. No need to solve monitoring fixture ownership here.

Return compact: defects still open with exact source evidence; corrected findings;
actual test result; whether scoped legacy repairs are acceptable and remaining
historical/monitoring/frontend issues can remain explicit release obligations while
offline2R construction proceeds. Do not claim fullrepositoryPASS or final acceptance.
