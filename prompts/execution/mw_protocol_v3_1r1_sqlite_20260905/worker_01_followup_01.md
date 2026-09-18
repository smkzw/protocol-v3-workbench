Delegated mode. You are a bounded worker, not the user-facing agent.
Follow only this prompt's Hard boundaries, assigned work and output schema. Do not leak secrets, write outside the boundary, start conferences, rediscover routes, scan the internet, or claim final acceptance. Do not read home AGENTS.md or SOUL.md.

# Execution module role: finite_code_executor — Task1R.1 bounded repair

Initial read set:
- `context/mw_protocol_v3_1r1_sqlite_20260905_execution_context.md`
- `plans/mw_protocol_v3_review_amendment_20260905.md`

Runner-managed report path: `runs/execution/mw_protocol_v3_1r1_sqlite_20260905/worker_01_followup_01.md`. Return your report as final response; never write this file through tools.

Output schema: # Execution Output; ## Boundary And Context Check; ## Work Performed; ## Artifacts And Evidence; ## Commands And Observations; ## Blockers Or Missing Environment; ## Rerun Requests Or Next Step.

Resume sess_1eefde6c-2f6f-4bf3-9536-355e7e92cab9 on the same declared ZCode/GLM-5.3-Flash:max route. Initial pass is REVISE, not accepted. This is targeted repair, no new task topology or delegation.

## Hard boundaries and mandatory reread

Read completely ../plan-upgrade-20260905/mw_protocol_v3_implementation_plan_v2_20260905.md and plans/mw_protocol_v3_review_amendment_20260905.md before editing (the initial receipt only proves sections40–190; report named wrong file). Read original execution context, ports and actual callers as needed to verify complete semantics. Approved1R.4 preserves safety/compatibility, no deletions now.

Writes ONLY the same four candidate files: services/api/app/protocol_workflow/storage/sqlite.py, storage/selected.py; tests/protocol_v3/test_repository_backends.py, test_sqlite_product_storage.py. New additive evidence only runs/mw_protocol_v3_1r1_20260905/repair_01/. Do not overwrite prior evidence. Codex-owned probes and reviews read-only. Runner owns report paths. No services, product models, network, packages, commits/staging, global edits, LIVE/monitoring/SOP/plan-upgrade writes. No old tests/fixtures/ports/memory/PoC/main/frontend edits.

Use apply_patch for manual file changes. First locate it with command -v apply_patch; parent verified an available executable. If unavailable in your shell, report that explicitly before using another editor; do not silently claim compliance. Initial native Write/Edit use was recorded. Do not write runner reports through tools.

## Consolidated acceptance blockers: red tests first, smallest safe fix

Read runs/mw_protocol_v3_1r1_codex_20260905/test_acceptance_probes.py (read-only) and independent runs/conference/mw_protocol_v3_1r1_fresh_20260905/evidence_single_object.md. Reviewer suggested conditional READY; Codex overrides using the following reproducible failures. Preserve initial reports as history.

1. A foreign DB with a populated table named schema_version (version0 or1) plus unrelated_legacy_notes is accepted/mutated. Validate known migration history and actual owned schema before adoption or any mutation. MAX(version) is insufficient; reject malformed/duplicate/gapped/unknown history and incompatible/missing owned structures. Existing unknown DB must not be rewritten even during rejection (consider readonly preflight and WAL close checkpoint risk). Do not introduce speculative migration frameworks or adopt existing foreign rows.
2. Factory-created UoW has autocommit connection until __enter__; repository writes before entry persist and rollback cannot remove them. Require active transaction for mutators centrally, preserve allowed read/diagnostic and closed/nested semantics. Do not change ports/memory. Add tests proving zero durable changes after rejected pre-entry mutation.
3. Event batch SQL second-write failure caught inside outer with commits the first row. Semantic prevalidation alone is insufficient. Use smallest SQLite atomic operation boundary (e.g. savepoint) to roll back the whole batch without losing unrelated successful work. Add actual injected SQL failure red test. Check sibling compound operations, especially read-model DELETE+INSERT replacement, for the same partial-write pattern; cover and fix the shared root cause within allowed adapter.
4. Product path ':memory:' is accepted and schema vanishes when bootstrap connection closes. Reject volatile special paths before I/O; actual file persistence, not backend label, is the requirement. Do not overreject ordinary supported file paths.
5. New chain-violation tests mask named failures with already-appended e1. Do not remove or weaken existing fixtures/assertions; add true first-violation cases for gap/prev/wrong-stream/in-batch duplicates and whole-batch rollback. Preserve immutable old negative tests.
6. _dt_to_iso silently treats naive dates as local time, changing data by8h. Reject naive timestamps explicitly at serialization boundary and add a focused negative test; verify aware UTC/offset roundtrip. Do not silently reinterpret caller data.
7. Add empty-version-row regression and correct obsolete narrow SQLite WAL defect comments. Keep default no-builder negative tests unchanged. Main composition environment switch is still required in1R.2; this task's explicit function route does not supersede that gate.

Driver-level exception translation in application/service.py and events/unit_of_work.py is mandatory1R.3 pending work outside your scope; report, do not edit those files. No need to build router or activate product now.

## Evidence and handoff

Use /opt/homebrew/bin/python3.12, PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/api:packages:. and pytest -p no:cacheprovider. First capture actual new failures, then minimum implementation. Run both new test files, the read-only Codex acceptance probes, and full tests/protocol_v3. No whole-repo run. All DBs test-owned tmp. Record exact commands/results, four final hashes, actual configuration/lifecycle behavior, unresolved items and source-scope diff. Initial104 cases consist74 shared+30 product, not48+24; use actual result counts. Do not claim task closure or product acceptance. Codex and independent verifier own done.
