# Current checkpoint

Active1R.4. Predecessor1R.3 independently accepted after substantive repairs:
reviews/codex_conference_mw_protocol_v3_1r3_fresh_20260905_review.md.
Merged1432passed33.08s; recheck29passed6.27s. Both reviewer runs terminal;
do not poll85680/57398 or redispatch. No user blocker.

User corrected repeated one-minute finals: use commentary during ongoing work,
continue across bounded steps; no stage-final/restart loop. Preserve existing
goal and do not confuse platform observation yields with execution completion.

Trellis1R.4 PRD/design/implement prepared and active. No1R.4 product edits yet.
Next: finalize bounded storage merge assignment using approved compatibility
design, write focused failing test then minimal implementation. Worker ownership
must avoid simultaneous changes to schema/test baseline. Execution plus fresh
verification selected because migration/recovery is a distinct substantial unit.
No security-specialist scope, product calls, live/monitoring writes or cleanup.
Historical full-repo four collection failures remain due beforeP1R-G1.

Continuation: previous goal turn only explained early stopping, no engineering
progress. Revalidated current sources. The earlier init-task packet was a
plan-only prompt and was NEVER dispatched; retained unchanged. Correct execution
packet mw_protocol_v3_1r4_storage_impl_20260905 passed preflight and was launched
once with runner hard wait7200, exec handle67227. Storage worker exclusively owns
sqlite.py and new test_result_storage_consolidation.py; no concurrent edits there.
No manager declared. Do not run generated cleanup commands (user prohibits it).
Next: inspect separate contract dependency callers while same runner executes,
then verify terminal output and independent acceptance. Task remains in_progress.

Codex disjoint edit: runtime/reservations.py ReservationOutcome now stores only
reservation and derives terminal_state/status/error_code, removing independently
supplied duplicate result state. Existing caller search found only five internal
constructors, all updated; public read properties retained. New
test_reservation_result_projection.py: red3 constructor failures, then focused
projection + existing execution_reservations42passed0.95s. Evidence
runs/mw_protocol_v3_1r_integration_20260905/1r4_result_projection_{red,green}.xml.
No attempt history or unknown reconciliation removed. This is partial1R.4,
not overall acceptance. Fresh verifier must review constructor compatibility.
Contract audit: node input tuple is actively compared in harness.py795;
document chapter tuple participates in document revision hashes. Replacing them
requires versioned digest plus old-contract reads, not silent field deletion.

Storage runner67227 terminal exit0, one round, no fallback; worker report read.
Reported18focused/123related pass; full1449pass4fail. Codex inspected paired
receipt/consumption/history paths. Four failures are schema-stage assertions:
two v2 literals, migration-history v2 list, obsolete12-column tamper fixture.
User-authorized stage supersession: update to schema3 and15-column fixture;
retain actual UNIQUE-loss rejection assertion and all row/hash preservation
checks. No medical content/scientific criterion changed. Negative fixture remains.
Projection active-state tests added:44passed0.95s. Full merged verification next.

Merged verification terminal35248:1455passed30.16s, one historical tar warning;
1r4_storage_projection_regression.xml. Worker actual Pi/opencode-go/
muse-spark-1.3-contributor:xhigh, session01a07130-bcaf-7000-b771-8caca37578f1,
448.566s,194toolcalls, no fallback; audit-execution PASS.
Fresh independent storage/projection reviewer launched once: packet
mw_protocol_v3_1r4_storage_fresh_20260905, exec74596, GrokBuild/grok-4.6/high,
hardwait7200. Source under review frozen; reviewer owns no product writes.
Keep waiting same handle; do not infer completion from report filename.

Frozen source identities during this review:
- sqlite.py a1f30d1155ba29b8f3ca49a1de41adf0de4262754ac3287eda98e91a55e75f24
- runtime/reservations.py 2d6f0a5b527d99d050b50cafd2a4fb9d952c68f402d3bb305f73a8f3859e1a81
- test_result_storage_consolidation.py 552257bca6070f3ced9670c7bf9f283db6ec7a52feed68072baf3478c67f07c8
- test_reservation_result_projection.py f3b3c106841767617d6bc2fe4774a67ce8941caf9a1dc866c71a4544e5560868

