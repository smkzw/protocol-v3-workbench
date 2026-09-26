# 0926V1 医学写作工作台审阅交接包

审阅仓库：smkzw/protocol-v3-workbench。
固定基线：53feb06fc1402df820a6dba5d8b6e3fa15d50437（相对0924V2基线新增30个提交）。

## 阅读顺序

先读 `docs/0926V1_REVIEW.md`，再将 `docs/0926V1_AGENT_NEXT.md` 交给接续Agent。执行验收使用 `docs/ACCEPTANCE_MATRIX.md`；涉及恢复与候选晋级时参照 `docs/RECOVERY_AND_FIDELITY_SPEC.md`。这些是本轮建议，不是已经合并的生产改动。

`findings.json` 提供10项分级发现；`evidence/source_manifest.json`列出固定提交的源码/文档位置和本轮来源；`evidence/ledger_reconciliation.json`区分旧快照、最近有时间的复核快照和未验证的现场状态。

## 已执行的隔离观察

从此目录执行（Python 3.10+；另需Node.js）：

```sh
python probes/run_numeric_probes.py
python probes/run_preparation_probe.py
python probes/run_reeval_probes.py
node probes/ui_message_excerpt.mjs
```

观察结果存于`evidence/*_probe_results.json`。脚本使用标准库/测试替身，不访问用户GitHub、数据库或模型。23项观察中包含有意暴露的错误；**脚本退出0不代表产品测试通过**。

- 数字：显式数值token输入的子检查，未执行所有前处理/其他忠实度门/真实候选晋级。
- 准备：新建方法前缀和缓存分支，mock IO；包含“仅修self引用”的反事实实验。
- 复检：SQLite筛选与数据流，模型和检查器为stub；用于证实查错来源/检查错对象，不证明完整真实流水线放行。
- 文案：纯JS函数，未执行浏览器。

`probes/proposed_repo_numeric_regressions.py`是建议迁入实际仓库的真实函数回归测试，**本审阅没有在完整仓库运行它**。不要把它和隔离观察混算成通过证据。

## 边界

未修改仓库或用户环境；完整Git直连DNS失败，源码通过连接器读取。完整pytest、真实模型、实际浏览器/视觉截图、现场DB、用户Mac/Word及DOCX二进制验证均NOT_RUN。台账和Office结果是来源作者报告，不是本轮现场复测。

完成本轮关键修复之前，不建议直接按旧HANDOFF重放574项或自动晋级忠实度阻断。不得删除历史、扩大到其他子系统或借无关重构绕开验收。
