# Conference Metrics: mw_protocol_v3_model_fallback_review_20260923

Date: 2026-09-23

| Role | Provider | Model | Status | Duration | API calls | Tokens | Result |
|---|---|---|---|---:|---:|---:|---|
| `evidence_single_object` | `codebuddy-cli` | `deepseek-v4.1-flash` | terminal success, 2 same-session rounds | 340.021 s | not reported | not reported | PASS after repair |

## Timeout And Retry Evidence

Initial pass 219.962 s; follow-up 120.059 s. Both used session `01a0ca17-f0b5-7162-9cfa-9a3b8b0c57eb`. No fallback, timeout, redispatch or new reviewer session occurred.

## Quality Decision

Initial REVISE; owner repaired material findings; same-session follow-up found no remaining P0/P1. Codex independently verified tests, build, diff and isolated API state, then accepted the bounded batch.
