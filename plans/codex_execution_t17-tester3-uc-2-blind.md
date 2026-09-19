# Codex Execution Plan: t17-tester3-uc-2-blind

Objective: 以真实用户身份使用ego(lite)浏览器在 http://127.0.0.1:5176 完成轻中度溃疡性结肠炎II期方案的端到端写作（盲测场景：仅一句话简述，系统应引导补齐关键设计），全程禁止直连后端API，只能页面点选；完成或到达时限后输出报告

## Work Items

| Worker | Assigned item | Report |
|---|---|---|
| `worker_01` | 场景3盲测：仅输入一句话简述（合成药U口服II期安慰剂对照8周诱导期）→整理→系统引导补齐→逐卡确认→生成完整初稿→保存→导出Word | `runs/execution/t17-tester3-uc-2-blind/worker_01.md` |
| `worker_02` | 盲测核对：成稿后检索正文是否存在斑秃/偏头痛/鼻窦炎/CRSwNP任何残留（反拟合A07）；报告格式：SOURCE_HEAD/PASSED/FAILED/NOT_RUN/KNOWN_LIMITATIONS+截图+问题清单（P0/P1/P2） | `runs/execution/t17-tester3-uc-2-blind/worker_02.md` |

## Codex Acceptance

TODO: verify artifacts, tests, source claims, rendered surfaces, blockers, and user-facing completeness.
