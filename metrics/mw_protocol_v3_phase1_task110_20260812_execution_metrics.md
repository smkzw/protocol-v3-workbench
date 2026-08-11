# Execution Metrics: mw_protocol_v3_phase1_task110_20260812

| Role | Provider | Model | Status | Duration | Tools | Result |
|---|---|---|---|---:|---:|---|
| `worker_01` | effective `opencode-go` | `deepseek-v4-flash:max` | accepted after same-session repair | 945.181 + 300.157 s | 108 + 21 calls | immutable inventory/quarantine; 54 focused pass |
| `worker_02` primary | effective `opencode-go` | `deepseek-v4-flash:max` | incomplete; resume session missing | 351.046 + 0.373 s | 31 calls | explicit terminal fallback condition |
| `worker_02` fallback | `deepseek` | `deepseek-v4-flash:max` | accepted after 2 initial repairs + Codex completion; post-verifier Recovery 04 complete | 954.321 + 1405.834 + 1000.658 + 255.012 s | 67 + 97 + 69 + 54 calls | exact whole-payload drift gate; 119 focused pass |
| `worker_03` | effective `opencode-go` | `deepseek-v4-flash:max` | accepted after same-session P1 repair | ~1459.4 + 282.442 s | 130 + 26 durable tool-result records | 101 route/94 service legacy-write guard; 47 focused and 1,221 full pass |
| `finite_code_manager_cursor` | `cursor-cli` | `auto` | `READY_FOR_FRESH_VERIFIER` | 341.049 s | runner did not expose count | read-only; 220 focused/1,221 full + falsification pass |

All prompts, runner reports, raw stdout/tool events, session IDs, health warnings and fallback evidence are retained under the task execution paths. Tool counts are `tool_execution_start` events in runner-owned stdout.
