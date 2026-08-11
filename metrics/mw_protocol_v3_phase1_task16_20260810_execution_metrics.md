# Execution Metrics: mw_protocol_v3_phase1_task16_20260810

Date: 2026-08-11

| Role | Provider | Model | Status | Runner duration | Session | Result |
|---|---|---|---|---:|---|---|
| `worker_01` | `cms-smk` | `cms-model` | completed | 740.55 s | `019feb71-c96a-7000-83b4-20443bf0bd01` | foundation accepted after Codex repair |
| `worker_02` | `cms-smk` | `cms-model` | completed + 1 follow-up | 8702.83 s | `019feb8b-1eb4-7000-a623-104113ad5bf8` | implementation rejected; Codex repaired current source |
| `worker_03` | `cms-smk` | `cms-model` | completed + same-session repairs | 1138.88 s | `019feb68-6061-7000-b4a6-b436e891bdef` | restored specification + export facade accepted |
| `finite_code_manager_cursor` | `cursor-cli` | `auto` | completed | 223.13 s | `b2741f11-8d7f-4cb3-86a6-4959b4564505` | READY with one P3 later closed by Codex |

Tool calls remained enabled. No execution-route fallback occurred. Codex, not workers or manager, performed final acceptance; worker boundary violations are retained in raw evidence and excluded from proof of done.
