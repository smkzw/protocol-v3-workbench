# Conference Metrics: mw_protocol_v3_phase1_task110_acceptance_20260812

Date: 2026-08-12

| Role | Provider | Model | Status | Duration | API calls | Tokens | Result |
|---|---|---|---|---:|---:|---:|---|
| `general_pi_qwen38` | `alibaba` | `qwen3.8-max:xhigh` | same-session repair recheck complete | 2041.333 + 61.539 s | 298 + 4 tool events | retained in raw logs | READY; original O2 closed by 8/8 counterexamples |
| `general_grok45` | `grok-build` | `grok-4.5` | first completion and same-session repair recheck complete | 22.255 + 44.974 + 34.341 s | runner did not expose count | retained in raw logs | READY; required counterexamples and regressions pass |

## Timeout And Retry Evidence

No primary fallback. Qwen and Grok post-repair checks reused their original sessions. Grok first terminal output lacked the report, then the same session completed it; no new session or route change.

## Quality Decision

First-pass conference was NOT_READY by Codex due independently reproduced explicit-coverage drift. Worker 02 Recovery 04 took 255.012 s / 54 tool events in the same accepted fallback session. Both participants then returned READY in their original sessions, and Codex independently reran 225 focused, 1,226 full and 3 API-isolation checks. Final conference decision: READY.
