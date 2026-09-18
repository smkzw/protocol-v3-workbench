# Task 1R.1 product storage gate — 2026-09-05

## Verdict

ACCEPTED, Task1R.1 only, after independent verifier READY on the exact final hashes below. Phase1R as a whole and the product workflow are NOT accepted. Task1R.2 has not started.

## Boundary

Product SQLite adapter and selection wiring plus repository/product tests only. Main API, frontend, monitoring, contracts and Task2.1 PoC have zero tracked deltas. No product model, service, OCR/translation, Word, live database, migration/cutover or full-repository regression was run by this gate. Current product schema remains v1; test-injected migration2 is not an activation.

## Frozen files

| File | SHA256 |
|---|---|
| services/api/app/protocol_workflow/storage/sqlite.py |18770a1c277f8808258280260cb84c04ed6bce96f4c8cf73bc7dc45eb389275e|
| services/api/app/protocol_workflow/storage/selected.py |153fc687d1414ca41218daec7b1777a73e98dbf8476491ba926a91c3d9d7a6d3|
| tests/protocol_v3/test_repository_backends.py |0b1dd33b2b551fb6b144d3df1bff652d886e51edf76b82bff94420d6c1d044f5|
| tests/protocol_v3/test_sqlite_product_storage.py |6710dd96865f2272b2b83ba0f5f615f453625983a404daca1e1bb56406a7c069|

## Verification

- Codex140focused PASS1.10s (8 independent acceptance probes included) and1372+101 fullProtocolv3 PASS18.70s. Evidence runs/mw_protocol_v3_1r1_codex_20260905/repair_03_focused.xml and repair_03_full.xml. No new skipped/xfail cases; two preexisting deprecation warnings.
- Independent GLM-5.3:max verifier independently reproduced140focused,1372+101full and2own closure probes. Codex then read those2probes and reproduced2PASS0.28s, repair_03_independent_closure.xml. Tests are temporarySQLite/fakes, not clinical/model acceptance.
- Final review: runs/conference/mw_protocol_v3_1r1_fresh_20260905/evidence_single_object_final_storage_verification.md. Session sess_e31a1421-b58b-4d69-8025-7a0795fbc289,167.816s,9observedtoolcalls,one round,nofallback, exactGLM-5.3:max request/response identity verified. ReportSHA266cb45fb065134a48a5a1c16f55a3ca153d553a613c60b37a9a6ea9ddda5480. Four hashes before/after equal; no implementation by verifier.
- Closed via actual counterexamples: foreign schema/version adoption, pre-entry durable writes, caught partial event/projection SQL failure, volatile product path, naive timestamp reinterpretation, missingPK/UNIQUE/NOTNULL, forward schema migration/cachedsignature drift and caughtpartialoutboxclaim.

## Execution and independent review lineage

Hermes was not assigned by these live route packets; no Hermes dispatch, manager or chair result is claimed. This statement records the actual route boundary, not a missing required node.

Originalworker sess_1eefde6c-2f6f-4bf3-9536-355e7e92cab9 produced initial/repair_01/repair_02; its constraints_gate packet actual audit-execution and review-gate passed for repair_02. Prior followup auditFAIL and shell-edit deviation remain historical failures, not erased. The final two bounded corrections were executed inline by Codex after all runners terminated, using apply_patch and real red-first tests; no duplicate active owner or new route was created. Independent verifier owned their disposition, returning READY only after new-source/probe checks. No manager was declared or claimed.

The execution packet's source hashes are historical; its PASS is not misrepresented as validating Codex's later direct revision. This gate binds the final revision using explicit hashes, fresh verifier evidence and non-LLM tests. validate-conference passed; all original prompts/reports/logs and NOT_READY decisions retained.

## Next action / limitations

Before Task1R.2 actual main mounting/full-regression TDD, resolve the pending user choice: isolated legacy-only PDF test dependencies versus moving old PDF migration earlier. Existing hash-locked v3 environment does not close the legacy main dependency tree (xlrd and fitz); do not silently add PyMuPDF to product lock or fake main import success. Product startup/routerdefaultoff and durableallowlist are not yet implemented.

1R.3 must classify driver/COMMIT failures and verify real API/restart/replay/backup; liveWAL requires backup API or provenconsistentcopy. Schema introspection is not arbitrary-file tamper authentication (trigger/view/collation/TOCTOU limitations remain); add practical startup/concurrency checks at actual integration. Preserve all safety/history compatibility in1R.4. Security/productmodel/UX/nativeWord/cutover gates remain pending. No cleanup.
