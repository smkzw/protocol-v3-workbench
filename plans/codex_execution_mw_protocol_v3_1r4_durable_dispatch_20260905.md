# Codex Execution Plan: mw_protocol_v3_1r4_durable_dispatch_20260905

Objective: Repair real SQLite reservation coordinator transaction boundary: durable reservation before physical dispatch, no takeover of active ownership, retain unknown reconciliation and explicit retry history. Current direct UoW composition fails independent-connection probe. Minimal factory/runtime wiring, not a new platform. No security-specialist work or product model calls.

## Work Items

| Worker | Assigned item | Report |
|---|---|---|
| `worker_01` | Own only services/api/app/protocol_workflow/runtime/reservations.py, services/api/app/protocol_workflow/storage/sqlite.py, tests/protocol_v3/test_sqlite_reservation_lifecycle.py, and new tests/protocol_v3/test_durable_reservation_dispatch.py. Read current1R.4 checkpoint for reproducible failure and context. Implement committed-operation coordinator factory without committing arbitrary caller business transactions; preserve shared UoW API. Add genuine crash and concurrent live-owner tests; retain old fixtures/expected, do not hide new failures. No product calls/live changes/cleanup/task closure. | `runs/execution/mw_protocol_v3_1r4_durable_dispatch_20260905/worker_01.md` |

## Manager

No execution manager is dispatched for this route; Codex reviews the worker outputs directly.

## Codex Acceptance

TODO: verify artifacts, tests, source claims, rendered surfaces, blockers, and user-facing completeness.
