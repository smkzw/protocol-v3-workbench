# C03 engineering review — V1.1 seed generation receipt/validation integration

Run: `runs/mw_protocol_v3_v1_1_model_integration_review_20260913` (route zcode/GLM-5.3, off_peak).
All 12 manifest files hash-verified: snapshot == current source, review performed against live code.
Probes: `probe_identity_and_classification.py`, `probe_factory_schema.py` (this directory, temp SQLite, venv
`runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python`, PYTHONPATH per dispatch contract).
Sibling green logs re-checked: graph_provider_receipt 41 passed, full_input_transport 35 passed,
seed_output_schema 13 passed — counts match the dispatch claims.

## Q1 — provider response identity across reuse and crash-window recovery

**Normal completed + reuse: retained (no defect).** `_ServiceTransport.dispatch` unwraps
`ConfiguredNodeServiceResult` and puts the actual id in both the receipt (runtime.py:199-203, 225-228)
and the `graph_node_result` event (runtime.py:220); the coordinator replaces the harness placeholder
`sess:res:*` with `receipt.get("provider_session_id")` on COMPLETED (reservations.py:537, 641-653).
Probe A: ledger id == event id == `completion-actual-1`.

**Defect D1 (medium): crash window "result event committed, coordinator COMPLETED lost" loses the actual
id on the reservation ledger.** `_load_reservation_states` builds repair triples
`(node_id, reservation_id, output_sha256)` and discards the event's `provider_session_id`
(runtime.py:954-966); `_apply_reservation_repairs` then calls `repo.transition(... to_status=COMPLETED,
output_sha256=...)` without `provider_session_id` (runtime.py:1727-1742), and the repository treats a
missing kwarg as "leave unchanged" (sqlite.py:1933-1937). Probe B: after simulating the exact post-crash
row (status running, placeholder id, NULL output sha) the repair completed the row with matching output
sha and **no redispatch** (service called once) — correct convergence — but the ledger keeps
`sess:res:b2ea…` while the event carries `completion-actual-1`. Failure scenario: an operator reconciling
UNKNOWN/unresolved work by `reservation.provider_session_id` queries the provider with a nonexistent
session id, concludes the call never reached the provider, and authorizes an explicit retry → duplicate
paid generation for work already delivered (the exact harm design.md:24 calls out); audit-wise, the two
durable records of one call disagree on identity.

Smallest fix (no storage-rule change): the repair transition runs from RUNNING, where the repository
already permits setting a provider id (the freeze at sqlite.py:1938-1948 guards only UNKNOWN→COMPLETED).
Carry `result.get("provider_session_id")` through the repair triple and pass it in the transition, only
when the persisted status is RUNNING (or the id equals the stored one). All existing recovery/negative
tests keep their meaning: UNKNOWN strictness untouched, placeholder semantics untouched for
deterministic nodes (their events carry no provider id → None → unchanged, same as today).

**Defect D2 (medium): receipt recovery of an UNKNOWN outcome cannot record the actual provider id at
all.** `resolve_unknown_with_receipt` takes no provider identity; `_append_node_result` is called
without `provider_session_id` (runtime.py:708-721) and `recover_unknown` is fed
`latest.provider_session_id` — the placeholder (runtime.py:724-735). Probe D: recovered event has **no**
`provider_session_id` key; ledger keeps `sess:res:d53e…`. Combined with the UNKNOWN id-freeze rule, a
crashed-after-response dispatch leaves the actual id only in the raw artifact binding (Q2) — never in
any queryable ledger/event field. Smallest fix within the stated constraint: extend
`resolve_unknown_with_receipt(output=..., output_sha256=..., provider_session_id=None)` and stamp the
**recovered result event** (append path is outside the repository rule); keep the ledger rule intact.
If the owner later wants ledger-level correction, the principled narrow amendment is to allow the id
change only when the stored value is still the coordinator-minted `sess:res:*` placeholder and the
recovered receipt carries a hash-matching raw artifact ref — evidence-backed completion, not an identity
swap; that touches a negative test and is a separate owner decision, not required for V1.1.

Latent note (low): `_load_reservation_states` collects RESERVED rows with committed result events into
the repair scan (runtime.py:959-963), but `_apply_reservation_repairs` only transitions
RUNNING/UNKNOWN (runtime.py:1730-1733) and the matrix forbids RESERVED→COMPLETED (sqlite.py:1880-1893).
Probe F: such a row is silently left `reserved`/NULL forever (visible in `find_unresolved`). Unreachable
in the live path (a result event implies RUNNING was reached); drop RESERVED from the scan or dispose it
explicitly.