Disjoint readonly legacy debt investigation found maintained typed-readiness
tests replacing old placeholder-body behavior;2focused tests passed0.65s.
See reviews/mw_protocol_v3_legacy_collection_disposition_20260905.md addition.
No old batch/model operations rerun. Contract compaction next-step design now
records actual harness/document consumers; implementation still pending.

Next contract slice red tests now written (test-only, frozen review source unchanged):
tests/protocol_v3/test_compact_dependency_contract.py imports existing synthetic
harness helpers, pins current legacy node hash44678e0c1a80d401e0ccfa067f1b7efa869206df4350f3e67ee122844d91d378,
requires explicit compact_dependencies(), minor-version roundtrip, no serialized
input tuple, actual build_request matching-input acceptance and missing/reorder/
replacement rejection. Result5failed1passed0.45s because method absent; evidence
1r4_compact_contract_red.xml. This is intentional new WIP, not a regression of
storage/projection;1455pass snapshot predates these six new tests. Do not claim
current full suite green until contract implementation lands. No product contracts
or harness source edited while storage reviewer runs.

Fresh reviewer74596 TERMINAL0: actual schedule shifted at19:00 startup to
ZCode/GLM-5.3-Flash:max (legal schedule reconciliation, NOT Grok actual runtime),
sessionsess_ec127744-fb0d-4fa6-987d-41851876b71b,1004.53s,39tools,no fallback.
Report read fully:149tests+15probes; reviewer probe initially deadlocked itself
and was stopped/fixed by reviewer, not product failure. Raw receipt retained.
R1 superseded history can become RECEIVED: reproduced1fail then3-line same-sha
replay preservation fix in sqlite.py;19relatedpassed0.41s, superseded red/green
XML. R2 SQLite lifecycle: added test_sqlite_reservation_lifecycle.py; normal
unknown/recover/reopen/completedreuse passed1/1. Additional independent-connection
dispatch check FAILED: observedNone instead of('running',1), proving raw UoW
coordinator composition does not commit reservation before physical dispatch.
Evidence1r4_dispatch_durability_red.xml (1fail1pass). This is a genuine product
composition gap, not stage assertion; do not weaken expected or claim1R.4done.

Next repair: committed reservation-operation factory/runtime entrypoint, preserving
business UoW atomicity (never commit arbitrary caller transaction). Check concurrent
active RESERVED ownership before classifying it as abandoned; current raw
reserve_or_reuse eagerly disposes any RESERVED row. Keep legacy orphan-recovery
fixtures valid through explicit recovery context, not blind live-owner takeover.
Then lifecycle/durability/concurrency/kill/retry tests and same-reviewer recheck.
Contracts compaction red tests still pending and distinct. No active runner now.

Durability repair execution launched once after preflight: packet
mw_protocol_v3_1r4_durable_dispatch_20260905, exec96967, declared
ZCode/GLM-5.3-Flash:max, hardwait7200. It exclusively owns sqlite.py,
runtime/reservations.py, test_sqlite_reservation_lifecycle.py and new
test_durable_reservation_dispatch.py. No main-agent edits to those until terminal.
Because this execution route shares the previous reviewer's model, that reviewer
cannot independently accept these new repairs; choose a fresh eligible different
review route after actual receipt is known, retaining both packet lineages.

Codex disjoint compaction implemented in packages/contracts/workbench_contracts/
protocol_v3.py, runtime/harness.py and canonical/document.py. Four contracts use
explicit v1.1 dependency digest; v1 default/serialized hashes preserved; conversion
returns a new model; harness validates ordered dependencies; document updates keep
minor version. New tests cover real build_request and document CAS replay,
lock/submission roundtrip and mismatched digest/legacy missing dependency rejection.
236passed0.52s in1r4_compact_all_types.xml. Initial first_green filename actually
contained1test API-assumption error (request.node_contract nonexistent); corrected
to real public request fields, not a product-failure suppression. Documentversion
regression first failed then fixed (1r4_compact_document_red.xml). Fresh independent
verification and full merged regression still required. Old1455 count is historical.

