# Protocol v3 Task1R.1 no-loss decision wait — 2026-09-05 15:40 CST

## Pause state

Engineering baseline review consolidated; PhaseR/H-R and Task1R.1 accepted. Task1R.2 has NOT started. Waiting for the user's existing native choice: isolate legacy-only PDF test dependencies for full-regression compatibility, or move legacy PDF migration earlier. The latter changes the current phase scope; neither option is silently assumed. No active worker/reviewer runners or unknown outcomes remain at this checkpoint.

This is a dependency-route decision boundary, not product completion or user-requested cancellation. The user still authorizes continuous implementation after the choice. No new services/product models/OCR/translation/Word/live database were run. No native App goal mutation: get_goal at checkpoint still reports the obsolete paused objective; available API cannot rewrite/resume it. Current objective is in the additive Plan/tracking, not the old goal text.

## Authority and immutable anchor

All five user-supplied hashes rechecked at checkpoint:

| Authority | SHA256 |
|---|---|
| ../plan-upgrade-20260905/mw_protocol_v3_design_v1.3_20260905.md |d97a0d3de6f4a5cf3ed9b8c17d43e35895c04910605605be9f668aba0f80efc5|
| ../plan-upgrade-20260905/mw_protocol_v3_implementation_plan_v2_20260905.md |040eb6ad323047737e8be6a3a23344fdb719dc85230ef7994b96c9af29257607|
| ../plan-upgrade-20260905/mw_protocol_v3_execution_handoff_20260905.md |ab5136d65bedf28f81d6c64405f71130986fa415f0e1dbc7b7e7b793a149e200|
| .hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md |fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914|
| /Users/smkzw/Documents/康哲项目资料/SOP/SOP For AI/TP-MA-07 临床试验方案（2期或3期）_清洁版_v2.0_20260905.docx |018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756|

Planv2+currentadditiveamendment govern, not originalTask2.2/r42continuation or the oldnativegoal'sDeepSeek/cleanuptext. Read latest global/projectAGENTS and currentfilesystem before resume. User-approved1R.4compatibility-preserving simplification and engineering-onlysubAgents permitted remain binding; productcalls stillbannedthrough1R.5.

## Completed source/test files

| Path | SHA256 |
|---|---|
| services/api/app/protocol_workflow/storage/sqlite.py |18770a1c277f8808258280260cb84c04ed6bce96f4c8cf73bc7dc45eb389275e|
| services/api/app/protocol_workflow/storage/selected.py |153fc687d1414ca41218daec7b1777a73e98dbf8476491ba926a91c3d9d7a6d3|
| tests/protocol_v3/test_repository_backends.py |0b1dd33b2b551fb6b144d3df1bff652d886e51edf76b82bff94420d6c1d044f5|
| tests/protocol_v3/test_sqlite_product_storage.py |6710dd96865f2272b2b83ba0f5f615f453625983a404daca1e1bb56406a7c069|

No staging/commits in this continuation; isolatedHEAD remains3d6772f. Dirty/untracked work is intentional and must be preserved. Main API, frontend, monitoring, contracts, typed-casePoC showzero tracked deltas at this gate. LIVEreadonly lastobserved14:34 hadthreeconcurrentmonitoringchanges; not ours, do not merge/revert/touch. HistoricalH-Rsourcebaseline doesnotpromise currentLIVEcleanliness.

## Verification evidence

- Final140focused PASS1.10s,1372+101fullProtocolv3PASS18.70s; twoexistingdeprecationwarnings. Evidence repair_03_focused.xml and repair_03_full.xml under runs/mw_protocol_v3_1r1_codex_20260905/.
- Independentverifier reproduced140/1372+101 and2newclosureprobes; Codexread/reproduced2PASS0.28s, repair_03_independent_closure.xml.
- Realred-first migration/claimtests: repair_03_red.xml2FAIL/1PASS; expandedcold/warm/addtable/addcolumn matrix repair_03_red_v2.xml4FAIL/1PASS beforeimplementation. Oldverifierobservationalprobesassertoldbrokenbehavior andremainunchangedhistory, not requiredto preservethebug afterrepair.
- Accepted gate: reviews/codex_mw_protocol_v3_1r1_storage_gate_20260905.md SHA c5883ade580b424d92952bffee4bdb6e033f4334e1d513397631f2d6f04af33d.
- Engineering report: reviews/mw_protocol_v3_engineering_review_20260905.md SHA e687003e40482aac8bfdcb79946e1af2423060efd18b48c0dca5bb5890fc8312.
- AdditivePlan: plans/mw_protocol_v3_review_amendment_20260905.md SHA cbc9ca5e0ccef5c838139b62c14af05c0e665c286940a5b59d710d2f4b869d0a.
- full-repository, realmain/APIintegration, browser, nativeWord, productmodelsandcutover NOTdone. Existing38-packagehashlockvenv is not main dependency closure: missingxlrd/fitz. PyMuPDFduallicenseconfirmed; isolationisnotlicenseexemption; productlockmustremainfreeofunapproveddependency.

