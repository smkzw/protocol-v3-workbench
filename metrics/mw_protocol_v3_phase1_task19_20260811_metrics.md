# Metrics: mw_protocol_v3_phase1_task19_20260811

Date: 2026-08-12

| Field | Value |
|---|---|
| Task type | `finite_code_task` |
| Risk | `high` |
| Primary effective route | `opencode-go/deepseek-v4-flash:max` |
| Manager | `cursor-cli/auto` |
| Duration | approximately 2 h 33 min from tracked-task initialization through Codex acceptance |
| Product source modules | 12 files under application/agent5/api/client |
| Product + focused-test footprint | approximately 508 KiB before cache cleanup |
| Focused verification | `115 passed` |
| Full Protocol v3 regression | `1001 passed` |
| Independent acceptance | Qwen `READY`; Cursor fallback same-session completion `READY` |
| Product storage | `sqlite / not_ready` |
| Result | `PASS` |

## Verification Burden

High: typed clinical-fact authority, atomic UoW/outbox behavior, idempotency, public/audit separation and cross-module API contracts required worker repair, manager review, two independent verifier contexts and Codex re-execution.

## Routing Decision

The night-window OpenCode Go overlay was used for finite-code work. Worker 01's first runtime identity mismatch triggered only the declared fallback; worker 02/03 and manager repairs reused their original sessions. No latency-based redispatch occurred.
