# Codex Execution Plan: t17-tester2-migraine-3b

Objective: 以真实用户身份使用ego(lite)浏览器在 http://127.0.0.1:5176 完成慢性偏头痛预防性治疗III期方案的端到端写作（入口B：零附件，仅写作说明），全程禁止直连后端API，只能页面点选；完成或到达时限后输出报告

## Work Items

| Worker | Assigned item | Report |
|---|---|---|
| `worker_01` | 场景2入口B：不传任何文件，写作说明输入（合成药M CGRP单抗/随机双盲/24周/主要终点每月偏头痛天数较基线变化）→整理→AI设计选项逐卡点选确认→生成完整初稿→保存→导出Word；注意样本量假设不得出现其他疾病数值 | `runs/execution/t17-tester2-migraine-3b/worker_01.md` |
| `worker_02` | 报告格式：SOURCE_HEAD/PASSED/FAILED/NOT_RUN/KNOWN_LIMITATIONS+每步截图+发现的问题清单（P0/P1/P2） | `runs/execution/t17-tester2-migraine-3b/worker_02.md` |

## Codex Acceptance

TODO: verify artifacts, tests, source claims, rendered surfaces, blockers, and user-facing completeness.
