# Codex Execution Plan: mw_protocol_v3_phase1_task14_20260810

Objective: 实现并验收 Protocol v3 Task 1.4 canonical reducers 与 CAS，保持 StudyDefinition 唯一事实源、SemanticDocumentRevision 唯一文字工作版本

## Work Items

| Worker | Assigned item | Report |
|---|---|---|
| `worker_01` | 实现 canonical hashing 与 StudyDefinition 纯 reducer/CAS，新增 test_study_definition_reducer.py | `runs/execution/mw_protocol_v3_phase1_task14_20260810/worker_01.md` |
| `worker_02` | 实现 DecisionRecord 幂等/CAS reducer，新增 test_decision_cas.py | `runs/execution/mw_protocol_v3_phase1_task14_20260810/worker_02.md` |
| `worker_03` | 实现 SemanticDocument 纯 reducer、fact revision 绑定和 typed fact proposal，新增 test_semantic_document_reducer.py | `runs/execution/mw_protocol_v3_phase1_task14_20260810/worker_03.md` |

## Manager

| Role | Provider | Model | Report |
|---|---|---|---|
| `finite_code_manager_cursor` | `cursor-cli` | `auto` | `runs/execution/mw_protocol_v3_phase1_task14_20260810/manager.md` |

## Codex Acceptance

TODO: verify artifacts, tests, source claims, rendered surfaces, blockers, and user-facing completeness.
