# Current checkpoint

Task1R.3 prepared under user-approved stage-sequencing amendment.1R.2 functional
review resolved; full-repository reconciliation still open beforeP1R-G1.
Execution plus fresh verification selected: bounded independent integration-test
construction offers parallel context relief; Codex owns product fixes/legacy
reconciliation and final acceptance. No product code or new tests written yet.
Current global AGENTS reread. No active runner; next governed worker dispatch.

Worker actually dispatched: packet mw_protocol_v3_1r3_integration_20260905,
Pi/opencode-go/muse-spark-1.3-contributor:xhigh, no manager; handle74695 live,
hardwait7200s and health-check. Initial Trellis context used wrong key(path)
and validator counted0; corrected to file key, implement/check each1entryPASS
before dispatch. Prompt preflightPASS; all protected paths explicit.
Worker only owns new integration tests/evidence; Codex can inspect product
error mapping and historical tests separately. No task acceptance claimed.
Do not wait terminal old reviewers96863/78784. Continue74695 without redispatch.

Codex narrowed one product defect: unclassified API exceptions previously told
users to retry although commit outcome was unknown. Added independent test
tests/protocol_v3/test_unknown_operation_response.py outside worker-owned paths.
Red receipt 1r3_unknown_response_red.xml: 1 failed at can_retry=True.
Changed shared router fallback to can_retry=False, outcome-not-confirmed copy,
refresh/check saved content before resubmission. No automatic reconciliation
engine or new security framework added; typed known errors remain unchanged.
Focused regression 1r3_unknown_response_green.xml: 64 passed in9.14s
(new test + API contract + actual-main mounting). Receipts under
runs/mw_protocol_v3_1r_integration_20260905/. Worker74695 still running;
independent integration/recovery verification and admission-error mapping pending.

Admission storage-error mapping now implemented separately by Codex: prior raw
storage exception reproduced (1r3_admission_response_red.xml:1failed1passed).
Read-only admission failure now returns503 stable Chinese envelope, explicitly
operation-not-executed, restore storage then refresh, no blind retry. Catches
product storage/SQLite/OS errors only. Focused suite65passed8.89s in
1r3_admission_response_green.xml; subsequent label-only edit reuses catalog
APPLICATION_SERVICE label (needs next regression). No worker files touched.

Concurrent regression (worker tests still under construction) returned
1422passed2failed31.62s, receipt1r3_error_mapping_regression.xml. Both failures
in worker-owned integration: unknown-commit test still expects can_retry=True
(contradicts new explicit unknown-result behavior); WAL backup precondition
pins reader after all writers closed, WAL size0 (pin must precede writes).
Do not overwrite active worker files. Review terminal output then provide one
consolidated same-session correction if these remain. Product label edit covered.

Next continuation classified prior turn as progress (two tested product fixes).
Worker74695 confirmed live; current files show it repaired both previous
integration failures, so no redispatch/correction was sent. Codex added distinct
test_commit_acknowledgement_loss.py outside its ownership: real commit succeeds,
then acknowledgement raises; fresh service reads persisted object, same logical
key replays once and complete business-table dump unchanged. Receipt1r3_ack_loss.xml
1passed0.35s. Existing behavior already correct; no fabricated red/fix needed.
Worker precommit fault uses explicit test rollback and does not cover this
postcommit branch; both coverage obligations retained. Await terminal then review.

Worker74695 terminal0,731.333s; actual Pi/opencode-go/muse-spark-1.3-contributor
xhigh session01a07108-837e-7000-9701-4ad4edefbfa5; no fallback. Report read.
audit-execution PASS (no manager declared). Worker19integration/1424totalPASS;
Codex merged regression1r3_final_codex_regression.xml:1425passed29.93s,0skip,
one historical tar warning. Whole repository still not accepted.
Fresh read-only review packet mw_protocol_v3_1r3_fresh_20260905 initialized,
context completed, preflightPASS and generated Grok4.6/high runner dispatched.
No security scope, live writes, product calls or cleanup. Task remains open
pending independent verdict; next1R.4 scope may be inspected without editing
the frozen review surfaces. No user decision needed.

Fresh reviewer actual live handle57398 (do not redispatch). Execution review and
metrics now filled from actual receipt; no manager/cleanup invented.
Read-only1R.4 reconnaissance: current inbox port permits standalone results
without an outbox row (test_repository_backends.py:743,765,1169); outbox schema
requires workflow_run_id/side_effect_kind/payload_sha256. A naive FK-only merge
would break real compatibility or invent dispatch metadata. Plan the physical
merge around optional result-bearing rows with explicit no-dispatch eligibility,
or an equivalently small representation; choose after full caller/contract audit.
Do not create fake requests just to preserve an inbox signature. Historical
rows cannot be dropped; migration must preserve originals and stable result IDs.
Received vs consumed remains distinct: InboxConsumer applies effect before
mark_consumed and requires idempotent handler on crash. Simplification cannot
turn receipt into completion. No1R.4 product edits yet; dependency1R.3 open.

Additional1R.4 caller audit: events/unit_of_work.py dispatch/ack/recovery methods
all obtain both ports; consume is separate. Contracts already distinguish
ReservationStatus(active RESERVED/RUNNING plus three terminals) from existing
ExecutionTerminalState(three values). Reuse this terminal enum rather than add
a duplicate status abstraction. Hash tuples are actively used by harness.py:795
to bind actual inputs and canonical/document.py creation/update paths. Therefore
deleting fields without a versioned material binding would change semantics;
the approved amendment requires compatible upcast and dependency-change tests.
No assumption that these fields are unused. Review57398 still live this turn.

