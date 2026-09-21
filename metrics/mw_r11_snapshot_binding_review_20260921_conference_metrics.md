# Conference Metrics: mw_r11_snapshot_binding_review_20260921

Date: 2026-09-21

| Role | Provider | Model | Status | Duration | Model requests | Final cumulative tokens | Result |
|---|---|---|---|---:|---:|---:|---|
| `general_single_object` | `zcode-live-bigmodel` | `GLM-5.3-Flash:max` | terminal | 24m 24s | 50 | 131892 | PASS after same-session corrective verification |

## Timeout And Retry Evidence

The first pass completed in 1074.272 seconds. The same session continued for corrective verification and completed without fallback. Session: `sess_6dbc92ce-b722-45a0-ae67-dd518c02cfe2`. Both runtime receipts verified requested and response model `GLM-5.3-Flash` with observed effort `max`.

## Quality Decision

The conference materially changed acceptance: it exposed a real stale-medical-facts error in Study A, caused owner rollback, and verified the corrected blocking semantics. The batch is accepted; full Study A and Protocol v3 acceptance remain open.
