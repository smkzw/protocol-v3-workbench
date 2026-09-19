# T03 存量污染只读定位报告（A26）

生成：2026-09-19 · 工具：`scripts/qc/protocol_v3/scan_legacy_case_pollution.py`（只读 mode=ro，零写入）
扫描对象：`runs/**` 全部 SQLite（browser_acceptance.sqlite、real_deepseek_seed.sqlite）
原始数据：`legacy_pollution_scan.json`（含每条 finding 的表/项目/记录ID/片段）

## 结论

1. **当前状态零泄漏**：`aggregate_revision`（事实/文档当前快照）中未检出任何案例拟合 token。当前研究事实、工作稿无需修正项。
2. **历史事件留存泄漏痕迹（按要求保留，不重写）**：
   - 9 条 `study_definition.decision_applied`（actor=medical_manager，用户在残差确认流中确认过含 "tipping point" 的缺失数据处理建议）；
   - 38 条 `graph_run_started` / 29 条 `graph_node_result`：派发输入材料中携带旧推荐表内容的执行痕迹；
   - 3 条 `manuscript_working_document_edited.v1` + 1 条 `manuscript_working_document_saved.v1`：曾写入后被后续版本覆盖。
3. **127 条 note**：真实 CRSwNP 参照项目（MG-K10 域）中的 SNOT-22/鼻息肉等词为其合法适应症内容，非污染。
4. **0 条 cross_hit**：校正分类后（按项目聚合体整块判断适应症域），无跨适应症串入。
5. 历史导出文档（如 12_final_clean.docx）正文中曾含 NRI/tipping point 表述，属既有交付物原稿——按 A26 保留，不批量改写；后续全章重生成自然以清洁路径覆盖。

## 处置

- 不自动修改任何事实、事件、稿件（A26）。
- 通用路径已在 28d1f9c 清洁（T01/T02 回归锁 9 项全绿）。
- 后续自然触发全章重生成时，新版本将以用户确认事实为唯一来源。