## Execution and conference lineage

- Worker sess_1eefde6c-2f6f-4bf3-9536-355e7e92cab9,ZCode/GLM-5.3-Flash:max. Initial+repair_01 terminal; repair_02 via mw_protocol_v3_1r1_constraints_gate_20260905 terminal593.078s,17observedtoolcalls,exactidentity,nofallback. NewexecutionauditPASS; originalfollowup declaration/outputbinding auditFAIL retained, nohistoryrewriting. The unused init-task constraints_repair packet wasneverdispatched andisnotcompleted.
- Independentverifier sess_e31a1421-b58b-4d69-8025-7a0795fbc289,ZCode/GLM-5.3:max,fresh fromworker. InitialconditionalREADY rejected bymaincounterexamples; repair_verification NOT_READY426.636s; final_storage_verification READY167.816s,9observedtoolcalls,exactidentity,nofallback. Reports/logs use those explicit basenames in runs/conference/... and logs/conference/...; originalgeneratedround2/3unused.
- Final boundedR1/R2 remediation was Codexinline afterallrunnersended; no duplicateowner, no newtopology,apply_patchonly. Independentverifier owned itsdisposition. Last runner86137 andtest57671 areCLOSED; do notwait orresumethem asactive.
- Userflowreview sess_36ce5dca-93ff-410d-99c3-5cdeed0d6da9 terminal804.092s; findings/correctionsmerged. H-Rverifier sess_2668f3b1-8a5c-4561-aecf-78fbb2aee3ac earlieraccepted; seeoriginalreceipts.
- NoHermes/manager/extra-chair nodesdeclared. No model-familydiversityorclinicalsignoffclaimed. Allprompts,rawlogs,reports,sessionIDs,redoutputsretained; nocleanup/archive.

## Resume instruction

1. Read thischeckpoint, currentreview/Plan/tracking, latestAGENTS andTask1R.1gate; verifyhashes/worktree, preserveunrelatedactivity. Do not repeatcompletedR/1R.1oroldtriage/download/OCR/faileditems. Re-testonlyifsource/environmentchangesorrelevantnewconcern.
2. Use the user's dependency-routeanswer. If isolatedlegacytestextras: createaseparateexplicitlytest-only environment/manifest; keep productlock/live/globalruntimeunchanged; nosecretmaterialcopy. If earlierPDFmigration: addthedeclaredscope/impactamendmentbeforeimplementation, preserveoldnegativefixtures. Do notfake/skipleadingmainimportsorcallcollectionerrorsPASS.
3. StartTask1R.2: actualmaincompositiondefaultoff, durableprojectallowlist(versionedifsharedDB), lazyfactory, scopedvalidationhandlerpreservinglegacybehavior; trueentrypoint/fullregression andH6sideeffects. Requiredtestchildruntimeoverrides mustsanitize inheritedAIsettings/role/eligibility paths; mainPROJECT_ROOTdefaultpointsabovecheckout. Neverusestart_stable_backend.zsh/live8910.
4. Then1R.3actualSQLiteAPI/restart/replay/backup/errorclassification; preserveunknownoutcome/safetycompatibility1R.4. FollowPlanserialgates. SinglecontrolledGLMprobeonly1R.6; nofallbackwithoutconfirmation/manifestcriteria. StopTask3R.6PhaseItemplatecardorproduction/cutoverdecision.

No product completion, acceptance of a real protocol, nativegoalcompletion or formal regulatory approval is claimed.