Legacy collection disposition is now a real file:
reviews/mw_protocol_v3_legacy_collection_disposition_20260905.md. Four failures
remain open; no tests skipped or historical assets regenerated.
Hash simplification audit: ProtocolV3Model.material_sha256 currently recursively
serializes all nonmetadata fields each call (protocol_v3.py:184–245). Existing
top-level hash includes dependency tuples; removing them changes the material
payload rather than merely avoiding duplicate hashing. A cached hash might
reduce repeated work but is not alone fulfillment of1R.4 compact contracts.
Design must distinguish compact stored dependency commitment from inspectable
legacy fields; preserve input order and schema-versioned canonical semantics.

Fresh reviewer57398 now TERMINAL0 (do not poll again), report fully read.
It found required HTTP landed-commit and actual unusable-DB503 coverage gaps,
plus event fold-vs-snapshot gap and ledger-corruption wrongly mapped retryableCAS.
Codex accepts these as engineering work, not user decision points. Added two
tests to now-unowned integration/test_mounted_api_integration.py: COMMIT first,
then lost ack→500→GET200→same POST replay true→all business tables unchanged;
real non-SQLite tmp file→mounted POST503→file bytes unchanged. No manual rollback.
Receipt1r3_http_review_gaps.xml:7passed6.14s. Existing product behavior suffices.

Critical next investigation: application/service.py create event calls
_effect_payload(fact_updates=None); genesis initial facts/seed are only in
aggregate snapshot construction, apparently not event payload. Inspect full
payload and event schema before implementing independent rebuild. Do not fake
event reconstruction by reading aggregate_revision again. New event schema or
explicit immutable genesis baseline may be required; preserve old event bytes.
1R.3 remains open. Rename precommit tests accurately and remove unreachable
landed branch with explicit two-branch coverage, not lowered requirements.
Ledger error mapping also pending; next same-session reviewer recheck only after
one consolidated remediation, retaining initial report/logs.

Reconstruction defect now has deterministic red evidence:
tests/protocol_v3/test_study_event_reconstruction.py reads real product stream
after create (not aggregate table), requires genesis_definition needed for
independent reconstruction.1r3_genesis_reconstruction_red.xml:1failed0.35s,
KeyError genesis_definition. No product patch yet. Current _effect_payload
contains decision/hash/revision and fact_updates(None on genesis), no seed/facts;
old event v1/noop:v1 cannot independently reconstruct initial state. Next add
explicitly versioned reconstruction payload for new events plus pure fold using
existing reducer, without rewriting old events; old missing-baseline streams
must report unsupported reconstruction rather than fabricate facts. Preserve
legacy ledger replay. Reviewer session a6a7a691-8ff8-4f7a-a1d2-cb15f23e1b76,
474.849s actual grok-build/grok-4.6/high, no fallback; recheck not yet dispatched.

Implemented additive genesis reconstruction extension in service.create:
reconstruction_schema_version=study_genesis_v1 and genesis_definition snapshot
inside new immutable creation event. Existing event envelope v1 and ledger
reader stay compatible; no old rows rewritten.50focused tests passed6.73s
in1r3_genesis_extension_green.xml. Added pure application/reconstruction.py,
reusing EventReplayEngine chain verification and StudyDefinitionReducer for
fact-change fold. No aggregate reads. Initial new fold test failed missingmodule;
then test incorrectly accessed quarantine on success (retained receipt
1r3_fold_green.xml), corrected to documented is_quarantined. Next receipt
1r3_fold_verified.xml. Remaining: old-baseline/unknown-version tests, full
regression, accurate precommit labels, ledger-error mapping, reviewer recheck.

Legacy reconstruction tests now4passed0.45s receipt1r3_legacy_reconstruction.xml.
Separate validly hashed synthetic event fixtures remove genesis or set future
extension version; reconstruction reports unsupported baseline with no state,
database unchanged. Tests do not mutate stored historical events. Broader
protocol_v3 regression running handle27192, receipt1r3_reconstruction_regression.xml.
Next read terminal result, fix ledger classification (current source maps
_LedgerRebuildError to retryableCAS despite event-chain errors already mapping
nonretryableCHECKPOINT_EVENT_MISMATCH), then consolidate reviewer recheck.

27192 terminal:1431passed34.31s,one existing tar warning. Ledger mapping red
1r3_ledger_mapping_red.xml:1failed2passed; corrected to existing nonretryable
CHECKPOINT_EVENT_MISMATCH/APPLICATION_SERVICE.52focused passed6.69s in
1r3_ledger_mapping_green.xml. Renamed precommit tests and replaced unreachable
else branch with explicit absent assertion (landed paths independently covered).
Consolidated reconstruction_recheck.md prompt prepared under existing conference
packet; NOT dispatched yet. Next preflight then resume same Grok session
a6a7a691-8ff8-4f7a-a1d2-cb15f23e1b76 with new output/log names, no duplicate.

Recheck actually dispatched, live handle85680, same session/model/high effort,
original route manifest and7200hardwait. Initial custom prompt preflight failed
missing explicit runner report path; corrected boundaries/read/output declarations
and preflightPASS before dispatch. No source changes during this review.
Merged protocol regression handle97444 running; new receipt
1r3_all_remediation_regression.xml. Prior27192 terminal1431passed34.31s;
current adds ledger-classification test and accurate precommit labels.
Do not poll old57398 or oldworker74695 (both terminal).