## Q2 — durable raw-output ↔ provider-id ↔ logical-work binding

Code facts: the adapter calls `output_sink(content)` after validation and before building the receipt
(zhipu_api.py:305-320); `OutputSink = Callable[[str], str]` (zhipu_api.py:89) — the sink never sees the
response id or the logical work identity, and the returned ref is opaque. The receipt
(`provider_session_id`, content sha, `output_artifact_ref`) reaches `_ServiceTransport`, which already
persists payload+id+reservation+logical key atomically in one `graph_node_result` append
(runtime.py:211-224, 1389-1403). The only existing store matching the need is
`LocalArtifactStore` (artifacts/local_store.py: content-addressed blobs + per-logical-key revision
manifest, idempotent put, no second DB).

Smallest coherent integration (no new job system, no adapter signature change): in the V1.1 glue service
(the callable registered in `services` that wraps `HarnessDispatcher` + zhipu adapter), after
`adapter.dispatch` returns the `DispatchReceipt`, `LocalArtifactStore.put(logical_key= f"model-output/
{workflow_run_id}/{node_id}/attempt-{n}", data=content_bytes)` and return
`ConfiguredNodeServiceResult(payload={output_artifact_ref (= that logical key), output_sha256
(= receipt content sha), observed_provider, observed_model, revision}, provider_session_id=receipt
.provider_session_id)`. Then:
- crash after the event append: binding is already atomic in the event + re-resolvable bytes (hash-bound);
- crash between the put and the event append: the orphan content is still attributed (logical key names
  the run/node/attempt; manifest carries the content sha) — no anonymous text — and UNKNOWN
  reconciliation can find it and adopt it via `resolve_unknown_with_receipt` (with the Q1/D2 event-stamp
  so the actual id lands in the event);
- crash before the sink: nothing below the provider can retain the response — acknowledged residual.
Injection point is correct today: `_ServiceTransport` knows workflow_run_id/node_id/reservation/attempt;
the adapter's dispatch payload also already carries `workflow_run_id`/`node_id`
(runtime.py:1242-1254) if the owner prefers binding inside `_dispatch` (would require widening
`OutputSink` to `(content, response_id)`).

## Q3 — malformed JSON must be neither unknown nor approved

Proven hazard (probe D): any exception inside the dispatch window — including a JSON parse of the
provider's content — is classified UNKNOWN (`dispatch_exception`, reservations.py:602-611), node
BLOCKED_UNKNOWN, run BLOCKED. So the glue must not parse in the window (design.md:20 already says
this; the current code enforces no such separation — it is a wiring discipline the V1.1 glue must
follow, plus the validator must not raise on content-caused failures).

Native-resume claim check (per instruction, from actual transport code): `_completion_body` sends only
`{model, messages, reasoning_effort, stream}` (zhipu_api.py:253-261); `_compose_messages` produces
exactly one user message (zhipu_api.py:263-289); `DirectApiAdapter.dispatch` accepts `session_id` but
ignores it (direct_api.py:151-197); the harness payload does carry `provider_session_id`/
`same_session_recovery` (harness.py:327-364) but zhipu `_dispatch` never reads it. Confirmed: the
completion response id is a receipt id, not a resumable conversation handle; correction must re-embed
content explicitly.

Smallest coherent shape (all pieces exist):
1. Model node returns the raw receipt only (Q2 payload) — completes with durable raw receipt.
2. Deterministic validator node consumes the model node's output payload, re-resolves the raw text
   hash-bound (resolver + sha check already exist: artifact_messages.py:26-34), runs
   `json.loads` → `read_seed_candidates`, and **returns** structured validity
   `{valid: bool, stage: json_parse|schema|quote|user_quote, errors: [...], raw: {ref, sha256,
   provider_session_id}}`; it never raises for content-caused failure (raising stays for genuine
   internal faults). This is what keeps malformed JSON out of both UNKNOWN and approval.
3. Bounded same-model correction: a dedicated correction model node whose service composes the message
   from (a) the original request material re-resolved under the byte budget, (b) the prior raw output
   (ref+sha from the validator payload), (c) the validator's structured errors — same provider/model
   pinned by its contract factory (share one constant; "不自动切模型"). Bounded by plan topology (one
   correction edge), so no auto-redispatch: the original model node's reservation stays COMPLETED with
   its receipt; correction is new logical work with its own key. Do not use `retry_node` for this —
   retry re-sends the identical reconstructed input (runtime.py:808-824), which cannot carry the
   prior output/errors.

