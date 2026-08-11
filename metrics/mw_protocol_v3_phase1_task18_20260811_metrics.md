# Metrics: mw_protocol_v3_phase1_task18_20260811

Date: 2026-08-11 (paused 17:44:49 CST)

| Field | Value |
|---|---|
| Task type | `finite_code_task` |
| Risk | `high` |
| Selected provider | `cms-smk` |
| Selected model | `deepseek-v4-flash` (same-session switch from historical `cms-model`) |
| Selected effort | `max` |
| Duration | Active 16:52–17:44 CST; resumed 20:26 CST; accepted 22:47 CST |
| API calls | All original-session recoveries, route switches, stdout and rejected/accepted reports retained |
| Artifact size | Common suite; Memory/SQLite/PostgreSQL adapters; 7 deterministic JSON receipts; decision; selected surface; focused tests; retained records/logs |
| Result | `ACCEPTED / SQLITE_SELECTED / PRODUCT_ACTIVATION_FAIL_CLOSED / READY_FOR_COMMIT` |

## Verification Burden

Task 1.8 closed its high-burden evidence: SQLite and PostgreSQL each passed all eight durable invariants; Memory passed five functional invariants and failed three durable capabilities explicitly; selection and import boundaries passed independent review.

## Routing Decision

Initial route reason: default route for task type.

## SQLite Acceptance Snapshot — 2026-08-11 21:36 CST

- Python / SQLite: `/opt/homebrew/bin/python3.12` / `3.53.1`.
- Full candidate runs: `2/2 all_passed`; deterministic digest match `64a56f66e4300b318f6586803151f475e2ad8de9a74d0acfad14fe46a81adad8`.
- Concurrent CAS: p95 `1.666 ms` and `1.687 ms`; `8` distinct actual workload connections; overlap `8`; lost/duplicate updates `0`.
- Crash: receipt explicit; `WIFSIGNALED=true`; `WTERMSIG=9`; derived return code `-9`; PID match; RPO `0`; pending outbox; duplicate effects `0`.
- Migration: `10` persisted families; `100%` accounting; every family includes persisted quarantine evidence.
- Regression: `870 passed`, `101 subtests passed`, one known Python 3.14 tar deprecation warning.

## Final Acceptance Snapshot — 2026-08-11 22:47 CST

- Selected target: SQLite 3.53.1 for local/private single-workstation deployment.
- Durable candidate digests: SQLite `64a56f66…adad8`; PostgreSQL `fce59b62…8630`.
- Memory receipt: 5 pass / 3 explicit fail; digest `8fc8a060…84a7b`.
- Current regression after Memory evidence/tests: `886 passed`, `101 subtests passed`.
- Manager: `READY`; Codex: accepted; monitoring diff 0; PostgreSQL process 0.
