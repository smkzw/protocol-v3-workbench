# Execution Output:

`P1-G1_FUNCTIONAL_NOT_READY`

Original frozen `P1-G1` cannot pass because Task 1.11/security is `USER_EXCLUDED`. The current functional amendment is also not ready because P0-CORE remains unverified, specifically H0/H1/H3 closure.

## Boundary And Context Check

- Read-only audit within the current workspace.
- No source, configuration, test, or report files modified.
- No services started, live databases accessed, or security tests/scans run.
- Task 1.11/security was not treated as PASS.
- Parent Codex retains final acceptance authority.

## Work Performed

- Audited current `HEAD` `9602458`, frozen plan, accepted Task 1.1–1.10 evidence, current Protocol v3 source/tests, storage PoC records, migration records, and Phase 0/P0-WORD evidence.
- Built the non-security P1-G1 predicate matrix.
- Reconciled test counts, migration hashes, storage selection, legacy-write guards, replay hashes, P0-CORE, and P0-WORD state.
- Confirmed migration mapping integrity: 7 families, 20 source types, `verified=True`, 0 issues.
- Confirmed no tracked diff and no source drift.

## Artifacts And Evidence

| Predicate | Status | Evidence |
|---|---|---|
| Canonical contracts/reducers/CAS | PASS | `packages/contracts/workbench_contracts/protocol_v3.py:204-247`; reducer/CAS tests passed. |
| Repository/artifact/UoW | PASS | `tests/protocol_v3/test_repository_contract.py:230-253,399-508,1306-1458`; `test_artifact_store.py:91-132,422-439`. |
| Event/outbox/inbox/replay | PASS | `test_event_outbox_atomicity.py:288-779,907-1074`; `test_event_replay.py:291-319,518-613`. |
| Execution reservations | PASS | `test_execution_reservations.py:258-357,369-449,461-515,610-686,698-743,755-843,856-880`. |
| Application service | PASS | `test_application_service.py:393-445,452-748`. |
| API boundary | PASS, contract-level | `test_protocol_v3_api_contract.py:1032-1072,1264-1284`; `main.py` has no `protocol_workflow` reference. |
| Agent⑤ authority boundary | PASS | `test_agent5_authority_boundary.py:1222-1347,1435-1541`. |
| Migration/quarantine/idempotency | PASS | `test_v2_v3_migration_dry_run.py:614-715`; `test_v2_v3_migration_idempotency.py:1859-1952,1974-1991,2237-2430`. |
| Selected storage decision | PASS, PoC/decision-level | SQLite 3.53.1 selected; evidence at `pocs/protocol_v3/storage/decision.md:8-18,26-72,108-142,193-228`. |
| Product storage activation | UNVERIFIED / not ready | `services/api/app/protocol_workflow/storage/selected.py:235-290,312-342`; product adapter is intentionally unwired. |
| Legacy store write guard | PASS, pure contract-level | `test_legacy_mutation_guard.py:274-324,389-424,480-489,633-680`; no live cutover occurred. |
| Artifact/event replay hash equality | PASS | `test_artifact_store.py:91-132,422-439`; `test_event_replay.py:529-589`. |
| P0-CORE validity | UNVERIFIED | `runs/mw_protocol_v3_phase0_repository_hygiene.md:58-60` explicitly leaves H0/H1/H3 open. |
| P0-WORD/release state | Technical `PASS_WITH_RESIDUALS` | `reviews/codex_mw_protocol_v3_phase0_task08_20260810_review.md:8,19-30,44-53`; not overall release readiness. |
| Task 1.11/security | USER_EXCLUDED | Explicit current-task boundary; never PASS. |

## Commands And Observations

- Collection with correct source roots:

  `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/api:packages python3 -m pytest --collect-only -q -p no:cacheprovider tests/protocol_v3`

  Result: `1,226 tests collected`.

- Focused non-security P1 subset:

  Result: `798 passed`.

- Full current Protocol v3 suite:

  Result: `1,225 passed, 1 failed`.

  The single failure was an environment permission error in `test_repository_hygiene_mutator.py::TestIntegrityRemediation::test_p1_builtin_occupancy_blocks_port_8911`, not a focused P1 functional failure. It was not rerun.

- Mapping verification:

  - Semantic hash: `34db4b34d5b94114f88c171c125c817d61962cfac3ad2329c1dd63b76b1bdfa2`
  - Raw mapping file hash: `8ee8ac78b98aa4ed836679f309a2695ca2c10d8dce65dd1fee153a88da1e6806`
  - 7 families, 20 source types, 0 verification issues.

- Storage evidence confirms both SQLite and PostgreSQL candidate receipts pass the frozen workload and eight invariant bodies. The decision record’s historical `870 passed, 101 subtests` count is stale relative to the current 1,226-test collection.

## Blockers Or Missing Environment

1. P0-CORE is not grounded. `runs/mw_protocol_v3_phase0_repository_hygiene.md:60` states occupancy remains unchecked, the protected manifest belongs to Task 0.4, and mutators remain locked. The source-closure repair also states it does not accept P0-CORE as a whole at `reviews/codex_mw_protocol_v3_phase0_source_closure_20260810_review.md:36-41`.
2. No final non-security P0-CORE acceptance record proving H0/H1/H3 closure was found.
3. Product SQLite activation remains intentionally fail-closed until the product adapter is wired.
4. The full aggregate suite has one sandbox permission blocker in the Phase 0 occupancy test; this does not change the focused P1 result.

## Rerun Requests Or Next Step

Do not promote this gate to READY or start Phase 2 under the frozen gate. The owning next step is to close and accept non-security H0/H1/H3/P0-CORE evidence, then rerun the focused P1-G1 functional matrix.

No Task 1.11/security rerun is requested or permitted under the current instruction.
