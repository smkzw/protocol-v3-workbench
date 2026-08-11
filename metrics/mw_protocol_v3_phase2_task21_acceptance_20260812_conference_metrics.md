# Conference Metrics: mw_protocol_v3_phase2_task21_acceptance_20260812

Date: 2026-08-12

| Role | Provider | Model | Status | Duration | API calls | Tokens | Result |
|---|---|---|---|---:|---:|---:|---|
| `general_pi_qwen38` | `alibaba` | `qwen3.8-max:xhigh` | same-session repair recheck complete | 1026.014 + 493.870 s | 91 + 48 tool events | retained in raw logs | round 1 NOT_READY; round 2 `TASK21_READY` |
| `general_grok45` | `grok-build` | `grok-4.5` | recovery exhausted; no usable verdict | 22.052 + 18.651 + 13.201 s | runner did not expose count | retained in raw logs | two cancelled/incomplete outputs, then explicit continuation failure |

## Timeout And Retry Evidence

Qwen reused session `019ff2f2-be75-7000-a21c-2f98c582c16d`; no fallback. Grok reused session `e63af615-c538-47f9-b160-7043a8482bd7` for both recoveries; round 3 exited 3 with `resumed session continuation failed`. No new session or fallback was launched during the user-requested pause closure.

## Quality Decision

Qwen's first-pass veto was correct and drove two bounded repairs plus four regressions. Its same-session recheck and Codex anchors support Task 2.1 acceptance. Grok provides no usable second opinion; final status is `PASS_WITH_PARTICIPANT_DEGRADED`, never unanimous READY.
