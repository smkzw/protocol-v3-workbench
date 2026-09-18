# C03 followup review — D1/D2/D4/D5 closure, Q2/D3 disposition, seed integration verification

Same C03 session (focused followup, not a fresh independent model). All 17 current-manifest files
hash-verified: snapshot == live source. Evidence logs re-inspected including the preserved FAILED
candidate (`seed_integration_candidate_green.log`: 1 failed StopIteration at
test_seed_workflow_integration.py:60, pytest-622 temp dir, 10 passed — honestly kept, current
`seed_integration_candidate_verified.log` shows 11 passed). Global AGENTS re-read before dispatch.

## Verification basis

- Scoped suites re-run by me: all six manifest test files pass (5+2+1+4+4+9=25). Two owner scopes
  reproduce exactly: response-persistence 34 passed/0.44s (zhipu_product_transport +
  zhipu_full_artifact_input + model_response_persistence) and integration 11 passed/0.65s
  (seed_execution_contract + seed_response_validation + seed_workflow_integration +
  model_response_persistence). The other owner logs (22/43/44/8) are overlapping file combinations
  whose exact lists were not supplied; I verified those behaviors directly with my own probes instead
  of guessing combinations (as instructed, counts not summed).
- My probes: `probe_followup.py` + `probe_followup_output.txt` (this directory) — **31 PASS / 0 FAIL**,
  temp SQLite + synthetic HTTP only, no product calls.
- Prior recovery history preserved: graph_runtime (29), graph_runtime_recovery + execution_reservations
  (49) all pass; the storage UNKNOWN id-freeze negative still raises (my probe 1).

## D1 — CLOSED (verified)

runtime.py:1768-1780 now passes `provider_session_id=view.results[node].get('provider_session_id')`
on the repair transition **only when the persisted status is RUNNING**; UNKNOWN rows keep the
omitted-kwarg "unchanged" semantics. My probe: RUNNING+placeholder crash state → repair completes with
ledger id == event id == `completion-actual-F1`, output sha matches, service not re-called;
UNKNOWN+committed-event variant → COMPLETED with ledger placeholder retained; direct repository
transition UNKNOWN→COMPLETED with a different id still raises RepositoryStateTransitionError
(sqlite.py:1938-1948 untouched). Owner suite `[True-True]` param (test_graph_model_contract.py:11,45-66)
covers the same window via SystemExit-after-append.

## D2 — CLOSED (verified)

`resolve_unknown_with_receipt(..., provider_session_id=None)` (runtime.py:654) stamps the recovered
**result event** (runtime.py:744, 1436-1437) while `recover_unknown` still passes
`latest.provider_session_id` (runtime.py:756) — ledger history unchanged. My Q2 end-to-end probe
recovered an UNKNOWN dispatch with the actual id `chatcmpl-actual-crash-case` on the event and the
ledger placeholder intact. Owner test
`test_unknown_receipt_adoption_retains_actual_identity_in_event_without_rewriting_ledger`
(test_graph_model_contract.py:104-124) asserts the same.

## D4 — CLOSED (verified)

`candidate: NonEmptyText | Annotated[list[NonEmptyText], Field(min_length=1)]`
(research_seed.py:101). My probe: shipped schema array variant now carries `minItems: 1`; pydantic
rejects `candidate: []` (too_short); the explicit `seed_empty_candidate` branch remains in
`read_seed_candidates` source as compatible defense. Schema still compiles from the single model class
(no dual-source drift).

## D5 — CLOSED (verified, promoted to pre-live as owner stated)

`_ServiceTransport.preflight` appends a `graph_node_dispatch` event (runtime.py:175-191) carrying the
compacted contract + reservation id + input hashes **before** the provider dispatch, guarded per
reservation id; `_build_contract` (runtime.py:1289-1297) returns the pinned recorded contract on any
later rebuild, after re-verifying `matches_dependencies`. My probe with a factory drifting **both**
model and output_schema_ref between dispatch and recovery: recovered event carries the original
(`glm-original` / `https://drift.example/original`), drifted factory never applied; deterministic nodes
emit no dispatch events (runtime.py:175 factory-only condition); replay tolerates the new event type
(recovery `_load` ran over a stream containing it). Owner test
`test_unresolved_call_keeps_pre_dispatch_contract_when_configuration_changes`
(test_graph_model_contract.py:69-101) covers model drift.

