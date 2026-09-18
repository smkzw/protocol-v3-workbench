# Protocol v3 current execution tracking — 2026-09-05

## Current state index (Trellis migration)

The table below is the retained pre-Trellis snapshot, not a second live board.
Current task: [.trellis/tasks/09-06-protocol-v3-3r3/task.json](../.trellis/tasks/09-06-protocol-v3-3r3/task.json).
Continuation: [checkpoint](../.trellis/tasks/09-06-protocol-v3-3r3/checkpoint.md).
3R.2 schema acceptance: reviews/mw_protocol_v3_3r2_acceptance_20260906.md;
1745 expanded regression passed, independentround2; v1 bytes/hashes unchanged.
3R.1 candidate extraction acceptance: reviews/mw_protocol_v3_3r1_acceptance_20260906.md;
51 focusedtests and independentround3; source obligations deferredexplicitly to3R3.
2R.1 offline acceptance: reviews/mw_protocol_v3_2r1_acceptance_20260906.md;
1687 regression passed, independent round3 closed concrete defects. No release claim.
P1R scoped legacy disposition independently reviewed and completed in its own
task; explicit construction launch amendment permits offline2R.1, not fullrepo/
release acceptance. Historical/monitoring/frontend obligations remain recorded.
Trellis initialized 0.6.14; current state and evidence are in the linked task. Bootstrap
guidelines remain in_progress (not all generated templates filled).
User resumed native Goal; current hard UX limits are20clicks/5mandatorytexts.
Historical PhaseR and1R.1 evidence remains at its original references below.
Future task state updates belong to Trellis; this document is the index only.

This tracking document records execution against immutable Plan v2 (040eb6ad323047737e8be6a3a23344fdb719dc85230ef7994b96c9af29257607). It does not rewrite the approved design or supersede its gates.

Goal: review actual frontend/backend architecture and test evidence, reconcile the other review with primary sources and independent verification, then implement the approved AI-led Protocol workflow in the isolated workspace. Word native and regulatory-ready document evidence remain mandatory; product acceptance is pending.

| Work | State | Evidence / next action |
|---|---|---|
| Authority and pause re-anchor | Complete | All five supplied hashes match; HEAD 3d6772f; original P1 security gate excluded, not passed |
| R.1 additive authority locator amendment | Accepted H-R | 13 relocations+8 additions verified; named R.1 checkpoint added; old immutable bytes retained |
| R.2 live/source drift reconciliation | Accepted H-R |313 differences,23 shared changed semantically disposed; baseline identity explicit; no merge |
| R.3 deterministic test baseline | Accepted H-R |1240 passed+101 subtests;183 focused;75 typed case tests; frontend offline tests green |
| H-R fresh verification | ACCEPTED 2026-09-05, Phase R only | Fresh ZCode GLM-5.3:max READY; actual42 tool calls and three pytest outputs separately verified; hr_tool_receipt_supplement.md; old NOT_READY retained |
| Engineering review / user-flow challenge | User-flow independent review returned; corrections incorporated | Component map and concrete failures; priorcross-project callback claim retracted due parentkey remount, unusedhook risk separated. Stale preview actualSSR contradiction confirmed; visual/nativeWord/product acceptance pending |
| 1R.1 product SQLite | ACCEPTED after independent READY | reviews/codex_mw_protocol_v3_1r1_storage_gate_20260905.md;140focused,1372+101full,2independentclosureprobes; fourhashesfrozen. Allrunners terminal; priorfailurehistoryretained |
| Trellis management adoption | Approved; initialization pending before next implementation | Local CLI 0.6.14 observed; no .trellis exists yet. Follow current additive Plan; import accepted evidence by reference, do not rerun accepted stages |
| 1R.2–1R.6 | Pending; PyMuPDF decision resolved by user | Personal local use permits PyMuPDF; record/pin actual dependencies in isolated environment before realmain/fullregression. No router/service/modelactivation yet |
| 2R typed facade | Pending | Three real kill/replay cases after P1R-G1 |
| 3R template/contracts/QC | Pending | Verified v2 template, full leaf obligations; stop at 3R.6 user decision |
| 4R–8R | Pending | Inherit Plan v2 and unmodified frozen obligations; no premature release claims |

Review hypotheses requiring proof: SQLite PoC is not yet a product adapter; API mounting must preserve legacy side effects; simplify identity/hash machinery only while preserving stale detection, multi-consumer delivery, retained history and unknown-outcome recovery; company precedent is a recommendation source subordinate to current applicable regulatory and project facts; eCTD document readiness is separate from a validated submission sequence. Native goal remains paused because its API has no objective-update/resume operation; no runtime database workaround is permitted.

User approved compatibility-preserving 1R.4 revision in this task. Current additive execution contract: plans/mw_protocol_v3_review_amendment_20260905.md; full engineering baseline review: reviews/mw_protocol_v3_engineering_review_20260905.md. Historical inference about multi-consumer delivery is a future integration concern, not a claim that current InboxRepository has a consumer_id field.

Live readonly status update ~14:34: three medical-monitoring admission/test files now modified by concurrent workspace activity, following earliercleanstatus. This task has made no LIVEwrites; preserve changes. HistoricalH-R is not currentLIVEcleanliness/cutoveracceptance. Details and active runner handles: runs/mw_protocol_v3_review_continuation_20260905_1435.md.
