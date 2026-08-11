# Conference Metrics: mw_protocol_v3_phase1_task17_acceptance_20260811

Date: 2026-08-11

| Role | Provider | Model | Status | Duration | API calls | Tokens | Result |
|---|---|---|---|---:|---:|---:|---|
| `general_pi_qwen38` | `alibaba` | `qwen3.8-max` | complete | runner-owned | runner-owned | runner-owned | Findings incorporated; report retained |
| `general_grok45` | `grok-build` | `grok-4.5` | complete after same-session follow-ups | runner-owned | runner-owned | runner-owned | Functional findings incorporated; reports retained |
| `fresh_luna_functional` | `openai CLI compatibility` | `gpt-5.6-luna` max | complete | same session | runner-owned | runner-owned | `READY`, P0–P4 all zero |

## Timeout And Retry Evidence

- Slow or incomplete outputs were continued only in their existing sessions; no latency-based redispatch occurred.
- Native Luna probe explicitly rejected the requested selector; CLI compatibility fallback used session `019fefbf-636b-7462-9720-2b4629f83a80`.
- One Luna pass was intentionally interrupted when it crossed into out-of-scope security testing. The final functional-only follow-up used the same session.

## Quality Decision

`PASS` for Task 1.7 functional scope. Historical findings and repairs remain visible; the final isolated functional verdict is `READY`, and Codex independently reproduced deterministic acceptance.
