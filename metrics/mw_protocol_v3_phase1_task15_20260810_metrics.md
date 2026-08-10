# Metrics: mw_protocol_v3_phase1_task15_20260810

Date: 2026-08-10

| Field | Value |
|---|---|
| Task type | `finite_code_task` |
| Risk | `high` |
| Initial provider/model | `cms-smk/cms-model` (`high`) |
| Duration | approximately 3 h 25 min including repair conferences |
| Functional files verified | 13 |
| Task 1.5 tests | 155 passed |
| Integrated Task 1.1–1.5 tests | 376 passed |
| Static checks | Ruff check/format, compile, diff check pass |
| Medical-monitoring changes | 0 |
| Result | `PASS` |

## Verification Burden

Initial worker output required main-venue counterexamples, three Luna passes, a two-participant final conference, declared Grok no-progress fallback, and two Cursor same-session repair reviews before no open P0–P4 remained.

## Routing Decision

Finite-code execution used the guard route. Independent high-risk verification used CLI-compatible Luna after the native current-session capability had already been rejected, then the current conference route. All sessions, fallbacks and outputs are preserved.
