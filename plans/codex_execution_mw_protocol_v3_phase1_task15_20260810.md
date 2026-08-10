# Codex Execution Plan: mw_protocol_v3_phase1_task15_20260810

Objective: 实现并验收 Protocol v3 Task 1.5 事件权威、transactional outbox/inbox、checkpoint 对账和确定性恢复

## Work Items

| Worker | Assigned item | Report |
|---|---|---|
| `worker_01` | 实现 events/models.py、events/store.py 与 test_event_replay.py：稳定事件 envelope/upcaster registry、确定性 replay、checkpoint/event 对账与 canonical hash 重建 | `runs/execution/mw_protocol_v3_phase1_task15_20260810/worker_01.md` |
| `worker_02` | 实现 events/outbox.py 与 events/inbox.py：发送后回写前崩溃恢复、idempotent inbox semantic effect 与明确状态机；不修改既有 ports | `runs/execution/mw_protocol_v3_phase1_task15_20260810/worker_02.md` |
| `worker_03` | 实现 events/unit_of_work.py、events/__init__.py 与 test_event_outbox_atomicity.py：canonical mutation/event/outbox 原子事务、inbox-first acknowledgement、跨组件恢复集成测试 | `runs/execution/mw_protocol_v3_phase1_task15_20260810/worker_03.md` |

## Manager

| Role | Provider | Model | Report |
|---|---|---|---|
| `finite_code_manager_cursor` | `cursor-cli` | `auto` | `runs/execution/mw_protocol_v3_phase1_task15_20260810/manager.md` |

## Codex Acceptance

Codex independently inspected every product/test diff, excluded worker 01/03 out-of-bound test runs, repaired counterexamples, ran 155 focused and 376 integrated functional tests, Ruff/format/compile/diff checks, and required a fresh-context final `READY`. Execution evidence is archived under `archives/execution/mw_protocol_v3_phase1_task15_20260810/`.
