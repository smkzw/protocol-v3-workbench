# Conference Metrics: mw_protocol_v3_1r2_functional_fresh_20260905

Date: 2026-09-05

| Role | Provider | Model | Status | Duration | API calls | Tokens | Result |
|---|---|---|---|---:|---:|---:|---|
| `general_single_object` | `grok-build` | `grok-4.6:high` | terminal | 663.365s | not extracted | not extracted | NOT_READY |
| same-session recheck | `grok-build` | `grok-4.6:high` | terminal | 196.145s | not extracted | not extracted | F1/F2 resolved |

## Timeout And Retry Evidence

Both used session a60e60e9-f3ba-4306-8d5a-ae19eef0f4f5. No fallback/failure; original and recheck runner receipts in logs/conference/mw_protocol_v3_1r2_functional_fresh_20260905/. Initial exec96863 and recheck78784 terminal0. Long waits retained same handles.

## Quality Decision

Functional findings resolved; no whole-task/full-repository acceptance inferred. Independent reviewer and Codex separately ran focused tests. No repeated discovery-round claim.