## Q4 — contract factory guard and schema compiler

**Defect D3 (low-medium): factory guard freezes only
{node_execution_contract_id, logical_call_id, idempotency_key} + dependency digest
(runtime.py:1301-1313).** Probe G: changing `output_schema_ref`, `input_schema_ref`,
`skill_definition_id`, `harness`, `prompt_sha256`, `timeout_seconds` is accepted and persisted; only the
idempotency key change was rejected. Concrete divergence shown: persisted contract
`output_schema_ref='schema:graph-x:some-other-schema'` next to the event's plan-derived
`output_schema='draft'`. `input_schema_ref`/`output_schema_ref` are graph-owned bindings (they name the
node's typed inputs/outputs used for producer matching, runtime.py:1223-1226, 1287-1288) — recommend
adding both to the frozen tuple at runtime.py:1308. The rest is legitimate application configuration.

**Defect D4 (low): shipped output schema permits `candidate: []`, validator rejects it.**
`seed_output_schema()` compiles the array variant as `{'type':'array','items':{...,'minLength':1}}` —
`minLength` constrains the strings, the array itself has no `minItems` (research_seed.py:100-106,
108-125); probe H confirmed `$defs` self-consistency (refs resolvable; only SeedCandidate/_Reference)
and that pydantic accepts `candidate: []` while `read_seed_candidates` raises `seed_empty_candidate`
(research_seed.py:148-149). A model emitting a schema-legal empty array gets structurally rejected —
correction-loop churn from a schema/validator drift. Smallest fix: declare the field as
`Annotated[list[NonEmptyText], Field(min_length=1)]` so the compiled schema carries `minItems: 1`
(single-source compilation preserved).

Sound parts verified: `compact_dependencies`/`matches_dependencies` digest form is consistent between
dispatch-time check and replay re-verification (protocol_v3.py:298-311; runtime.py:913-927); recovered
unknown-outcome idempotence guard works (runtime.py:1406-1417); validator/schema agree on unknown
fields, optional fields, and `required: ['fields']`; recommendation-basis candidates correctly come out
`ai_recommendation` + `requires_confirmation: True`.

**Observation D5 (low, planned-gap adjacent): the full execution contract of a dispatched-but-unresolved
reservation is not durable.** The reservation row stores only `node_execution_contract_id` +
`input_sha256`; the compacted contract is persisted only on the result event, which by premise does not
exist for UNKNOWN work. `resolve_unknown_with_receipt` re-runs the factory (runtime.py:707) — a drifted
factory/config produces a recovered event whose contract differs from the one the real call ran under.
Deterministic factories are safe today; if the owner wants provenance parity, the smallest route is a
pre-dispatch `graph_node_dispatch` event carrying the compacted contract (replay's if/elif ignores
unknown types — backward compatible), which also benefits correction provenance. Not required for V1.1
wiring; classify as a known planned gap until real calls land.

## New-code defects vs known planned gaps

- New-code defects (fix in the next integration change): D1 (repair drops provider id, RUNNING window),
  D2 (recovered event cannot carry actual id), D3 (factory guard misses schema refs), D4
  (schema `minItems` drift). D1/D2 are the design.md:24 "崩溃窗口…恢复仍待验证" items — now verified
  and concretely located.
- Known planned gaps (not defects; real calls intentionally not wired): no glue service constructing
  `ConfiguredNodeServiceResult` from a real `DispatchReceipt`; output sink not bound to
  LocalArtifactStore; validator/correction nodes not yet in a seed plan; D5 contract durability for
  unresolved dispatches.
- Guard note: C01 import limitation treated as orchestration disclosure per dispatch contract; no
  guard audit pass claimed here.

## Evidence index

- Probe outputs in this directory (run logs inline in probe scripts' stdout; DBs `probe.sqlite.*`,
  `probe2.sqlite*`).
- Cited lines: runtime.py 199-228, 707-735, 929-967, 1223-1226, 1256-1316, 1389-1433, 1717-1743;
  reservations.py 536-547, 588-598, 600-653; sqlite.py 1880-1948, 1996-2020; zhipu_api.py 89, 253-289,
  291-320; direct_api.py 151-197; harness.py 216-268, 287-364, 367-414; artifact_messages.py 6-36;
  research_seed.py 91-125, 128-177; artifacts/local_store.py (logical-key manifest store);
  protocol_v3.py 298-311; tests test_graph_model_contract.py:11-55, test_zhipu_full_artifact_input.py.
