# 缺陷清单（2026-10-17，基于 HEAD e67a18d）

状态说明：**代码已核**=本次读代码确认；**记录**=来自仓库内测试/审计记录，未本次复现；**待复核**=可能已修，需确认。

| ID | 级别 | 问题 | 位置/证据 | 状态 | 处理 | 里程碑 |
|---|---|---|---|---|---|---|
| B01 | P0 | 按章节标题关键词插入写死的"标准监管文本骨架"，含 24h 报告、纸质原始记录、中央随机揭盲、妊娠入排等具体实施规则 | services/api/app/medical_writing_repository.py `_SAFETY_REGULATORY_HEADING_MARKERS`、`_SAFETY_*_TEMPLATE`、`_gap_placeholder_block` | 代码已核 | 删除；由 ClauseBank 提供带出处条款 | M3 |
| B02 | P0 | 外用给药 + 标题含"药代动力学" → 自动写"全身暴露极低，不设该类评估"，属无依据医学结论 | 同上 `_is_topical_route` / `_NA_BY_ROUTE_HEADING_RE` | 代码已核 | 删除；PK 适用性做成决定卡 | M3/M4 |
| B03 | P0 | 样本量守卫用正则解析正文并改写"每组N例"；只支持连续/两比例 z 公式；按 `section_number.startswith("9")`（旧章号，模板统计为第11章）触发 | medical_writing_full_draft.py `sample_size_declaration_check`、`_rewrite_declared_sample_size`、`apply_sample_size_guard_to_section` | 代码已核 | 改为结构化参数 + 计算器 + 渲染；正文检查只标记 | M3/M4 |
| B04 | P1 | 全文初稿提示约5千字，含轮次补丁（NEW-37、A3②、P1-53）、适应症专属规则（DLQI）及互相冲突规则（必须写原值 vs 必须 source_gap；语料只学措辞 vs 竞品片段可借鉴改写） | medical_writing_full_draft.py `_instruction`；ai_gateway.py `_system_prompt` | 代码已核 | 分层提示 + lint（03_WRITING_SYSTEM） | M3 |
| B05 | P1 | 分诊中约24个专病函数（心衰EF、COPD、UC、CRSwNP） | medical_writing_competitor_triage.py 1702–2491 行附近 | 代码已核 | 通用术语标准化（MeSH/CT.gov 条件词表）+ 语义匹配 + 用户确认 | M2 |
| B06 | P1 | 公司方案文件名与权重写死在代码 | medical_writing_corpus_policy.py | 代码已核 | 移到 runtime 配置 | M0/M2 |
| B07 | P1 | 111 份章节合同未被全文初稿主路径直接消费；导出件使用旧编号（9.x 统计、14.x 附录） | full_draft 未引用 chapter_contracts；审计记录 | 代码已核+记录 | SectionCard 由合同生成，生成按语义节点 | M3 |
| B08 | P1 | 高影响章节 `review_level` 永远是 standard：`_review_policy` 中 `required_reasons` 从未追加 | medical_writing_full_draft.py `_review_policy` | 代码已核（可能是有意降级） | 由风险分级替代 | M3 |
| B09 | P0 | 正式 Word 需 107 章逐章冻结，按钮长期置灰 | r1-D 测试报告 | 记录 | 文档级发布 + 缺口清单 | M5 |
| B10 | P1 | 统计师："目录像本书，翻开是提纲"；r10-A 导出 33 处【待补齐】 | r1-B、r11-B/r12-B 审阅 | 记录 | M3 主目标；用覆盖率指标跟踪 | M3 |
| B11 | P1 | 安全/PV 内容错位到附录 14.4 并重复 7–8 次，第8章空 | HANDOFF_1004 | 记录 | 按语义节点装配后复测 | M3/M5 |
| B12 | P1 | 分诊自动排除同药注册研究（TRuE-AD1/2） | 10-11 检查点 | 记录 | 优先级规则：同药/同靶点不得自动排除 | M2 |
| B13 | P1 | journey 写入死锁、版本冻结、UI 恢复失效（新纪元 R3） | 10-11 检查点 | 记录/待复核 | 先写复现测试 | M4 |
| B14 | P1 | 设计确认循环依赖（picos_alignment 需 picos_sha256，而 PICOS 依赖"完成第二步"） | 10-13/14 检查点；10-15 记"④复验通过" | 待复核 | 补回归测试 | M4 |
| B15 | P1 | 幂等继承死路（r12 ⑥） | retest_r12 | 记录 | 复现后修 | M5 |
| B16 | P1 | 样本量假设修订后基数不重算（P1-53） | SPEC_sample_size_revision_gate | 记录 | 被 B03 新方案取代 | M4 |
| B17 | P2 | 导出主审件标题含"V1"测试标记 | r11-B/r12-B | 记录 | 导出检查器 | M5 |
| B18 | P1 | 全库验收门 FAIL：70 个未匹配失败、selftests 0/5、pyflakes undefined name（medical_writing_repository.py 3510–3511） | runs/acceptance_gate/run_2026-10-07... | 记录 | M0 记录基线，逐族清理 | M0 |
| B19 | P1 | 生成吞吐：本地 375s/章、单章思考 2–3.5 万字、温度 1.0；21 批约 200 分钟 | model_bench_20261013；收敛报告 | 记录 | 逐节生成 + 模型选型 + 思考上限 | M1/M3 |
| B20 | P1 | 长任务前端轮询 1200×900ms 后把仍在运行判为失败（W07） | 0922V2 01_REVIEW | 待复核 | 复用同 job 继续观察 | M5 |
| B21 | P1 | 仓库公开，含公司名称（约1042个文件）、本机竞品库路径、真实方案文件名、真实项目流程截图 | GitHub API visibility=public | 已核 | 暂缓，待用户后续指令；期间不新增敏感提交 | 后续 |
| B22 | P2 | main.py 1.3万行、App.jsx 1.7万行 | — | 已核 | 只在触及时按新模块拆分，不做大重构 | 持续 |
