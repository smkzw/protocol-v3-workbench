# DECISIONS — protocol-v3-workbench

| 日期 | 决定 | 原因 | 被否方案 |
|---|---|---|---|
| 2026-10-17 | 采纳 mw_reboot_20261017 重启包为新方向基线 | 过去一月以"修测试症状"为主，判绿标准降至≥3章即绿，方案质量无稳定度量；个案拟合（专病函数/标题关键词分支/轮次补丁提示） | 继续旧 LOOP 收敛路线 |
| 2026-10-17 | runs/ 移出 git（untrack+ignore，本地保留） | 仓库公开且臃肿（13G运行产物） | 删除本地文件；改写 git 历史（待用户后续指令一并处置可见性） |
| 2026-10-17 | 停用 dwfrun 工作流与多测试者 LOOP | 单轮自检3-6小时、账本口径争议、质量反馈不可复现 | 修复 LOOP 判绿口径继续跑 |
| 2026-10-17 | 主数据对象 schema 以 02_ARCHITECTURE.md 为准（ProjectProfile/CompetitorSet/StyleKit/ClauseBank/StudyDefinition/DecisionCard/SectionCard/SectionDraft/Manuscript） | 评测驱动需要稳定契约；StyleKit/ClauseBank 是数据不是代码 | 在旧 repository 标题骨架上继续打补丁 |
| 2026-10-17 | M0 先取基线（3 dev 项目全文+全量测试失败族），基线之前不改写作提示词 | 无度量不动引擎 | 立即重写提示词 |
| 2026-10-17 | 九对象schema定稿（eval/SCHEMAS.md）：StudyDefinition复用现有typed对象不新建表；SectionCard由111份冻结章节合同压缩生成非手写；StyleKit/ClauseBank为runtime数据不进代码不进git | 第一天定接口（05_PLAN并行前提） | 新建独立StudyDefinition表；手写SectionCard |
