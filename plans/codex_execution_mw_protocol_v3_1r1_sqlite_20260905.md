# Codex Execution Plan: mw_protocol_v3_1r1_sqlite_20260905

Objective: 实现Task1R.1产品SQLite adapter与同套双后端ports合同，先红测后最小实现；只在隔离区，保留旧负向测试与历史证据，不启动服务或产品模型。H-R通过后才派发。

## Work Items

| Worker | Assigned item | Report |
|---|---|---|
| `worker_01` | Task1R.1：产品SQLite adapter、明确开启的factory和双后端ports合同测试；禁止改main、前端、monitoring、旧fixture和PoC；保留必要安全语义。 | `runs/execution/mw_protocol_v3_1r1_sqlite_20260905/worker_01.md` |

## Manager

No execution manager is dispatched for this route; Codex reviews the worker outputs directly.

## Codex Acceptance

Initial worker returned (exec59154 closed), session sess_1eefde6c-2f6f-4bf3-9536-355e7e92cab9. Codex verdict REVISE: full suite1344+101green but4 independent acceptance probes red. Fresh GLM-5.3:max reviewer dispatched as mw_protocol_v3_1r1_fresh_20260905 (exec84336 pending). Keep four candidate files frozen until review returns; consolidate findings into same-session worker remediation, no silent fallback/re-dispatch. No product/UI acceptance; no cleanup/archive.