## D3 — WITHDRAWN (owner's position is correct; executable proof)

My original remedy (freeze base `input_schema_ref`/`output_schema_ref`) is wrong for the real
integration, and the underlying risk is already guarded by the actual path:

- The real factory `seed_execution_contract` (seed_contract.py:17-28) exists precisely to replace the
  graph's symbolic refs (`schema:{graph_id}:…`, runtime.py:1321-1322) with the registered skill's real
  URIs. Verified against the mounted registry: `skill.research-seed-proposal` (10th entry; old 9
  preserved) → `https://protocol-v3.local/schemas/research-seed-proposal-{input,output}.v1.json`.
- `_validate_skill_binding` (harness.py:742-756) enforces contract.skill_definition_id ==
  skill.skill_definition_id AND both schema refs == the skill's, and the dispatcher re-runs the full
  validator before every physical call. My probes: the **base** (symbolic-ref) contract is REJECTED by
  real `build_request` (HarnessPolicyError on skill id first) — i.e. freezing base refs would make the
  real dispatch impossible; a **drifted** contract ref (bound + tampered output_schema_ref) is likewise
  REJECTED with the output_schema_ref message. No real mismatch survives the harness path. The
  first-pass "divergence" existed only because my synthetic service bypassed build_request entirely.
- Residual (observation, no action required): GraphRuntime itself does not cross-check contract↔skill;
  that is the harness's job and every configured executor must go through build_request/dispatcher to
  make a provider call.

## Q2 — owner implementation verified; original remedy superseded

Correction accepted: the store API is `ArtifactStore.store/read` (ports/artifacts.py:173,221;
LocalArtifactStore local_store.py:180,238), not `put`; and binding at sink time inside the adapter is
stronger than my glue-level suggestion because it closes the crash window between receipt construction
and event append. Verified in source and probe:

- `receipt_sink(content, receipt_data)` called after `_validated_completion`, replacing the legacy
  sink when selected; constructor enforces exactly one sink (zhipu_api.py:90,124-154,324).
- The receipt binds provider id, observed provider/model, output sha, contract/logical-call/idempotency
  ids, prompt sha, requested effort, and input artifact ref+sha pairs — **no input excerpts, no
  credential** (probe: every input_artifact entry is exactly {ref, sha256}; no 'snippet', no
  credential material in the envelope).
- `persist_model_response` (model_response.py:9-16) writes content+receipt as ONE `model_response.v1`
  JSON artifact in the existing store, returns `logical_key:revision:N` (matches
  `_ARTIFACT_REF_RE`, harness.py:164 — DispatchReceipt accepts it, probe-verified).
- Full crash-window story proven end-to-end (probe 3): dispatch interrupted AFTER durable persistence
  → reservation UNKNOWN (`dispatch_exception`); the artifact is discoverable from the ledger alone via
  the deterministic key `seed-response:sha256(reservation_id)` (seed_workflow.py:92); adoption via
  `resolve_unknown_with_receipt` with the envelope's artifact ref + raw sha + actual provider id →
  recovered event stamped, ledger freeze intact, validator node then completes on the adopted artifact
  with **zero additional provider calls** (opener.calls unchanged), graph reaches completed.
- Honest residual, matching owner's statement: a crash **before** the sink stores nothing recoverable
  (nothing was ever received/stored); no such claim is made in code or tests.

## Seed integration (two-node + one correction) — verified

Real temp-SQLite GraphRuntime + mounted registries (product-llm role: zhipu-coding-plan /
glm-5.3-flash / cn / confidential) + HarnessDispatcher + HTTP-composition adapter + LocalArtifactStore:
- generate (configured) persists the raw receipt and returns `ConfiguredNodeServiceResult`;
  validate (deterministic) reads the artifact hash-bound and returns structured validity
  (`needs_structure_correction` vs valid `needs_information`/`ready_for_review`); malformed JSON is
  neither UNKNOWN nor approved (seed_validation.py:7-31 catches JSON/ValidationError/ValueError into
  structured errors). Graph COMPLETED ≠ content approval — statuses keep them separate.
