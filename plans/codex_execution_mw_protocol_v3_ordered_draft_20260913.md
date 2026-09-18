# Codex Execution Plan: mw_protocol_v3_ordered_draft_20260913

Objective: 实现V1完整初稿所需有序章节候选载体，复用既有StructuredTable，保留对象顺序与证据身份，不修改已确认事实或声称医学/Word验收。

## Work Items

| Worker | Assigned item | Report |
|---|---|---|
| `worker_01` | 实现services/api/app/protocol_workflow/registries/ordered_draft.py及tests/protocol_v3/test_ordered_chapter_draft.py；读取Plan有序章节产物要求和现存ChapterSkillOutput/StructuredTable，先反例后最小实现。只改这两个新文件，纯候选结构和确定性校验，不接模型、存储、router或改变旧合同。段落A→2x2表1→段落B→同kind表2的JSON往返顺序、身份、各格、来源保真；拒绝重复块ID/表身份错配/悬空引用，不能将occurrences当实例，不能生成医学准入或分数。复用既有表格模型并保持原表格语义；必要时只提出后续接口建议。 | `runs/execution/mw_protocol_v3_ordered_draft_20260913/worker_01.md` |

## Codex Acceptance

TODO: verify artifacts, tests, source claims, rendered surfaces, blockers, and user-facing completeness.
