# Metrics: mw_protocol_v3_phase1_task110_20260812

Date: 2026-08-12 (accepted)

| Field | Value |
|---|---|
| Task type | `finite_code_task` |
| Risk | `high` |
| Selected provider | `opencode-go` |
| Selected model | `deepseek-v4-flash` |
| Selected effort | `max` |
| Duration | Worker 01/02/03, 341.049 s manager and verifier durations retained in execution/conference metrics |
| API calls | Worker 03 durable session adds 130 initial + 26 repair tool-result records; raw stdout and full session history retained |
| Artifact size | 101 guarded legacy-write routes; 94 guarded legacy-write service operations; 195 discovered service candidates |
| Result | accepted; manager READY, first verifier found P1, same-session repair closed it, Qwen/Grok rechecks READY, Codex final checks pass |

## Verification Burden

High: pure migration evidence must bind real source identity, preserve every source field explicitly, prevent hash drift, retain all lineage and prove zero shared/monitoring mutation. Final burden is 225 focused, 1,226 full and 3 API-isolation tests plus direct drift/cutover/project counterexamples and two independent post-repair rechecks.

## Routing Decision

Finite-code route selected by the executable guard. Worker 02 used the declared `deepseek` fallback only after its primary session returned incomplete and the same-session resume explicitly failed with `Session not found`; no fallback was triggered by latency.