- Correction is a separate graph with its own logical keys; `seed_correction_inputs`
  (seed_workflow.py:36-57) refuses valid/sparse output and correction-of-correction, binds material by
  input sha + output sha, and carries prior request/output/errors/response id/model/effort;
  `generate` re-checks provider/model/effort against the new contract before composing
  (seed_workflow.py:86-88). No native conversation claim: `_completion_body` still sends one fresh
  user message; the correction message embeds the original material + prior output + errors
  (integration test asserts content + `seed_invalid_json` present, same model). `retry_node` not used.
- Ordered-hash catch verified from first principles: `_dependency_hash` is order-sensitive
  (protocol_v3.py:267-272), the graph compacts over sorted hashes (runtime.py:1326), and
  `_validate_artifact_binding` requires the exact ordered tuple (harness.py:793-799). My probe:
  unsorted artifact tuple → HarnessPolicyError; sorted (by sha) → accepted; seed_workflow.py:103-105
  sorts before build_request. No checker was relaxed. The preserved FAILED log + pytest-622 diagnostic
  and the deterministic nonce loop in the integration test (opposite digest order) document the catch.
- Timeout: seed contract pins `REQUEST_TIMEOUT_SECONDS` (600) (seed_contract.py:22) and the adapter is
  built with `timeout_seconds=contract.timeout_seconds` (seed_workflow.py:98), used by
  `opener.open(..., timeout=...)` (zhipu_api.py:182). Actual adapter receives the contract timeout.
- Old deterministic interface/results remain: graph_runtime 29 passed; my deterministic-node probe
  emits no dispatch events and behaves as before.

## Genuinely pending concerns (not V1.1 blockers)

1. Deterministic pre-call rejections inside `generate` (e.g. `seed_correction_model_mismatch`,
   `seed_intake_material_mismatch`, seed_workflow.py:63-64,86-88) raise inside the dispatch window →
   classified UNKNOWN rather than FAILED. Fail-closed and pre-provider-call (no wrong-model call
   occurs), but each such event loads the UNKNOWN reconciliation path for what is a deterministic
   condition. A future preflight-level distinction would remove the noise; do not relax the
   coordinator to guess.
2. Hard-crash RUNNING row (no result event) with a stored receipt: the artifact is discoverable by the
   derived key, but adoption requires UNKNOWN_OUTCOME (runtime.py:720); a RUNNING row still needs
   explicit failure+retry. Owner-declared pending reconciliation/orchestration tooling covers this —
   keep it on that list.
3. `_build_contract` pinned lookup is first-dispatch-event-wins per node (runtime.py:1291-1297):
   an explicit later attempt reuses attempt-1's contract even if the factory legitimately changed.
   Consistent with "resumed call uses recorded contract"; worth one doc line so it is a chosen
   behavior, not a surprise.
4. `seed-validate` performs store reads while `NodeService` docs describe services as pure/no-I/O
   (ports.py:29-33). Doc-level divergence only; no provider access occurs.
5. Suite-log scopes are file combinations; two reproduce exactly, the rest overlap. Bind future
   evidence logs to explicit file lists so counts are independently reconstructible.
6. Owner-declared pending, agreed: application/API orchestration, derived run-id selection, loading
   the old successful product probe into the shared cache, and any UI/product acceptance — tests alone
   are not product acceptance.

## Disposition summary

D1 CLOSED · D2 CLOSED · D4 CLOSED · D5 CLOSED (pre-live) · D3 WITHDRAWN (owner correct, proof above) ·
Q2 superseded by verified receipt_sink implementation · ordered-hash fix verified, no checker relaxed ·
no new blocking defects found in the frozen 17.

Evidence: probe_followup.py / probe_followup_output.txt (31 PASS / 0 FAIL),
scoped_suites_rerun.txt, sibling runs/mw_protocol_v3_v1_1_20260913 logs (incl. preserved FAILED
candidate). Key lines: runtime.py 166-192, 647-774, 1280-1350, 1751-1781; zhipu_api.py 90, 124-154,
296-336; model_response.py 9-27; seed_contract.py 12-28; seed_validation.py 7-31; seed_workflow.py
36-57, 60-132; research_seed.py 101; harness.py 164, 736-756, 777-799, 862-930;
protocol_v3.py 267-311; local_store.py 180-259.
