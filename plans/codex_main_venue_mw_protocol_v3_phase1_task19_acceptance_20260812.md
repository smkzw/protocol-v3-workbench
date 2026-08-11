# Codex Main-Venue Plan: mw_protocol_v3_phase1_task19_acceptance_20260812

Date: 2026-08-12
Objective: 独立反证验收 Task 1.9 application service、Agent⑤ authority、API/client 合同与医学监查隔离

## Task Decomposition

1. 独立验证 storage-neutral application/UoW、CAS、重放和零写查询。
2. 独立反证 Agent⑤ retained authority、lineage、Gate/QC/提交状态越权。
3. 独立验证 API/client 项目隔离、中文公开错误、OpenAPI、Node 实执行及共享路径零差异。

## Source Packet

- 冻结 Task 1.9 及 SHA-256。
- design-v1.2 指定章节。
- 当前 application/agent5/api/client 与三项测试。
- 相邻 canonical/events/ports/storage/errors/registries 只读合同。
- 禁止读取 Worker/manager 或其他 participant 的推理报告。

## Participant Assignments

| Role | Route | Output |
|---|---|---|
| Participant 1 | `alibaba/qwen3.8-max:xhigh` | `runs/conference/mw_protocol_v3_phase1_task19_acceptance_20260812/general_pi_qwen38.md` |
| Participant 2 primary | `grok-build/grok-4.5` | `runs/conference/mw_protocol_v3_phase1_task19_acceptance_20260812/general_grok45*.md` |
| Participant 2 declared fallback | `cursor-cli/cursor-grok-4.5-high` | `runs/conference/mw_protocol_v3_phase1_task19_acceptance_20260812/general_grok45_cursor_fallback*.md` |

## Conference Panel Coordination

Codex chairs directly. Grok's incomplete three-pass session triggered the declared Cursor fallback. Cursor's missing Shell evidence was repaired by resuming the same Cursor session with Shell enabled; no replacement session was opened.

## Main-Venue Review

Codex compares independent reports only after completion, reruns decisive deterministic checks from the current filesystem, and owns final acceptance.

## Timeout And Retry Tracking

All session IDs, durations, cancelled tool calls, Ask-mode rejection, fallback reason and same-session recovery are recorded in the conference metrics and runner logs. No fixed-interval polling or latency-based fallback occurred.

## Codex Verification Checklist

- [x] Plan SHA exact match.
- [x] Focused trio 115 passed.
- [x] Full Protocol v3 suite 1001 passed.
- [x] Node client executed and not skipped.
- [x] Product storage remains fail-closed `not_ready`.
- [x] Shared main.py remains unmounted.
- [x] Medical-monitoring/shared tracked delta zero.
- [x] No P0–P4 defect remains in bounded Task 1.9.
- [x] No security, service, browser or live-model work performed.
