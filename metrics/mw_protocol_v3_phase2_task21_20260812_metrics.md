# Metrics: mw_protocol_v3_phase2_task21_20260812

Date: 2026-08-12

| Field | Value |
|---|---|
| Task type | `finite_code_task` |
| Risk | `high` |
| Selected provider | `opencode-go` |
| Selected model | `deepseek-v4-flash` |
| Selected effort | `max` |
| Duration | 2,362.007 s accumulated worker + manager runner time; wall-clock not reconstructed |
| API calls | not exposed; 737 worker tool events plus manager count unavailable |
| Artifact size | 186,981 bytes across seven PoC source/test files |
| Result | `TASK21_ACCEPTED_FUNCTIONAL_POC_WITH_DEGRADED_SECOND_PARTICIPANT` |

## Verification Burden

High-risk immutable/recovery contracts required focused and full deterministic tests, direct falsification of parallel-edge cycles and mutable nested inputs, fresh independent review, plan/material hashes and protected-path verification. No browser/live-provider check was appropriate for this offline contract-only slice.

## Routing Decision

The executable policy selected effective `opencode-go/deepseek-v4-flash:max` for workers and `cursor-cli/auto` for the manager. The conference used Qwen and native Grok Build as recorded; no silent fallback occurred. The older direct Pi scaffold was superseded and not dispatched.