Contract focused final237passed0.54s (1r4_compact_final_focused.xml); all four v1
JSON serializations and material hashes compared to HEAD model code in memory,
identical. Contract review launched once: mw_protocol_v3_1r4_contract_fresh_20260905,
exec92926, declaredZCode/GLM-5.3-Flash:max, hardwait7200. This reviews Codex's
three disjoint contract/harness/document files, not the concurrentZCode executor's
SQLite/reservation edits. Those contract sources now frozen until review returns.
Active handles:96967 durability executor;92926 contract reviewer. No duplicate
dispatch. Storage review finaldisposition REVISE saved, not task acceptance.

Both handles now terminal0; do not poll/re-dispatch them. Durability worker
actual ZCode/GLM-5.3-Flash:max session sess_b4ba2900-e3f0-46d4-ac2d-b4b3ab74de59,
reported1474pass. Main found its process-local ownership assumption inadequate:
new real spawn-process test failed (1r4_cross_process_owner_red.xml), proving
live RESERVED takeover and original owner's failed->running error. Main added
local flock ownership to committed repository (before publishing shell; OS
release on process death; terminal/close release; never unlink lock files).
No new lease platform, polling or service.47focusedpassed2.30s in
1r4_cross_process_owner_green.xml; terminal release followup needs rerun.
Raw UoW remains transaction-scoped and is not the physical-dispatch composition.

Contract independent report returned:237pytest and100/101 independent probes;
one probe assumed cross-type digest identity should differ. Digest intentionally
binds a named ordered dependency set, not a whole model; outer material hash
binds model content, so equal chapter dependency sets may share the digest.
No product cross-type comparison exists. Do not claim101probes passed or add
a new security requirement. Golden compact hashes and explicit docstring next;
2R.1 must still introduce first product v1_1 generation and real persistence.
1R.4 remains open pending merged tests and independent durability review.

20:10 continuation: first durability reviewer52360 TERMINAL0, actual
Pi/opencode-go/muse-spark-1.3-contributor:xhigh,session
01a0716c-d301-7000-bcb0-ed9f38af0236,115.534s.52tests passed; found orphan
disposition race. Main red1fail then48focusedgreen via catch/re-read convergence.
Same-session followup now ACTIVE exec88070; only this reviewer is running.
Frozen sqlite.py/reservations.py until return. No duplicate/cleanup.
Main merged1475passed33.82s before later golden/race tests; needs final rerun.
Contract bounded review accepted with explicit2R.1 integration obligations;
four compact golden pairs added,12compacttests passed0.43s.

Legacy dynamic matrix updated under approved assertion supersession;19original
tests pass, added actual numeric provenance test; combined template/dynamic47
pass1.57s. Three absent historical batch-tool tests remain unchanged and explicitly
NOT EXECUTED; Plan amendment names exact exclusions and preserves scientific
obligations in3R/4R/7R. Maintained collection9082tests succeeded9.30s; not execution.
No pytest.ini hidden exclusions, no removed fixtures, no historical reruns.

1R.6 readonly preparation: role registry still DeepSeek default; direct adapter
only injected callables. omp provider absent from models.yml but auth_credentials
contains2api_key rows for zhipu-coding-plan. No credentials printed/copied;
need resolve actual omp selection semantics, not pick an arbitrary row.
Venv lacks yaml; globalPython has it, used readonly introspection only, no install.

FINAL1R4: same-session88070terminal0,72independenttests andrace4/4passed.
Main1477mergedpass35.17s,fullrecord1r4_final_merged_20260905.xml. Codexclosedtask
afterpairedreviews; review-gatePASS afterexplicitactualPi-notHermesidentitynote.
No active1R4handles. Continueddirectlyto1R6Trellistask; seeitscheckpoint.
R2committedphysicaldispatchcomposition remainsmandatory2R.1wiring;lockfilesretained,
recoveryfind_unresolvedincludesRUNNING/UNKNOWN. No cleanup or productioncalls.
