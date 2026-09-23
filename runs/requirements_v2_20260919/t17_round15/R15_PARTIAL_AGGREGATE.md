# T17 第十五轮半程聚合（2026-09-24 凌晨 · 无损暂停点）

## 测试者状态（交班时刻）
| tester | 模型 | 场景 | 状态 |
|---|---|---|---|
| 1 | muse-spark(max) | COPD/入口A | 交卷：BLOCKED（新前沿 F-E） |
| 2 | gemini(high) | MS/入口B | 交卷：**EXIT=OK 全链走通** |
| 3 | grok(high) | MDD/盲测 | **仍在运行**（进程存活，报告未出；下会话先读 /tmp/t17_r15_tester3_report.md） |
| 4 | deepseek(max) | 膝OA/入口B | 交出中期状态后按会话机制收尾 |

## 重大成果
1. **tester2 EXIT=OK**：入口B从一句话起步 → 事实拆解14条 → 检索580项锁定Ponesimod直接竞品 → 框架完成（影响确认2.5秒通过=F-C修复实战生效）→ PICOS完成 → 例外放行 → 111节点文档 → 流程图自动生成(6节点) → 目录/表目录/图目录联动 → 文献库 → Word导出质量门禁正确拦截未完成稿 → 21批全文生成流式运行中。核心决策点击16次（达标）。
2. **F-C 真等待态实战通过**：影响确认不再死锁。
3. **导出门禁正确行为首证**：文档未完成时"预览/正式Word"被拦截=防止空模板交付（这是设计内正确行为，非缺陷）。

## 新前沿 F-E（下批修复，tester1 命中）
- 点击"采用推荐"→ `prefill package journey revision is stale: expected 4, package 2`（推荐包过期不可采用）；
- 点击"更新建议"→ `prefill generation is already in flight for this revision (logical call mwprefillcall_...); force cannot interrupt the live call`，等待15分钟+全按钮禁用。
- 根因定位：medical_writing_authoring_journey.py:5758 附近 in_flight 守卫——被中断/挂起的生成调用没有时间回收机制；stale 包只报错不引导再生成。修法方向：①给 in_flight 预约加超时回收（超时翻转为 unknown_outcome 后 force 可接管）②stale 包错误信息给出明确的一键"重新生成推荐"路径。

## tester4 中期发现（下批核实）
- cms_regulatory_zh_v1 中文候选批次 228/230 失败（translation_generation_failed → document_plan_anchor_filter），语料准入挂起；属 F-B 家族的大规模失败形态，需在 c3acd77 修复后的基础上再诊断规划器本身失败原因。

## 交班注意事项
- tester3 会话仍在跑：下会话开工前先检查其报告是否完整（EXIT标记），若完整则并入本轮归档。
- 开工前照例备份清理 R15 测试项目（本轮4项目）。
- 测试窗口内有过一次同步重启（部署 4cc2deb），已在各报告中如实记录。
