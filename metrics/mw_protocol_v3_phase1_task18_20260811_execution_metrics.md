# Execution Metrics: mw_protocol_v3_phase1_task18_20260811

| Role | Session | Effective terminal route | Status | Result |
|---|---|---|---|---|
| `worker_01` | `019ff00a-9afc-7000-80c9-eaa0a9e136c9` | `deepseek/deepseek-v4-flash:max` | accepted Recovery 04 | SQLite 8/8; rejected/incomplete earlier passes and undeclared-model event retained |
| `worker_02` | `019ff00a-9af3-7000-b7ab-0e0cf2021adb` | `cms-smk/deepseek-v4-flash:max` | accepted Recovery 02 after Codex transport rerun | PostgreSQL 8/8; two Codex Unix-socket-only fresh runs |
| `worker_03` | `019ff120-5bc1-7000-be3d-4e7e0fb1db71` | `opencode-go/deepseek-v4-flash:max` | accepted Recovery 01 | SQLite selected; Memory 5/8 executable receipt; no fallback |
| `finite_code_manager_cursor` | `22119497-40ea-428d-b7e8-a4f0d66dce6e` | `cursor-cli/auto` | `READY` Recovery 01 | independent read-only consolidation; no fallback |

All prompts, stdout, rejected reports, terminal reports and session identifiers are retained. Current accepted verification: 7/7 digests recompute; focused 16/16; full 886 tests + 101 subtests; plan hash match; monitoring diff 0; PostgreSQL process 0.
